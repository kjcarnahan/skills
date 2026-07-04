# Scheduling patrols

## Cadence

Start simple: a fixed number of patrols per day keyed to the property's quiet risk windows (typically after dusk, midnight-ish, pre-dawn). One perimeter loop per window is a solid default. Add interior sweeps only where the perimeter loop leaves blind spots - more patrols means more battery cycles and more wear; schedule for coverage, not for motion.

## Randomize timing

A patrol that leaves the dock at exactly 22:00 every night is trivially predictable. Add jitter to every scheduled run:

```python
import random
jitter = random.uniform(-25, 25) * 60   # +/- 25 minutes
run_at = scheduled_time + jitter
```

Randomize within the window, not across windows - the pre-dawn patrol should still happen pre-dawn. For higher-security properties, also rotate route direction or alternate between overlapping route variants per night.

## Quiet hours and neighbors

The robot is not silent, and night patrols with lights on are visible. Respect local noise rules and neighbor goodwill: keep routes that hug a shared fence line out of the 23:00-06:00 window, or run those legs lights-dimmed if lighting is the main concern. Deterrence rarely requires provoking a complaint.

## Battery-aware scheduling

- Gate every run on the preflight battery check ([running-patrols.md](running-patrols.md)); a skipped patrol should automatically reschedule once charge recovers, within its window.
- Leave recharge headroom between windows: patrol runtime + full recharge time must fit in the gap, or the next patrol will silently skip every night.
- Winter note: cold reduces effective capacity. Recorded consumption numbers from summer runs will be optimistic in January - re-measure per season, especially with the snow-blower head fitted (heavier module, higher draw even with the tool disarmed).

## Coordinating with real work plans

Patrols and mowing share one robot and one battery. Give mowing/clearing jobs priority: the scheduler must check that no work plan is active or imminent before starting a patrol, and a patrol should never be scheduled where its recharge tail overlaps a mowing window. The `patrol-` plan-name prefix ([defining-patrol-routes.md](defining-patrol-routes.md)) keeps the two categories unambiguous in scheduler logic.

## Where to run the scheduler

- **Standalone**: cron or a systemd timer invoking [scripts/patrol_controller.py](../scripts/patrol_controller.py) - simplest, no dependencies beyond the library.
- **Home Assistant**: time-triggered automations calling `community_yarbo.start_plan`, which composes naturally with presence, weather, and camera entities (see [home-assistant.md](home-assistant.md)). Prefer this when patrols should react to other sensors - e.g. skip the patrol when someone is in the yard, or trigger a chokepoint check when the driveway camera fires.
