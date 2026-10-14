# Multisport live win probability

Unofficial fan project. Not affiliated with any sport or league.

Win probability for NFL, NHL, NBA, NCAAF, NCAAH, and NCAAB. 

![Expanded view of an NFL slate, with the score and win-probability charts](screenshot.png)


## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Serve

```powershell
python -m live_win_prob serve
```

The live site is on GitHub Pages. Select any date to load that day’s slate and chart any game (scores and win probability).

For local development, run `python -m live_win_prob serve` and open http://127.0.0.1:8765.