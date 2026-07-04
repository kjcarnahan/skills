# Safety

A patrol sends a 60+ kg robot moving around a property unattended, often at night. These rules are not optional polish; build them into the controller.

## Blades off, always

A patrol never needs the work tool. Before every `start_plan`:

1. Send `set_blade_speed` with 0.
2. Confirm blade state via telemetry before the robot moves.
3. If confirmation doesn't arrive, do not start the patrol.

Do this even when you believe the blades are already off - it must be an invariant of the patrol lifecycle, not an assumption. The same applies to other heads (snow blower auger, trimmer): disarm the tool for the fitted head before departure. The `patrol-` plan naming convention exists so no scheduler path can confuse a patrol with a work plan.

## Stop hierarchy

- `planning_paused` - transient conditions; robot holds position, plan resumable.
- `dstop` - graceful stop; the default abort.
- `emergency_stop_active` - immediate hardware stop; use when the robot is misbehaving near people, animals, or property. After an e-stop, require a human to physically inspect the robot before any software resumes operation.

The physical stop button on the robot always wins. Anyone regularly on the property should know where it is.

## People and pets

- Yarbo's onboard obstacle avoidance is the primary protection, but do not lean on it: schedule patrols for windows when the yard is expected empty, and in Home Assistant gate patrol start on presence (nobody in the yard per cameras/presence sensors).
- Night patrols run lights-on so people can see the robot even if it fails to see them.
- Dogs left out overnight and robots on patrol are a bad combination - either the dog's window or the patrol's window, not both.

## Physical boundaries

Patrols inherit the map and its no-go zones, and RTK keeps position honest - but verify the perimeter route on foot after any map edit. Pay attention to: gates that might be open (a mapped boundary is not a physical one), slopes near the route edge when wet, and pool/pond margins, which should carry generous exclusion buffers.

## Weather and terrain

Do not patrol in active heavy rain, lightning, or on snow/ice with the mower head fitted (wrong head for the traction conditions). Wet slopes that are fine to mow in daylight at low speed deserve wider margins on an unattended night run.

## Legal and privacy

- Keep routes and camera coverage on your own property. A patrol route along a shared fence line points cameras at the neighbor's yard - angle or exclude accordingly.
- Recording laws vary by jurisdiction, particularly for audio. If patrol footage is retained, treat it like any other surveillance recording: know your local rules, retain minimally, secure the storage.
- If the property has staff or regular visitors, disclose that a camera-equipped robot patrols the grounds.

## Failure posture

Design every failure to converge on: robot stopped or docked, human notified, patrol logged as failed. Never design a failure path that retries indefinitely, and never auto-resume after an emergency stop.
