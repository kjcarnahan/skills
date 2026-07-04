# Home Assistant integration

The community integration [`markus-lassfolk/home-assistant-yarbo`](https://github.com/markus-lassfolk/home-assistant-yarbo) (HACS) exposes the same local MQTT surface as entities and services, which makes it the best host for patrols that should react to other sensors - presence, cameras, weather, door contacts.

## Setup

Install via HACS, then add the integration. The config flow auto-discovers the base station (DHCP MAC OUI `C8:FE:0F`), connects to MQTT on port 1883, waits for telemetry, and extracts the serial number. Enable the extended sensors you need (RTK, satellites, heading are disabled by default).

## Relevant services

| Service | Use in patrols |
| --- | --- |
| `community_yarbo.start_plan` | Start a patrol route (saved plan) |
| `community_yarbo.pause` / `community_yarbo.resume` | Transient holds (rain, person in yard) |
| `community_yarbo.return_to_dock` | End of patrol / abort |
| `community_yarbo.set_lights` | Lights on for night patrols |
| `community_yarbo.send_command` | Raw MQTT for anything not wrapped (e.g. blade speed 0 preflight) |

Sensors cover battery, activity state, attached module, charging, error flags, and (extended) RTK/satellites/heading. The GPS device tracker entity puts the robot on the HA map - useful for the stuck-detection and position-based alerts described in [monitoring-and-alerts.md](monitoring-and-alerts.md).

## Patrol automation shape

A patrol automation should mirror the lifecycle in [running-patrols.md](running-patrols.md):

```yaml
alias: Night perimeter patrol
triggers:
  - trigger: time
    at: "22:30:00"
conditions:
  - condition: numeric_state
    entity_id: sensor.yarbo_battery
    above: 55
  - condition: state
    entity_id: sensor.yarbo_activity
    state: "idle"
  - condition: state          # nobody in the yard
    entity_id: binary_sensor.yard_occupancy
    state: "off"
actions:
  - delay: "{{ '00:%02d:00' | format(range(0, 25) | random) }}"   # jitter
  - action: community_yarbo.send_command
    data: { command: set_blade_speed, payload: { speed: 0 } }
  - action: community_yarbo.set_lights
    data: { state: on }
  - action: community_yarbo.start_plan
    data: { plan: patrol-perimeter }
```

Pair it with watchdog automations: a rain-triggered pause/dock (the integration ships a blueprint for exactly this), a battery-floor abort, and a "still active past runtime ceiling" alert using a `for:` duration on the activity sensor.

## Event-driven chokepoint checks

The pattern that standalone cron can't do: trigger a short targeted route from another sensor.

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.driveway_camera_person
    to: "on"
conditions:
  - condition: state
    entity_id: sensor.yarbo_activity
    state: "idle"
actions:
  - action: community_yarbo.start_plan
    data: { plan: patrol-driveway-check }
```

Keep event-driven patrols rate-limited (automation `mode: single` plus a cooldown condition) so a busy squirrel doesn't run the battery down by dinnertime.
