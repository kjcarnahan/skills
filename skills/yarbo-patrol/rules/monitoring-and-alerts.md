# Monitoring and alerts

An unmonitored patrol is worse than none: the robot can sit stuck against a gate all night while you believe the grounds were covered. Every patrol run needs a live watchdog.

## Telemetry

`DeviceMSG` streams at ~1-2 Hz on `snowbot/{SN}/device/DeviceMSG`. Parsed fields (`YarboTelemetry`):

- `battery` - percent, 0-100
- `state` - `"idle"` or `"active"`
- `heading` - degrees
- `position_x`, `position_y` - meters, RTK-relative
- `speed` - m/s
- `raw` - full DeviceMSG dict (RTK fix quality, satellites, charging state, head type, error flags, rain sensor live here)

`heart_beat` (~1 Hz) is a liveness signal; `plan_feedback` fires on plan state changes.

## Watchdog rules

Run these continuously during a patrol; on trip, follow the abort path in [running-patrols.md](running-patrols.md).

**Stuck detection.** Track position over a rolling 90-second window. If displacement stays under ~1 m while `state` is `"active"`, the robot is stuck (wheel-spinning on mud, wedged, or endlessly replanning). Pause, wait 15 s, resume once; if still stuck, abort and alert with the GPS position.

**Heartbeat loss.** No `heart_beat` for 30 s means you've lost the link (robot out of base-station range, broker down, network fault). You cannot command what you cannot reach - alert immediately and keep listening; the robot's own onboard failsafes handle local safety, but the patrol is over.

**Battery floor.** Abort to dock the moment battery drops below the greater of 25% or (distance-home estimate + 10 points). Never let a patrol run the battery to the robot's own low-battery behavior - you want docking to be your decision, logged, not a surprise.

**Runtime ceiling.** Each route has a recorded normal runtime (from route verification). Abort at 1.5x that number regardless of what telemetry claims - it catches every failure mode you didn't think of.

**Weather.** On rain detection (rain sensor in `raw`, or an external weather feed), pause and evaluate: light drizzle is usually fine to resume after a few minutes; sustained rain means dock and reschedule. Traction and RTK both degrade wet.

**RTK degradation.** If fix quality drops and stays degraded for over a minute, treat it like stuck: the robot may hold position waiting for fix. Pause/resume once, then abort.

## Anomaly observations

A patrol is a sensor sweep. Log per run: start/end time, route, battery consumed, pauses and their causes, and every watchdog event with position. Diffs against the route's baseline are the interesting output - a patrol that suddenly takes 12 minutes longer on the same route, or pauses at the same fence corner three nights running, is telling you something changed on the ground. Surface those diffs in the completion notification, not just "patrol done."

## Notification tiers

- **Info** (log only): normal completion, scheduled skip with reason.
- **Notify** (push/message): patrol aborted and docked successfully, patrol skipped two consecutive windows, route ran anomalously long.
- **Urgent** (wake someone): heartbeat loss, emergency stop issued, robot failed to dock after abort, stuck and unrecovered.
