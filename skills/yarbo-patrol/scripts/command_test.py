#!/usr/bin/env python3
"""Safe command-path test for the yarbo-patrol module.

Verifies that the robot accepts commands, without any movement:
acquires the controller, chirps the buzzer, cycles the lights, and
sends the blades-off command used by every patrol preflight.

Run check_connection.py first. Be near the robot so you can hear/see
the responses - this script cannot observe the buzzer or lights itself.

Usage:
    python3 command_test.py --broker 192.168.1.50 --sn YB2024XXXXXX

Exit codes: 0 all commands sent and robot still healthy, 1 failure.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from yarbo import YarboClient

STATUS_TIMEOUT_S = 20


async def get_status_retry(client: YarboClient, timeout: float = STATUS_TIMEOUT_S):
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


async def run(broker: str, sn: str, force: bool = False) -> int:
    async with YarboClient(broker=broker, sn=sn) as client:
        status = await get_status_retry(client)
        if status is None:
            print(f"No telemetry within {STATUS_TIMEOUT_S}s - run "
                  "check_connection.py first and fix connectivity.")
            return 1
        print(f"Robot reachable: state={status.state} battery={status.battery}%")
        if status.state != "idle":
            print("\nRobot does not report 'idle'. Raw state fields (to see "
                  "what it thinks it's doing - docked/charging often reads "
                  "as active):")
            raw = status.raw if isinstance(getattr(status, "raw", None), dict) else {}
            interesting = {k: v for k, v in raw.items()
                           if any(s in k.lower() for s in
                                  ("state", "charg", "dock", "work", "mode",
                                   "task", "plan", "status"))}
            print(f"  {interesting or raw or 'no raw telemetry available'}")
            if not force:
                print("\nIf the robot is physically parked/docked and not "
                      "doing a job, re-run with --force. Never force this "
                      "while it is actually moving or mid-job.")
                return 1
            print("\n--force given - proceeding.")

        print("Acquiring controller (fails if the Yarbo app holds it - "
              "close the app and retry)...")
        await client.get_controller()

        print("Buzzer test (cmd_buzzer state=1/0) - listen for a beep...")
        await client.buzzer(state=1)
        await asyncio.sleep(2)
        await client.buzzer(state=0)
        await asyncio.sleep(1)

        print("Lights on...")
        await client.lights_on()
        await asyncio.sleep(3)
        print("Lights off...")
        await client.lights_off()

        print("Sending set_blade_speed=0 (the patrol preflight disarm)...")
        await client.publish_raw("set_blade_speed", {"speed": 0})
        await asyncio.sleep(2)

        status = await get_status_retry(client)
        if status is None:
            print("Warning: no status after the commands - telemetry gap, "
                  "check the robot before proceeding.")
            return 1
        print(f"Robot still healthy: state={status.state} battery={status.battery}%")
        print("\nDid you see the lights cycle and hear at least one beep?")
        print("Lights + blade-disarm passing is what matters for patrols; the")
        print("beep is only the start announcement. Note which buzzer test (if")
        print("any) beeped, and check the mute toggle next to the volume slider")
        print("in Yarbo Settings if neither did.")
        print("Next step: a supervised patrol_controller.py run on a short")
        print("'patrol-test' plan, standing near the robot.")
        return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Yarbo safe command test (no movement)")
    ap.add_argument("--broker", required=True, help="base station IP")
    ap.add_argument("--sn", required=True, help="robot serial number")
    ap.add_argument("--force", action="store_true",
                    help="proceed even if the robot does not report 'idle' "
                         "(only when it is physically parked/docked)")
    args = ap.parse_args()
    try:
        sys.exit(asyncio.run(run(args.broker, args.sn, args.force)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
