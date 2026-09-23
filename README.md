# Multisport live win probability

Unofficial fan project. Not affiliated with the NFL, NHL, NBA, NCAA, or ESPN. Not betting advice.

The NFL widget demo is Jacksonville at Denver on 20 Sep 2026. The Harbor sample remains the unit fixture. The widget does not fetch.

When possession, down, distance, and yard line are all present, win probability includes a small expected-points term. If any of those is missing, it is the clock-and-score number. Team primary colors come from the replay frames. Not betting advice. Unofficial.

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
```

One line per snapshot: time, score, and the home win probability from `compute_wp(state, state.prior_home, nfl_config)`. `examples/nfl_sample.json` is the Harbor fixture. `examples/nfl_jax_den.json` is JAX at DEN.

## ESPN ingest

A saved ESPN NFL scoreboard event or game summary can be ingested to snapshots. The adapter does not call the network. ESPN's unofficial site shape can change without notice. Not betting advice. `ingest-espn --density situation` emits a snapshot per play with a full situation so the widget can move between scores.

```powershell
python -m live_wp ingest-espn tests/fixtures/espn_nfl_summary_snippet.json examples/nfl_espn_sample.json
python -m live_wp replay examples/nfl_espn_sample.json
python -m live_wp render-widget examples/nfl_espn_sample.json out.js
```

`replay` prints `compute_wp(state, state.prior_home, nfl_config)`. `render-widget` writes `window.NFL_REPLAY` with those win probabilities already computed. The page plays JAX at DEN. Harbor stays in `widget/nfl_replay.js` for tests.

## Widget

Open [widget/index.html](widget/index.html) in a browser. There is no build step. The page loads [widget/nfl_jax_den.js](widget/nfl_jax_den.js), the Jacksonville at Denver replay with win probabilities already computed by the Python football pack. The page script does not estimate win probability and does not fetch.

Three sport buttons:

- **NFL** plays JAX at DEN.
- **CFB** is disabled and marked next.
- **NHL** is disabled and marked soon.

The page header reads Elevation Edge Sports Data, Multisport live win probability, and a small V1 badge. Compact and Expanded sit on that title line, on the right. NFL, CFB, and NHL sit on the left of the row below. Expanded is the default. A replay whose last snapshot is final opens on that snapshot; a pre or live replay opens on the first snapshot. Compact is the small ticker on a home/away color field, with no charts. Expanded is the detail view, with larger team names and the two charts. Play, pause, and the scrubber walk the same snapshots the CLI prints.

While a snapshot can still change, home win probability is clipped to 0.0001–0.9999. The widget prints that as a percent with two decimals, so the live rails read 99.99% and 0.01%. A decided snapshot is `status=final`, or the Q4/OT clock at 0:00 with the score not tied. Home win probability is then 1.0 or 0.0 from the score, with no clip. The widget prints a final as 100 or 0.

Expanded shows two charts. Compact does not. Both charts share elapsed game time from the replay as the x-axis, and both move with play, pause, and the scrubber.

- Score: the away and home names from the replay, as two step series taken from the snapshot scores. On the demo those names are JAX and DEN.
- Win probability: one series, the home team's precomputed win probability. The home side of the scale is the bottom of the chart. Above 50% the line is the home color and the tint fills the gap up to the 50% line. Below 50% the line is the away color and the tint fills the gap down to 50%. The 50% line itself is thin. The page does not calculate the probability.
