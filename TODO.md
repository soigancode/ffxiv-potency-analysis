# Development tasks

## Validate current jobs

- Audit a real Machinist log with Bioblaster. Check application hits, target-specific ticks, snapshots, and total potency; add a regression case for any behavior the existing tests miss.
- Complete damage-penalty handling using representative player logs: a BRD food-expiry regression now reconstructs `Well Fed` windows and adjusts the Crit baseline and damage-based classification. Current audit fixtures have no selected player's landed hit under Damage Down, Weakness, or Brink of Death. The downloader saves player-targeted Debuffs events; verify encounter-specific Damage Down factors and snapshot timing before changing potency or BRD damage classification for those penalties.
- Check how Astrologian's The Balance and The Spear appear in FF Logs damage multipliers and whether variable-potency classification already removes their effects correctly.
- Revisit Machinist Queen and Rook scaling if the exact damage formula becomes available.
- Improve variable-potency estimates if FF Logs exposes the underlying resources.

## FF Logs and reports

- Support FF Logs partitions when selecting rankings and reports.
- Handle adds excluded from FF Logs rankings if a supported encounter uses them.
- Let users select a fight and player from an unselected report URL or report ID.
- Generate a navigable HTML report from exported analysis JSON.

## Jobs, gear, and content

- Interpret additional damage-affecting traits from the job guide when adding jobs or synced levels. BRD and MCH Increased Action Damage traits are already exported and used for auto-attack conversion at level 100.
- Support additional jobs and validate them against real logs.
- Support older (synced) ultimates.
- Support more gear profiles or user-provided stats. For older or synced content, distinguish the encounter's release patch from the patch and gear used to play it.

## Test organization

- Split mixed analysis tests by responsibility as they grow: shared hit and potion behavior versus Machinist pet behavior. Split the large CLI test file by command when editing those areas. Keep the real-log audit tests grouped by fight.
