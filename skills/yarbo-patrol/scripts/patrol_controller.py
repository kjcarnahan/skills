#!/usr/bin/env python3
"""Yarbo patrol controller.

Runs one patrol: preflight checks, blades disarmed, saved plan started,
telemetry watchdog for the whole run, dock on completion or abort.

Usage:
    pip install python-yarbo
    python patrol_controller.py --broker 192.168.1.50 --sn YB2024XXXXXX \
        --plan patrol-perimeter --expected-runtime 900

Schedule with cron/systemd for recurring patrols; add jitter at the
scheduler layer (see rules/scheduling.md). Exit codes: 0 completed,
1 skipped at preflight, 2 aborted by watchdog, 3 lost contact.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import sys
import threading
import time
import zlib

import paho.mqtt.client as mqtt
from yarbo import YarboClient

log = logging.getLogger("yarbo-patrol")

# Watchdog tuning - see rules/monitoring-and-alerts.md
STUCK_WINDOW_S = 90
STUCK_DISPLACEMENT_M = 1.0
HEARTBEAT_TIMEOUT_S = 30
BATTERY_FLOOR = 25
PREFLIGHT_BATTERY_MARGIN = 20
RUNTIME_CEILING_FACTOR = 1.5
START_CONFIRM_TIMEOUT_S = 30


class PatrolAbort(Exception):
    """Watchdog tripped; carries the reason for the incident log."""


class PlanMonitor:
    """Tracks plan_feedback on its own MQTT connection.

    The idle/active flag in parsed telemetry conflates charging with
    working (verified on real hardware), so plan start/finish detection
    keys on plan_feedback instead: the robot streams it ~every 2s while
    a plan runs, with state == 3 meaning running.
    """

    RUNNING_STATE = 3

    def __init__(self, broker: str, sn: str):
        self._lock = threading.Lock()
        self._last: dict | None = None
        self._last_at: float | None = None
        self.seen_running = False
        try:
            self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except (AttributeError, TypeError):  # paho-mqtt 1.x
            self._client = mqtt.Client()
        self._client.on_message = self._on_message
        self._client.connect(broker, 1883, keepalive=30)
        self._client.subscribe(f"snowbot/{sn}/device/plan_feedback")
        self._client.loop_start()

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(zlib.decompress(msg.payload))
        except Exception:
            try:
                data = json.loads(msg.payload)
            except Exception:
                return
        with self._lock:
            self._last = data
            self._last_at = time.monotonic()
            if data.get("state") == self.RUNNING_STATE:
                self.seen_running = True

    def snapshot(self) -> tuple[bool | None, float | None, object]:
        """(running, seconds_since_last_feedback, raw state field)."""
        with self._lock:
            if self._last is None:
                return None, None, None
            age = time.monotonic() - self._last_at
            state = self._last.get("state")
            return state == self.RUNNING_STATE, age, state

    def stop(self) -> None:
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass


def notify(level: str, message: str) -> None:
    """Notification hook - wire this to ntfy/Pushover/HA webhook.

    Tiers per rules/monitoring-and-alerts.md: info, notify, urgent.
    """
    log.log(logging.WARNING if level != "info" else logging.INFO,
            "[%s] %s", level, message)


async def get_status_retry(client: YarboClient, timeout: float = 20.0):
    """get_status() can return None when no telemetry arrived - retry."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status = await asyncio.wait_for(client.get_status(), timeout=5)
        except (TimeoutError, asyncio.TimeoutError):
            status = None
        if status is not None:
            return status
        await asyncio.sleep(1)
    return None


def _looks_docked_charging(status) -> bool:
    """Charging on the dock can report state 'active' on real firmware.

    Detect it from raw battery telemetry: negative current = charging.
    """
    raw = status.raw if isinstance(getattr(status, "raw", None), dict) else {}
    stack = [raw]
    while stack:
        node = stack.pop()
        for key, val in node.items():
            if isinstance(val, dict):
                stack.append(val)
            elif key.lower() in ("current", "chargecurrent", "charge_current"):
                try:
                    if float(val) < 0:
                        return True
                except (TypeError, ValueError):
                    pass
    return False


async def preflight(client: YarboClient, min_battery: int,
                    force: bool = False):
    """Return the robot's status if the patrol may start, else None."""
    status = await get_status_retry(client)
    if status is None:
        notify("notify", "patrol skipped: no telemetry from robot")
        return None
    if status.battery is None:
        notify("notify", "patrol skipped: battery level unknown")
        return None
    if status.state != "idle":
        if _looks_docked_charging(status):
            log.info("state=%s but battery current is negative - treating "
                     "as docked+charging, proceeding", status.state)
        elif force:
            log.warning("state=%s, proceeding due to --force", status.state)
        else:
            notify("info", f"patrol skipped: robot busy (state={status.state})")
            return None
    if status.battery < min_battery:
        notify("info", f"patrol skipped: battery {status.battery}% < {min_battery}%")
        return None
    return status


async def disarm_blades(client: YarboClient) -> None:
    # Invariant before every departure - never assume blades are off.
    await client.publish_raw("set_blade_speed", {"speed": 0})
    await asyncio.sleep(2)


async def wait_plan_start(plans: PlanMonitor, timeout: float) -> bool:
    """True once plan_feedback shows the plan running."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if plans.seen_running:
            return True
        await asyncio.sleep(1)
    return False


async def watch_patrol(client: YarboClient, expected_runtime: float,
                       plans: PlanMonitor,
                       initial_battery: int | None = None) -> None:
    """Stream telemetry until the plan completes; raise PatrolAbort on trip.

    Caller must have confirmed the plan started (plans.seen_running).
    """
    started = time.monotonic()
    ceiling = expected_runtime * RUNTIME_CEILING_FACTOR
    positions: list[tuple[float, float, float]] = []  # (t, x, y)
    last_battery = initial_battery

    stream = client.watch_telemetry()
    while True:
        try:
            t = await asyncio.wait_for(anext(stream), timeout=HEARTBEAT_TIMEOUT_S)
        except (TimeoutError, asyncio.TimeoutError):
            raise TimeoutError(
                f"no telemetry for {HEARTBEAT_TIMEOUT_S}s") from None
        now = time.monotonic()

        if now - started > ceiling:
            raise PatrolAbort(f"runtime ceiling hit ({ceiling:.0f}s)")
        # Telemetry fields can be None when the robot hasn't reported them
        # yet, and real firmware occasionally emits zeroed junk frames - an
        # implausible drop (>30 points in one frame) is a glitch, not a
        # battery, so ignore it rather than aborting on it.
        if t.battery is not None:
            if (last_battery is not None
                    and last_battery - t.battery > 30):
                log.debug("ignoring implausible battery reading %s%% "
                          "(last good %s%%)", t.battery, last_battery)
            else:
                last_battery = t.battery
                if t.battery < BATTERY_FLOOR:
                    raise PatrolAbort(f"battery floor hit ({t.battery}%)")

        # Plan lifecycle from plan_feedback, not the idle/active telemetry
        # flag (which reads 'active' while merely charging on the dock)
        running, feedback_age, feedback_state = plans.snapshot()
        if running is False:
            log.info("plan finished (plan_feedback state=%s)", feedback_state)
            return
        if feedback_age is not None and feedback_age > 60:
            raise PatrolAbort(
                f"plan feedback stalled for {feedback_age:.0f}s")

        # Stuck detection: displacement over a rolling window while running
        if t.position_x is None or t.position_y is None:
            continue
        positions.append((now, t.position_x, t.position_y))
        positions = [p for p in positions if now - p[0] <= STUCK_WINDOW_S]
        if running and now - positions[0][0] >= STUCK_WINDOW_S:
            dx = t.position_x - positions[0][1]
            dy = t.position_y - positions[0][2]
            if math.hypot(dx, dy) < STUCK_DISPLACEMENT_M:
                raise PatrolAbort(
                    f"stuck: <{STUCK_DISPLACEMENT_M}m displacement in "
                    f"{STUCK_WINDOW_S}s at ({t.position_x:.1f}, {t.position_y:.1f})")


async def run_patrol(args: argparse.Namespace) -> int:
    async with YarboClient(broker=args.broker, sn=args.sn) as client:
        min_battery = BATTERY_FLOOR + PREFLIGHT_BATTERY_MARGIN + args.expected_battery_cost
        start_status = await preflight(client, min_battery, force=args.force)
        if start_status is None:
            return 1

        await client.get_controller()
        await disarm_blades(client)
        # Lights are the start-of-patrol announcement. No buzzer chirp:
        # cmd_buzzer is silently ignored on tested firmware (the app's
        # Find My Yarbo beep goes via Yarbo's cloud, not the local broker).
        if args.lights:
            await client.lights_on()

        # The robot identifies plans by planId (visible in plan_feedback
        # when the plan runs), not by the display name from the app. The
        # exact accepted payload shape varies by firmware, so try known
        # variants until plan_feedback confirms the plan is running.
        plan_ref = int(args.plan) if str(args.plan).isdigit() else args.plan
        plans = PlanMonitor(args.broker, args.sn)
        attempts: list[tuple[str, object]] = []
        lib_start = getattr(client, "start_plan", None)
        if lib_start is not None:
            attempts.append(("library client.start_plan()",
                             lambda: lib_start(str(plan_ref))))
        lib_direct = getattr(client, "start_plan_direct", None)
        if lib_direct is not None and isinstance(plan_ref, int):
            attempts.append(("library client.start_plan_direct()",
                             lambda: lib_direct(plan_ref, percent=100)))
        attempts += [
            ("raw planId+percent",
             lambda: client.publish_raw("start_plan",
                                        {"planId": plan_ref, "percent": 100})),
            ("raw planId only",
             lambda: client.publish_raw("start_plan", {"planId": plan_ref})),
            ("raw planId as string",
             lambda: client.publish_raw("start_plan",
                                        {"planId": str(plan_ref)})),
        ]

        plan_started = False
        for label, attempt in attempts:
            log.info("start attempt: %s (planId=%r)", label, plan_ref)
            try:
                await attempt()
            except Exception as e:
                log.warning("start attempt %s errored: %s", label, e)
                continue
            if await wait_plan_start(plans, START_CONFIRM_TIMEOUT_S):
                log.info("plan confirmed running via plan_feedback")
                plan_started = True
                break
            log.warning("no plan_feedback after %s - trying next variant",
                        label)

        if not plan_started:
            plans.stop()
            notify("notify", "patrol aborted: no start variant produced "
                             "plan_feedback - plan never ran")
            await client.publish_raw("dstop", {})
            if args.lights:
                await client.lights_off()
            return 2

        try:
            await asyncio.wait_for(
                watch_patrol(client, args.expected_runtime, plans,
                             initial_battery=start_status.battery),
                timeout=args.expected_runtime * RUNTIME_CEILING_FACTOR + 120,
            )
        except PatrolAbort as e:
            notify("notify", f"patrol aborted: {e}")
            await client.publish_raw("dstop", {})
            await asyncio.sleep(5)
            await client.publish_raw("cmd_recharge", {})
            return 2
        except (TimeoutError, asyncio.TimeoutError):
            # Can't command what we can't reach - alert and stop trying.
            notify("urgent", "lost contact with robot during patrol")
            return 3
        finally:
            plans.stop()
            if args.lights:
                try:
                    await client.lights_off()
                except Exception:
                    pass

        await client.publish_raw("cmd_recharge", {})
        notify("info", f"patrol {args.plan} completed")
        return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Run one Yarbo patrol")
    ap.add_argument("--broker", required=True, help="base station IP")
    ap.add_argument("--sn", required=True, help="robot serial number")
    ap.add_argument("--plan", required=True,
                    help="numeric planId of the saved plan (find it in "
                         "plan_feedback via sniff_commands.py while the plan "
                         "runs once from the app)")
    ap.add_argument("--expected-runtime", type=float, required=True,
                    help="normal route runtime in seconds (from route verification)")
    ap.add_argument("--expected-battery-cost", type=int, default=15,
                    help="battery percent the route normally consumes")
    ap.add_argument("--lights", action="store_true", help="lights on for the run")
    ap.add_argument("--force", action="store_true",
                    help="proceed when the robot does not report 'idle' - "
                         "only for supervised runs with the robot physically "
                         "parked (docked+charging is auto-detected and never "
                         "needs this)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(asyncio.run(run_patrol(args)))


if __name__ == "__main__":
    main()
