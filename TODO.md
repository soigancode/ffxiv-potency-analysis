# Development tasks

## Validate current jobs

- Audit a real Machinist log with Bioblaster. Check application hits, target-specific ticks, snapshots, and total potency; add a regression case for any behavior the existing tests miss.
- Handle a food buff expiring, a mechanic's damage-down debuff, and the two damage penalties after a revive. Check how each appears in events and how it affects potency and damage-based classification.
- Check how Astrologian's The Balance and The Spear appear in FF Logs damage multipliers and whether variable-potency classification already removes their effects correctly.
- Revisit Machinist Queen and Rook scaling if the exact damage formula becomes available.
- Improve variable-potency estimates if FF Logs exposes the underlying resources.

## FF Logs and reports

- Support FF Logs partitions when selecting rankings and reports.
- Handle adds excluded from FF Logs rankings if a supported encounter uses them.
- Let users select a fight and player from an unselected report URL or report ID.
- Generate a navigable HTML report from exported analysis JSON.

## Jobs, gear, and content

- Import traits that affect action damage without listing new potency from the job guide. Replace the manually configured multipliers where the imported data is reliable.
- Support additional jobs and validate them against real logs.
- Support older (synced) ultimates.
- Support more gear profiles or user-provided stats. For older or synced content, distinguish the encounter's release patch from the patch and gear used to play it.

## Test organization

- Split mixed analysis tests by responsibility as they grow: shared hit and potion behavior versus Machinist pet behavior. Split the large CLI test file by command when editing those areas. Keep the real-log audit tests grouped by fight.
