# Development tasks

## Validate current jobs

- Revisit Machinist Queen and Rook scaling if the exact damage formula becomes available.
- Improve variable-potency estimates if FF Logs exposes the underlying resources.

## FF Logs and reports

- Cache per-player analysis results so ranking comparisons and later single-log views reuse calculations. Invalidate when the analyzer revision or any relevant log, action, gear, consumable, encounter, or raid-effect data changes; keep presentation formatting outside the cache.
- Handle adds excluded from FF Logs rankings if a supported encounter uses them.
- Let users select a fight and player from an unselected report URL or report ID.
- Generate a navigable HTML report from exported analysis JSON.

## Jobs, gear, and content

- Interpret additional damage-affecting traits from the job guide when adding jobs or synced levels. BRD and MCH Increased Action Damage traits are already exported and used for auto-attack conversion at level 100.
- Support additional jobs and validate them against real logs.
- When adding a tank or melee job, verify Astrologian's The Balance on a real log. The Spear is already covered for Bard.
- Support older (synced) ultimates.
- Support more gear profiles or user-provided stats. For older or synced content, distinguish the encounter's release patch from the patch and gear used to play it.

## Data layout

- Move job-specific reference data under `data/jobs/<job>/` when adding more jobs. Keep shared consumables, raid effects, and encounters outside that folder.

## Test organization

- Split mixed analysis tests by responsibility as they grow: shared hit and potion behavior versus Machinist pet behavior. Split the large CLI test file by command when editing those areas. Keep the real-log audit tests grouped by fight.
