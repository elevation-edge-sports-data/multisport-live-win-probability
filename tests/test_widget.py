"""Static widget contract: sport buttons, period panes, two views, no second model."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIDGET = ROOT / "widget"


class _Buttons(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.buttons: list[tuple[dict[str, str], str]] = []
        self._open = False
        self._attrs: dict[str, str] = {}
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "button":
            self._open = True
            self._attrs = {key: value or "" for key, value in attrs}
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "button" and self._open:
            self.buttons.append((self._attrs, "".join(self._text)))
            self._open = False

    def handle_data(self, data: str) -> None:
        if self._open:
            self._text.append(data)


def test_widget_filters_games_from_the_manifest_and_keeps_two_views():
    html = (WIDGET / "index.html").read_text(encoding="utf-8")
    css = (WIDGET / "widget.css").read_text(encoding="utf-8")
    script = (WIDGET / "widget.js").read_text(encoding="utf-8")
    page = html.lower()
    assert "espn" not in page
    assert "espn.com" not in page
    assert "http://" not in page and "https://" not in page
    assert "fetch(" not in script
    assert "espn" not in script
    assert "https://" not in script
    assert "fetch(" not in css
    assert "espn" not in css.lower()
    assert "http://" not in css and "https://" not in css
    assert "logos/nfl/" not in html
    assert 'id="c-home-logo"' in html and 'id="c-away-logo"' in html
    assert 'id="e-home-logo"' in html and 'id="e-away-logo"' in html
    assert html.count("<img") == 4
    assert "applyLogo" in script
    assert "img.hidden = true" in script
    assert "frame.home_logo" in script and "frame.away_logo" in script
    assert 'src="manifest.js"' in html
    assert 'src="live_replay.js"' in html
    assert html.index('src="manifest.js"') < html.index('src="live_replay.js"')
    assert html.index('src="live_replay.js"') < html.index('src="colors.js"')
    assert html.index('src="colors.js"') < html.index('src="widget.js"')
    for name in (
        "nfl_nyg_den.js",
        "nhl_edm_col.js",
        "nba_den_lal.js",
        "ncaaf_cu_ttu.js",
        "ncaah_den_mich.js",
        "ncaab_cu_fla.js",
        "ncaaf_replay.js",
    ):
        assert f'src="{name}"' not in html
    assert (WIDGET / "nfl_replay.js").is_file()
    assert "Red Oak" not in script
    assert 'home !== "harbor" && away !== "harbor"' in script
    assert "frame.home_color" in script or "home_color" in script
    assert "away_color" in script
    assert "--home: #1f8f86" in css
    assert "--away: #c94b32" in css
    demo = (WIDGET / "nfl_nyg_den.js").read_text(encoding="utf-8").lower()
    assert "espn" not in demo
    assert "fetch(" not in demo
    assert "https://" not in demo and "http://" not in demo
    assert "margin_sd" not in script
    assert "college hockey" not in page

    parser = _Buttons()
    parser.feed(html)
    sports = [item for item in parser.buttons if "sport" in item[0].get("class", "")]
    views = [item for item in parser.buttons if "data-view-choice" in item[0]]
    assert [text.strip() for _, text in sports] == ["Pro", "College"]
    assert all("disabled" not in item[0] for item in sports)
    assert ">Pro<" in html and ">College<" in html
    assert html.index('id="level-pro"') < html.index('id="level-college"')
    assert html.index('id="level-college"') < html.index('id="sports"')
    assert html.index('id="sports"') < html.index('id="game-row"')
    assert html.index('id="game-row"') < html.index('id="games"')
    assert 'id="scrub-panes"' not in html
    assert 'id="position"' in html
    assert 'text("position", frame.clock)' in script
    assert "renderScrubPanes" not in script
    assert [item[0]["data-view-choice"] for item in views] == ["compact", "expanded"]
    assert 'data-view="expanded"' in html
    assert views[0][0].get("aria-pressed") == "false"
    assert views[1][0].get("aria-pressed") == "true"
    assert "function openingIndex" in script
    assert 'last.status === "final"' in script
    assert "Not betting advice" not in html
    assert "Unofficial project from Elevation Edge Sports Data." in html
    assert "split-colors" not in html + css + script
    assert "large-marks" not in html + css + script
    assert "Split colors" not in html and "Large marks" not in html

    sport_text = " ".join(text for _, text in sports)
    assert "CFB" not in sport_text and "CBB" not in html
    assert "college hockey" not in (html + css + script).lower()
    assert html.index("title-line") < html.index("data-view-choice") < html.index('class="toolbar"')
    assert ">V3<" not in html and ">V3.3<" not in html and ">V0<" not in html
    assert 'id="badge"' in html
    assert script.count("V3.3") == 1
    assert 'var BADGE_TEXT = "V3.3"' in script
    assert "badge.textContent = BADGE_TEXT" in script
    assert 'src="colors.js"' in html
    assert 'data-theme="charcoal"' in html
    assert 'id="theme-dark"' in html and 'id="theme-light"' in html
    assert ">Dark<" in html and ">Light<" in html
    assert "Charcoal" not in html and "Off-white" not in html
    assert html.index('id="theme-dark"') < html.index('id="theme-light"')
    assert html.index('aria-pressed="true">Dark<') < html.index('aria-pressed="false">Light<')
    assert html.index('id="scrub"') < html.index('id="appearance"') < html.index('id="prior"')
    assert 'localStorage.getItem("mswp:theme")' in html
    assert "saved.theme" not in html and "saved.theme" not in script
    assert 'localStorage.setItem("mswp:theme", themeName)' in script
    assert "theme: themeName" not in script
    assert 'getElementById("theme-dark")' in script
    assert 'getElementById("theme-light")' in script
    assert "playhead" not in script
    assert "end-cap" in script
    assert "localStorage" in script
    assert 'id="play"' in html
    assert html.index('id="play"') < html.index('id="step-forward"') < html.index('id="step-back"')
    assert "Step forward" in html and "Step back" in html
    assert "tri-right" in html and "tri-left" in html
    assert 'id="scrub"' in html
    assert ".position" in css and "text-align: right" in css
    assert "function yAtLow" in script
    assert "yAtLow(current.p, 0, 1)" in script
    assert "function step" in script
    assert "Pregame home " not in script
    assert "Pregame " in script
    assert "pregame > 0.5" in script
    assert 'id="score-chart"' in html
    assert 'id="wp-chart"' in html
    assert ".charts { display: none; }" in css
    assert '[data-view="expanded"] .charts' in css
    assert "panel compact" in html
    assert 'id="score-chart"' not in html.split('class="panel compact"', 1)[1].split("</article>", 1)[0]
    assert "frame.home_score" in script or "home_score" in script
    assert "frame.wp" in script
    assert "wp-rail" in script
    assert "NormalDist" not in script
    assert "Home win probability" not in html
    assert "function frameIsOvertime" in script
    assert "Number(frame.period) > 4" in script
    assert '=== "ot"' in script
    assert '"Q" + (bi + 1)' in script
    assert "function overtimeLabel" in script
    assert "function paneName" in script
    assert "function axisLabels" in script
    assert 'text: "OT"' not in script
    assert 'text: "2OT"' not in script
    assert "OT_PANE_FLOOR" not in script
    assert '["nfl", "nhl", "nba", "ncaaf", "ncaah", "ncaab"]' in script
    assert "function bandPosition" in script
    assert "function loadGame" in script
    assert "function useFrames" in script
    assert "MSWP_MANIFEST" in script
    assert "sport-nfl" not in script
    for binding in ("NFL_REPLAY", "NHL_REPLAY", "NBA_REPLAY", "NCAAF_REPLAY", "NCAAH_REPLAY", "NCAAB_REPLAY"):
        assert f'return "{binding}"' in script
    assert 'getElementById("level-pro").addEventListener("click"' in script
    assert 'getElementById("level-college").addEventListener("click"' in script
    assert 'getElementById("sports").addEventListener("click"' in script
    assert 'getElementById("games").addEventListener("click"' in script
    load_game = script[script.index("function loadGame"): script.index("playButton.addEventListener")]
    assert load_game.index("setPlaying(false)") < load_game.index('createElement("script")')
    use_frames = script[script.index("function useFrames"): script.index("function loadGame")]
    assert use_frames.index("setPlaying(false)") < use_frames.index("openingIndex(frames)")
    for path in WIDGET.rglob("*"):
        if path.suffix.lower() not in {".html", ".js", ".css"}:
            continue
        text = path.read_text(encoding="utf-8").lower()
        assert "espn" not in text, path.name
        assert "espn.com" not in text, path.name
        assert "fetch(" not in text, path.name
        assert "https://" not in text, path.name
        bare = text.replace("http://www.w3.org/2000/svg", "")
        assert "http://" not in bare, path.name
    ncaaf_logos = sorted(path.name for path in (WIDGET / "logos" / "ncaaf").iterdir())
    assert ncaaf_logos == ["COLO.png", "GT.png", "TTU.png"]


def test_extra_period_panes_follow_time_played():
    node = shutil.which("node")
    assert node, "node is required to check the chart geometry"
    probe = r"""
const fs = require("fs");
const vm = require("vm");
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("widget/widget.js", "utf8"), sandbox);
const bands = sandbox.mswpBands;
const text = fs.readFileSync("widget/ncaaf_replay.js", "utf8");
const frames = JSON.parse(text.slice(text.indexOf("["), text.lastIndexOf("]") + 1));
const layout = bands.layoutBands(frames, "ncaaf");
const placed = frames.map((frame) => ({
  period: frame.period,
  x: bands.bandPosition(frame, frames, layout, "ncaaf")
}));
const q4 = placed.filter((row) => row.period === 4).map((row) => row.x);
const ot = placed.filter((row) => row.period === 5).map((row) => row.x);
const two = placed.filter((row) => row.period === 6).map((row) => row.x);
const nfl = [
  {period: 4, seconds_remaining_period: 0, status: "live", clock: "Q4 0:00"},
  {period: 5, seconds_remaining_period: 600, status: "live", clock: "OT 10:00"},
  {period: 5, seconds_remaining_period: 0, status: "live", clock: "OT 0:00"},
  {period: 6, seconds_remaining_period: 300, status: "live", clock: "2OT 5:00"}
];
const nflLayout = bands.layoutBands(nfl, "nfl");
const nflX = nfl.map((frame) => bands.bandPosition(frame, nfl, nflLayout, "nfl"));
const empty = [
  {period: 1, seconds_remaining_period: 900, status: "live", clock: "Q1 15:00"},
  {period: 4, seconds_remaining_period: 450, status: "live", clock: "Q4 7:30"}
];
const emptyLayout = bands.layoutBands(empty, "nfl");
const otOnly = [
  {period: 4, seconds_remaining_period: 0, status: "live", clock: "Q4 0:00"},
  {period: 5, seconds_remaining_period: 300, status: "final", clock: "FINAL"}
];
const otOnlyLayout = bands.layoutBands(otOnly, "nfl");
const three = [
  {period: 4, seconds_remaining_period: 0, status: "live", clock: "Q4 0:00"},
  {period: 7, seconds_remaining_period: 100, status: "live", clock: "3OT 1:40"}
];
const threeLayout = bands.layoutBands(three, "nfl");
const threeX = bands.bandPosition(three[1], three, threeLayout, "nfl");
const nba = [{period: 2, seconds_remaining_period: 360, status: "live", clock: "Q2 6:00"}];
const nbaLayout = bands.layoutBands(nba, "nba");
const ncaab = [
  {period: 2, seconds_remaining_period: 600, status: "live", clock: "H2 10:00"},
  {period: 3, seconds_remaining_period: 120, status: "live", clock: "OT 2:00"}
];
const ncaabLayout = bands.layoutBands(ncaab, "ncaab");
function names(rows, sport, bandLayout) {
  return bands.axisLabels(rows, sport, bandLayout).map((item) => item.text);
}
console.log(JSON.stringify({
  span: layout.span,
  paneCount: layout.paneCount,
  widths: layout.widths,
  q4max: Math.max(...q4),
  otmin: Math.min(...ot),
  otmax: Math.max(...ot),
  twomin: Math.min(...two),
  twomax: Math.max(...two),
  labelAt: bands.axisLabels(frames, "ncaaf", layout).map((item) => item.at),
  nfl: nflX,
  nflSpan: nflLayout.span,
  nflPaneCount: nflLayout.paneCount,
  nflWidths: nflLayout.widths,
  emptySpan: emptyLayout.span,
  emptyWidths: emptyLayout.widths,
  emptyQ4: bands.bandPosition(empty[1], empty, emptyLayout, "nfl"),
  labels: names(frames, "ncaaf", layout),
  nflLabels: names(nfl, "nfl", nflLayout),
  otOnlyLabels: names(otOnly, "nfl", otOnlyLayout),
  otOnlySpan: otOnlyLayout.span,
  otOnlyWidths: otOnlyLayout.widths,
  threeSpan: threeLayout.span,
  threeX: threeX,
  threeLabels: names(three, "nfl", threeLayout),
  threeWidths: threeLayout.widths,
  nbaLabels: names(nba, "nba", nbaLayout),
  nbaSpan: nbaLayout.span,
  ncaabLabels: names(ncaab, "ncaab", ncaabLayout),
  ncaabSpan: ncaabLayout.span,
  ncaabWidths: ncaabLayout.widths
}));
"""
    completed = subprocess.run(
        [node, "-e", probe],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)
    ou_share = 6 / 7
    assert report["paneCount"] == 6
    assert report["widths"][:4] == [1, 1, 1, 1]
    assert report["widths"][4] == pytest.approx(ou_share)
    assert report["widths"][5] == pytest.approx(ou_share)
    assert report["widths"][4] < 1 and report["widths"][5] < 1
    assert report["span"] == pytest.approx(4 + ou_share + ou_share)
    assert report["span"] < 6
    assert report["q4max"] <= 4
    assert report["otmin"] > 4
    assert report["otmax"] == pytest.approx(4 + ou_share)
    assert report["twomin"] > report["otmax"]
    assert report["twomax"] == pytest.approx(report["span"])
    assert report["labelAt"][:4] == pytest.approx([0.5, 1.5, 2.5, 3.5])
    assert report["labelAt"][4] == pytest.approx(4 + ou_share / 2)
    assert report["labelAt"][5] == pytest.approx(4 + ou_share + ou_share / 2)
    q4_end, ot_start, ot_end, two_start = report["nfl"]
    assert q4_end == 4
    assert ot_start == 4
    assert ot_end == 5
    assert report["nflWidths"] == pytest.approx([1, 1, 1, 1, 1, 0.5])
    assert two_start == pytest.approx(5.5)
    assert two_start == pytest.approx(report["nflSpan"])
    assert report["nflSpan"] == pytest.approx(5.5)
    assert report["nflPaneCount"] == 6
    assert report["nflSpan"] < 6
    assert report["emptySpan"] == 4
    assert report["emptyWidths"] == [1, 1, 1, 1]
    assert 3 < report["emptyQ4"] < 4
    assert report["labels"] == ["Q1", "Q2", "Q3", "Q4", "OT", "2OT"]
    assert report["nflLabels"] == ["Q1", "Q2", "Q3", "Q4", "OT", "2OT"]
    assert report["otOnlyLabels"] == ["Q1", "Q2", "Q3", "Q4", "OT"]
    assert report["otOnlyWidths"] == pytest.approx([1, 1, 1, 1, 0.5])
    assert report["otOnlySpan"] == pytest.approx(4.5)
    assert report["threeWidths"] == pytest.approx([1, 1, 1, 1, 1, 1, 500 / 600])
    assert report["threeSpan"] == pytest.approx(4 + 1 + 1 + 500 / 600)
    assert report["threeX"] == pytest.approx(report["threeSpan"])
    assert report["threeSpan"] < 7
    assert report["threeLabels"] == ["Q1", "Q2", "Q3", "Q4", "OT", "2OT", "3OT"]
    assert report["nbaLabels"] == ["Q1", "Q2", "Q3", "Q4"]
    assert report["nbaSpan"] == 4
    assert report["ncaabLabels"] == ["H1", "H2", "OT"]
    assert report["ncaabWidths"] == pytest.approx([1, 1, 0.6])
    assert report["ncaabSpan"] == pytest.approx(2.6)


def test_hockey_period_bands_keep_each_extra_period():
    node = shutil.which("node")
    assert node, "node is required to check the chart geometry"
    probe = r"""
const fs = require("fs");
const vm = require("vm");
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("widget/widget.js", "utf8"), sandbox);
const bands = sandbox.mswpBands;
const regulation = [
  {period: 1, seconds_remaining_period: 1200, status: "live", clock: "P1 20:00"},
  {period: 2, seconds_remaining_period: 600, status: "live", clock: "P2 10:00"},
  {period: 3, seconds_remaining_period: 0, status: "live", clock: "P3 0:00"}
];
const bare = bands.layoutBands(regulation, "nhl");
const withOt = regulation.concat([
  {period: 4, seconds_remaining_period: 1200, status: "live", clock: "OT 20:00"},
  {period: 4, seconds_remaining_period: 968, status: "live", clock: "OT 16:08"},
  {period: 4, seconds_remaining_period: 968, status: "final", clock: "FINAL"}
]);
const layout = bands.layoutBands(withOt, "nhl");
const placed = withOt.map((frame) => bands.bandPosition(frame, withOt, layout, "nhl"));
const football = bands.layoutBands(regulation);
const twoOt = regulation.concat([
  {period: 4, seconds_remaining_period: 600, status: "live", clock: "OT 10:00"},
  {period: 5, seconds_remaining_period: 600, status: "live", clock: "2OT 10:00"}
]);
const twoLayout = bands.layoutBands(twoOt, "nhl");
console.log(JSON.stringify({
  bareSpan: bare.span,
  bareLabels: bands.axisLabels(regulation, "nhl", bare).map((item) => item.text),
  span: layout.span,
  paneCount: layout.paneCount,
  widths: layout.widths,
  p3: placed[2],
  otStart: placed[3],
  otGoal: placed[4],
  finalX: placed[5],
  footballSpan: football.span,
  labels: bands.axisLabels(withOt, "nhl", layout).map((item) => item.text),
  twoSpan: twoLayout.span,
  twoWidths: twoLayout.widths,
  twoLabels: bands.axisLabels(twoOt, "nhl", twoLayout).map((item) => item.text)
}));
"""
    completed = subprocess.run(
        [node, "-e", probe],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)
    ot_played = (1200 - 968) / 1200
    assert report["bareSpan"] == 3
    assert report["bareLabels"] == ["P1", "P2", "P3"]
    assert "OT" not in report["bareLabels"]
    assert report["paneCount"] == 4
    assert report["widths"] == pytest.approx([1, 1, 1, ot_played])
    assert report["widths"][3] < 1
    assert report["span"] == pytest.approx(3 + ot_played)
    assert report["p3"] == 3
    assert report["otStart"] == 3
    assert report["otGoal"] == pytest.approx(report["span"])
    assert report["otGoal"] > report["otStart"]
    assert report["finalX"] == pytest.approx(report["otGoal"])
    assert report["footballSpan"] == 4
    assert report["labels"] == ["P1", "P2", "P3", "OT"]
    assert report["twoWidths"] == pytest.approx([1, 1, 1, 0.5, 0.5])
    assert report["twoSpan"] == pytest.approx(4)
    assert report["twoSpan"] < 5
    assert report["twoLabels"] == ["P1", "P2", "P3", "OT", "2OT"]
    ncaah = r"""
const fs = require("fs");
const vm = require("vm");
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("widget/widget.js", "utf8"), sandbox);
const bands = sandbox.mswpBands;
const text = fs.readFileSync("widget/ncaah_den_mich.js", "utf8");
const frames = JSON.parse(text.slice(text.indexOf("["), text.lastIndexOf("]") + 1));
const layout = bands.layoutBands(frames, "ncaah");
const last = frames[frames.length - 1];
const finalX = bands.bandPosition(last, frames, layout, "ncaah");
const goal = frames.filter((frame) => frame.clock === "2OT 7:25")[0];
console.log(JSON.stringify({
  span: layout.span,
  paneCount: layout.paneCount,
  widths: layout.widths,
  finalX: finalX,
  goalX: bands.bandPosition(goal, frames, layout, "ncaah"),
  labelAt: bands.axisLabels(frames, "ncaah", layout).map((item) => item.at),
  labels: bands.axisLabels(frames, "ncaah", layout).map((item) => item.text)
}));
"""
    completed = subprocess.run(
        [node, "-e", ncaah],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    ncaah_report = json.loads(completed.stdout)
    ot_width = (1200 - 26) / 1200
    two_width = (1200 - 445) / 1200
    assert ncaah_report["paneCount"] == 5
    assert ncaah_report["widths"][:3] == [1, 1, 1]
    assert ncaah_report["widths"][3] == pytest.approx(ot_width)
    assert ncaah_report["widths"][4] == pytest.approx(two_width)
    assert ncaah_report["widths"][4] < 1
    assert ncaah_report["widths"][4] < ncaah_report["widths"][0]
    assert ncaah_report["span"] == pytest.approx(3 + ot_width + two_width)
    assert ncaah_report["span"] < 5
    assert ncaah_report["finalX"] == pytest.approx(ncaah_report["goalX"])
    assert ncaah_report["goalX"] == pytest.approx(ncaah_report["span"])
    assert 4 < ncaah_report["goalX"] < 5
    assert ncaah_report["labelAt"][:3] == pytest.approx([0.5, 1.5, 2.5])
    assert ncaah_report["labels"] == ["P1", "P2", "P3", "OT", "2OT"]
    node = shutil.which("node")
    assert node, "node is required to check the chart geometry"
    probe = r"""
const fs = require("fs");
const vm = require("vm");
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("widget/widget.js", "utf8"), sandbox);
const bands = sandbox.mswpBands;
const text = fs.readFileSync("widget/ncaaf_cu_gt.js", "utf8");
const frames = JSON.parse(text.slice(text.indexOf("["), text.lastIndexOf("]") + 1));
const layout = bands.layoutBands(frames);
const overtime = frames.filter((frame) => bands.frameIsOvertime(frame, "ncaaf"));
console.log(JSON.stringify({
  span: layout.span,
  paneCount: layout.paneCount,
  extras: layout.extras,
  overtime: overtime.length,
  periods: [...new Set(frames.map((frame) => frame.period))],
  labels: bands.axisLabels(frames, "ncaaf", layout).map((item) => item.text)
}));
"""
    completed = subprocess.run(
        [node, "-e", probe],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)
    assert report["span"] == 4
    assert report["paneCount"] == 4
    assert report["extras"] == []
    assert report["overtime"] == 0
    assert report["periods"] == [1, 2, 3, 4]
    assert report["labels"] == ["Q1", "Q2", "Q3", "Q4"]
    assert "OT" not in report["labels"]


def test_appearance_keeps_the_changed_team_and_colorado_gold():
    node = shutil.which("node")
    assert node, "node is required to check appearance rules"
    probe = r"""
const fs = require("fs");
const vm = require("vm");
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("widget/colors.js", "utf8"), sandbox);
vm.runInContext(fs.readFileSync("widget/widget.js", "utf8"), sandbox);
const app = sandbox.mswpAppearance;
function club(sport, id) {
  return app.findClub(sport, id);
}
const colo = club("ncaaf", "COLO");
const ttu = club("ncaaf", "TTU");
const nyg = club("nfl", "NYG");
const den = club("nfl", "DEN");
const coloNames = app.buildSwatches(colo).map((swatch) => swatch.name + " " + swatch.hex);
const ttuNames = app.buildSwatches(ttu).map((swatch) => swatch.name);
const denNames = app.buildSwatches(den).map((swatch) => swatch.name);
const defaults = app.resolveDefaults(colo, ttu, "charcoal");
const bothWhite = app.resolveChange(nyg, den, "charcoal", "#FFFFFF", "#FFFFFF", "home", "#FFFFFF");
const light = app.resolveChange(colo, ttu, "offwhite", "#CFB87C", "#CC0000", "home", "#FFFFFF");
const keptNavy = app.restorePair(nyg, den, "charcoal", "#0B2265", "#FB4F14");
const keptWhite = app.restorePair(nyg, den, "offwhite", "#A71930", "#FFFFFF");
const unknown = app.restorePair(nyg, den, "charcoal", "#123456", "#FB4F14");
const nflDefaults = app.resolveDefaults(nyg, den, "charcoal");
let record = app.appearanceRecord(null, "charcoal", "#0B2265", "#FB4F14");
record = app.appearanceRecord(record, "offwhite", "#A71930", "#FFFFFF");
const darkSlot = app.swatchesForTheme(record, "charcoal");
const lightSlot = app.swatchesForTheme(record, "offwhite");
record = app.appearanceRecord(record, "charcoal", "#0B2265", "#FFFFFF");
const darkAfter = app.swatchesForTheme(record, "charcoal");
const lightAfter = app.swatchesForTheme(record, "offwhite");
const legacy = { homeSwatch: "#FB4F14", awaySwatch: "#A71930" };
const migrated = app.appearanceRecord(legacy, "charcoal", legacy.awaySwatch, legacy.homeSwatch);
console.log(JSON.stringify({
  coloNames: coloNames,
  ttuNames: ttuNames,
  denNames: denNames,
  away: defaults.away,
  home: defaults.home,
  whiteAway: bothWhite.away,
  whiteHome: bothWhite.home,
  lightAway: light.away,
  lightHome: light.home,
  keptNavy: keptNavy,
  keptWhite: keptWhite,
  unknownAway: unknown.away,
  unknownHome: unknown.home,
  nflAway: nflDefaults.away,
  nflHome: nflDefaults.home,
  darkSlot: darkSlot,
  lightSlot: lightSlot,
  darkAfter: darkAfter,
  lightAfter: lightAfter,
  legacyDark: app.swatchesForTheme(legacy, "charcoal"),
  migratedDark: app.swatchesForTheme(migrated, "charcoal"),
  migratedLight: app.swatchesForTheme(migrated, "offwhite")
}));
"""
    completed = subprocess.run(
        [node, "-e", probe],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)
    assert report["coloNames"] == ["Gold #CFB87C", "Silver #A2A4A3", "White #FFFFFF", "Black #000000"]
    assert report["ttuNames"] == ["Red", "Black", "White"]
    assert "Black" not in report["denNames"]
    assert report["away"] == "#CFB87C"
    assert report["home"] == "#CC0000"
    assert report["whiteHome"] == "#FFFFFF"
    assert report["whiteAway"] != "#FFFFFF"
    assert report["lightHome"] == "#FFFFFF"
    assert report["lightAway"] == "#000000"
    assert report["keptNavy"] == {"away": "#0B2265", "home": "#FB4F14"}
    assert report["keptWhite"] == {"away": "#A71930", "home": "#FFFFFF"}
    assert report["unknownAway"] == report["nflAway"]
    assert report["unknownHome"] == report["nflHome"]
    assert report["keptNavy"]["away"] != report["nflAway"]
    assert report["darkSlot"] == {"homeSwatch": "#FB4F14", "awaySwatch": "#0B2265"}
    assert report["lightSlot"] == {"homeSwatch": "#FFFFFF", "awaySwatch": "#A71930"}
    assert report["darkAfter"] == {"homeSwatch": "#FFFFFF", "awaySwatch": "#0B2265"}
    assert report["lightAfter"] == report["lightSlot"]
    assert report["legacyDark"] == {"homeSwatch": "#FB4F14", "awaySwatch": "#A71930"}
    assert report["migratedDark"] == {"homeSwatch": "#FB4F14", "awaySwatch": "#A71930"}
    assert report["migratedLight"] is None
    widget_script = (WIDGET / "widget.js").read_text(encoding="utf-8")
    set_theme = widget_script[widget_script.index("function setTheme"):widget_script.index("function show")]
    assert set_theme.index("writeAppearance()") < set_theme.index("themeName = next")
    assert "repairPair(" not in set_theme


_DEMOS = {
    "nfl_nyg_den.js": ("nfl", "NYG", "DEN"),
    "nhl_edm_col.js": ("nhl", "EDM", "COL"),
    "nba_den_lal.js": ("nba", "DEN", "LAL"),
    "ncaaf_cu_ttu.js": ("ncaaf", "COLO", "TTU"),
    "ncaah_den_mich.js": ("ncaah", "MICH", "DEN"),
    "ncaab_cu_fla.js": ("ncaab", "COLO", "FLA"),
}


def _rendered_replay_names() -> set[str]:
    names: set[str] = set()
    for path in WIDGET.glob("*.js"):
        text = path.read_text(encoding="utf-8")
        if "window." in text and "_REPLAY =" in text:
            names.add(path.name)
    return names


def test_write_manifest_lists_rendered_replays_except_harbor(tmp_path):
    from live_wp.replay import manifest_entries, manifest_entry, render_manifest_script, write_manifest

    dest = write_manifest()
    assert dest == WIDGET / "manifest.js"
    text = dest.read_text(encoding="utf-8")
    assert text == render_manifest_script(manifest_entries(WIDGET))
    assert "espn.com" not in text.lower()
    assert "fetch(" not in text
    assert "https://" not in text and "http://" not in text
    assert "Harbor" not in text and "Red Oak" not in text
    entries = json.loads(text[text.index("[") : text.rindex("]") + 1])
    by_file = {entry["file"]: entry for entry in entries}
    assert _DEMOS.keys() <= by_file.keys()
    assert len(entries) > len(_DEMOS)
    rendered = _rendered_replay_names()
    assert "nfl_replay.js" in rendered
    assert "nfl_replay.js" not in by_file
    assert rendered - {"nfl_replay.js"} == set(by_file)
    assert manifest_entry(WIDGET / "nfl_replay.js") is None
    away_harbor = tmp_path / "away_harbor.js"
    away_harbor.write_text(
        'window.NFL_REPLAY = [{"away": "Harbor", "home": "DEN", "period": 1}];\n',
        encoding="utf-8",
        newline="\n",
    )
    assert manifest_entry(away_harbor) is None
    assert "live_replay.js" not in by_file
    assert "widget.js" not in by_file
    assert "colors.js" not in by_file
    nfl = [entry for entry in entries if entry["sport"] == "nfl"]
    assert nfl[0]["file"] == "nfl_nyg_den.js"
    for entry in entries:
        assert entry["home"].casefold() != "harbor"
        assert entry["away"].casefold() != "harbor"
    for file_name, (sport, away, home) in _DEMOS.items():
        entry = by_file[file_name]
        assert list(entry) == ["sport", "away", "home", "label", "file"]
        assert entry["sport"] == sport
        assert entry["away"] == away
        assert entry["home"] == home
        assert entry["label"] == f"{away} at {home}"
    harbor = (WIDGET / "nfl_replay.js").read_text(encoding="utf-8")
    assert "home_logo" not in harbor and "away_logo" not in harbor
    assert '"home": "Harbor"' in harbor
    assert '"away": "Red Oak"' in harbor
    completed = subprocess.run(
        [sys.executable, "-m", "live_wp", "write-manifest"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert dest.read_text(encoding="utf-8") == text


def test_render_widget_refreshes_the_manifest_only_in_widget(tmp_path, monkeypatch):
    from live_wp import replay as replay_mod
    from live_wp.__main__ import render_widget

    monkeypatch.setattr(replay_mod, "_WIDGET_DIR", tmp_path)
    assert render_widget(ROOT / "examples" / "ncaaf_sample.json", tmp_path / "ncaaf_replay.js") == 0
    manifest = json.loads(
        (tmp_path / "manifest.js").read_text(encoding="utf-8").split("=", 1)[1].strip().rstrip(";")
    )
    assert manifest == [
        {
            "sport": "ncaaf",
            "away": "OU",
            "home": "TEX",
            "label": "OU at TEX",
            "file": "ncaaf_replay.js",
        }
    ]
    assert render_widget(ROOT / "examples" / "nfl_sample.json", tmp_path / "nfl_replay.js") == 0
    assert (tmp_path / "nfl_replay.js").is_file()
    manifest = json.loads(
        (tmp_path / "manifest.js").read_text(encoding="utf-8").split("=", 1)[1].strip().rstrip(";")
    )
    assert manifest == [
        {
            "sport": "ncaaf",
            "away": "OU",
            "home": "TEX",
            "label": "OU at TEX",
            "file": "ncaaf_replay.js",
        }
    ]
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert render_widget(ROOT / "examples" / "nfl_sample.json", elsewhere / "harbor.js") == 0
    assert not (elsewhere / "manifest.js").is_file()
    harbor = json.loads(elsewhere.joinpath("harbor.js").read_text(encoding="utf-8").split("=", 1)[1].strip().rstrip(";"))
    assert "home_logo" not in harbor[0] and "away_logo" not in harbor[0]
    assert harbor[-1]["home"] == "Harbor"
    assert harbor[-1]["home_score"] == 27
    assert harbor[-1]["away_score"] == 23


def test_sport_buttons_load_manifest_games_and_keep_2ot_panes(tmp_path):
    node = shutil.which("node")
    assert node, "node is required to load the manifest"
    from live_wp.replay import write_manifest

    write_manifest()
    probe = r"""
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function element(tag) {
  const el = {
    tagName: String(tag).toUpperCase(),
    children: [],
    attrs: {},
    style: {
      setProperty(name, value) { this[name] = value; },
      removeProperty(name) { delete this[name]; }
    },
    hidden: false,
    className: "",
    parentNode: null,
    listeners: {},
    value: "",
    max: "",
    src: "",
    _text: "",
    id: "",
    dataset: {}
  };
  el.classList = {
    add(name) {
      const parts = el.className.split(/\s+/).filter(Boolean);
      if (parts.indexOf(name) < 0) parts.push(name);
      el.className = parts.join(" ");
    },
    remove(name) {
      el.className = el.className.split(/\s+/).filter((part) => part && part !== name).join(" ");
    },
    toggle(name, force) {
      const parts = el.className.split(/\s+/).filter(Boolean);
      const has = parts.indexOf(name) >= 0;
      const on = arguments.length > 1 ? !!force : !has;
      if (on && !has) parts.push(name);
      if (!on) {
        el.className = parts.filter((part) => part !== name).join(" ");
        return on;
      }
      el.className = parts.join(" ");
      return on;
    }
  };
  el.setAttribute = (key, value) => { el.attrs[key] = String(value); };
  el.getAttribute = (key) => (Object.prototype.hasOwnProperty.call(el.attrs, key) ? el.attrs[key] : null);
  el.removeAttribute = (key) => { delete el.attrs[key]; };
  el.appendChild = (child) => {
    if (child) child.parentNode = el;
    el.children.push(child);
    return child;
  };
  el.removeChild = (child) => {
    el.children = el.children.filter((item) => item !== child);
    return child;
  };
  Object.defineProperty(el, "firstChild", { get: () => el.children[0] || null });
  Object.defineProperty(el, "textContent", {
    get: () => el._text,
    set: (value) => {
      el._text = value == null ? "" : String(value);
      el.children = [];
    }
  });
  el.addEventListener = (type, fn) => {
    if (!el.listeners[type]) el.listeners[type] = [];
    el.listeners[type].push(fn);
  };
  el.click = () => {
    const event = { target: el };
    let node = el;
    while (node) {
      const list = node.listeners && node.listeners.click ? node.listeners.click.slice() : [];
      list.forEach((fn) => fn(event));
      node = node.parentNode;
    }
  };
  return el;
}

const byId = {};
function getElementById(id) {
  if (!byId[id]) byId[id] = element("div");
  byId[id].id = id;
  return byId[id];
}
const viewCompact = element("button");
const viewExpanded = element("button");
viewCompact.setAttribute("data-view-choice", "compact");
viewExpanded.setAttribute("data-view-choice", "expanded");
const docEl = element("html");
docEl.setAttribute("data-theme", "charcoal");
const body = element("body");
const store = {};
const document = {
  documentElement: docEl,
  body: body,
  getElementById: getElementById,
  createElement: (tag) => element(tag),
  createElementNS: (_ns, tag) => element(tag),
  createTextNode: (text) => ({ nodeType: 3, textContent: String(text), parentNode: null }),
  querySelectorAll: (selector) => (selector === "[data-view-choice]" ? [viewCompact, viewExpanded] : [])
};
const sandbox = {
  console,
  setInterval: () => 1,
  clearInterval: () => {},
  getComputedStyle: () => ({ getPropertyValue: () => "#888888" }),
  localStorage: {
    getItem: (key) => (Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null),
    setItem: (key, value) => { store[key] = String(value); }
  },
  document
};
sandbox.window = sandbox;
vm.createContext(sandbox);
const realAppend = body.appendChild.bind(body);
body.appendChild = (node) => {
  const result = realAppend(node);
  if (node && node.tagName === "SCRIPT" && node.src) {
    const file = path.join(process.cwd(), "widget", node.src);
    vm.runInContext(fs.readFileSync(file, "utf8"), sandbox);
    if (typeof node.onload === "function") node.onload();
  }
  return result;
};
function run(name) {
  vm.runInContext(fs.readFileSync(path.join("widget", name), "utf8"), sandbox);
}
run("manifest.js");
sandbox.MSWP_MANIFEST.push({
  sport: "nfl",
  away: "Red Oak",
  home: "Harbor",
  label: "Red Oak at Harbor",
  file: "nfl_replay.js"
});
sandbox.MSWP_MANIFEST.push({
  sport: "nfl",
  away: "Harbor",
  home: "DEN",
  label: "Harbor at DEN",
  file: "away_harbor.js"
});
run("colors.js");
run("widget.js");

function buttonLabel(button) {
  if (button.textContent) return button.textContent;
  let text = "";
  (button.children || []).forEach((child) => {
    if (child.nodeType === 3) text += child.textContent;
  });
  return text;
}
function buttonsIn(id) {
  return document.getElementById(id).children.filter((child) => child.tagName === "BUTTON");
}
function sportButtons() { return buttonsIn("sports"); }
function gameButtons() { return buttonsIn("games"); }
function clickSport(sport) {
  const button = sportButtons().find((child) => child.getAttribute("data-sport") === sport);
  if (!button) throw new Error("missing sport " + sport);
  button.click();
}
function clickFile(file) {
  const button = gameButtons().find((child) => child.getAttribute("data-file") === file);
  if (!button) throw new Error("missing " + file);
  button.click();
}
function periodLabels(id) {
  const out = [];
  function walk(node) {
    if (!node || typeof node !== "object") return;
    if (node.getAttribute && node.getAttribute("data-series") === "period-label") out.push(node.textContent);
    (node.children || []).forEach(walk);
  }
  walk(document.getElementById(id));
  return out;
}
function paneWidths() {
  const rails = [];
  let right = null;
  function walk(node) {
    if (!node || typeof node !== "object") return;
    if (node.getAttribute) {
      const series = node.getAttribute("data-series");
      if (series === "period-rail") rails.push(Number(node.getAttribute("x1")));
      if (series === "wp-rail") right = Number(node.getAttribute("x2"));
    }
    (node.children || []).forEach(walk);
  }
  walk(document.getElementById("wp-chart"));
  rails.sort((a, b) => a - b);
  if (rails.length < 2 || right == null) return [];
  const share = rails[1] - rails[0];
  const edges = [rails[0] - share].concat(rails, [right]);
  const widths = [];
  for (let i = 1; i < edges.length; i++) widths.push(edges[i] - edges[i - 1]);
  return widths;
}
function readout() {
  return document.getElementById("position").textContent;
}
const play = document.getElementById("play");
const scrub = document.getElementById("scrub");
const score = document.getElementById("c-score");
const bootScore = score.textContent;
const bootClock = document.getElementById("c-clock").textContent;
const bootPosition = readout();
const bootAtEnd = scrub.value === scrub.max && scrub.max !== "0";
const bootSports = sportButtons().map(buttonLabel);
const bootSportPressed = sportButtons().filter((button) => button.getAttribute("aria-pressed") === "true").map(buttonLabel);
const bootGames = gameButtons().map(buttonLabel);
const bootFiles = gameButtons().map((button) => button.getAttribute("data-file"));
const bootGameRow = document.getElementById("game-row").hidden === true;
play.click();
const duringPlay = play.textContent;
const duringScore = score.textContent;
document.getElementById("level-college").click();
const filteredScore = score.textContent;
const collegeSports = sportButtons().map(buttonLabel);
const collegeGamesWhileNfl = gameButtons().map(buttonLabel);
clickSport("ncaaf");
const ncaafScore = score.textContent;
const ncaafPlay = play.textContent;
const ncaafGames = gameButtons().map(buttonLabel);
clickFile("ncaaf_replay.js");
const ouScoreLabels = periodLabels("score-chart");
const ouWpLabels = periodLabels("wp-chart");
const ouWidths = paneWidths();
const ouPosition = readout();
const ouPlay = play.textContent;
const ouClock = document.getElementById("c-clock").textContent;
const ouAtEnd = scrub.value === scrub.max;
clickFile("ncaaf_cu_gt.js");
const gtLabels = periodLabels("score-chart");
const gtWidths = paneWidths();
const gtPosition = readout();
clickSport("ncaah");
const michLabels = periodLabels("score-chart");
const michWp = periodLabels("wp-chart");
const michWidths = paneWidths();
const michPosition = readout();
document.getElementById("step-back").click();
const michStep = readout();
document.getElementById("step-forward").click();
const michGames = gameButtons().length;
const michRow = document.getElementById("game-row").hidden === true;
clickSport("ncaab");
const ncaabGames = gameButtons().length;
const ncaabRow = document.getElementById("game-row").hidden === true;
const ncaabScore = score.textContent;
document.getElementById("level-pro").click();
const proSports = sportButtons().map(buttonLabel);
const proScoreWhileNcaab = score.textContent;
clickSport("nba");
const nbaGames = gameButtons().length;
const nbaRow = document.getElementById("game-row").hidden === true;
const nbaScore = score.textContent;
clickSport("nfl");
const nygAgain = score.textContent;
const nygPosition = readout();
document.getElementById("step-back").click();
const nygStep = readout();
function bootWidget(preloadNames, extraEntries) {
  const localById = {};
  function localGet(id) {
    if (!localById[id]) localById[id] = element("div");
    localById[id].id = id;
    return localById[id];
  }
  const localDocEl = element("html");
  localDocEl.setAttribute("data-theme", "charcoal");
  const localBody = element("body");
  const localViewCompact = element("button");
  const localViewExpanded = element("button");
  localViewCompact.setAttribute("data-view-choice", "compact");
  localViewExpanded.setAttribute("data-view-choice", "expanded");
  const localStore = {};
  const localDocument = {
    documentElement: localDocEl,
    body: localBody,
    getElementById: localGet,
    createElement: (tag) => element(tag),
    createElementNS: (_ns, tag) => element(tag),
    createTextNode: (text) => ({ nodeType: 3, textContent: String(text), parentNode: null }),
    querySelectorAll: (selector) => (selector === "[data-view-choice]" ? [localViewCompact, localViewExpanded] : [])
  };
  const localSandbox = {
    console,
    setInterval: () => 1,
    clearInterval: () => {},
    getComputedStyle: () => ({ getPropertyValue: () => "#888888" }),
    localStorage: {
      getItem: (key) => (Object.prototype.hasOwnProperty.call(localStore, key) ? localStore[key] : null),
      setItem: (key, value) => { localStore[key] = String(value); }
    },
    document: localDocument
  };
  localSandbox.window = localSandbox;
  vm.createContext(localSandbox);
  const localAppend = localBody.appendChild.bind(localBody);
  localBody.appendChild = (node) => {
    const result = localAppend(node);
    if (node && node.tagName === "SCRIPT" && node.src) {
      vm.runInContext(fs.readFileSync(path.join(process.cwd(), "widget", node.src), "utf8"), localSandbox);
      if (typeof node.onload === "function") node.onload();
    }
    return result;
  };
  function localRun(name) {
    vm.runInContext(fs.readFileSync(path.join("widget", name), "utf8"), localSandbox);
  }
  preloadNames.forEach(localRun);
  localRun("manifest.js");
  (extraEntries || []).forEach((entry) => localSandbox.MSWP_MANIFEST.push(entry));
  localRun("colors.js");
  localRun("widget.js");
  return localDocument;
}
const harborDoc = bootWidget(["nfl_replay.js"], [{
  sport: "nfl",
  away: "Red Oak",
  home: "Harbor",
  label: "Red Oak at Harbor",
  file: "nfl_replay.js"
}]);
function harborLabels() {
  const out = [];
  function walk(node) {
    if (!node || typeof node !== "object") return;
    if (node.getAttribute && node.getAttribute("data-series") === "period-label") out.push(node.textContent);
    (node.children || []).forEach(walk);
  }
  walk(harborDoc.getElementById("score-chart"));
  return out;
}
function harborHidden(id) {
  const img = harborDoc.getElementById(id);
  return img.hidden === true && img.getAttribute("src") == null;
}
const harborGames = harborDoc.getElementById("games").children
  .filter((child) => child.tagName === "BUTTON")
  .map(buttonLabel);
console.log(JSON.stringify({
  badge: document.getElementById("badge").textContent,
  bootScore: bootScore,
  bootClock: bootClock,
  bootPosition: bootPosition,
  bootAtEnd: bootAtEnd,
  bootSports: bootSports,
  bootSportPressed: bootSportPressed,
  bootGames: bootGames,
  bootFiles: bootFiles,
  bootGameRow: bootGameRow,
  duringPlay: duringPlay,
  duringScore: duringScore,
  filteredScore: filteredScore,
  collegeSports: collegeSports,
  collegeGamesWhileNfl: collegeGamesWhileNfl,
  ncaafScore: ncaafScore,
  ncaafPlay: ncaafPlay,
  ncaafGames: ncaafGames,
  ouScoreLabels: ouScoreLabels,
  ouWpLabels: ouWpLabels,
  ouWidths: ouWidths,
  ouPosition: ouPosition,
  ouPlay: ouPlay,
  ouClock: ouClock,
  ouAtEnd: ouAtEnd,
  gtLabels: gtLabels,
  gtWidths: gtWidths,
  gtPosition: gtPosition,
  michLabels: michLabels,
  michWp: michWp,
  michWidths: michWidths,
  michPosition: michPosition,
  michStep: michStep,
  michGames: michGames,
  michRow: michRow,
  ncaabGames: ncaabGames,
  ncaabRow: ncaabRow,
  ncaabScore: ncaabScore,
  proSports: proSports,
  proScoreWhileNcaab: proScoreWhileNcaab,
  nbaGames: nbaGames,
  nbaRow: nbaRow,
  nbaScore: nbaScore,
  nygAgain: nygAgain,
  nygPosition: nygPosition,
  nygStep: nygStep,
  harborScore: harborDoc.getElementById("c-score").textContent,
  harborClock: harborDoc.getElementById("c-clock").textContent,
  harborPosition: harborDoc.getElementById("position").textContent,
  harborLabels: harborLabels(),
  harborGames: harborGames,
  logosHidden: ["c-home-logo", "c-away-logo", "e-home-logo", "e-away-logo"].every(harborHidden)
}));
"""
    probe_path = tmp_path / "manifest_load.js"
    probe_path.write_text(probe, encoding="utf-8", newline="\n")
    completed = subprocess.run(
        [node, str(probe_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)
    football = ["Q1", "Q2", "Q3", "Q4", "OT", "2OT"]
    hockey = ["P1", "P2", "P3", "OT", "2OT"]
    regulation = ["Q1", "Q2", "Q3", "Q4"]
    assert report["badge"] == "V3.3"
    assert "NYG" in report["bootScore"] and "DEN" in report["bootScore"]
    assert report["bootClock"] == "FINAL"
    assert report["bootPosition"] == "FINAL"
    assert "·" not in report["bootPosition"]
    assert report["bootAtEnd"] is True
    assert report["bootSports"] == ["NFL", "NHL", "NBA"]
    assert report["bootSportPressed"] == ["NFL"]
    assert report["collegeSports"] == ["NCAAF", "NCAAH", "NCAAB"]
    assert report["proSports"] == ["NFL", "NHL", "NBA"]
    assert len(report["bootGames"]) > 1
    for label in ("NYG at DEN", "JAX at DEN"):
        assert label in report["bootGames"]
    for label in report["bootGames"]:
        assert "Harbor" not in label
    assert "Red Oak at Harbor" not in report["bootGames"]
    assert "Harbor at DEN" not in report["bootGames"]
    assert "nfl_replay.js" not in report["bootFiles"]
    assert "away_harbor.js" not in report["bootFiles"]
    assert report["bootGameRow"] is False
    assert report["duringPlay"] == "Pause"
    assert report["duringScore"] != report["bootScore"]
    assert report["filteredScore"] == report["duringScore"]
    assert report["collegeGamesWhileNfl"] == []
    assert "COLO" in report["ncaafScore"] and "TTU" in report["ncaafScore"]
    assert report["ncaafPlay"] == "Play"
    assert len(report["ncaafGames"]) > 1
    for label in ("COLO at TTU", "COLO at GT", "OU at TEX"):
        assert label in report["ncaafGames"]
    assert report["ouScoreLabels"] == football
    assert report["ouWpLabels"] == football
    assert len(report["ouScoreLabels"]) == 6
    assert report["ouPosition"] == "FINAL"
    assert "".join(football) not in report["ouPosition"]
    ou_share = report["ouWidths"][0]
    assert ou_share > 0
    assert report["ouWidths"][4] == pytest.approx(ou_share * 6 / 7)
    assert report["ouWidths"][5] == pytest.approx(ou_share * 6 / 7)
    assert report["ouWidths"][4] < ou_share
    assert report["ouWidths"][5] < ou_share
    assert report["ouPlay"] == "Play"
    assert report["ouAtEnd"] is True
    assert report["ouClock"] == "FINAL"
    assert report["gtLabels"] == regulation
    assert "OT" not in report["gtLabels"]
    assert report["gtPosition"] == "FINAL"
    assert report["gtWidths"][-1] == pytest.approx(report["gtWidths"][0])
    assert len(report["gtWidths"]) == 4
    assert report["michLabels"] == hockey
    assert report["michWp"] == hockey
    assert len(report["michLabels"]) == 5
    assert report["michPosition"] == "FINAL"
    assert report["michStep"] == "2OT 7:25"
    assert "·" not in report["michStep"]
    assert "/" not in report["michStep"]
    assert "".join(hockey) not in report["michStep"]
    mich_share = report["michWidths"][0]
    assert report["michWidths"][4] == pytest.approx(mich_share * (1200 - 445) / 1200)
    assert report["michWidths"][4] < mich_share
    assert report["michWidths"][3] == pytest.approx(mich_share * (1200 - 26) / 1200)
    assert report["michGames"] == 0
    assert report["michRow"] is True
    assert report["ncaabGames"] == 0
    assert report["ncaabRow"] is True
    assert "FLA" in report["ncaabScore"]
    assert report["proScoreWhileNcaab"] == report["ncaabScore"]
    assert report["nbaGames"] == 0
    assert report["nbaRow"] is True
    assert "LAL" in report["nbaScore"]
    assert "NYG" in report["nygAgain"] and "DEN" in report["nygAgain"]
    assert report["nygPosition"] == "FINAL"
    assert report["nygStep"] == "Q4 0:00"
    assert "".join(regulation) not in report["nygStep"]
    assert report["harborScore"] == "Red Oak 23 – Harbor 27"
    assert report["harborClock"] == "FINAL"
    assert report["harborPosition"] == "FINAL"
    assert report["harborLabels"] == regulation
    assert "OT" not in report["harborLabels"]
    for label in report["harborGames"]:
        assert "Harbor" not in label
    assert "Red Oak at Harbor" not in report["harborGames"]
    assert report["logosHidden"] is True
