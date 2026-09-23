# Multisport live win probability

Unofficial fan project. Not affiliated with the NFL, NHL, NBA, or NCAA. Not betting advice.

This slice replays a made-up NFL game from the clock, the score, and a constant pregame home win probability. It does not fetch a live feed.

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
```

One line per snapshot: time, score, and the home win probability from `compute_wp(state, state.prior_home, nfl_config)`.

## Widget

Open [widget/index.html](widget/index.html) in a browser. There is no build step. The page loads [widget/nfl_replay.js](widget/nfl_replay.js), which is the sample path with win probabilities already computed by the Python football pack. The page script does not estimate win probability and does not call ESPN.

Three sport buttons:

- **NFL** plays the sample.
- **CFB** is disabled and marked next.
- **NHL** is disabled and marked soon.

The page header reads Elevation Edge Sports Data, Multisport live win probability, and a small V0 badge. NFL, CFB, and NHL sit on the left of that control row. Compact and Expanded sit on the right. Expanded is the default. A replay whose last snapshot is final opens on that snapshot; a pre or live replay opens on the first snapshot. Compact is the small ticker on a home/away color field, with no charts. Expanded is the detail view, with larger team names and the two charts. Play, pause, and the scrubber walk the same snapshots the CLI prints.

While a snapshot can still change, home win probability is clipped to 0.0001–0.9999. The widget prints that as a percent with two decimals, so the live rails read 99.99% and 0.01%. A decided snapshot is `status=final`, or the Q4/OT clock at 0:00 with the score not tied. Home win probability is then 1.0 or 0.0 from the score, with no clip. The widget prints a final as 100 or 0.

Expanded shows two charts. Compact does not. Both charts share elapsed game time from the replay as the x-axis, and both move with play, pause, and the scrubber.

- Score: Harbor and Red Oak as two step series, taken from the snapshot scores.
- Win probability: one series, Harbor's precomputed win probability. Above 50% the line is Harbor's color and the tint fills the gap up to the 50% line. Below 50% the line is Red Oak's color and the tint fills the gap down to 50%. The 50% line itself is thin. The page does not calculate the probability.
