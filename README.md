# Multisport live win probability

Unofficial fan project. Not affiliated with the NFL, NHL, NBA, NCAA, or ESPN. Not betting advice.

Regular-season NFL overtime changed in 2025. Regular season and playoffs both give each team a possession, even if the first team scores a touchdown. Regular season is one 10-minute period and can tie, including when the first offense uses the whole period. Playoff overtime is 15 minutes and cannot tie. A defensive score on the first possession still ends the game. After both teams have possessed, the next score wins.

College football is a second config of the football pack. Regulation is four 15-minute quarters. College overtime is not a timed quarter and not the NFL 10-minute clock: each team gets a possession from the opponent 25, then 2-point tries after the second extra period.

NHL is the hockey pack. Regulation is three 20-minute periods. Regular-season overtime is 5:00 of 3-on-3, then a shootout. Game-win probability after a scoreless overtime follows the pregame rate gap and is not 0.5. Playoff overtime is 20:00 sudden death, not that shootout. A scoreless playoff period starts another 20:00.

The widget does not estimate win probability. On 127.0.0.1 or localhost it polls the live replay file and today's slate and does not request any other file. Each chart draws one pane per period. A completed regulation period gets one equal share. An extra period gets that share times the fraction of the period that elapsed. Football regulation is Q1 Q2 Q3 Q4. Hockey regulation is P1 P2 P3. Basketball keeps the quarters or halves already in the replay. Each extra period adds its own pane, labeled OT, then 2OT, then 3OT, on the chart axis. A 2OT football replay has six panes. A 2OT hockey replay has five. Michigan at Denver ends on the 2OT goal, so that pane is only the played fraction of a full period. OU at TEX does the same for OT and 2OT. A regulation replay has no OT pane. The scrubber readout is the current snapshot only: the period and clock, or FINAL. The situation line under that readout is the same snapshot. It stays blank on pregame, on a final, and when the snapshot has no situation.

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

A saved NFL, college-football, or NHL scoreboard event or game summary can be ingested to snapshots. NBA and NCAAB game summaries can be ingested on the same command. The adapter does not call the network. A college-football summary is written with sport `ncaaf`. An NHL summary is written with sport `nhl`. An NBA summary is written with sport `nba`. An NCAAB summary is written with sport `ncaab`. Any other league is refused. Follow sports are nfl, nhl, and nba. ESPN's unofficial site shape can change without notice. Not betting advice.

```powershell
python -m live_wp ingest-espn tests/fixtures/espn_nfl_summary_snippet.json examples/nfl_espn_sample.json
python -m live_wp ingest-espn tests/fixtures/espn_ncaaf_summary_snippet.json examples/ncaaf_from_espn.json
python -m live_wp render-widget examples/ncaaf_sample.json widget/ncaaf_replay.js
python -m live_wp render-widget examples/ncaaf_cu_gt.json widget/ncaaf_cu_gt.js
python -m live_wp render-widget examples/nhl_col_min_g5.json widget/nhl_col_min_g5.js
```

## Calibration

```powershell
python -m live_wp calibrate
```

The command replays every file in `examples/` and ingests the saved ESPN fixtures through the same path as `ingest-espn`. A file that path refuses is skipped and recorded. It prints a table and writes `artifacts/calibration.json`. That directory is gitignored.

This is a smoke table on the fixtures we have, not a historical backtest. The fixture count is too small to retune margin_sd, possession points, or strength multipliers.

## Follow

Unofficial ESPN feed, command line only. Follow sports are nfl, nhl, and nba. The widget still only replays a saved file. Not affiliated with ESPN. Not betting advice. This breaks when ESPN changes the payload shape.

```powershell
python -m live_wp follow --date 20260920
python -m live_wp follow --game 401872940
python -m live_wp follow --sport nhl --game 401871420
python -m live_wp follow --sport nba --game 401547684
```

`--sport` is nfl, nhl, or nba. nfl is the default. `--date` prints each event id, away @ home, status, and score, then exits. `--game` polls that event until it is final. The default pause is 15 seconds, and a pause under 5 seconds is rejected. A line is printed only when the clock, score, period, status, or situation changes. The first home moneyline is kept for later polls. If no payload has one, that prior stays 0.5. College football, college hockey, and college basketball are rejected.

## Serve

```powershell
python -m live_wp serve
python -m live_wp live --game 401872940
```

The server hosts the repository root. Open the served page and run live in another shell. On 127.0.0.1 or localhost the page polls that file and can show the live game. On that same host it also polls slate.js, written by `python -m live_wp slate`.

## Widget

Open [/](/) in a browser. GitHub Pages serves that root. There is no build step. `widget/manifest.js` lists the rendered replays the picker can open, with `sport`, `away`, `home`, `label`, and `file`. Red Oak at Harbor is the `examples/nfl_sample.json` prototype in `widget/nfl_replay.js`. A replay with home Harbor or away Harbor is omitted from that list and is not a game button. The file stays on disk. Pro shows NFL, NHL, and NBA. College shows NCAAF, NCAAH, and NCAAB. Choosing a sport loads that sport's first replay. When that sport has more than one replay, the page draws one button per replay using the manifest label. A sport with one replay does not draw that row. Choosing a game loads its file. Those win probabilities were already computed by the Python pack for that sport. The page does not estimate win probability. On 127.0.0.1 or localhost it polls live_replay.js and slate.js. Club colors for the selected sport load from assets/colors/{sport}.json. A game in the live file is a Live button on that sport's row, labeled from the frame. It is not a manifest entry. For the selected pro sport, today's slate is a row of buttons above the archive games. Each button reads away at home. A pre game has no score. A live, final, or stale game appends the away-home score. A sport with one archive replay still draws that replay when the slate is visible. College does not draw a slate row. A slate game whose id is the live file opens that replay. Any other slate game stops play and shows a scoreboard card with away, home, score, status, and the pregame prior. The page query keeps sport, game, and live=1, and adds id= while that card or the matching live game is selected.

```powershell
python -m live_wp write-manifest
```

`render-widget` rewrites the same manifest when it writes a script into `widget/`.

The six presentation demos stay in the list: NYG at DEN, EDM at COL, DEN at LAL, COLO at TTU, MICH at DEN, and COLO at FLA. The other rendered replays are listed with them. The Harbor prototype is not one of those buttons.

Each sport uses local PNGs under assets/logos/nfl/, assets/logos/nhl/, assets/logos/nba/, assets/logos/ncaaf/, assets/logos/ncaah/, or assets/logos/ncaab/. The logo URL is assets/logos/{sport}/{abbr}.png. Harbor has no logo. A missing logo file hides the image.

The page header reads Elevation Edge Sports Data, Multisport live win probability, and a small V4.0 badge. Compact and Expanded sit on that title line. Pro and College sit below that line and choose which three sports are shown. Expanded is the default. The page opens NYG at DEN. A replay whose last snapshot is final opens on that snapshot. Choosing a sport or a game stops play and opens on that snapshot when it is final. Compact is the ticker, including OT and 2OT as text. Expanded adds the two charts. Period labels stay on the chart axis. The charts move with play, pause, and the scrubber. The readout under the scrubber is the current snapshot only: the period and clock, or FINAL. The situation line under it follows that snapshot and stays blank when the snapshot has none.

While a snapshot can still change, the home win probability stays off 0 and 1. The widget prints two decimals. A decided snapshot is final, or the end of regulation with a lead. It then prints 100 or 0 from the score.
