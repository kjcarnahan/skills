# Defining patrol routes

Patrol routes are ordinary **saved plans** created in the Yarbo app. The MQTT surface can start, pause, resume, and stop a saved plan, but it cannot author one - route geometry, no-go zones, and RTK mapping all live in the app. Design routes there, then drive them from this module.

## Route design patterns

**Perimeter loop.** A narrow plan that traces the property boundary just inside the fence line. This is the workhorse patrol: maximum ground covered per minute, passes every gate and approach. Keep it a single continuous loop so a patrol is one plan execution.

**Waypoint sweep.** A plan that snakes through interior areas of interest - driveway, outbuildings, garden, blind spots not visible from the house. Use the app's zone editing to shape the pass pattern so the robot's cameras face the structures, not away from them.

**Chokepoint check.** Short plans that visit one specific spot (rear gate, shed door) and return. Useful as targeted follow-ups when a sensor elsewhere (driveway camera, gate contact) raises suspicion.

## Practical rules

- **One patrol = one plan.** Chain multiple plans from the controller if you want a compound patrol (perimeter, then interior sweep). Let each plan end near the dock or near the start of the next plan to avoid long dead transits.
- **Name plans with a `patrol-` prefix** in the app (`patrol-perimeter`, `patrol-driveway`) so patrol routes stay visually separate from real mowing plans. Note that `start_plan` references plans by **numeric `planId`**, not name - after creating a plan, run it once from the app while `scripts/sniff_commands.py` is watching and record the `planId` from `plan_feedback` alongside the name.
- **Respect no-go zones.** Patrols inherit the map's exclusion zones. Verify soft surfaces (flower beds, play areas) are excluded before scheduling night patrols - a patrol that tears up mulch at 2 a.m. is worse than no patrol.
- **Size routes to battery.** A patrol should complete on comfortably less than a full charge (target under 50% consumption) so the robot can always dock, and so back-to-back patrols after a partial recharge remain possible. Check consumption by running the plan once while watching the `battery` telemetry field.
- **Mind RTK coverage.** Route legs that pass under dense tree canopy or close to tall metal buildings can lose RTK fix. Watch the RTK/satellite telemetry on a trial run and reroute legs where fix quality drops - a patrol that pauses for signal every night is not a patrol.

## Verifying a new route

1. Run the plan manually from the app once, walking along with the robot.
2. Run it once via `start_plan` from the controller while watching telemetry (`position_x/y`, `speed`, `state`).
3. Record total runtime and battery consumed; store both with the route definition so the scheduler and watchdog have real numbers (see [monitoring-and-alerts.md](monitoring-and-alerts.md)).
