#!/usr/bin/env python3
"""Read-only connectivity check for the yarbo-patrol module.

Connects to the base station's MQTT broker, prints a status snapshot,
then streams live telemetry for a short window. Sends NO commands -
the robot will not move, beep, or light up.

Usage:
    python3 check_connection.py --broker 192.168.1.50 --sn YB2024XXXXXX
    python3 check_connection.py --discover              # LAN scan (not on Termux)

Exit codes: 0 telemetry received, 1 could not connect or no telemetry.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from yarbo import YarboClient

TELEMETRY_TIMEOUT_S = 20


async def discover() -> tuple[str, str] | None:
    from yarbo import discover_yarbo
    print("Scanning the local subnet for a Yarbo base station...")
    try:
        robots = await discover_yarbo()
    except Exception as e:  # raw sockets unavailable (e.g. Termux), etc.
        print(f"Discovery failed ({e}).")
        print("Find the base station IP in your router's client list "
              "(MAC prefix C8:FE:0F) and pass --broker/--sn explicitly.")
        return None
    if not robots:
        print("No base station found. Check that this machine is on the "
              "same network/VLAN, then pass --broker/--sn explicitly.")
        return None
    r = robots[0]
    print(f"Found: broker={r.broker} sn={r.sn}")
    return r.broker, r.sn


async def check(broker: str, sn: str, watch_s: float) -> int:
    print(f"Connecting to mqtt://{broker}:1883 (sn={sn})...")
    try:
        async with YarboClient(broker=broker, sn=sn) as client:
            try:
                status = await asyncio.wait_for(
                    client.get_status(), timeout=TELEMETRY_TIMEOUT_S)
            except (TimeoutError, asyncio.TimeoutError):
                print(f"Connected, but no telemetry within {TELEMETRY_TIMEOUT_S}s.")
                print("Most common cause: wrong serial number - the topic "
                      f"snowbot/{sn}/device/... never publishes. "
                      "Double-check the SN in the Yarbo app.")
                return 1

            print("\n--- Status snapshot ---")
            print(f"  state:    {status.state}")
            print(f"  battery:  {status.battery}%")
            print(f"  position: ({status.position_x:.2f}, {status.position_y:.2f}) m")
            print(f"  heading:  {status.heading:.1f} deg")
            print(f"  speed:    {status.speed:.2f} m/s")

            print(f"\n--- Live telemetry for {watch_s:.0f}s (Ctrl-C to stop) ---")
            n = 0
            end = time.monotonic() + watch_s
            stream = client.watch_telemetry()
            while time.monotonic() < end:
                remaining = end - time.monotonic()
                try:
                    t = await asyncio.wait_for(
                        anext(stream), timeout=max(remaining, 0.1))
                except (TimeoutError, asyncio.TimeoutError):
                    break
                n += 1
                print(f"  battery={t.battery}% state={t.state} "
                      f"pos=({t.position_x:.2f},{t.position_y:.2f}) "
                      f"speed={t.speed:.2f}")
            rate = n / watch_s if watch_s else 0.0
            print(f"\nReceived {n} messages (~{rate:.1f}/s; healthy is 1-2/s).")
            if n == 0:
                return 1
            print("Connectivity OK - next step: command_test.py")
            return 0
    except OSError as e:
        print(f"Could not reach the broker: {e}")
        print("Check the IP, that you're on the same network/VLAN, and that "
              "nothing is firewalling port 1883 between you and the base station.")
        return 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Yarbo read-only connectivity check")
    ap.add_argument("--broker", help="base station IP")
    ap.add_argument("--sn", help="robot serial number")
    ap.add_argument("--discover", action="store_true",
                    help="scan the LAN instead of passing --broker/--sn")
    ap.add_argument("--watch", type=float, default=15,
                    help="seconds of live telemetry to stream (default 15)")
    args = ap.parse_args()

    async def run() -> int:
        broker, sn = args.broker, args.sn
        if args.discover and not (broker and sn):
            found = await discover()
            if not found:
                return 1
            broker, sn = found
        if not (broker and sn):
            ap.error("--broker and --sn are required (or use --discover)")
        return await check(broker, sn, args.watch)

    try:
        sys.exit(asyncio.run(run()))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
