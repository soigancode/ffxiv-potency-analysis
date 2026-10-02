# FFXIV Potency Analysis

Compare logs from the **same job and fight** by the potency of attacks that actually dealt damage. Potency removes the random damage roll and Crit/Direct Hit damage variance, making it easier to compare rotations. The tool also shows potency per second (PPS), hit luck, and FF Logs rDPS and nDPS.

**Current support:** level 100 with configured gear, for fights played during patches 7.4–7.56.

Supported duties:

- Heavyweight (Savage, M9S–M12S)
- Dancing Mad (Ultimate)
- Doomtrain and Enuo (Extreme)
- Another Merchant's Tale (Criterion)
- Mistwake and The Clyteum (Dungeons)

| Patch | Supported jobs |
| --- | --- |
| 7.4–7.56 | Warrior (WAR), Bard (BRD), Machinist (MCH), Dancer (DNC) |

Leaderboard support covers the global partitions, including Savage Echo. Dungeon fights use their played date to identify the patch. See [Limitations](#limitations) for gear and sync assumptions.

## Contents

- [Get started](#get-started)
- [How to use it](#how-to-use-it)
  - [Rankings](#rankings)
  - [Analyse one log](#analyse-one-log)
  - [Compare your logs](#compare-your-logs)
- [Understanding the results](#understanding-the-results)
- [Calculation details](#calculation-details)
  - [Shared calculations](#shared-calculations)
  - [Warrior](#warrior)
  - [Bard](#bard)
  - [Machinist](#machinist)
  - [Dancer](#dancer)
- [Limitations](#limitations)
- [Future features](#future-features)

## Get started

Install Python 3.11 or newer. In the project folder on Linux or macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell instead. Activate the environment again in each new terminal session.

Create an FF Logs V2 API client and put its ID and secret in a `.env` file in the project root:

```text
FFLOGS_CLIENT_ID=your_client_id
FFLOGS_CLIENT_SECRET=your_client_secret
```

The tool reads `.env` automatically. Keep it private. Required job data is included in the repository.

## How to use it

### Rankings

Compare the current top ten accessible logs for a job and fight, ordered by FF Logs rDPS. Mistwake and The Clyteum use DPS rankings:

```bash
ffxiv-potency fflogs brd umad
ffxiv-potency fflogs mch m10s
```

Analyse **any leaderboard position** instead:

```bash
ffxiv-potency fflogs brd umad 3
```

Compare an inclusive range or select individual ranks:

```bash
ffxiv-potency fflogs mch m11s 20-25
ffxiv-potency fflogs mch m10s 1,2,3,153
```

Ranges and comma-separated selections contain 2–25 distinct leaderboard positions. The numbers represent the actual ranks on FF Logs. Inaccessible or ambiguous ranks are skipped. Anonymous reports work when the player can be identified from the selected fight. Downloads are reused.

| Fight | Encounter |
| --- | --- |
| `m9s` | Vamp Fatale (Savage) |
| `m10s` | Red Hot and Deep Blue (Savage) |
| `m11s` | The Tyrant (Savage) |
| `m12sp1` | Lindwurm (Savage) |
| `m12sp2` | Lindwurm II (Savage) |
| `dmu` or `umad` | Dancing Mad Ultimate |
| `doomtrain` | Doomtrain (Extreme) |
| `enuo` | Enuo (Extreme) |
| `amt` | Another Merchant's Tale |
| `mistwake` | Mistwake |
| `clyteum` | The Clyteum |

Use `war`, `brd`, `mch`, or `dnc` for the job. The full job names also work.

The `--partition` option is optional. Savage defaults to the global 7.5 standard-composition leaderboard. To select another global leaderboard:

```bash
ffxiv-potency fflogs mch m9s 1 --partition 13
ffxiv-potency fflogs brd m11s 20-25 --partition 2
```

| Savage partition | Patch | Composition | Echo |
| ---: | --- | --- | --- |
| 1 | 7.4 | Standard | No |
| 2 | 7.4 | Non-standard | No |
| 7 | 7.5 | Standard | No |
| 8 | 7.5 | Non-standard | No |
| 13 | 7.5 | Standard | Yes |
| 14 | 7.5 | Non-standard | Yes |

Dancing Mad defaults to partition 1. Use partition 2 for non-standard compositions. Only global FF Logs partitions are supported.

Doomtrain and Enuo default to partition 7. Doomtrain also supports partitions 1, 2, and 8. Enuo also supports partition 8. Extreme fights with Echo are not supported.

### Analyse one log

Provide a report link to choose a fight and a supported player from the report:

```bash
ffxiv-potency analyse "https://www.fflogs.com/reports/REPORT1"
```

Bare report IDs also work with `analyse`, `fflogs`, and `compare`, for example `ffxiv-potency analyse XhcqCfrJzNgZdQxP`.

When there is only one supported fight or player, it is selected automatically.

A link with `fight` and `source` already selected runs without the prompts:

```bash
ffxiv-potency analyse "https://www.fflogs.com/reports/REPORT1?fight=9&source=18"
```

The report shows the player, fight, duration, date, patch, assumed gear, potency, PPS, and FF Logs damage metrics. It marks wipes and lists deaths and damage penalties. Below the summary are action totals, hit outcomes, potions, auto-attacks, and job-specific details.

To save a fight without analysing it, run `ffxiv-potency fflogs "<report URL>"`.

| Command | Removes |
| --- | --- |
| `ffxiv-potency clear logs` | Downloaded logs |
| `ffxiv-potency clear cache` | Saved calculations |
| `ffxiv-potency clear` | Both |

These commands ask for confirmation and leave job data intact. Add `--yes` to skip the prompt.

The tool remembers calculated results to speed up later views. Clearing logs frees storage while keeping these results. After downloading a log again, the tool reuses its calculation if the log and analysis data are unchanged.

The analysis shows the patch in effect on the fight date and the gear assumed for that patch. This can differ from FF Logs’ broader ranking patch bracket shown above a leaderboard. Gear is an assumption, not equipment recovered from the log.

The default is **7.4 Savage BiS** before patch 7.55 and **7.55 Relic BiS** from 7.55 until 8.0. To choose a different set, add `--gear savage_7_4` or `--gear relic_7_55` to `analyse`, `compare`, or a leaderboard command. The choice applies to all logs in that command. Run `analyse` to see the gear used for a particular log.

### Compare your logs

Provide two to ten URLs for the **same job and encounter**:

```bash
ffxiv-potency compare \
  "https://www.fflogs.com/reports/REPORT1?fight=9&source=18" \
  "https://www.fflogs.com/reports/REPORT2?fight=4&source=7"
```

The comparison shows full duration, targetable time, rDPS, nDPS, landed potency, PPS, aHB, Luck, adjusted Luck, partition, patch, and the fight date in UTC (`dd/mm/yy`). Saved fights are reused.

WAR and MCH combine equal rDPS and nDPS values in one **rDPS/nDPS** column.

## Understanding the results

**Potency** adds the potency of hits that landed, including configured personal buffs and potion gains. It also accounts for pet actions and estimates auto-attack potency. Multi-target hits use their action's falloff rules. Recorded overkill reduces the credited potency in proportion to damage dealt. Other players' damage buffs do **not** increase personal potency. **PPS** divides total potency by targetable time in seconds.

**Luck** shows how favorable the observed Crit and Direct Hit outcomes were, weighted by each hit's potency. A critical hit contributes more than a Direct Hit because its configured damage multiplier is larger. **Luck baseline** shows the expected score from the configured unbuffed gear rates. Comparing the two indicates whether hit outcomes were favorable for that gear profile. It does not measure rotation quality.

**Adjusted Luck** (`aLuck` in comparisons) subtracts the *expected* benefit of tracked party and target Crit/DH rate buffs. The original Luck score remains visible because those actual outcomes still affect FF Logs damage rankings. Adjusted Luck does not change potency or PPS. [The formulas](#luck-and-adjusted-luck) explain both scores.

FF Logs **rDPS and nDPS** remain the original reported damage metrics. Potency and PPS measure a different thing: landed action value without Crit, Direct Hit, or base damage roll variance. Compare the same fight and job, with comparable gear and stats.

## Calculation details

### Shared calculations

#### Targetable time

PPS uses time when an enemy is available for damage. Simultaneous enemies count once, while encounter transitions and travel between enemy groups are excluded. Full duration and the excluded time remain visible in analyse.

Supported raid and trial kills use the duration established by FF Logs damage and DPS when consistent with the enemy timeline. Dungeon and Criterion runs use encounter-wide enemy appearances, targetability updates, deaths, and lethal hits. Unknown spawn times begin at the first party hit, so these windows are marked estimated. A missing timeline falls back to full duration and is labelled unavailable. Ordinary gaps between a player's attacks never count as downtime.

#### Food

Configured gear stats include food bonuses.

When FF Logs records `Well Fed` ending or being reapplied, the report shows the interval without food. During that interval, BRD damage-based potency estimates use the lower Determination and Crit values, and luck baselines use the lower Crit rate. Food does not directly multiply action potency. If no food changes are recorded, the configured food is assumed throughout the fight and marked unverified in the report.

#### Potions

HQ Gemdraughts increase the job's main stat by 10%, up to the item's cap, for 30 seconds. Extra potency follows the change in the tiered main-stat damage factor:

```math
P_{\mathrm{potted}} = P_{\mathrm{base}}\times
\frac{f_{\mathrm{main}}(\mathrm{potted\ stat})}{f_{\mathrm{main}}(\mathrm{unpotted\ stat})}.
```

Party bonuses come from the fight roster. At level 100, the main-stat coefficient is 190 for tanks and 237 for the supported ranged jobs. Pet damage uses its own configured factor. DoTs and delayed effects such as Wildfire retain the potion state at application.

#### Damage penalties

Weakness reduces the player's main damage stat by 25%. Brink of Death reduces it by 50%. These effects apply across encounters. The tool calculates their damage factors from the configured gear, accounting for a potion when one overlaps the hit.

Damage Down strength is configured by encounter. The tool reduces potency on landed hits carrying that status. Older DoT snapshots without it retain their potency. Consecutive applications appear as one interval with refresh times and a combined affected-hit count.

#### Auto-attacks

Auto-attacks have no current official listed potency in the job guide. The reference values are **90** for WAR and DNC's melee Attack and **80** for BRD and MCH's Shot. These values agree with damage-per-potency comparisons in the supplied logs. The tool estimates weapon delay from consecutive hits and matches it to a known delay for the job. BRD's Shots under Army's Paeon or Army's Muse still count toward potency, but do not set the base weapon-delay estimate. It reports an error if no known delay is close enough. Action-comparable potency per auto-attack is:

```math
P_{\mathrm{auto}}=P_{\mathrm{base}}\times
\frac{\left\lfloor F\times\text{weapon delay}/3\right\rfloor}{F}
\times\frac{\text{Skill Speed factor}}{\text{action-damage trait multiplier}}.
```

```math
F=\left\lfloor\frac{\text{level main stat}\times
\text{job attribute modifier}}{1000}\right\rfloor
+\text{weapon damage}.
```

WAR uses an action-damage trait multiplier of `1.0`. BRD, MCH, and DNC divide by `1.2` because their action-damage trait does not apply to auto-attacks. With the configured stats, WAR's 3.36 s weapon delay gives about **100.59 action-comparable potency per Attack**, MCH's 2.64 s delay gives **58.65 potency per Shot**, and DNC's 3.12 s delay gives **77.88 potency per Attack**, before potion effects. These approximations agree with the damage-per-potency comparisons in checked logs.

#### Hit Bonus and Adjusted Hit Bonus

**HB** is the potency-weighted damage bonus from recorded Crits and Direct Hits, including guaranteed outcomes. **aHB** subtracts the expected contribution from external Crit/DH rate buffs. A value of +48% means those outcomes add 48% damage over the same observed attacks without their Crit/DH bonuses. Only aHB appears between PPS and Luck in leaderboards and comparisons. Analyse uses the full names **Hit Bonus** and **Adjusted Hit Bonus**.

Guaranteed hits include both the Direct Hit attribute conversion and the deterministic damage benefit from external Crit/DH rate buffs. Explicitly non-random damage such as Wildfire contributes potency with no hit bonus. Periodic damage without a recorded outcome is excluded. The metric uses configured gear and observed outcomes, rather than converting potency into FF Logs nDPS. Unlike Luck, it also depends on the mix of attacks used.

#### Luck and adjusted Luck

For each eligible landed hit $i$, let $P_i$ be its potency (including potion gains), $C$ the critical damage multiplier calculated from the configured Crit stat, and $M_i$ its observed multiplier:

| Outcome | $M_i$ |
| --- | ---: |
| Normal Hit | $1$ |
| Direct Hit | $1.25$ |
| Critical Hit | $C$ |
| Direct Critical Hit | $1.25C$ |

```math
\mathrm{Luck}=100\%\times
\frac{\sum_i P_i(M_i-1)}{\sum_i P_i(1.25C-1)}.
```

Zero means no eligible hit rolled Crit or DH. A score of 100% means every eligible hit rolled both. Guaranteed Crit/DH and configured non-random damage, such as Wildfire, are excluded from **both sums**. Eligible pet hits and auto-attacks count too. This is an observed score, not a probability or an FF Logs ranking metric.

With gear Crit chance $p_C$ and DH chance $p_D$, the unbuffed Luck baseline is:

```math
\mathrm{Baseline}=100\%\times
\frac{(1+p_C(C-1))(1+0.25p_D)-1}{1.25C-1}.
```

The analysis also prints each hit outcome's observed rate beside its gear baseline. For adjusted Luck, the tool calculates the expected extra hit bonus from Crit/DH rate buffs active on each hit. With buffed chances $p'_C$ and $p'_D$:

```math
A_i=(1+p'_C(C-1))(1+0.25p'_D)
-(1+p_C(C-1))(1+0.25p_D).
```

```math
\mathrm{Adjusted\ Luck}=100\%\times
\min\!\left(1,\max\!\left(0,
\frac{\sum_i P_i\bigl((M_i-1)-A_i\bigr)}
{\sum_i P_i(1.25C-1)}\right)\right).
```

Tracked effects are Battle Litany, Battle Voice, Army's Paeon, the Wanderer's Minuet, Devilment on the Dancer or Dance Partner, and Chain Stratagem on the target. The adjustment subtracts the **expected** buff benefit. It does not erase actual Crits or Direct Hits.

### Warrior

#### Potencies and personal buffs

| Action | Before 7.5 | From 7.5 |
| --- | ---: | ---: |
| Inner Chaos | 660 | 700 |
| Primal Rend | 700 | 720 |
| Primal Ruination | 780 | 800 |

Comboed Maim has 340 potency, Storm's Path and Storm's Eye have 500, and Mythril Tempest has 140. Other hits use their base potency. Primal Rend, Primal Ruination, and Primal Wrath deal 50% potency to additional targets. WAR's other damaging AoEs have no falloff.

Surging Tempest adds 10% personal damage. The attack that first grants it uses the preceding buff state. Damnation contributes 55 potency per landed counterattack. Its defensive cast is not a ghosted attack when no counterattack occurs.

Inner Chaos, Chaotic Cyclone, Primal Rend, and Primal Ruination guarantee critical direct hits. Inner Release guarantees them for Fell Cleave and Decimate, but not other actions. Beast Gauge controls spender availability without changing potency.

#### Execution summary

Analyse shows Surging Tempest uptime, attacks without it, and their lost potency. Inner Release lists uses and unused charges at confirmed expiry. Primal Rend, Primal Ruination, Primal Wrath, and Nascent Chaos list ready grants, uses, expirations, and overwrites. Pre-pull effects count as grants. Consuming a ready effect counts as use even if the damage ghosts. Effects still active at the fight's end are not counted as wasted.

Melee downtime groups consecutive Tomahawks into one line, timestamped at the first Tomahawk. It shows the preceding and following melee GCDs and every gap between casts. Abilities woven between GCDs do not break the chain. No exact replacement loss is assigned because the available melee action is uncertain.

### Bard

#### Songs and personal buffs

Songs grant distinct Codas. Radiant Finale consumes them for a 2%, 4%, or 6% personal damage bonus. Radiant Encore then deals 700, 800, or 1,100 potency, with 50% potency on additional targets. Raging Strikes adds 15% damage. The report shows consumed Codas, Encore potency, and song durations.

Barrage makes Refulgent Arrow strike three times or raises Shadowbite to 300 potency. Caustic Bite and Stormbite retain their personal buff snapshot on each target. Iron Jaws refreshes both effects with a new snapshot. Application damage and tick potency are reported separately.

#### Variable potency from damage

Pitch Perfect has 100, 220, or 360 potency for one, two, or three stacks. Apex Arrow has $140+7(G-20)$ potency for Soul Voice Gauge $G$ from 20 to 100. Using at least 80 gauge grants Blast Arrow Ready.

Hidden resource values are estimated from normalized damage. Burst Shot (220), Refulgent Arrow (280), Empyreal Arrow (260), and Heartbreak Shot (180) provide fixed-potency references. Each hit is divided by its Crit/DH outcome and recorded damage multiplier. Potted hits correct FF Logs' recorded 1.05 factor to the configured potion factor $Q$:

```math
D_{\mathrm{norm}}=\frac{D_{\mathrm{logged}}}{C^{I_C}\,1.25^{I_D}\,M_{\mathrm{FF}}}\times Q.
```

The median normalized damage per reference potency establishes a local baseline. Up to 30 nearby same-target hits are used. Fewer than three references trigger a less-certain fallback. Overkill hits cannot establish the baseline.

Candidate potencies allow a 94%–106% damage roll plus 0.5% rounding tolerance. Multi-target damage narrows falloff assignments, and Blast Arrow narrows Apex candidates to 80–100 gauge. Multiple plausible fits remain visible. The nearest fit is flagged when none matches. These are deterministic estimates rather than recovered gauge values.

### Machinist

#### Hypercharge and Wildfire

Hypercharge grants five stacks that add 20 potency to single-target weaponskills, including Blazing Shot. Auto Crossbow receives no bonus. Reassemble guarantees a critical direct hit on the next eligible weaponskill. Full Metal Field guarantees that outcome independently.

Wildfire adds 240 potency per weaponskill that lands during its ten-second window, up to six hits and 1,440 potency. Pet attacks and auto-attacks do not contribute. Detonator can end the window early. Wildfire does not roll Crit or DH. Each detonation lists its contributing weaponskills and potency.

#### Automaton Queen and Battery

Queen spends 50–100 Battery, with attack potency scaled linearly between those endpoints:

```math
P(G)=P_{50}+(P_{100}-P_{50})\frac{G-50}{50}.
```

Queen and Rook damage uses an approximate 0.89 conversion to player-comparable potency. The report groups attacks by deployment and identifies missing Queen finishers and early Overdrive use. Successful action resolutions grant Battery even if their damage later ghosts.

For Lindwurm II, the preceding phase-one kill establishes carried Battery when available. A pre-pull Queen's spent Battery is counted separately. Otherwise, later Queens with known Battery can narrow the opening gauge to 50, 60, 70, 80, 90, or 100. A unique fit requires at least two opening hits and two comparable later Queens, allowing a 95%–105% damage roll, multiplier rounding of ±0.005, and damage rounding of ±2. Overkill and damage-penalty hits cannot establish the reference. An unresolved opening Queen retains a labelled 100-Battery assumption.

### Dancer

#### Finishes and personal buffs

| Successful steps | Standard Finish | Technical Finish |
| ---: | ---: | ---: |
| 0 | 360 | 350 |
| 1 | 540 | 540 |
| 2 | 850 | 720 |
| 3 | — | 900 |
| 4 | — | 1,300 |

Standard Finish grants 2% or 5% damage for one or two steps, lasting 60 seconds. Technical Finish grants 1%, 2%, 3%, or 5% for one through four steps, lasting 20 seconds. Zero steps grant no bonus. Finishing Move deals 850 potency and grants the full Standard Finish bonus.

The Dancer's own finish bonuses multiply together. Another Dancer's bonuses do not add personal potency. Finish damage uses the buff state before its own grant or refresh. Pre-pull strength must have a unique fit from recorded damage multipliers.

Major damaging AoEs deal 40% potency to additional targets. Starfall Dance deals 25% and guarantees a critical direct hit. Devilment adds 20 percentage points to Crit and DH chances for the Dancer and Dance Partner.

#### Feathers and Threefold

Cascade and Windmill have a 50% Symmetry chance. Comboed Fountain and Bladeshower have a 50% Flow chance. The enabled proc GCD then has a separate 50% Feather chance, making the ordinary two-roll chain 25%. Flourish skips the unlock roll and grants a separate guaranteed Threefold effect. Fan Dance and Fan Dance II spend one feather and each make another 50% Threefold roll.

The report separates random and Flourish grants, consumption, overwrites, expiry, death losses, and remaining effects. AoEs make one proc roll per use, rather than per target. Esprit controls Saber Dance availability without changing its 540 potency. Dance of the Dawn replaces an eligible use with 1,000 potency. Random party-generated Esprit is not reconstructed.

The Feather gauge holds four. Starting feathers are zero for fresh pulls and complete Dungeon or Criterion runs. M12S phase-two carry-over or missing checkpoint context allows 0–4. Generating actions, spending actions, the cap, and death resets bound successful Feather rolls. Ending gauge and overcap are unlogged, so displayed Feather scores are minimums supported by the log.

#### Luck indices and combined score

Stage rarity indices use $100\Phi(Z)$, where $\Phi$ is the standard normal cumulative distribution function. The baseline is 50. For the Feather chain, initial grants $R$ are weighted by their subsequent Feather chance $q=0.5$ and combined with successful Feather rolls $S$:

```math
Z=\frac{q(R-E_R)+(S-E_S)}{\sqrt{q^2V_R+V_S}},\qquad
E=np,\quad V=np(1-p).
```

Threefold has its own rarity index. These indices describe surplus relative to sample size, rather than proc chance or an exact percentile. They can approach 100 without every roll succeeding.

The final **Feather luck score** combines all three observed random rates:

```math
\mathrm{FeatherLuck}=100\sqrt[3]{
\frac{R}{N_R}\times\frac{S_{\min}}{N_S}\times\frac{T}{N_T}}.
```

$T$ is random Threefold grants. Each $N$ is that stage's actual opportunities. Guaranteed grants are excluded. Rates of 50% at all stages give 50, rates of 75% give 75, and every roll succeeding gives 100. The score is a geometric mean of rates, separate from damage Luck and the rarity indices. Missing or inconsistent evidence leaves it unavailable. Small samples and invisible Feather overcap limit comparisons between runs.

## Limitations

- Combat profiles assume level 100 configured stats, weapon damage, and delay. A different gear set or synced content can change potion gains, auto-attack estimates, and luck baselines. Use `--gear` to choose between the available sets. Level-synced content is not supported yet.
- BRD gauge and Pitch Perfect stacks sometimes remain ambiguous. The report marks those estimates.
- Auto-attack conversion and MCH pet scaling are approximations.

## Future features

- Add more jobs and support additional gear and level-sync profiles.
- Improve variable-potency estimates if FF Logs exposes the underlying resources.
- Provide an HTML report generated from exported analysis data.
