#!/usr/bin/env python3
"""List the robot's saved plans over local MQTT.

Publishes read_all_plans and prints the response - the plan ids shown
are what patrol_controller.py --plan expects. Community docs note some
firmware only answers this while the robot is active; if you get no
response while it sits idle, run it again while a plan is running.

Usage:
    python3 list_plans.py --broker 192.168.1.50 --sn YB2024XXXXXX
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time
import zlib

import paho.mqtt.client as mqtt
from yarbo import YarboClient


def main() -> None:
    ap = argparse.ArgumentParser(description="List saved Yarbo plans")
    ap.add_argument("--broker", required=True, help="base station IP")
    ap.add_argument("--sn", required=True, help="robot serial number")
    ap.add_argument("--timeout", type=float, default=20,
                    help="seconds to wait for a response (default 20)")
    args = ap.parse_args()

    responses: list[tuple[str, dict]] = []
    got = threading.Event()

    def on_message(client, userdata, msg):
        try:
            data = json.loads(zlib.decompress(msg.payload))
        except Exception:
            try:
                data = json.loads(msg.payload)
            except Exception:
                return
        label = str(data.get("topic", ""))
        if "plan" in label or "plan" in msg.topic.rsplit("/", 1)[-1]:
            responses.append((msg.topic, data))
            got.set()

    try:
        watcher = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except (AttributeError, TypeError):  # paho-mqtt 1.x
        watcher = mqtt.Client()
    watcher.on_message = on_message
    watcher.connect(args.broker, 1883, keepalive=30)
    watcher.subscribe(f"snowbot/{args.sn}/device/#")
    watcher.loop_start()

    async def run() -> None:
        async with YarboClient(broker=args.broker, sn=args.sn) as client:
            print("Requesting plan list (read_all_plans)...")
            await client.publish_raw("read_all_plans", {})
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline and not got.is_set():
                await asyncio.sleep(0.5)

    try:
        asyncio.run(run())
    finally:
        watcher.loop_stop()
        watcher.disconnect()

    if not responses:
        print(f"No plan response within {args.timeout:.0f}s. Known firmware "
              "quirk: the robot may only answer while active - try again "
              "during a running plan, or use sniff_commands.py while "
              "starting the plan from the app and read planId from "
              "plan_feedback.")
        sys.exit(1)

    print("\n--- Plan responses ---")
    for topic, data in responses:
        plans = data.get("data")
        if isinstance(plans, list):
            for p in plans:
                if isinstance(p, dict):
                    print(f"  id={p.get('id')!r}  name={p.get('name')!r}  "
                          f"areaIds={p.get('areaIds')!r}")
                else:
                    print(f"  {p!r}")
        else:
            print(f"[{topic}]\n  {json.dumps(data, default=str)[:2000]}")


if __name__ == "__main__":
    main()
