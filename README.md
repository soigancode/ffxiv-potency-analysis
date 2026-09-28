# FFXIV Potency Analysis

Compare logs from the **same job and fight** by the potency of attacks that actually dealt damage. Potency removes the random damage roll and Crit/Direct Hit damage variance, making it easier to compare rotations. The tool also shows potency per second (PPS), hit luck, and FF Logs rDPS and nDPS.

**Current support:** level 100 Bard (BRD) and Machinist (MCH), using patch 7.55 job data and configured gear stats. The supported leaderboard fights are the 7.4 Savage tier (M9S–M12S) and Dancing Mad Ultimate in 7.5. See [Limitations](#limitations) for gear and sync assumptions.

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

Compare the current top ten accessible logs for a job and fight, ordered by FF Logs rDPS:

```bash
ffxiv-potency fflogs brd umad
ffxiv-potency fflogs mch m10s
```

Analyse **one leaderboard position** instead (1–10):

```bash
ffxiv-potency fflogs brd umad 3
```

The number is the actual FF Logs rank, including positions the tool cannot access. For comparisons, inaccessible or ambiguous ranks are skipped and the search continues down the leaderboard. Anonymous reports work when the player can be identified from the selected fight. Downloads are reused.

| Fight | Encounter |
| --- | --- |
| `m9s` | Vamp Fatale |
| `m10s` | Red Hot and Deep Blue |
| `m11s` | The Tyrant |
| `m12sp1` | Lindwurm |
| `m12sp2` | Lindwurm II |
| `umad` or `dmu` | Dancing Mad Ultimate |

Use `mch` or `brd` for the job; the full job names also work.

### Analyse one log

Copy a selected player's FF Logs URL containing `fight` and `source`, and quote the entire link:

```bash
ffxiv-potency analyse "https://www.fflogs.com/reports/REPORT1?fight=9&source=18"
```

The report starts with the player, fight, duration, nDPS, rDPS, landed events, potency, and PPS. It then shows any variable potency estimates, reduced damage and ghosted casts, potion windows, hit outcomes and luck, action totals, auto-attacks, and job-specific details. A ghosted cast dealt no positive recorded damage; its note may identify an untargetable target, a defeated target, or a boss phase HP lock.

To download a selected fight without analysing it, run `ffxiv-potency fflogs "<report URL with fight and source>"`. To empty `data/logs`, run `ffxiv-potency clear logs`; it asks for confirmation and leaves job data intact. Add `--yes` to skip the prompt.

### Compare your logs

Provide two to ten URLs for the **same job and encounter**:

```bash
ffxiv-potency compare \
  "https://www.fflogs.com/reports/REPORT1?fight=9&source=18" \
  "https://www.fflogs.com/reports/REPORT2?fight=4&source=7"
```

The comparison shows duration, rDPS, nDPS, landed potency, PPS, Luck, and adjusted Luck. Saved fights are reused.

## Understanding the results

**Potency** adds the potency of hits that landed, including configured personal buffs and potion gains. It also accounts for pet actions and estimates auto-attack potency. Multi-target hits use their action's falloff rules; recorded overkill reduces the credited potency in proportion to damage dealt. Other players' damage buffs do **not** increase personal potency. **PPS** divides total potency by fight duration in seconds.

**Luck** shows how favorable the observed Crit and Direct Hit outcomes were, weighted by each hit's potency. A critical hit contributes more than a Direct Hit because its configured damage multiplier is larger. **Luck baseline** shows the expected score from the configured unbuffed gear rates. Comparing the two indicates whether hit outcomes were favorable for that gear profile; it does not measure rotation quality.

**Adjusted Luck** (`aLuck` in comparisons) subtracts the *expected* benefit of tracked party and target Crit/DH rate buffs. The original Luck score remains visible because those actual outcomes still affect FF Logs damage rankings. Adjusted Luck does not change potency or PPS. [The formulas](#luck-and-adjusted-luck) explain both scores.

FF Logs **rDPS and nDPS** remain the original reported damage metrics. Potency and PPS measure a different thing: landed action value without Crit, Direct Hit, or base damage roll variance. Compare the same fight and job, with comparable gear and stats.

## Calculation details

### Shared calculations

#### Potions

A Grade 4 Gemdraught of Dexterity [HQ] raises Dexterity by 10%, capped at 541, for 30 seconds. The configured party Dexterity is 6,838 before a potion and 7,379 during it. The tool converts the resulting change in the level 100 main-stat damage factor into extra potency on hits in the potion window:

```math
P_{\mathrm{potted}} = P_{\mathrm{base}}\times
\frac{f_{\mathrm{main}}(7379)}{f_{\mathrm{main}}(6838)}.
```

The factor uses level 100's tiered main-stat calculation, so a 541 Dexterity gain is not treated as 10% extra damage. MCH pets use their own configured main-stat factor. BRD DoT ticks and MCH Wildfire use the potion state snapshotted when their effect was applied.

#### Auto-attacks

Shot has no current official listed potency in the job guide. The tool assumes a base value of **80**, estimates weapon delay from consecutive Shots, and matches it to a known delay for the job. It reports an error if no known delay is close enough. For the configured level 100 profile, action-comparable potency per Shot is:

```math
P_{\mathrm{Shot}}=80\times
\frac{\left\lfloor F\times\text{weapon delay}/3\right\rfloor}{F}
\times\frac{\text{Skill Speed factor}}{1.2}.
```

```math
F=\left\lfloor\frac{\text{level main stat}\times
\text{job attribute modifier}}{1000}\right\rfloor
+\text{weapon damage}.
```

Dividing by `1.2` accounts for the configured action damage trait, which does not apply to Shots. With the configured MCH stats and 2.64 s weapon delay, the result is about **58.65 action-comparable potency per Shot** before potion effects. This approximation agrees with the damage-per-potency comparison in checked logs; it is not an official Shot potency.

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

Zero means no eligible hit rolled Crit or DH; 100% means every eligible hit rolled both. Guaranteed Crit/DH and configured non-random damage, such as Wildfire, are excluded from **both sums**. Eligible pet hits and auto-attacks count too. This is an observed score, not a probability or an FF Logs ranking metric.

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

Tracked effects are Battle Litany, Battle Voice, Army's Paeon, the Wanderer's Minuet, Devilment on the Dance Partner, and Chain Stratagem on the target. The adjustment subtracts the **expected** buff benefit; it does not erase actual Crits or Direct Hits.

#### Variable potency from damage

Some actions have a potency determined by a resource that FF Logs does not expose directly. For BRD, the tool estimates it from the same player's fixed-potency hits: Burst Shot (220), Refulgent Arrow (280), Empyreal Arrow (260), and Heartbreak Shot (180). Each reference hit gives an estimate of **damage per potency** after normalization. It uses the median of up to 30 hits on the same target nearest in time; when fewer than three are available, it uses up to 20 reference hits, prioritizing the same target, and marks the baseline as less certain. Overkill hits are excluded from the reference set.

For each reference or variable-potency hit, the tool divides logged damage by its configured Crit multiplier if it crit, by 1.25 if it Direct Hit, and by FF Logs' recorded damage multiplier. That multiplier includes recorded damage buffs, target debuffs, and FF Logs' **1.05** contribution for Medicated. A potted hit also needs a correction: the actual potion effect uses the configured Dexterity damage factor, which differs from 1.05.

```math
D_{\mathrm{norm}}=\frac{D_{\mathrm{logged}}}{C^{I_C}\,1.25^{I_D}\,M_{\mathrm{FF}}}\times Q.
```

Here $I_C$ and $I_D$ are 1 when the hit crits or Direct Hits, otherwise 0. $M_{\mathrm{FF}}$ is FF Logs' multiplier (assumed to be 1 if absent). $Q$ is **1.05 ÷ configured potion factor** for Medicated hits, otherwise 1. The median of reference values $D_{\mathrm{norm}}/P_{\mathrm{known}}$ is the baseline $B$; the variable hit's estimated potency is $D_{\mathrm{norm}}/B$.

The estimate is compared with the action's possible potencies. For **Pitch Perfect**, those are 100, 220, or 360 for one, two, or three stacks, and half those values for an additional target. Relative damage between multiple landed targets narrows which hit could have received full potency. A single landed hit is treated as full potency unless another target in the same use was immune. The tool allows a **94%–106%** damage roll plus **0.5%** tolerance for the estimated baseline and rounded multiplier: a candidate $P$ is plausible when estimated potency lies between $0.935P$ and $1.065P$. It lists multiple plausible fits when their ranges overlap. If none fits, it still selects the nearest candidate and reports how far outside the expected range the hit was.

For **Apex Arrow**, candidate potency is $140+7(g-20)$ for Soul Voice Gauge $g$ from 20 to 100 in steps of five; a following Blast Arrow narrows the candidates to 80–100 gauge. The best fit minimizes relative error across its landed hits, while candidates within **6.5%** on every hit remain plausible. **Radiant Encore** uses Codas reconstructed from song casts. The report marks ambiguous assignments; selected potencies are deterministic estimates, not recovered gauge or stack values.

### Bard

- **Pitch Perfect** stacks and **Apex Arrow** gauge are estimated using [normalized damage and reference hits](#variable-potency-from-damage). Apex also lists estimated gauge and total potency per use.
- **Radiant Finale and Radiant Encore** use Codas reconstructed from song casts. The report shows Codas spent, Encore hits, and potency; it also lists each song's average duration.
- **Caustic Bite and Stormbite** ticks are matched to their application or **Iron Jaws** refresh, per target. Their personal buffs and potion state are snapshotted at application. The report separates direct application and tick potency.
- **Barrage** changes Shadowbite potency when its buff is consumed. Additional-target falloff and landed AoE hits are counted separately. The action totals include ordinary and Barrage-enhanced hits.

### Machinist

- **Wildfire** counts weaponskills that actually landed during each window, including an early detonation when present. Its potency uses the potion state at application.
- **Automaton Queen and Rook Autoturret** are deployment actions; their own landed attacks add potency. The report shows Battery Gauge spent and total potency per deployment, identifies missing Queen finishers, and notes Queen Overdrive. The configured conversion of pet action potency to player-comparable potency is **0.89**, an approximation. Deployments and Queen Overdrive themselves do not add damage potency.

## Limitations

- Combat profiles assume level 100 configured stats, weapon damage, and delay. A different gear set or synced content can change potion gains, auto-attack estimates, and luck baselines. Review `data/<job>/7.55/combat_profile.json` if your stats differ.
- Action damage traits are currently configured in combat profiles. The job-guide importer does not yet extract traits that increase damage without listing potency for each action, including traits used by BRD and MCH.
- BRD gauge and Pitch Perfect stacks sometimes remain ambiguous. The report marks those estimates; it does not claim to recover hidden resources exactly.
- Auto-attack conversion and MCH pet scaling are approximations. This tool does not reproduce FF Logs rDPS or nDPS from potency.

## Future features

- Support selecting FF Logs partitions for rankings and reports.
- Add more jobs and support additional gear and level-sync profiles.
- Import damage affecting traits from the job guide and use their multipliers in analysis.
- Improve variable-potency estimates if FF Logs exposes the underlying resources.
- Provide an HTML report generated from exported analysis data.
- Select a fight and player from a report without copying a source-specific link.
