# Running patrols

## Command set

Commands are published to `snowbot/{SN}/app/{cmd}` as JSON envelopes (`cmd`, `sn`, `timestamp`, `payload`), zlib-compressed. The ones a patrol controller needs:

| Command | Effect |
| --- | --- |
| `start_plan` | Start a saved plan (the patrol route) |
| `planning_paused` | Pause the active plan in place |
| `resume` | Resume a paused plan |
| `dstop` | Graceful stop of current activity |
| `emergency_stop_active` | Immediate hardware stop - reserve for emergencies |
| `cmd_recharge` | Return to dock and charge |
| `set_blade_speed` | Blade speed - **set to 0 before every patrol** (see [safety.md](safety.md)) |
| `light_ctrl` | LED control - lights on for night patrols aid deterrence and the robot's own visibility |
| `cmd_buzzer` | Buzzer on/off (`{"state": 1}`) - **silently ignored on tested firmware**; the app's Find My Yarbo beep travels via Yarbo's cloud, not the local broker, so do not rely on a local chirp |

With `python-yarbo`, high-level helpers cover lights (`lights_on()`/`lights_off()`), buzzer (`buzzer()`), and telemetry; anything without a helper goes through `publish_raw(cmd, payload)`:

```python
await client.publish_raw("start_plan", {"plan": "patrol-perimeter"})
```

Acquire the controller (`get_controller()`) before sending drive-affecting commands - the robot accepts commands from one controller at a time, and this avoids fighting the app if someone has it open.

## Patrol lifecycle

A single patrol run should always follow this sequence:

1. **Preflight.** Read one telemetry snapshot. Require: `state == "idle"`, battery above the route's recorded consumption plus a 20-point margin, no error flags, robot docked or at a known position. Skip the patrol (and log why) if any check fails - never force it.
2. **Disarm the tool.** `set_blade_speed` to 0. Confirm via telemetry before moving.
3. **Announce.** Lights on (night patrols: always). Lights are the announcement - the local buzzer command does not sound on tested firmware.
4. **Start.** `start_plan` with the patrol route. Watch `plan_feedback` and `DeviceMSG` for confirmation that the plan actually started; if `state` is still idle after 30 s, retry once, then abort and alert.
5. **Monitor.** Stream telemetry for the whole run - position, speed, battery, RTK fix, error flags. The watchdog rules live in [monitoring-and-alerts.md](monitoring-and-alerts.md).
6. **Complete.** On plan completion (idle state near route end, or completion feedback), send `cmd_recharge` unless the route already ends at the dock. Log runtime, battery consumed, and any incidents.
7. **Abort path.** On watchdog trip: `dstop`, then `cmd_recharge`, then alert. If the robot does not respond to `dstop`, escalate to `emergency_stop_active` and alert as an incident requiring a human.

## Pause and resume

`planning_paused` / `resume` preserve plan progress. Use them for transient conditions (rain shower expected to pass, person detected on the route) rather than aborting. Cap total paused time - if a patrol has been paused longer than the route's normal runtime, abort and dock instead of resuming into stale conditions.

## Chaining routes

For compound patrols, run plans sequentially from the controller: wait for plan N to reach a completed/idle state before issuing `start_plan` for plan N+1, and re-run the battery preflight between legs. Do not queue-fire multiple `start_plan` commands.
