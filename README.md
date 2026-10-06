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
| 7.4–7.56 | Paladin (PLD), Warrior (WAR), Bard (BRD), Machinist (MCH), Dancer (DNC) |

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
  - [Paladin](#paladin)
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
ffxiv-potency fflogs brd dmu
ffxiv-potency fflogs mch m10s
```

Analyse **any leaderboard position** instead:

```bash
ffxiv-potency fflogs brd dmu 3
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

Use `pld`, `war`, `brd`, `mch`, or `dnc` for the job. The full job names also work.

Add `--html` to save a browser report in `reports/`:

```bash
ffxiv-potency fflogs pld m12sp1 7 --html
ffxiv-potency fflogs war dmu --html
ffxiv-potency fflogs pld dmu 1-5 --html
ffxiv-potency fflogs pld dmu 1,3,7 --html
```

One rank saves `job_fight_rank.html`. Leaderboards save `job_fight_top.html`, ranges save `job_fight_first-last.html`, and selected ranks save `job_fight_ranks-1-3-7.html`. A leaderboard file includes the comparison table and every successfully analysed player's full report. Click a player to open their analysis. The sidebar highlights the section being viewed and lets you switch between reports. Click a leaderboard column header to sort, then click again to reverse the order. Hover over Notes for the comparison explanations. Skipped ranks retain their reasons. The files work offline. The `umad` alias uses `dmu` in filenames.

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

The report shows the player, fight, duration, date, patch, assumed gear, potency, PPS, and FF Logs damage metrics. It marks wipes and lists deaths and damage penalties. All jobs use the same section order where applicable: execution summary, deaths and damage penalties, cooldowns and burst windows, combos and ready effects, melee downtime, potions, missing-hit diagnostics, Hit Bonus and Luck, action totals and auto-attacks, and data assumptions. DoT potency tables appear between the main action table and auto-attacks.

Add `--html report.html` to `analyse` to also save an HTML report in `reports/` with the same results and section order as the terminal report. It shows the saved individual FF Logs rank when available. An explicit directory path overrides the default location. Open the file in a browser. Styles are included, so it works offline.

To save a fight without analysing it, run `ffxiv-potency fflogs "<report URL>"`.

| Command | Removes |
| --- | --- |
| `ffxiv-potency clear logs` | Downloaded logs |
| `ffxiv-potency clear cache` | Saved calculations |
| `ffxiv-potency clear` | Both |

These commands ask for confirmation and leave job data intact. Add `--yes` to skip the prompt.

The tool remembers calculated results to speed up later views. Clearing logs frees storage while keeping these results. After downloading a log again, the tool reuses its calculation if the log and analysis data are unchanged.

The analysis shows the patch in effect on the fight date and the gear assumed for that patch. This can differ from FF Logs’ broader ranking patch bracket shown above a leaderboard. Gear is an assumption, not equipment recovered from the log.

The default is **7.4 Savage BiS** before patch 7.55. From 7.55 until 8.0, PLD assumes **7.55 Real BiS** and other jobs assume **7.55 Relic BiS**. To choose a different set, add `--gear savage_7_4`, `--gear relic_7_55`, or PLD's `--gear real_7_55` to `analyse`, `compare`, or a leaderboard command. The choice applies to all logs in that command. Run `analyse` to see the gear used for a particular log.

### Compare your logs

Provide two to ten URLs for the **same job and encounter**:

```bash
ffxiv-potency compare \
  "https://www.fflogs.com/reports/REPORT1?fight=9&source=18" \
  "https://www.fflogs.com/reports/REPORT2?fight=4&source=7"
```

The comparison shows duration, targetable time, damage metrics, potency, PPS, and the PPS difference from the first selected log. Leaderboards use rank 1 as the reference when included, otherwise the highest selected rank. Raid comparisons show adjusted Hit Bonus and adjusted Luck. Dungeon DPS comparisons show Hit Bonus and Luck. Notes mark deaths (`KO`), Damage Down (`DD`), and confirmed attacks lost to target death or untargetability (`G`). Saved fights are reused.

PLD, WAR and MCH combine equal rDPS and nDPS values in one **rDPS/nDPS** column.

## Understanding the results

The execution summary lists **Cooldown opportunities** when recorded uses fall below an estimated maximum. Damaging actions require a damageable target. Self buffs can be used before bosses become targetable, except during recorded Down for the Count periods. Cooldowns recover during downtime and cutscenes, respecting charge caps. Deaths do not reduce possible uses. A shortfall alone does not establish an avoidable missed use or potency loss.

Fight or Flight, Inner Release and Raging Strikes include pre-pull uses confirmed by opening buffs or damage snapshots, even when the activation cast is missing. Recorded casts are counted once.

**Potency** adds the potency of hits that landed, including configured personal buffs and potion gains. It also accounts for pet actions and estimates auto-attack potency. Multi-target hits use their action's falloff rules. Recorded overkill reduces the credited potency in proportion to damage dealt. Other players' damage buffs do **not** increase personal potency. **PPS** divides total potency by targetable time in seconds.

**Luck** shows how favorable the observed Crit and Direct Hit outcomes were, weighted by each hit's potency. A critical hit contributes more than a Direct Hit because its configured damage multiplier is larger. **Luck baseline** shows the expected score from the configured unbuffed gear rates. Comparing the two indicates whether hit outcomes were favorable for that gear profile. It does not measure rotation quality.

**Adjusted Luck** (`aLuck` in comparisons) subtracts the *expected* benefit of tracked party and target DH/Crit rate buffs. The original Luck score remains visible in analyse. Adjusted Luck does not change potency or PPS. [The formulas](#luck-and-adjusted-luck) explain both scores.

FF Logs **rDPS and nDPS** remain the original reported damage metrics. Potency and PPS measure a different thing: landed action value without Crit, Direct Hit, or base damage roll variance. Compare the same fight and job, with comparable gear and stats.

## Calculation details

### Shared calculations

#### Targetable time

PPS uses time when an enemy is available for damage. Simultaneous enemies count once, while encounter transitions and travel between enemy groups are excluded. Full duration and targetable time remain visible in analyse.

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

All supported jobs show each potion window's start, end, landed base potency and potion gain, followed by overall totals. Window potency includes snapshotted damage and auto-attacks. Unknown boundaries remain marked as unavailable, and uncertain potency retains its range.

PLD and WAR potion-alignment markers follow recorded damage snapshots. Buffs extending beyond a potion do not warn by themselves. Potted hits remain covered when they land after expiry, and DoT ticks retain the application's snapshot. Unpotted landed hits are flagged, with estimated missed potion gain on direct hits when potency is known. Logs without damage evidence retain cast-timing checks.

#### Execution diagnostics

Shared burst tables compare recorded casts with one highest-potency feasible package and show base potency completion. PLD comparisons include Circle of Scorn's application and expected ticks until each target's HP lock, untargetability or effect expiry. Both orders average one tick per three seconds because server-tick timing is unknown. Ticks can continue after the buff window ends. Hit columns count application hits. Other packages compare direct potency. Comparisons preserve ordinary landed GCD opportunities up to each damageable boundary, using the observed regular GCD pace and opening weave timing. Extra weaves are allowed when they do not cost a landed GCD. Ordinary filler slots do not generate hypothetical resources. Equal-potency packages favour earlier landed damage. Packages use patch references, recorded grants, cooldown recovery and hit delays. Damageable windows exclude downtime and evidenced HP locks while retaining other available targets. Gauge spends prove availability at their recorded timestamps. Unrecorded resource generation remains unconfirmed.

Cooldown timing starts at the first recorded use and counts time the action can be used while the player is alive. It uses the same availability rules as cooldown opportunities, but excludes deaths. Charged actions show a conservative minimum at full charges because opening charges are unknown. Recharge continues throughout. Recorded Infuriate and Double Check/Checkmate reductions are included. Delays can reflect intentional buff alignment.

In HTML burst tables, hover over Completion to compare recorded and proposed action orders with cast timestamps and any estimated gain. Both orders show other ability weaves. In the proposed package they move with the surrounding GCD, keeping roughly the same weave slots. Resource activations retain recorded timing when their grants cannot be replayed. Damaging actions show cast and hit times. Proposed hit times use observed delays from the log. Both orders show recorded HP-lock and untargetable timestamps where available. Uncertain comparisons are marked for review.

PLD burst cast and hit counts attribute held follow-ups to the burst that granted them, including uses in the next window. Landed potency retains the actual buff snapshots. Hold comparisons check early uses against witnessed cleave timings, including the next Fight or Flight opening before a new Valor overwrites Honor's grant. They respect combo expiry, Requiescat charges, GCD spacing and recorded future actions. Tooltips compare combined potency with personal buffs and potions, excluding DH/Crit and other players' buffs. Unprofitable candidates are discarded early. Completion remains unconfirmed when the available evidence cannot support the comparison. This is a local package comparison, not a full-fight rotation solver.

Burst alignment groups landed potency by personal buff windows and summarizes actions outside them, ordered by potential gain. DoTs use their application snapshot. Damage-buff tables exclude the selected buff from potency. Reassemble and Devilment instead estimate hit-bonus gains using assumed gear and baseline DH/Crit rates, separately from potency and PPS. Regular uses between windows, finite charges and overlapping buffs mean these gains are not confirmed losses or additive totals.

PLD, WAR, MCH and DNC report recorded combo losses and infer missing combo fields only from a unique normalized-damage fit against at least three consistent physical hits on the same enemy instance. Up to 30 references within 60 seconds use a 94%-106% damage band plus 0.5% tolerance. Normalization corrects DH/Crit, recorded modifiers, potion, revival and food effects. Clipped, sparse or ambiguous evidence retains a base-to-combo potency range. Inferred breaks show the timestamp, preceding GCD and estimated base loss. DNC proc trials and MCH combo-dependent Battery gains use consistent inferred packet evidence.

Missing follow-ups show recorded death, sustained downtime, expiry, overwrite or fight-ending context. Casts without landed hits retain existing ghost and HP-lock classifications. Matching contexts are grouped. Unexplained omissions remain unconfirmed.

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

PLD and WAR use an action-damage trait multiplier of `1.0`. BRD, MCH, and DNC divide by `1.2` because their action-damage trait does not apply to auto-attacks. With the configured stats, PLD's 2.24 s weapon delay gives about **66.83 action-comparable potency per Attack**, WAR's 3.36 s weapon delay gives about **100.59 action-comparable potency per Attack**, MCH's 2.64 s delay gives **58.65 potency per Shot**, and DNC's 3.12 s delay gives **77.88 potency per Attack**, before potion effects. These approximations agree with the damage-per-potency comparisons in checked logs.

#### Hit Bonus and Adjusted Hit Bonus

**HB** is the potency-weighted damage bonus from recorded Direct Hits and Crits, including guaranteed outcomes. **aHB** subtracts the expected contribution from external DH/Crit rate buffs. A value of +48% means those outcomes add 48% damage over the same observed attacks without their DH/Crit bonuses. Raid leaderboards and comparisons show aHB and aLuck after PPS. Dungeon DPS tables show HB and Luck. Analyse uses the full names **Hit Bonus** and **Adjusted Hit Bonus**.

Guaranteed hits include both the Direct Hit attribute conversion and the deterministic damage benefit from external DH/Crit rate buffs. Explicitly non-random damage such as Wildfire contributes potency with no hit bonus. Simulated DoT ticks are excluded from Hit Bonus and Luck because their actual DH and Crit outcomes are unavailable. The metric uses configured gear and observed outcomes, rather than converting potency into FF Logs nDPS. Unlike Luck, it also depends on the mix of attacks used.

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

Zero means no eligible hit rolled DH or Crit. A score of 100% means every eligible hit rolled both. Guaranteed DH/Crit and configured non-random damage, such as Wildfire, are excluded from **both sums**. Eligible pet hits and auto-attacks count too. This is an observed score, not a probability or an FF Logs ranking metric.

With gear DH chance $p_D$ and Crit chance $p_C$, the unbuffed Luck baseline is:

```math
\mathrm{Baseline}=100\%\times
\frac{(1+p_C(C-1))(1+0.25p_D)-1}{1.25C-1}.
```

The analysis also prints each hit outcome's observed rate beside its gear baseline. For adjusted Luck, the tool calculates the expected extra hit bonus from DH/Crit rate buffs active on each hit. With buffed chances $p'_D$ and $p'_C$:

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

### Paladin

PLD uses Strength for both weaponskills and damaging spells. Listed guide potencies already include level-100 trait upgrades.

#### Cooldowns and burst windows

Fight or Flight adds 25% personal damage. Analyse shows offensive cooldown use counts, timing and burst opportunities. Expiacion, Imperator, Confiteor, Blade of Faith, Blade of Truth, Blade of Valor and Blade of Honor deal 40% potency to additional targets.

Burst completion compares landed direct base potency with the highest-potency feasible package in each recorded Fight or Flight window. Expected casts belong to one jointly scheduled package, including earned follow-ups. Hit delays must fit the damageable windows before downtime and evidenced phase HP locks. Incomplete expectations show `n/a`. Missing landed hits are highlighted separately in HTML. Recorded grants establish Goring Blade and the Confiteor sequence. Combo dependencies, GCD recasts and potency priorities come from the selected action snapshot. Opportunities exclude downtime and recorded deaths. Cooldown additions must preserve all recorded outside-window and later uses. Unknown opening charges or missing availability evidence show `?`. Outside multi-target follow-ups are retained without asserting that moving them would improve damage. Resource evidence limits the comparison to a local package. Unknown gauge availability and opening charges remain unscored.

Potion tables flag unpotted landed hits from the associated Fight or Flight sequence. Start and End tooltips group alignment evidence. Completion scores actions inside the window, while alignment markers review potion placement.

Landed-hit counts are separate from completed casts and exclude periodic ticks. Window potency includes all landed damage and auto-attacks with a Fight or Flight snapshot, including periodic damage attributed to its application.

##### Follow-up context

Confiteor, Blade of Faith, Blade of Truth and Blade of Valor have 500, 260, 380 and 500 base potency respectively, increasing to 1,000, 760, 880 and 1,000 with Requiescat. Follow-ups remain grouped under the preceding burst. Casts without an active Requiescat charge use unenhanced potency. Proposed packages replay the four charges for 30 seconds from the selected Imperator cast, accounting for other spell uses and deaths. Analyse retains follow-up context under cooldowns and burst windows. Missing follow-ups list recorded death, sustained boss downtime, fight ending or ready-effect expiry context. Absent hits reuse the shared ghost and HP-lock evidence. Actions sharing a context are grouped, and unexplained omissions remain unconfirmed. Context alone does not establish an avoidable loss.

##### Spell casts

Holy Spirit has 400 base potency, 500 with Divine Might, or 700 with Requiescat. Holy Circle has 100, 250, or 350 respectively. Divine Might takes priority and leaves Requiescat charges intact. Analyse groups casts by spell, enhancement and cast-time evidence, with Divine Might before Requiescat and None within each spell.

#### Combos, ready effects and charges

Combo losses cover landed Riot Blade, Royal Authority and Prominence hits. Base losses account for overkill before buffs and penalties. Missing fields follow the shared combo-evidence rules above.

Atonement, Supplication and Sepulchre are grouped as a sequence, retaining their recorded grants, uses, expiry, overwrites, death losses and remaining effects. Spell enhancements replay recorded grants, stacks, consumption, expiry and death before each cast resolves. Other ready effects and spell charges follow separately.

#### Melee downtime

Melee downtime groups consecutive Shield Lobs and confirmed hard-cast Holy Spirits, with neighboring GCDs and every cast gap. Gaps use the recorded cast start for hard-cast spells. Instant Holy Spirit and the opening Holy Spirit are excluded. Missing begin-cast evidence remains unconfirmed.

#### Action totals and auto-attacks

##### Circle of Scorn

Circle of Scorn contributes a 140-potency application and 30-potency periodic ticks, retaining the application's personal buff, potion and damage-penalty snapshot. Analyse reports applications and periodic ticks separately.

### Warrior

#### Potencies and personal buffs

| Action | Before 7.5 | From 7.5 |
| --- | ---: | ---: |
| Inner Chaos | 660 | 700 |
| Primal Rend | 700 | 720 |
| Primal Ruination | 780 | 800 |

Comboed Maim has 340 potency, Storm's Path and Storm's Eye have 500, and Mythril Tempest has 140. Missing combo fields follow the shared evidence rules above. Primal Rend, Primal Ruination, and Primal Wrath deal 50% potency to additional targets. WAR's other damaging AoEs have no falloff.

Surging Tempest adds 10% personal damage. The attack that first grants it uses the preceding buff state. Damnation contributes 55 potency per landed counterattack. Its defensive cast is not a ghosted attack when no counterattack occurs.

Inner Chaos, Chaotic Cyclone, Primal Rend, and Primal Ruination guarantee critical direct hits. Inner Release guarantees them for Fell Cleave and Decimate, but not other actions. Beast Gauge controls spender availability without changing potency.

#### Cooldowns and burst windows

Cooldown timing covers Inner Release, Infuriate, Upheaval/Orogeny and Onslaught. Upheaval and Orogeny share one cooldown. Cooldowns and burst windows shows Inner Release sequence completion, followed by potion-window casts and landed hits for IR spenders, Infuriate, Nascent Chaos consumers, Primal follow-ups, Upheaval/Orogeny and Onslaught. Inner Release sequences compare landed direct base potency with the highest-potency feasible package from recorded resources. The calculation considers reordered spenders, earned Primal follow-ups, patch-specific potency and recasts, targetable time and observed hit delays. Expected casts describe one complete package. Potion windows also compare jointly scheduled resources and cooldowns. Alignment markers identify actions from the associated IR sequence used before or after the potion, early Nascent Chaos spending and late IR starts. These checks apply to every WAR report. Completion scores the package available within the window and does not optimize potion placement. Opening buffs, linked IR snapshots and charge consumption can confirm pre-pull completion without an activation timestamp. Unsupported expectations and outside cleaves remain unscored. Infuriate counts resource uses and is excluded from completion. Its potion-table tooltip replays charge recovery and recorded spender reductions when timing is established. A missing carried Nascent Chaos grant is marked for preparation review when a pre-potion charge is established. Moving Infuriate earlier still requires gauge and GCD planning, so this replay does not add hypothetical Nascent Chaos uses. Follow-up context explains recorded omissions and missing hits. The shared Potions section shows landed potion-snapshot potency and gain, including auto-attacks.

#### Combos, ready effects and charges

Analyse shows actual Surging Tempest uptime and hit coverage. Missing-buff warnings and lost potency exclude all attacks before the first application and setup after a confirmed natural expiry during downtime. Other unbuffed attacks remain listed. Inner Release lists uses and unused charges at confirmed expiry. Primal Rend, Primal Ruination, Primal Wrath, and Nascent Chaos list ready grants, uses, expirations, and overwrites. Pre-pull effects count as grants. Consuming a ready effect counts as use even if the damage ghosts. Effects still active at the fight's end are not counted as wasted.

#### Melee downtime

Melee downtime groups consecutive Tomahawks into one line, timestamped at the first Tomahawk. It shows the preceding and following melee GCDs and every gap between casts. Abilities woven between GCDs do not break the chain. No exact replacement loss is assigned because the available melee action is uncertain.

### Bard

#### Songs and personal buffs

Songs grant distinct Codas. Radiant Finale consumes them for a 2%, 4%, or 6% personal damage bonus. Radiant Encore then deals 700, 800, or 1,100 potency, with 50% potency on additional targets. Raging Strikes adds 15% damage. The report shows consumed Codas, Encore potency, and song durations. Radiant Finale’s possible-use count follows a 120-second buff cycle, while its action data retains the actual 110-second cooldown.

Cooldown timing also covers Barrage, Empyreal Arrow and Sidewinder. Alignment uses Raging Strikes, including DoT snapshots, and Radiant Encore lists missing-cast or missing-hit context.

Barrage makes Refulgent Arrow strike three times or raises Shadowbite to 300 potency. Caustic Bite and Stormbite retain their personal buff snapshot on each target. Iron Jaws refreshes both effects with a new snapshot. Application damage and tick potency are reported separately.

#### Variable potency from damage

Pitch Perfect has 100, 220, or 360 potency for one, two, or three stacks. Apex Arrow has $140+7(G-20)$ potency for Soul Voice Gauge $G$ from 20 to 100. Using at least 80 gauge grants Blast Arrow Ready.

Hidden resource values are estimated from normalized damage. Burst Shot (220), Refulgent Arrow (280), Empyreal Arrow (260), and Heartbreak Shot (180) provide fixed-potency references. Each hit is divided by its DH/Crit outcome and recorded damage multiplier. Potted hits correct FF Logs' recorded 1.05 factor to the configured potion factor $Q$:

```math
D_{\mathrm{norm}}=\frac{D_{\mathrm{logged}}}{C^{I_C}\,1.25^{I_D}\,M_{\mathrm{FF}}}\times Q.
```

The median normalized damage per reference potency establishes a local baseline. Up to 30 nearby same-target hits are used. Fewer than three references trigger a less-certain fallback. Overkill hits cannot establish the baseline.

Candidate potencies allow a 94%–106% damage roll plus 0.5% rounding tolerance. Multi-target damage narrows falloff assignments, and Blast Arrow narrows Apex candidates to 80–100 gauge. Multiple plausible fits remain visible. The nearest fit is flagged when none matches. These are deterministic estimates rather than recovered gauge values.

### Machinist

Cooldown timing includes recorded Blazing Shot recharge reductions. Reassemble alignment compares Drill, Air Anchor, Chain Saw and Excavator. Combo diagnostics cover Slug Shot/Clean Shot and their Heated versions. Follow-up context covers Excavator, Full Metal Field, incomplete Hypercharge/Wildfire windows and missing Queen finishers.

#### Hypercharge and Wildfire

Hypercharge grants five stacks that add 20 potency to single-target weaponskills, including Blazing Shot. Auto Crossbow receives no bonus. Reassemble guarantees a critical direct hit on the next eligible weaponskill. Full Metal Field guarantees that outcome independently.

Wildfire adds 240 potency per weaponskill that lands during its ten-second window, up to six hits and 1,440 potency. Pet attacks and auto-attacks do not contribute. Detonator can end the window early. Wildfire does not roll DH or Crit. The report lists hit counts and potency. Windows with fewer than six hits also list their contributing weaponskills. Double Check and Checkmate use a charge simulation with the recorded Blazing Shots, which reduce both recharge timers by 15 seconds. It respects the three-charge cap and targetable windows. The result is an upper bound that does not model weaving or buff alignment.

#### Automaton Queen and Battery

Queen spends 50–100 Battery, with attack potency scaled linearly between those endpoints:

```math
P(G)=P_{50}+(P_{100}-P_{50})\frac{G-50}{50}.
```

Queen and Rook damage uses an approximate 0.89 conversion to player-comparable potency. The report groups attacks by deployment and identifies missing Queen finishers and early Overdrive use. Successful action resolutions grant Battery even if their damage later ghosts.

For Lindwurm II, the preceding phase-one kill establishes carried Battery when available. A pre-pull Queen's spent Battery is counted separately. Otherwise, later Queens with known Battery can narrow the opening gauge to 50, 60, 70, 80, 90, or 100. A unique fit requires at least two opening hits and two comparable later Queens, allowing a 95%–105% damage roll, multiplier rounding of ±0.005, and damage rounding of ±2. Overkill and damage-penalty hits cannot establish the reference. An unresolved opening Queen retains a labelled 100-Battery assumption.

### Dancer

Cooldown timing covers Devilment, Flourish and Technical Step. Alignment reports Technical Finish and Devilment separately. Combo diagnostics cover Fountain and Bladeshower. Follow-up context covers Last Dance, Tillana, Starfall Dance and Dance of the Dawn.

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

Major damaging AoEs deal 40% potency to additional targets. Starfall Dance deals 25% and guarantees a critical direct hit. Devilment adds 20 percentage points to DH and Crit chances for the Dancer and Dance Partner.

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
