# Multisport live win probability

Unofficial fan project. Not affiliated with any sport or league.

Live and archived win probability for NFL, NHL, NBA, NCAAF, NCAAH, and NCAAB, each with its own model.

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

Open the served page. On localhost you can select a date and chart live or completed games. GitHub Pages shows the archive demos.
