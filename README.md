# Multisport live win probability

Unofficial fan project. Not affiliated with the NFL, NHL, NBA, NCAA, or ESPN. Not betting advice.

College football is a second config of the football pack. Regulation is four 15-minute quarters. College overtime is not a timed quarter: each team gets a possession from the opponent 25, then 2-point tries after the second extra period.

NHL is the hockey pack. Regulation is three 20-minute periods. Playoff overtime in the model is 20:00 sudden death, not the regular-season 3-on-3 period of 5:00. A scoreless playoff period starts another 20:00.

The widget does not fetch. Football charts use four equal columns, then one OT pane when any snapshot is in an extra period. Hockey charts use three equal columns, P1 P2 P3, then one OT pane on the same rule. The pane width follows the number of extra-period snapshots, with one OT label even if the replay reaches 2OT.

## Setup

From this directory, in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Tests

```powershell
python -m pytest
```

## Replay

```powershell
python -m live_wp replay examples/nfl_sample.json
python -m live_wp replay examples/nfl_jax_den.json
python -m live_wp replay examples/ncaaf_sample.json
python -m live_wp replay examples/ncaaf_cu_gt.json
python -m live_wp replay examples/nhl_col_min_g5.json
```

`examples/nfl_sample.json` is the Harbor fixture. `examples/nfl_jax_den.json` is Jacksonville at Denver. `examples/ncaaf_sample.json` is the college overtime sample and reaches 2OT. `examples/ncaaf_cu_gt.json` is Colorado at Georgia Tech, 3 Sep 2026. `examples/nhl_col_min_g5.json` is Minnesota at Colorado, Game 5, 13 May 2026.

## ESPN ingest

A saved NFL, college-football, or NHL scoreboard event or game summary can be ingested to snapshots. The adapter does not call the network. A college-football summary is written with sport `ncaaf`. An NHL summary is written with sport `nhl`. NBA and any other league are refused. Follow stays NFL-only and still rejects college football and hockey. ESPN's unofficial site shape can change without notice. Not betting advice.

```powershell
python -m live_wp ingest-espn tests/fixtures/espn_nfl_summary_snippet.json examples/nfl_espn_sample.json
python -m live_wp ingest-espn tests/fixtures/espn_ncaaf_summary_snippet.json examples/ncaaf_from_espn.json
python -m live_wp render-widget examples/ncaaf_sample.json widget/ncaaf_replay.js
python -m live_wp render-widget examples/ncaaf_cu_gt.json widget/ncaaf_cu_gt.js
python -m live_wp render-widget examples/nhl_col_min_g5.json widget/nhl_col_min_g5.js
```

## Follow

Unofficial ESPN NFL feed, command line only. The widget still only replays a saved file. Not affiliated with ESPN. Not betting advice. This breaks when ESPN changes the payload shape.

```powershell
python -m live_wp follow --date 20260920
python -m live_wp follow --game 401872940
```

`--date` prints each event id, away @ home, status, and score, then exits. `--game` polls that NFL event until it is final. The default pause is 15 seconds, and a pause under 5 seconds is rejected. A line is printed only when the clock, score, period, status, or situation changes. The first home moneyline is kept for later polls. If no payload has one, that prior stays 0.5. College football is rejected.

## Widget

Open [widget/index.html](widget/index.html) in a browser. There is no build step. The page loads six saved replays. Those win probabilities were already computed by the Python pack for that sport. The page does not estimate win probability and does not fetch.

Each sport uses local PNGs under widget/logos/nfl/, widget/logos/nhl/, widget/logos/nba/, widget/logos/ncaaf/, widget/logos/ncaah/, or widget/logos/ncaab/ when the abbreviation matches. Harbor has no logo. A missing logo file hides the image.

The buttons sit on two levels.

Pro:

- **NFL** plays the Giants at Denver.
- **NHL** plays Edmonton at Colorado.
- **NBA** plays Denver at the Lakers.

College:

- **NCAAF** plays Colorado at Texas Tech.
- **NCAAH** plays Michigan at Denver.
- **NCAAB** plays Colorado at Florida.

The page header reads Elevation Edge Sports Data, Multisport live win probability, and a small V3 badge. Compact and Expanded sit on that title line. Pro and College sit below that line. Expanded is the default. A replay whose last snapshot is final opens on that snapshot. Switching sport resets play. Compact is the ticker, including OT and 2OT as text. Expanded adds the two charts. Both charts share the period-band axis and move with play, pause, and the scrubber.

While a snapshot can still change, the home win probability stays off 0 and 1. The widget prints two decimals. A decided snapshot is final, or the end of regulation with a lead. It then prints 100 or 0 from the score.
