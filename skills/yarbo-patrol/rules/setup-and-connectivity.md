# Setup and connectivity

## Quickstart

The scripts directory contains everything for initial setup and a safe, staged first test:

```bash
cd skills/yarbo-patrol/scripts
bash setup.sh                                            # install deps (Termux-aware)
python3 check_connection.py --broker <ip> --sn <serial>  # read-only: telemetry check
python3 command_test.py --broker <ip> --sn <serial>      # buzzer + lights, no movement
python3 patrol_controller.py --broker <ip> --sn <serial> \
    --plan <planId> --expected-runtime 300 --lights -v  # first supervised patrol
```

Run the stages in order and don't skip ahead: each one proves a layer (network -> telemetry -> command path -> movement) so a failure is easy to localize. Before the last step: create a short test plan in the Yarbo app, run it once from the app with `sniff_commands.py` watching, and note the numeric `planId` from the `plan_feedback` messages - that id (not the plan's name) is what `--plan` takes. Stand near the robot for the first supervised run.

## Prerequisites

- A Yarbo robot paired with its base station (data center) and mapped in the Yarbo app.
- The base station reachable on your LAN. The robot talks to the base station over its own link; you talk to the base station's MQTT broker.
- Python 3.10+ on the machine that will run patrols (a Raspberry Pi or the Home Assistant host works well).

## Install the client library

```bash
pip install python-yarbo
```

## Find the robot on the network

The base station identifies itself by MAC OUI `C8:FE:0F`. The library can scan for it:

```python
from yarbo import discover_yarbo

robots = await discover_yarbo()            # scans the local subnet
robots = await discover_yarbo(subnet="192.168.1.0/24")  # or be explicit
```

Each result includes the broker IP and the robot serial number (SN). Pin the base station to a static DHCP lease so the broker IP does not move between patrols.

## Connect

```python
from yarbo import YarboClient

async with YarboClient(broker="192.168.1.50", sn="YB2024XXXXXX") as client:
    status = await client.get_status()
    print(status.battery, status.state)
```

`YarboClient.connect_sync()` exists for synchronous scripts.

## MQTT surface

- Broker: base station, port **1883**, anonymous (no username/password/TLS).
- Command topic: `snowbot/{SN}/app/{cmd}`
- Telemetry topics: `snowbot/{SN}/device/DeviceMSG` (~1-2 Hz, zlib-compressed JSON), `heart_beat` (~1 Hz, plain JSON), plus `plan_feedback`, `data_feedback` on state changes.
- Command payloads are JSON envelopes: `{"cmd": ..., "sn": ..., "timestamp": ..., "payload": {...}}`, zlib-compressed except `heart_beat`. `python-yarbo` handles encoding/decoding.

## Security - read this before deploying

The broker is **unauthenticated**. Anyone on your LAN can read telemetry (including GPS position) and send drive commands to the robot. Before running unattended patrols:

- Put the base station and the patrol controller on an isolated VLAN or dedicated IoT network.
- Firewall port 1883 so only the patrol controller host can reach it.
- Do not port-forward or otherwise expose the broker to the internet under any circumstances.
