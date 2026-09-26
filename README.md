# FFXIV Potency

Compare players of the **same job in the same fight** by the potency of attacks that actually dealt damage. Base damage rolls, critical hits, and direct hits do not change an attack's potency, so this makes it easier to see who performed the stronger rotation without damage RNG deciding the result. The app reads FF Logs reports and shows potency, potency per second (PPS), and hit luck alongside FF Logs rDPS and nDPS.

**Current support:** level 100 Machinist, patch 7.5x. See [Disclaimers](#disclaimers).

## Get started

Install Python 3.11 or newer. From the project folder on Linux or macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell instead. Activate the environment again when you open a new terminal.

Create an FF Logs V2 API client and put its ID and secret in a `.env` file in the project root:

```text
FFLOGS_CLIENT_ID=your_client_id
FFLOGS_CLIENT_SECRET=your_client_secret
```

The app reads this file automatically. Keep it private. Required job snapshots are kept in the project's `data/` folder.

## Compare the top ten

```bash
ffxiv-potency fflogs mch m10s
```

The app selects the current top ten logs for the chosen job and fight by FF Logs rDPS, downloads missing fights, and prints a comparison. Saved fights are reused. The table keeps FF Logs ranking order. Potency, PPS, Luck, and adjusted Luck help explain differences between the players. For now, `mch` is the supported job abbreviation.

| Fight | Boss |
| --- | --- |
| `m9s` | Vamp Fatale |
| `m10s` | Red Hot and Deep Blue |
| `m11s` | The Tyrant |
| `m12sp1` | Lindwurm |
| `m12sp2` | Lindwurm II |
| `umad` or `dmu` | Dancing Mad |

## Analyse one player

Copy an FF Logs link with `fight` and `source` in it, and quote the whole URL:

```bash
ffxiv-potency analyse "https://www.fflogs.com/reports/zYLAW7KTBk8P4XxG?fight=9&source=18"
```

The report shows the player and fight, nDPS and rDPS, landed and matched hit counts, total potency, and PPS. Next come ghosted casts (when present), potion uses and windows, observed hit outcomes and luck scores, action uses and hits, auto-attacks, pet deployments (when present), and unmatched damage (when present). You can also pass a previously downloaded `data/logs/<report>/fight-<id>/source-<id>` folder.

To download a fight without analysing it, use `ffxiv-potency fflogs "<report URL with fight and source>"`.

## Compare your own logs

Pass two to ten links for the **same boss and job**:

```bash
ffxiv-potency compare \
  "https://www.fflogs.com/reports/REPORT1?fight=9&source=18" \
  "https://www.fflogs.com/reports/REPORT2?fight=4&source=7"
```

The app downloads missing fights and prints duration, rDPS, nDPS, potency, PPS, Luck, and adjusted Luck.

## What the numbers mean

**Potency** adds the potency of hits that landed. It includes the configured effect of your potion, pet actions, and auto-attacks. An action that was cast but dealt no damage appears under ghosted casts instead of adding potency. **PPS** is total potency divided by fight duration in seconds.

**Luck** measures how favorable the actual critical hits and direct hits were, weighted by each hit's potency. Critical hits contribute more than direct hits because their damage multiplier is higher. For an eligible hit $i$, let $P_i$ be its potency (including the potion effect when present), $C$ the critical damage multiplier calculated from the configured Crit stat, and $M_i$ its observed hit multiplier:

| Outcome | $M_i$ |
| --- | ---: |
| Normal | $1$ |
| Direct Hit | $1.25$ |
| Critical Hit | $C$ |
| Direct Critical Hit | $1.25C$ |

The displayed percentage is:

```math
\mathrm{Luck} = 100\% \times \frac{\sum_i P_i(M_i-1)}{\sum_i P_i(1.25C-1)}.
```

Zero means no eligible hit was a Crit or DH; 100% means every eligible hit was both. Guaranteed Crit/DH outcomes and configured non-random damage are excluded from **both sums**. Pet hits and auto-attacks with known potency count too. Luck is an observed score, not a probability or an FF Logs ranking metric.

**Luck baseline** is the score expected from the configured, unbuffed gear rates. With Crit chance $p_C$ and DH chance $p_D$:

```math
\mathrm{Baseline} = 100\% \times
\frac{(1+p_C(C-1))(1+0.25p_D)-1}{1.25C-1}.
```

Compare Luck to this baseline to see whether outcomes were favorable for those gear stats. The `analyse` view also shows the gear baseline and observed rate for each hit outcome.

**Adjusted Luck** (`aLuck` in comparisons) accounts for tracked raid effects that raise Crit or DH chance. For each eligible hit, the app calculates the **expected extra hit bonus** from the Crit and DH buffs active on that hit. With buffed chances $p'_C$ and $p'_D$, that extra bonus is:

```math
A_i = (1+p'_C(C-1))(1+0.25p'_D)
      - (1+p_C(C-1))(1+0.25p_D).
```

Then it subtracts those expected bonuses from the observed score:

```math
\mathrm{Adjusted\ Luck} = 100\% \times
\operatorname{clamp}_{[0,1]}\!\left(
\frac{\sum_i P_i\bigl((M_i-1)-A_i\bigr)}
     {\sum_i P_i(1.25C-1)}\right).
```

Tracked effects are Battle Litany, Battle Voice, Army's Paeon, the Wanderer's Minuet, and Chain Stratagem on the target. Adjusted Luck estimates how much of the score remains after accounting for their *expected* benefit; it does not remove actual Crits or DHs, and it does not change potency or PPS. The ordinary Luck score remains useful for comparing the outcomes that contributed to a ranking.

## Disclaimers

- Only Machinist and patch 7.5x are supported. Synced gear and other jobs need additional handling.
- Potion gains, critical damage, hit rates, and pet scaling use the configured level 100 BiS Machinist gear profile ("Relic Weapon BiS"). Change that profile if your stats differ. Queen and Rook use an approximate player-equivalent scaling factor.
- Auto-attack potency is an approximation based on an assumed base value for Shot and a weapon delay inferred from the log. The formula and its limits are explained below.
- Potency measures landed actions. It does not incorporate other players' damage buffs or reproduce FF Logs rDPS/nDPS.

For MCH auto-attacks, the app converts each Shot to action-comparable potency using:

```math
\text{Shot potency}=80\times
\frac{\left\lfloor F\times\text{weapon delay}/3\right\rfloor}{F}
\times\frac{\text{Skill Speed factor}}{1.2}.
```

Here, $F$ is the weapon factor:

```math
F=\left\lfloor\frac{\text{level main stat}\times\text{job attribute modifier}}{1000}\right\rfloor+\text{weapon damage}.
```

The app estimates weapon delay from consecutive Shots and matches it to a known value; it reports an error if none is close. `80` is the assumed Shot base potency, and dividing by `1.2` accounts for an action trait that does not apply to auto-attacks. At the configured level 100 stats and 2.64 s delay, this gives about **58.65 potency per Shot** before potion effects. The resulting potency is consistent with observed damage per potency in the checked logs, so Shots can be compared with job actions in the same summary. It remains an approximation rather than an official listed Shot potency.

## Future features

- Add more jobs and level- or gear-synced content.
- Add damage-over-time snapshot timing when testing a job that uses DoTs regularly.
- Offer a browser summary generated from exported analysis data.
- Let users select a fight and player from a report without copying a source-specific link.
