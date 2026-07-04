---
name: yarbo-patrol
description: Ground patrols with a Yarbo modular yard robot - route planning, scheduling, telemetry monitoring, and safe operation over local MQTT
metadata:
  tags: yarbo, robot, patrol, mqtt, home-assistant, automation, security
---

## When to use

Use this skill whenever you are setting up, running, or troubleshooting patrols of a property with a Yarbo robot (mower, snow blower, or other head). A patrol is a scheduled traversal of saved routes with the work tool disabled, used to keep eyes on the grounds, deter intrusion, and detect anomalies - not to mow or clear snow.

## How it works

Yarbo's base station runs a local MQTT broker (port 1883, no authentication). Commands are published to `snowbot/{SN}/app/{cmd}` and telemetry arrives on `snowbot/{SN}/device/{leaf}`. Patrol routes are created as saved plans in the Yarbo app; this module starts them with `start_plan`, watches live telemetry, and docks the robot when the patrol completes or something goes wrong. The community `python-yarbo` library and the `community_yarbo` Home Assistant integration provide the client layers.

Yarbo has announced an official Open Platform (planned for early 2027). Until it ships, this local MQTT surface is community-documented and unofficial - expect firmware updates to occasionally change behavior.

## How to use

Read individual rule files for detailed explanations and examples:

- [rules/setup-and-connectivity.md](rules/setup-and-connectivity.md) - Discovering the robot, connecting to the local MQTT broker, installing python-yarbo, network security
- [rules/defining-patrol-routes.md](rules/defining-patrol-routes.md) - Designing patrol routes as saved Yarbo plans - perimeter loops, waypoint sweeps, naming conventions
- [rules/running-patrols.md](rules/running-patrols.md) - Starting, pausing, resuming, and aborting a patrol; the command set and payload format
- [rules/scheduling.md](rules/scheduling.md) - Patrol cadence, randomized timing, quiet hours, battery-aware scheduling
- [rules/monitoring-and-alerts.md](rules/monitoring-and-alerts.md) - Telemetry fields, stuck detection, battery watchdog, weather handling, notifications
- [rules/safety.md](rules/safety.md) - Blades off during patrol, emergency stop, people and pets, legal and privacy considerations
- [rules/home-assistant.md](rules/home-assistant.md) - Running patrols through the community_yarbo Home Assistant integration and blueprints

A complete working patrol controller is provided at [scripts/patrol_controller.py](scripts/patrol_controller.py).
