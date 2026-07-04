#!/usr/bin/env python3
"""Watch app->robot commands on the Yarbo broker.

Subscribes to the robot's command topics and prints every command the
Yarbo app sends, with its decoded payload. Use it to learn the exact
command shape for an action: run this, trigger the action in the app
(e.g. its beep / find-robot function), and read the command off the
screen. Purely passive - sends nothing.

Usage:
    python3 sniff_commands.py --broker 192.168.1.50 --sn YB2024XXXXXX
    python3 sniff_commands.py ... --all     # include device telemetry topics

Stop with Ctrl-C.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import zlib

import paho.mqtt.client as mqtt

# High-rate telemetry we hide unless --all is given
NOISY_LEAVES = {"DeviceMSG", "heart_beat"}


def decode(payload: bytes):
    for attempt in (lambda b: json.loads(zlib.decompress(b)),
                    lambda b: json.loads(b)):
        try:
            return attempt(payload)
        except Exception:
            continue
    return f"<{len(payload)} bytes, not zlib/json: {payload[:32].hex()}...>"


def main() -> None:
    ap = argparse.ArgumentParser(description="Passive Yarbo MQTT command sniffer")
    ap.add_argument("--broker", required=True, help="base station IP")
    ap.add_argument("--sn", help="unused (watches all topics); kept for "
                                 "command-line compatibility")
    ap.add_argument("--all", action="store_true",
                    help="also show DeviceMSG/heart_beat telemetry spam")
    args = ap.parse_args()

    seen_noisy: set[str] = set()
    recent: dict[tuple, float] = {}  # dedup across overlapping filters
    # Several patterns because the broker may deny wide wildcards by ACL;
    # whichever it grants still catches app->robot commands.
    sub_filters = ["#", "snowbot/#", "+/+/app/+", "+/+/device/+"]

    def on_connect(client, userdata, flags, reason_code, properties=None):
        print("Connected - requesting subscriptions "
              "(trigger the action in the Yarbo app once granted)")
        for f in sub_filters:
            client.subscribe(f)

    def on_subscribe(client, userdata, mid, reason_codes, properties=None):
        for rc in reason_codes:
            granted = getattr(rc, "is_failure", None)
            if granted is None:  # paho 1.x gives plain ints (128 = denied)
                ok = int(rc) < 128
            else:
                ok = not rc.is_failure
            print(f"  subscription {'granted' if ok else 'DENIED by broker'} "
                  f"({rc})")

    def on_message(client, userdata, msg):
        # Overlapping filters can deliver the same message more than once
        now = time.monotonic()
        key = (msg.topic, bytes(msg.payload))
        for k, ts in list(recent.items()):
            if now - ts > 1.0:
                del recent[k]
        if key in recent:
            return
        recent[key] = now

        leaf = msg.topic.rsplit("/", 1)[-1]
        if not args.all and leaf in NOISY_LEAVES:
            # Announce each telemetry topic once - proves the broker is
            # publishing and shows the robot's true topic root/SN
            if msg.topic not in seen_noisy:
                seen_noisy.add(msg.topic)
                print(f"(telemetry flowing on {msg.topic} - hidden from "
                      f"now on, use --all to see it)")
            return
        stamp = time.strftime("%H:%M:%S")
        body = decode(msg.payload)
        if isinstance(body, dict):
            body = json.dumps(body, default=str)
        print(f"[{stamp}] {msg.topic}\n    {body}")

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except (AttributeError, TypeError):  # paho-mqtt 1.x
        client = mqtt.Client()
    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    try:
        client.connect(args.broker, 1883, keepalive=30)
    except OSError as e:
        print(f"Could not reach broker: {e}")
        sys.exit(1)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nDone.")


if __name__ == "__main__":
    main()
