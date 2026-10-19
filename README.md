# CQR: Complete Quarterback Rating

One number for everything a quarterback does: passing, running, sacks, turnovers, crunch time and the
defenses he faced. 50 is exactly league average; 90+ is an MVP-level season.

The site in `site/` shows live rankings for the current NFL season, every season back to 2016, the formula
and its track record. A GitHub Actions workflow rebuilds it on Monday, Tuesday and Friday mornings during
the season, so Sunday, Monday-night and Thursday-night games are always in.

## The formula

Every play a quarterback is responsible for gets a value **A**, measured against an average play of the
same kind:

```
A    = ½ × (EPA* − avg) + ½ × (AY − avg) ÷ 9

EPA* = EPA − ¼ × receiver's YAC beyond expected
           + 4 × (lost − p)      on the QB's own fumbles
           × ½                   on pass interference drawn

AY   = pass yds + rush yds − sack yds − ¼ × YAC beyond expected
       + 20 × TD − 45 × INT − 45 × p per fumble
```

* **avg** is the league average for a dropback, or for an NFL run in the same situation (short yardage or
  not) when the play is a designed QB run.
* **p** is how often that kind of fumble is lost league-wide (strip-sack 52%, designed run 41%, botched
  snap 26%, other dropback 19%).
* **EPA** is nflfastR's expected points added; **AY** is an all-plays version of ANY/A. Nine adjusted yards
  equal one point, which gives the two halves equal spread.

Then:

```
      Σ w×A − Σ w×D
V  = ───────────────      w = 1.25 in the 4th quarter / OT within 8 points, else 1
      dropbacks + 100     D = rating of the defense faced (per dropback)

CQR = 100 ÷ (1 + e^(−V ÷ 0.085))
```

* **D** is each defense's average A allowed to *other* teams' quarterbacks, regressed toward average with
  an 800-dropback prior.
* **+100** gives every QB 100 dropbacks of league-average play, so one hot game can't make a backup No. 1.
* Designed runs add to the numerator but not the denominator, so a dual threat's running adds value
  instead of diluting his passing rate.
* Qualified QBs have at least 14 dropbacks per team game (the NFL's passer-rating bar).

Counted plays: pass attempts, sacks, scrambles, designed runs (including sneaks), botched snaps,
two-point tries and drawn defensive pass interference. Ignored: kneel-downs, spikes and plays wiped out by
any other penalty. Regular season only.

The code is the spec: [`qbrank/formula.py`](qbrank/formula.py).

## Why each piece is there

| Piece | Why |
|---|---|
| Expected points (EPA) | Knows that 4 yards on 3rd-and-3 beats 9 yards on 3rd-and-12, and what a turnover or sack does to the drive. |
| Adjusted yards (AY) | Keeps the rating anchored to production fans can see. In testing, blending the two roughly halved the "no way" orderings without making the rating any less stable. |
| ¼ of YAC beyond expected goes to the receiver | A 5-yard slant turned into a 70-yard score by broken tackles is mostly the receiver. The QB keeps the expected YAC his throw set up, and most of the rest. |
| Fumbles at their average cost | Putting the ball on the ground is the QB's fault; who recovers it is close to a coin flip. |
| Designed runs against an average NFL run | Credits dual threats for what their runs add over a normal run play, without penalizing pocket passers. |
| 1.25× late and close | Crunch time matters, but a handful of snaps shouldn't decide a season. |
| Defense adjustment | 300 yards against the best pass defense isn't 300 yards against the worst. |
| 100-dropback cushion | Small samples are noisy; this keeps a backup's great half from topping the list. |

Tested and left out: discounting garbage time (it made rankings less stable and fixed nothing), stripping
all YAC from the QB (much less stable), counting drawn pass interference in full (less stable), and
rewarding volume (per-game value agreed less with the eye test than the per-dropback rate).

## Track record (2016-2025 regular seasons)

| Rating | Split-half reliability | Year to year | Correlation with win % |
|---|---|---|---|
| **CQR** | 0.493 | 0.363 | 0.718 |
| Passer rating | 0.413 | 0.339 | 0.632 |
| ANY/A | 0.445 | 0.356 | 0.667 |
| EPA per play | 0.466 | 0.351 | 0.721 |
| ESPN Total QBR | 0.505 | 0.287 | 0.664 |

Split-half compares a QB's rating in odd weeks with his rating in even weeks of the same season; year to
year compares consecutive seasons; the last column is the correlation with his team's win rate in his
starts. CQR is the most stable from one season to the next and essentially tied with raw EPA for the
closest link to winning. Total QBR is a little steadier within a season but much less stable across seasons.

* The AP MVP ranked first or second in CQR in 8 of 9 seasons (2016-2024). The exception is Lamar Jackson in
  2023 (5th, behind Purdy, Prescott, Allen and Tagovailoa, who were more efficient per play).
* **Clear-cut pairs:** two qualified QBs in the same season where one is at least as good in passer rating,
  ANY/A, rushing yards per game, TDs per game, giveaways per game and sack rate. There were 852 of them;
  CQR orders 850 correctly. The two exceptions come from schedule strength (Trubisky 2020) and a near tie
  (Garoppolo vs. Cousins 2021).
* Best seasons since 2016: Lamar Jackson 2019 (97.0), Lamar Jackson 2024 (96.2), Patrick Mahomes 2018
  (94.3), Brock Purdy 2023 (94.3), Matt Ryan 2016 (92.9).

Reproduce with `python -m qbrank.validate`.

## Running it

```bash
pip install -r requirements.txt
python -m qbrank.build              # current season -> site/data/<season>.json
python -m qbrank.build --all        # every season since 2016
python -m qbrank.validate           # back-test -> site/data/validation.json
python -m pytest -q
python -m http.server -d site 8000  # then open http://localhost:8000
```

Data comes from [nflverse](https://github.com/nflverse/nflverse-data) (play-by-play with the nflfastR
expected points model, plus rosters) and is cached in `.cache/`.

## Weekly updates and hosting

`.github/workflows/update-rankings.yml` runs on Monday, Tuesday and Friday at 13:17 UTC from September
through February. It tests the formula, rebuilds the current season, commits the new data and deploys
`site/` to GitHub Pages. Run it any time from the Actions tab ("Run workflow"); tick "Rebuild every season"
after changing the formula.

One-time setup: **Settings → Pages → Build and deployment → Source: GitHub Actions**. The site then lives at
`https://<user>.github.io/QBrankings/`.
