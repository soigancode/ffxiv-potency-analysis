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
| 7.4–7.56 | Bard (BRD), Machinist (MCH), Dancer (DNC) |

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
    - [Variable potency from damage](#variable-potency-from-damage)
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

Use `brd`, `mch`, or `dnc` for the job. The full job names also work.

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

The comparison shows duration, rDPS, nDPS, landed potency, PPS, Luck, adjusted Luck, partition, patch, and the fight date in UTC (`dd/mm/yy`). Saved fights are reused.

## Understanding the results

**Potency** adds the potency of hits that landed, including configured personal buffs and potion gains. It also accounts for pet actions and estimates auto-attack potency. Multi-target hits use their action's falloff rules. Recorded overkill reduces the credited potency in proportion to damage dealt. Other players' damage buffs do **not** increase personal potency. **PPS** divides total potency by fight duration in seconds.

**Luck** shows how favorable the observed Crit and Direct Hit outcomes were, weighted by each hit's potency. A critical hit contributes more than a Direct Hit because its configured damage multiplier is larger. **Luck baseline** shows the expected score from the configured unbuffed gear rates. Comparing the two indicates whether hit outcomes were favorable for that gear profile. It does not measure rotation quality.

**Adjusted Luck** (`aLuck` in comparisons) subtracts the *expected* benefit of tracked party and target Crit/DH rate buffs. The original Luck score remains visible because those actual outcomes still affect FF Logs damage rankings. Adjusted Luck does not change potency or PPS. [The formulas](#luck-and-adjusted-luck) explain both scores.

FF Logs **rDPS and nDPS** remain the original reported damage metrics. Potency and PPS measure a different thing: landed action value without Crit, Direct Hit, or base damage roll variance. Compare the same fight and job, with comparable gear and stats.

## Calculation details

### Shared calculations

#### Food

The shared HQ food and potion definitions are in `data/consumables/`. The configured BiS stats already include Caramel Popcorn's food bonuses.

When FF Logs records `Well Fed` ending or being reapplied, the report shows the interval without food. During that interval, BRD damage-based potency estimates use the lower Determination and Crit values, and luck baselines use the lower Crit rate. Food does not directly multiply action potency. If no food changes are recorded, the configured food is assumed throughout the fight and marked unverified in the report.

#### Potions

A Grade 4 Gemdraught of Dexterity [HQ] raises Dexterity by 10%, capped at 541, for 30 seconds. The reference sets use Miqo'te - Seekers of the Sun. The configured party Dexterity is 6,841 before a potion and 7,382 during it. The tool converts the resulting change in the level 100 main-stat damage factor into extra potency on hits in the potion window:

```math
P_{\mathrm{potted}} = P_{\mathrm{base}}\times
\frac{f_{\mathrm{main}}(7382)}{f_{\mathrm{main}}(6841)}.
```

The factor uses level 100's tiered main-stat calculation, so a 541 Dexterity gain is not treated as 10% extra damage. MCH pets use their own configured main-stat factor. DoT ticks and MCH Wildfire use the potion state snapshotted when their effect was applied.

The values above describe a five-role party. For another composition, the tool recomputes party Dexterity and the potion factor from the fight roster.

#### Damage penalties

Weakness reduces the player's main damage stat by 25%. Brink of Death reduces it by 50%. These effects apply across encounters. The tool calculates their damage factors from the configured gear, accounting for a potion when one overlaps the hit.

Damage Down strength is configured by encounter. The tool reduces potency on landed hits carrying that status. Older DoT snapshots without it retain their potency. Consecutive applications appear as one interval with refresh times and a combined affected-hit count.

#### Auto-attacks

Auto-attacks have no current official listed potency in the job guide. The reference values are **80** for BRD and MCH's Shot and **90** for DNC's melee Attack. These values agree with damage-per-potency comparisons in the supplied logs. The tool estimates weapon delay from consecutive hits and matches it to a known delay for the job. BRD's Shots under Army's Paeon or Army's Muse still count toward potency, but do not set the base weapon-delay estimate. It reports an error if no known delay is close enough. Action-comparable potency per auto-attack is:

```math
P_{\mathrm{auto}}=P_{\mathrm{base}}\times
\frac{\left\lfloor F\times\text{weapon delay}/3\right\rfloor}{F}
\times\frac{\text{Skill Speed factor}}{1.2}.
```

```math
F=\left\lfloor\frac{\text{level main stat}\times
\text{job attribute modifier}}{1000}\right\rfloor
+\text{weapon damage}.
```

Dividing by `1.2` accounts for the action-damage trait read from the job guide, which does not apply to auto-attacks. With the configured MCH stats and 2.64 s weapon delay, the result is about **58.65 action-comparable potency per Shot** before potion effects. DNC's 3.12 s delay gives about **77.88 potency per Attack**. These approximations agree with the damage-per-potency comparisons in checked logs.

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

#### Variable potency from damage

Some actions have a potency determined by a resource that FF Logs does not expose directly. For BRD, the tool estimates it from the same player's fixed-potency hits: Burst Shot (220), Refulgent Arrow (280), Empyreal Arrow (260), and Heartbreak Shot (180). Each reference hit gives an estimate of **damage per potency** after normalization. It uses the median of up to 30 hits on the same target nearest in time. When fewer than three are available, it uses up to 20 reference hits, prioritizing the same target, and marks the baseline as less certain. Overkill hits are excluded from the reference set.

For each reference or variable-potency hit, the tool divides logged damage by its configured Crit multiplier if it crit, by 1.25 if it Direct Hit, and by FF Logs' recorded damage multiplier. That multiplier includes recorded damage buffs, target debuffs, and FF Logs' **1.05** contribution for Medicated. A potted hit also needs a correction: the actual potion effect uses the configured Dexterity damage factor, which differs from 1.05.

```math
D_{\mathrm{norm}}=\frac{D_{\mathrm{logged}}}{C^{I_C}\,1.25^{I_D}\,M_{\mathrm{FF}}}\times Q.
```

Here $I_C$ and $I_D$ are 1 when the hit crits or Direct Hits, otherwise 0. $M_{\mathrm{FF}}$ is FF Logs' multiplier (assumed to be 1 if absent). $Q$ is **1.05 ÷ configured potion factor** for Medicated hits, otherwise 1. The median of reference values $D_{\mathrm{norm}}/P_{\mathrm{known}}$ is the baseline $B$. The variable hit's estimated potency is $D_{\mathrm{norm}}/B$.

The estimate is compared with the action's possible potencies. For **Pitch Perfect**, those are 100, 220, or 360 for one, two, or three stacks, and half those values for an additional target. Relative damage between multiple landed targets narrows which hit could have received full potency. A single landed hit is treated as full potency unless another target in the same use was immune. The tool allows a **94%–106%** damage roll plus **0.5%** tolerance for the estimated baseline and rounded multiplier: a candidate $P$ is plausible when estimated potency lies between $0.935P$ and $1.065P$. It lists multiple plausible fits when their ranges overlap. If none fits, it still selects the nearest candidate and reports how far outside the expected range the hit was.

For **Apex Arrow**, candidate potency is $140+7(g-20)$ for Soul Voice Gauge $g$ from 20 to 100 in steps of five. A following Blast Arrow narrows the candidates to 80–100 gauge. The best fit minimizes relative error across its landed hits, while candidates within **6.5%** on every hit remain plausible. **Radiant Encore** uses Codas reconstructed from song casts. The report marks ambiguous assignments. Selected potencies are deterministic estimates, not recovered gauge or stack values.

### Bard

#### Songs, Codas, and variable potency

Each song grants its own Coda. Radiant Finale consumes the available distinct Codas and grants 2%, 4%, or 6% damage for one, two, or three Codas. Radiant Encore then deals 700, 800, or 1,100 potency, with 50% potency on additional targets. The report shows the Codas spent, Encore damage, and average duration of each song.

Pitch Perfect deals 100, 220, or 360 potency for one, two, or three Repertoire stacks. Apex Arrow scales with Soul Voice Gauge. At 20 gauge it deals 140 potency, increasing by 7 for each additional gauge point up to 700 at 100 gauge. An Apex Arrow at 80 or more gauge grants Blast Arrow Ready. These hidden resource values are estimated from [normalized damage and reference hits](#variable-potency-from-damage). The report lists plausible alternatives when damage rolls leave more than one possible value.

#### Damage-over-time snapshots

Caustic Bite and Stormbite have separate direct-hit and damage-over-time components. Each target retains the personal damage buffs and potion state present when the effect was applied. Iron Jaws refreshes both effects and takes a new snapshot. Later buff changes do not change an existing DoT's potency. The report separates application damage from tick potency.

#### Personal buffs and Barrage

Raging Strikes adds 15% personal damage. Radiant Finale adds its Coda-dependent bonus. Both affect direct actions, snapshotted DoTs, and auto-attacks. Crit/DH rate effects instead contribute to the expected benefit used for adjusted Luck.

Barrage makes Refulgent Arrow strike three times or raises Shadowbite to 300 potency. Only landed hits contribute. Shadowbite's additional-target falloff is applied separately, and ordinary and Barrage-enhanced damage both appear in the action totals.

### Machinist

#### Hypercharge and guaranteed hits

Hypercharge grants five Overheated stacks. Its 20-potency bonus applies to single-target weaponskills, including Blazing Shot, but not Auto Crossbow. Reassemble guarantees a critical direct hit on the next eligible weaponskill. Full Metal Field guarantees that outcome independently. Their landed potency counts normally, while guaranteed outcomes are excluded from Luck and adjusted Luck.

#### Wildfire

Wildfire adds 240 potency per weaponskill that lands during its ten-second window, up to six weaponskills and 1,440 potency. Auto-attacks and pet attacks do not contribute. Detonator can end the window early. Wildfire uses the potion state at application and does not roll Crit or DH. The report lists landed weaponskills and resulting potency for each detonation.

#### Automaton Queen and Battery

Automaton Queen spends between 50 and 100 Battery. Its attack potency scales linearly between the values at those endpoints:

```math
P(G)=P_{50}+(P_{100}-P_{50})\frac{G-50}{50}.
```

Queen and Rook Autoturret damage is converted to player-comparable potency using the configured **0.89** factor. This is an approximation. Summoning and Queen Overdrive add no damage themselves. The report groups landed pet attacks by deployment, identifies missing Queen finishers, and shows early Overdrive use.

Battery gains follow successful action resolutions. An action can grant Battery even when its damage fails to land because the target disappears. Such an action adds no landed potency.

#### Lindwurm II opening Battery

Battery carried from phase one is included when the preceding kill is available. A Queen summoned before the pull is treated separately, so its spent Battery is not counted again for the next Queen.

When carried Battery is unknown, an unexplained opening Queen initially uses an unconfirmed 100-Battery assumption. Damage from later Queens with known Battery can narrow this to a unique estimate at 50, 60, 70, 80, 90, or 100 Battery. At least two opening hits and two comparable later Queens must support the fit. Comparisons use the same attack, Crit outcome, and potion state, with corrections for Direct Hits and recorded damage modifiers. They allow a 95%–105% damage roll, multiplier rounding of ±0.005, and damage rounding of ±2. Overkill and damage-penalty hits do not establish the reference. Inferred Battery remains labelled as an estimate.

### Dancer

#### Dance finishes and personal buffs

Finish potency depends on the number of successfully completed steps:

| Successful steps | Standard Finish | Technical Finish |
| ---: | ---: | ---: |
| 0 | 360 | 350 |
| 1 | 540 | 540 |
| 2 | 850 | 720 |
| 3 | — | 900 |
| 4 | — | 1,300 |

Standard Finish grants 2% damage for one step or 5% for two steps, lasting 60 seconds. Technical Finish grants 1%, 2%, 3%, or 5% for one through four steps, lasting 20 seconds. Finishing Move deals 850 potency and grants the full Standard Finish bonus. Zero-step finishes add damage but grant no finish damage bonus.

The Dancer's own finish bonuses count toward personal potency, including auto-attacks. They multiply when both are active. Another Dancer's finish bonuses do not add personal potency. A finish deals damage using the buff state before it applies or refreshes its own bonus. The report lists each finish's step count, landed hits, and potency.

A finish bonus already present at the pull has an unlogged step count. Its strength is inferred from rounded damage multipliers, using later hits with the same external buffs when necessary. Only a unique fit is accepted. An unresolved initial strength produces an explicit error.

#### Multi-target damage and guaranteed hits

Dancer's major multi-target actions deal 40% potency after the first enemy. Starfall Dance deals 25%. The full-potency target is identified after correcting damage for Crit, Direct Hit, and recorded damage modifiers. Each landed target contributes its own potency, including overkill clipping.

Starfall Dance guarantees a critical direct hit. Its potency counts normally, but it is excluded from Luck and adjusted Luck. Devilment adds 20 percentage points to Crit and DH chances for the Dancer and Dance Partner. This changes the expected Crit/DH benefit on eligible hits, rather than their listed potency.

#### Feathers and proc luck

Cascade and Windmill each have a 50% chance to grant Silken Symmetry. A comboed Fountain or Bladeshower has a 50% chance to grant Silken Flow. Symmetry enables Reverse Cascade or Rising Windmill, and Flow enables Fountainfall or Bloodshower. Flourish grants separate Flourishing Symmetry and Flow effects without a random roll.

The detailed report shows initial opportunities and grants, Flourish grants, proc GCD uses, consumption, overlaps, expiration, death losses, and unused effects. The Feather-chain index combines the initial unlock and Feather rolls. Threefold has its own index. The final Feather luck score combines all three observed random proc rates. Flourish's guaranteed grants are excluded from random proc rates. Feather expectations use the generating actions actually resolved, and Threefold expectations use Fan Dance actions that resolved. Initial proc luck therefore changes the number of later opportunities without changing their individual chances.

Reverse Cascade, Fountainfall, Rising Windmill, and Bloodshower each have a 50% chance to grant one Fourfold Feather on successful resolution. An AoE action makes one roll per use, rather than one per target. With $N$ eligible uses, the expected number of successful rolls is $0.5N$. The gauge holds four feathers, so a successful roll at the cap adds no usable feather.

Fan Dance and Fan Dance II each spend one feather. The analysis counts their uses and bounds the number of feathers gained during the fight using the order of generating actions, spending actions, the four-feather cap, and death resets. Fresh Savage, Extreme, and Ultimate pulls start at zero feathers, including pulls after a wipe. M12S phase two uses zero after a verified checkpoint wipe, while carry-over or missing checkpoint context allows 0–4 starting feathers. Supported Dungeon and Criterion logs cover the complete run, including trash and bosses, and also start at zero feathers. Ending gauge values and cap losses are unlogged. These bounds describe possible resource histories, not an exact reconstruction or a confidence interval. The displayed Feather luck score is the minimum supported by the log. Invisible Feather overcap can make the true score higher. Expected rolls include possible cap losses and should not be compared directly with feathers spent.

Each successful Fan Dance or Fan Dance II has a separate 50% chance to grant Threefold Fan Dance. These random procs are counted from their buff applications and refreshes. Flourish also grants Threefold Fan Dance, but its guaranteed grants are reported separately and excluded from random proc luck. The report shows their expected count, observed count, and proc rate. A granted proc can be overwritten, expire, or be lost on death, so grants and uses need not match.

#### Proc rarity indices

An ordinary Cascade or Windmill, or a correctly comboed Fountain or Bladeshower, has a 50% chance to unlock a proc GCD. That proc GCD then has a 50% chance to grant a feather. Assuming it is used successfully, the whole chain has a 25% chance to produce a feather. Flourish skips the first roll, so its guaranteed proc GCD has a 50% Feather chance. Fan Dance and Fan Dance II make a separate 50% roll for Threefold after spending a feather.

The detailed proc indices use an approximate normal-reference index from 0 to 100, with 50 representing expected luck. Below 50 is below expectation, and above 50 is above expectation. They are separate from damage Luck and do not represent proc chance, an exact percentile, or a confidence interval.

For each random stage, expected grants are $np$ and variance is $np(1-p)$. Let $R$ be initial random grants, $S$ successful Feather rolls, and $E_R$ and $E_S$ their expectations. Initial grants are weighted by their subsequent Feather chance $q$, currently 0.5. The Feather-chain index is:

```math
Z=\frac{q(R-E_R)+(S-E_S)}{\sqrt{q^2V_R+V_S}},\qquad
\mathrm{Index}=100\Phi(Z).
```

$\Phi$ is the standard normal cumulative distribution function. Separate weights are used if the two initial proc families have different Feather chances. This standardizes the surplus against the number of opportunities and accounts for both rolls of the Feather chain. Guaranteed Flourish grants and execution losses do not count as random luck.

The report displays only the Feather-chain index calculated from the minimum feasible number of successful Feather rolls. It labels this as a minimum because cap losses are unlogged. Equal displayed scores do not establish equal luck, and a higher minimum does not prove one run was luckier. Threefold uses its own observed random grants and variance, without changing the Feather-chain index. These indices measure how unusual a surplus is for the sample size. They can approach 100 without every roll succeeding. Missing or inconsistent evidence, or zero variance, leaves the affected score unavailable. Small samples and rotation-dependent opportunities make these descriptive comparison indices rather than calibrated probabilities.

#### Combined Feather luck score

The final score combines the initial GCD unlock rate, the Feather generation rate, and the random Threefold rate. Initial GCD rate pools random Symmetry and Flow grants over their combined opportunities. Each later rate uses that stage's actual opportunities, including eligible actions enabled by Flourish. Guaranteed Flourish grants are excluded from successful random grants.

```math
\mathrm{FeatherLuck}=100\sqrt[3]{
\frac{R}{N_R}\times\frac{S_{\min}}{N_S}\times\frac{T}{N_T}}.
```

$R$ is the observed initial random grant count, $S_{\min}$ is the minimum feasible successful Feather roll count, and $T$ is the observed random Threefold grant count. Each $N$ is that stage's number of random opportunities. All three stages currently have an expected 50% rate. Rates of 50% at all stages give a score of 50, rates of 75% give 75, and every roll succeeding gives 100. Scaling all counts by the same amount leaves the score unchanged. This is a geometric mean of observed rates, rather than a probability or rarity index.

The score is labelled as a minimum because Feather overcap and ending gauge are unlogged. Carry-over pulls also allow unknown starting feathers. A missing stage, zero opportunities at any stage, or inconsistent evidence leaves the combined score unavailable. Small samples are less reliable for comparison, and different minimum scores alone cannot prove which run had greater true luck. Unused resources and proc losses describe execution separately from the successful rolls.

#### Esprit

Esprit governs Saber Dance use, but does not vary its fixed 540 potency. Dance of the Dawn replaces an eligible Saber Dance with a fixed 1,000-potency action. Random party-generated Esprit is not reconstructed. The analyser counts the actions actually used rather than treating unspent or unobserved resources as damage.

## Limitations

- Combat profiles assume level 100 configured stats, weapon damage, and delay. A different gear set or synced content can change potion gains, auto-attack estimates, and luck baselines. Use `--gear` to choose between the available sets. Level-synced content is not supported yet.
- BRD gauge and Pitch Perfect stacks sometimes remain ambiguous. The report marks those estimates.
- Auto-attack conversion and MCH pet scaling are approximations.

## Future features

- Add more jobs and support additional gear and level-sync profiles.
- Improve variable-potency estimates if FF Logs exposes the underlying resources.
- Provide an HTML report generated from exported analysis data.
