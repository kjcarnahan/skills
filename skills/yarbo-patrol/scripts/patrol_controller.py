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
import logging
import math
import sys
import time

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


async def preflight(client: YarboClient, min_battery: int) -> bool:
    status = await get_status_retry(client)
    if status is None:
        notify("notify", "patrol skipped: no telemetry from robot")
        return False
    if status.battery is None:
        notify("notify", "patrol skipped: battery level unknown")
        return False
    if status.state != "idle":
        notify("info", f"patrol skipped: robot busy (state={status.state})")
        return False
    if status.battery < min_battery:
        notify("info", f"patrol skipped: battery {status.battery}% < {min_battery}%")
        return False
    return True


async def disarm_blades(client: YarboClient) -> None:
    # Invariant before every departure - never assume blades are off.
    await client.publish_raw("set_blade_speed", {"speed": 0})
    await asyncio.sleep(2)


async def watch_patrol(client: YarboClient, expected_runtime: float) -> None:
    """Stream telemetry until the plan completes; raise PatrolAbort on trip."""
    started = time.monotonic()
    ceiling = expected_runtime * RUNTIME_CEILING_FACTOR
    positions: list[tuple[float, float, float]] = []  # (t, x, y)
    seen_active = False

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
        # Telemetry fields can be None when the robot hasn't reported them yet
        if t.battery is not None and t.battery < BATTERY_FLOOR:
            raise PatrolAbort(f"battery floor hit ({t.battery}%)")

        if t.state == "active":
            seen_active = True
        elif seen_active:
            log.info("plan finished (state idle after active)")
            return
        elif now - started > START_CONFIRM_TIMEOUT_S:
            raise PatrolAbort("plan never started (still idle)")

        # Stuck detection: displacement over a rolling window while active
        if t.position_x is None or t.position_y is None:
            continue
        positions.append((now, t.position_x, t.position_y))
        positions = [p for p in positions if now - p[0] <= STUCK_WINDOW_S]
        if seen_active and t.state == "active" and now - positions[0][0] >= STUCK_WINDOW_S:
            dx = t.position_x - positions[0][1]
            dy = t.position_y - positions[0][2]
            if math.hypot(dx, dy) < STUCK_DISPLACEMENT_M:
                raise PatrolAbort(
                    f"stuck: <{STUCK_DISPLACEMENT_M}m displacement in "
                    f"{STUCK_WINDOW_S}s at ({t.position_x:.1f}, {t.position_y:.1f})")


async def run_patrol(args: argparse.Namespace) -> int:
    async with YarboClient(broker=args.broker, sn=args.sn) as client:
        min_battery = BATTERY_FLOOR + PREFLIGHT_BATTERY_MARGIN + args.expected_battery_cost
        if not await preflight(client, min_battery):
            return 1

        await client.get_controller()
        await disarm_blades(client)
        if args.lights:
            await client.lights_on()
        await client.buzzer(state=1)

        log.info("starting plan %s", args.plan)
        await client.publish_raw("start_plan", {"plan": args.plan})

        try:
            await asyncio.wait_for(
                watch_patrol(client, args.expected_runtime),
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
    ap.add_argument("--plan", required=True, help="saved plan name, e.g. patrol-perimeter")
    ap.add_argument("--expected-runtime", type=float, required=True,
                    help="normal route runtime in seconds (from route verification)")
    ap.add_argument("--expected-battery-cost", type=int, default=15,
                    help="battery percent the route normally consumes")
    ap.add_argument("--lights", action="store_true", help="lights on for the run")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(asyncio.run(run_patrol(args)))


if __name__ == "__main__":
    main()
