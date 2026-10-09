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
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (WIDGET / "widget.css").read_text(encoding="utf-8")
    script = (WIDGET / "widget.js").read_text(encoding="utf-8")
    page = html.lower()
    assert "espn" not in page
    assert "espn.com" not in page
    assert "http://" not in page and "https://" not in page
    assert script.count("fetch(") == 4
    assert 'fetch("/follow"' in script
    assert 'fetch("widget/follow.json"' in script
    assert 'method: "POST"' in script
    assert 'method: "GET"' in script
    assert "live_replay.js?" in script
    assert "slate.js?" in script
    assert 'src="slate.js"' not in html
    assert "slate.js" not in html
    assert "MSWP_LIVE" in script
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
    assert 'return "assets/logos/"' in script
    assert 'return "assets/colors/"' in script
    assert "frame.home_logo" in script and "frame.away_logo" in script
    assert "colors.js" not in script
    assert "widget/logos" not in script
    assert "logos/nfl/" not in script
    assert 'src="widget/manifest.js"' in html
    assert 'src="widget/colors.js"' in html
    assert 'src="live_replay.js"' not in html
    assert "live_replay.js" not in html
    assert html.index('src="widget/manifest.js"') < html.index('src="widget/colors.js"') < html.index('src="widget/widget.js"')
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
    assert html.index('id="sports"') < html.index('id="slate-row"')
    assert html.index('id="slate-row"') < html.index('id="slate"')
    assert html.index('id="slate"') < html.index('id="game-row"')
    assert html.index('id="game-row"') < html.index('id="games"')
    assert 'id="scrub-panes"' not in html
    assert 'id="position"' in html
    assert 'id="situation"' in html
    assert html.index('id="position"') < html.index('id="situation"') < html.index('id="appearance"')
    assert 'var clock = clockLabel(frame)' in script
    assert 'text("position", clock)' in script
    assert "paintSituation(frame)" in script
    assert 'getElementById("situation")' in script
    assert 'return clock + " STALE"' in script
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
    assert ">V3<" not in html and ">V3.3<" not in html and ">V3.5<" not in html and ">V0<" not in html
    assert 'id="badge"' in html
    assert "V3.3" not in script
    assert "V3.5" not in script
    assert script.count("V4") == 1
    assert 'var BADGE_TEXT = "V4"' in script
    assert "badge.textContent = BADGE_TEXT" in script
    assert 'src="widget/colors.js"' in html
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
    assert ".situation" in css and ".situation:empty" in css
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
        if path.name == "widget.js":
            assert text.count("fetch(") == 4, path.name
            assert 'fetch("/follow"' in text, path.name
            assert 'fetch("widget/follow.json"' in text, path.name
            assert "live_replay.js" in text, path.name
        else:
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
        encoding="utf-8",
        errors="strict",
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
        encoding="utf-8",
        errors="strict",
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
        encoding="utf-8",
        errors="strict",
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
        encoding="utf-8",
        errors="strict",
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
vm.runInContext(fs.readFileSync("widget/widget.js", "utf8"), sandbox);
sandbox.mswpColors.ingest("nfl", JSON.parse(fs.readFileSync("assets/colors/nfl.json", "utf8")));
sandbox.mswpColors.ingest("ncaaf", JSON.parse(fs.readFileSync("assets/colors/ncaaf.json", "utf8")));
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
  denHex: app.buildSwatches(den).map((swatch) => swatch.hex),
  nygHex: app.buildSwatches(nyg).map((swatch) => swatch.hex),
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
        encoding="utf-8",
        errors="strict",
    )
    report = json.loads(completed.stdout)
    assert report["coloNames"] == ["Gold #CFB87C", "Black #000000"]
    assert report["ttuNames"] == ["Red", "Black"]
    assert "Black" not in report["denNames"]
    assert report["nygHex"] == ["#0B2265", "#A71930", "#FFFFFF"]
    assert report["denHex"] == ["#FB4F14", "#002244", "#FFFFFF"]
    assert report["nflAway"] == "#A71930"
    assert report["nflHome"] == "#FB4F14"
    assert report["away"] == "#CFB87C"
    assert report["home"] == "#DA291C"
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
    const srcName = String(node.src);
    const rel = srcName.indexOf("widget/") === 0 ? srcName : path.join("widget", srcName);
    vm.runInContext(fs.readFileSync(path.join(process.cwd(), rel), "utf8"), sandbox);
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
      const srcName = String(node.src);
      const rel = srcName.indexOf("widget/") === 0 ? srcName : path.join("widget", srcName);
      vm.runInContext(fs.readFileSync(path.join(process.cwd(), rel), "utf8"), localSandbox);
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
  if (typeof img.onerror === "function" && img.getAttribute("src")) img.onerror();
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
        encoding="utf-8",
        errors="strict",
    )
    report = json.loads(completed.stdout)
    football = ["Q1", "Q2", "Q3", "Q4", "OT", "2OT"]
    hockey = ["P1", "P2", "P3", "OT", "2OT"]
    regulation = ["Q1", "Q2", "Q3", "Q4"]
    assert report["badge"] == "V4"
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


def test_localhost_live_button_hides_on_404_and_keeps_the_archive(tmp_path):
    node = shutil.which("node")
    assert node, "node is required to poll the live replay"
    from live_wp.replay import manifest_entries, write_manifest

    live = tmp_path / "live_replay.js"
    live.write_text(
        "window.NFL_REPLAY = ["
        '{"sport": "nfl", "away": "NYG", "home": "DEN", "period": 1}'
        "];\n"
        "window.MSWP_LIVE = window.NFL_REPLAY;\n",
        encoding="utf-8",
        newline="\n",
    )
    archive = tmp_path / "nfl_nyg_den.js"
    archive.write_text(
        'window.NFL_REPLAY = [{"away": "NYG", "home": "DEN", "period": 1}];\n',
        encoding="utf-8",
        newline="\n",
    )
    harbor = tmp_path / "nfl_replay.js"
    harbor.write_text(
        'window.NFL_REPLAY = [{"away": "Red Oak", "home": "Harbor", "period": 1}];\n',
        encoding="utf-8",
        newline="\n",
    )
    entries = manifest_entries(tmp_path)
    assert [entry["file"] for entry in entries] == ["nfl_nyg_den.js"]
    written = write_manifest(tmp_path)
    manifest_text = written.read_text(encoding="utf-8")
    assert "live_replay.js" not in manifest_text
    assert "Harbor" not in manifest_text
    assert "Red Oak" not in manifest_text
    page_manifest = (WIDGET / "manifest.js").read_text(encoding="utf-8")
    assert "live_replay.js" not in page_manifest

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

function frame(over) {
  return Object.assign({
    sport: "nfl",
    clock: "Q1 10:00",
    wp: 0.5,
    home: "DEN",
    away: "NYG",
    home_score: 0,
    away_score: 0,
    status: "live",
    period: 1,
    seconds_remaining_period: 600,
    prior_home: 0.5
  }, over || {});
}

const frameA = frame({});
const frameB = frame({
  clock: "Q2 5:00",
  period: 2,
  seconds_remaining_period: 300,
  home_score: 7,
  away_score: 3,
  wp: 0.42
});
const frameC = frame({
  clock: "Q3 8:00",
  period: 3,
  seconds_remaining_period: 480,
  home_score: 14,
  away_score: 10,
  wp: 0.61
});
const frameD = frame({
  clock: "Q4 1:00",
  period: 4,
  seconds_remaining_period: 60,
  home_score: 21,
  away_score: 13,
  wp: 0.8,
  status: "stale"
});

function liveSource(rows) {
  return "window.NFL_REPLAY = " + JSON.stringify(rows) + ";\nwindow.MSWP_LIVE = window.NFL_REPLAY;\n";
}

function bindingOnly() {
  return "window.NFL_REPLAY = " + JSON.stringify([
    frame({ away_score: 99, home_score: 1, clock: "Q1 1:00" })
  ]) + ";\n";
}

function http(status, body) {
  return { status: status, ok: status >= 200 && status < 300, body: body == null ? "" : String(body) };
}

function settle() {
  return new Promise((resolve) => setImmediate(resolve));
}

async function boot(hostname, protocol, first) {
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
  const fetches = [];
  const intervals = [];
  const feed = { items: [first] };
  const sandbox = {
    console,
    setInterval: (fn, ms) => {
      intervals.push({ fn, ms });
      return intervals.length;
    },
    clearInterval: () => {},
    getComputedStyle: () => ({ getPropertyValue: () => "#888888" }),
    localStorage: {
      getItem: (key) => (Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null),
      setItem: (key, value) => { store[key] = String(value); }
    },
    location: { hostname: hostname, protocol: protocol },
    fetch: (url, options) => {
      const address = String(url);
      fetches.push({
        url: address,
        cache: options && options.cache ? options.cache : ""
      });
      if (address.indexOf("assets/colors/") === 0) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve([]),
          text: () => Promise.resolve("[]")
        });
      }
      if (address.indexOf("follow.json") >= 0) {
        return Promise.resolve({
          ok: false,
          status: 404,
          text: () => Promise.resolve("")
        });
      }
      const item = feed.items.shift() || http(404, "");
      return Promise.resolve({
        ok: item.ok,
        status: item.status,
        text: () => Promise.resolve(item.body)
      });
    },
    document
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  const realAppend = body.appendChild.bind(body);
  body.appendChild = (node) => {
    const result = realAppend(node);
    if (node && node.tagName === "SCRIPT" && node.src) {
      const srcName = String(node.src);
      const rel = srcName.indexOf("widget/") === 0 ? srcName : path.join("widget", srcName);
      vm.runInContext(fs.readFileSync(path.join(process.cwd(), rel), "utf8"), sandbox);
      if (typeof node.onload === "function") node.onload();
    }
    return result;
  };
  function run(name) {
    vm.runInContext(fs.readFileSync(path.join("widget", name), "utf8"), sandbox);
  }
  run("manifest.js");
  run("colors.js");
  run("widget.js");
  const archive = sandbox.NFL_REPLAY;
  for (let i = 0; i < 8; i++) await settle();
  return { document, sandbox, fetches, intervals, feed, archive };
}

function snapshot(page) {
  const games = page.document.getElementById("games").children.filter((child) => child.tagName === "BUTTON");
  const live = games.filter((button) => button.getAttribute("data-live") === "true");
  const last = page.sandbox.NFL_REPLAY[page.sandbox.NFL_REPLAY.length - 1];
  return {
    score: page.document.getElementById("c-score").textContent,
    clock: page.document.getElementById("c-clock").textContent,
    eClock: page.document.getElementById("e-clock").textContent,
    position: page.document.getElementById("position").textContent,
    play: page.document.getElementById("play").textContent,
    liveCount: live.length,
    liveLabel: live.length ? live[0].textContent : "",
    liveFile: live.length ? live[0].getAttribute("data-file") : null,
    archiveSame: page.sandbox.NFL_REPLAY === page.archive,
    archiveAway: last.away_score,
    archiveHome: last.home_score,
    liveGlobal: Object.prototype.hasOwnProperty.call(page.sandbox, "MSWP_LIVE"),
    scrub: page.document.getElementById("scrub").value,
    scrubMax: page.document.getElementById("scrub").max
  };
}

function scrubTo(page, value) {
  const scrub = page.document.getElementById("scrub");
  scrub.value = String(value);
  (scrub.listeners.input || []).slice().forEach((fn) => fn());
}

function playTick(page) {
  const timers = page.intervals.filter((item) => item.ms === 1000);
  if (!timers.length) throw new Error("play timer missing");
  timers[timers.length - 1].fn();
}

async function pollNext(page, item) {
  page.feed.items.push(item);
  const poll = page.intervals.find((entry) => entry.ms === 15000);
  if (!poll) throw new Error("live poll missing");
  poll.fn();
  for (let i = 0; i < 8; i++) await settle();
}

(async () => {
  const page = await boot("127.0.0.1", "http:", http(404, ""));
  const after404 = snapshot(page);
  await pollNext(page, http(200, ""));
  const afterEmpty = snapshot(page);
  await pollNext(page, http(200, bindingOnly()));
  const afterBindingOnly = snapshot(page);
  await pollNext(page, http(200, liveSource([frameA, frameB])));
  const afterGood = snapshot(page);
  const manifestFiles = page.sandbox.MSWP_MANIFEST.map((entry) => entry.file);
  await pollNext(page, http(200, "   \n"));
  const afterEmptyAgain = snapshot(page);
  await pollNext(page, http(200, liveSource([frameA, frameB])));
  const afterGoodAgain = snapshot(page);
  page.document.getElementById("play").click();
  const duringArchivePlay = snapshot(page);
  const liveButton = page.document.getElementById("games").children.find((child) => child.getAttribute && child.getAttribute("data-live") === "true");
  if (!liveButton) throw new Error("missing live button");
  liveButton.click();
  const afterSelect = snapshot(page);
  page.document.getElementById("step-back").click();
  const afterStepBack = snapshot(page);
  page.document.getElementById("play").click();
  playTick(page);
  const afterPlayTick = snapshot(page);
  scrubTo(page, 0);
  const afterScrub = snapshot(page);
  await pollNext(page, http(200, liveSource([frameA, frameB, frameC])));
  const afterAppendHeld = snapshot(page);
  scrubTo(page, 2);
  const afterSeekEnd = snapshot(page);
  await pollNext(page, http(200, liveSource([frameA, frameB, frameC, frameD])));
  const afterAppendAdvance = snapshot(page);
  const archiveButton = page.document.getElementById("games").children.find((child) => child.getAttribute && child.getAttribute("data-file") === "nfl_nyg_den.js");
  if (!archiveButton) throw new Error("missing archive button");
  archiveButton.click();
  const afterArchive = snapshot(page);
  const liveAgain = page.document.getElementById("games").children.find((child) => child.getAttribute && child.getAttribute("data-live") === "true");
  liveAgain.click();
  const afterLiveAgain = snapshot(page);
  await pollNext(page, http(404, ""));
  const afterMissing = snapshot(page);
  scrubTo(page, 0);
  const afterMissingScrub = snapshot(page);
  page.document.getElementById("play").click();
  playTick(page);
  const afterMissingPlay = snapshot(page);
  const filePage = await boot("localhost", "file:", http(200, liveSource([frameA, frameB])));
  const otherPage = await boot("example.github.io", "https:", http(200, liveSource([frameA, frameB])));
  const localPage = await boot("localhost", "http:", http(200, liveSource([frameA, frameB])));
  console.log(JSON.stringify({
    pollMs: page.intervals.filter((entry) => entry.ms === 15000).map((entry) => entry.ms),
    fetches: page.fetches,
    manifestFiles: manifestFiles,
    after404: after404,
    afterEmpty: afterEmpty,
    afterBindingOnly: afterBindingOnly,
    afterGood: afterGood,
    afterEmptyAgain: afterEmptyAgain,
    afterGoodAgain: afterGoodAgain,
    duringArchivePlay: duringArchivePlay,
    afterSelect: afterSelect,
    afterStepBack: afterStepBack,
    afterPlayTick: afterPlayTick,
    afterScrub: afterScrub,
    afterAppendHeld: afterAppendHeld,
    afterSeekEnd: afterSeekEnd,
    afterAppendAdvance: afterAppendAdvance,
    afterArchive: afterArchive,
    afterLiveAgain: afterLiveAgain,
    afterMissing: afterMissing,
    afterMissingScrub: afterMissingScrub,
    afterMissingPlay: afterMissingPlay,
    fileFetches: filePage.fetches.map((item) => item.url),
    fileLive: snapshot(filePage).liveCount,
    fileScore: snapshot(filePage).score,
    otherFetches: otherPage.fetches.map((item) => item.url),
    otherLive: snapshot(otherPage).liveCount,
    localLive: snapshot(localPage).liveCount,
    localLabel: snapshot(localPage).liveLabel,
    localArchiveSame: snapshot(localPage).archiveSame,
    localFetches: localPage.fetches.map((item) => item.url)
  }));
})().catch((err) => {
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
});
"""
    probe_path = tmp_path / "live_poll.js"
    probe_path.write_text(probe, encoding="utf-8", newline="\n")
    completed = subprocess.run(
        [node, str(probe_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="strict",
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    dash = "\u2013"
    archive_score = f"NYG 32 {dash} DEN 33"
    live_a = f"NYG 0 {dash} DEN 0"
    live_b = f"NYG 3 {dash} DEN 7"
    live_c = f"NYG 10 {dash} DEN 14"
    live_d = f"NYG 13 {dash} DEN 21"
    assert report["pollMs"] == [15000]
    assert report["fetches"]
    saw_live = False
    saw_slate = False
    for item in report["fetches"]:
        assert (
            item["url"].startswith("widget/live_replay.js?t=")
            or item["url"].startswith("widget/slate.js?t=")
            or item["url"] == "widget/follow.json"
            or item["url"].startswith("assets/colors/")
        )
        assert "espn" not in item["url"]
        assert "http://" not in item["url"] and "https://" not in item["url"]
        assert item["cache"] == "no-store"
        if item["url"].startswith("widget/live_replay.js?t="):
            saw_live = True
        if item["url"].startswith("widget/slate.js?t="):
            saw_slate = True
    assert saw_live and saw_slate
    assert "live_replay.js" not in report["manifestFiles"]
    assert report["after404"]["liveCount"] == 0
    assert report["after404"]["score"] == archive_score
    assert report["after404"]["clock"] == "FINAL"
    assert "STALE" not in report["after404"]["clock"]
    assert report["after404"]["archiveSame"] is True
    assert report["afterEmpty"]["liveCount"] == 0
    assert report["afterEmpty"]["score"] == archive_score
    assert report["afterBindingOnly"]["liveCount"] == 0
    assert report["afterBindingOnly"]["archiveSame"] is True
    assert report["afterBindingOnly"]["archiveAway"] == 32
    assert report["afterBindingOnly"]["archiveHome"] == 33
    assert report["afterBindingOnly"]["liveGlobal"] is False
    assert report["afterBindingOnly"]["score"] == archive_score
    assert report["afterGood"]["liveCount"] == 1
    assert report["afterGood"]["liveLabel"] == "NYG at DEN"
    assert report["afterGood"]["liveFile"] is None
    assert report["afterGood"]["score"] == archive_score
    assert report["afterGood"]["clock"] == "FINAL"
    assert report["afterGood"]["archiveSame"] is True
    assert report["afterGood"]["liveGlobal"] is False
    assert report["afterGood"]["archiveAway"] == 32
    assert report["afterEmptyAgain"]["liveCount"] == 0
    assert report["afterEmptyAgain"]["clock"] == "FINAL"
    assert report["afterEmptyAgain"]["score"] == archive_score
    assert report["afterGoodAgain"]["liveCount"] == 1
    assert report["afterGoodAgain"]["liveLabel"] == "NYG at DEN"
    assert report["duringArchivePlay"]["play"] == "Pause"
    assert report["afterSelect"]["play"] == "Play"
    assert report["afterSelect"]["score"] == live_b
    assert report["afterSelect"]["clock"] == "Q2 5:00"
    assert report["afterSelect"]["archiveSame"] is True
    assert report["afterStepBack"]["score"] == live_a
    assert report["afterStepBack"]["clock"] == "Q1 10:00"
    assert report["afterPlayTick"]["score"] == live_b
    assert report["afterPlayTick"]["play"] == "Play"
    assert report["afterScrub"]["score"] == live_a
    assert report["afterScrub"]["clock"] == "Q1 10:00"
    assert report["afterAppendHeld"]["score"] == live_a
    assert report["afterAppendHeld"]["clock"] == "Q1 10:00"
    assert report["afterAppendHeld"]["scrubMax"] == "2"
    assert report["afterSeekEnd"]["score"] == live_c
    assert report["afterSeekEnd"]["clock"] == "Q3 8:00"
    assert report["afterAppendAdvance"]["score"] == live_d
    assert report["afterAppendAdvance"]["clock"] == "Q4 1:00 STALE"
    assert report["afterAppendAdvance"]["eClock"] == "Q4 1:00 STALE"
    assert report["afterAppendAdvance"]["position"] == "Q4 1:00 STALE"
    assert report["afterArchive"]["score"] == archive_score
    assert report["afterArchive"]["clock"] == "FINAL"
    assert "STALE" not in report["afterArchive"]["clock"]
    assert report["afterArchive"]["liveCount"] == 1
    assert report["afterArchive"]["archiveSame"] is True
    assert report["afterLiveAgain"]["score"] == live_d
    assert report["afterLiveAgain"]["clock"] == "Q4 1:00 STALE"
    assert report["afterMissing"]["liveCount"] == 0
    assert report["afterMissing"]["score"] == live_d
    assert report["afterMissing"]["clock"] == "Q4 1:00 STALE"
    assert report["afterMissing"]["archiveSame"] is True
    assert report["afterMissingScrub"]["score"] == live_a
    assert report["afterMissingScrub"]["clock"] == "Q1 10:00 STALE"
    assert report["afterMissingScrub"]["liveCount"] == 0
    assert report["afterMissingPlay"]["score"] == live_b
    assert report["afterMissingPlay"]["clock"] == "Q2 5:00 STALE"
    assert report["fileFetches"] == ["assets/colors/nfl.json"]
    assert report["fileLive"] == 0
    assert report["fileScore"] == archive_score
    assert report["otherFetches"] == ["assets/colors/nfl.json"]
    assert report["otherLive"] == 0
    assert report["localLive"] == 1
    assert report["localLabel"] == "NYG at DEN"
    assert report["localArchiveSame"] is True
    assert report["localFetches"]
    assert "widget/follow.json" in report["localFetches"]
    assert any(url.startswith("widget/live_replay.js?t=") for url in report["localFetches"])


def test_situation_line_is_the_current_frame_only(tmp_path):
    node = shutil.which("node")
    assert node, "node is required to check the situation line"
    probe = r"""
const fs = require("fs");
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

const BINDING = {
  nfl: "NFL_REPLAY",
  ncaaf: "NCAAF_REPLAY",
  nhl: "NHL_REPLAY",
  ncaah: "NCAAH_REPLAY",
  nba: "NBA_REPLAY",
  ncaab: "NCAAB_REPLAY"
};

function boot(sport, rows) {
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
  sandbox.MSWP_MANIFEST = [{
    sport: sport,
    away: rows[0].away,
    home: rows[0].home,
    label: rows[0].away + " at " + rows[0].home,
    file: "fixture.js"
  }];
  sandbox[BINDING[sport]] = rows;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync("widget/colors.js", "utf8"), sandbox);
  vm.runInContext(fs.readFileSync("widget/widget.js", "utf8"), sandbox);
  return document;
}

function snap(sport, extra) {
  const row = {
    clock: "Q1 10:00",
    wp: 0.62,
    home: "DEN",
    away: "NYG",
    home_score: 10,
    away_score: 7,
    status: "live",
    period: 2,
    seconds_remaining_period: 494,
    seconds_remaining_total: 2294,
    prior_home: 0.8,
    game_id: "fixture",
    elapsed_seconds: 1306
  };
  Object.keys(extra || {}).forEach((key) => { row[key] = extra[key]; });
  if (sport === "nhl" || sport === "ncaah") {
    row.clock = row.clock.indexOf("FINAL") === 0 ? row.clock : "P1 10:00";
    row.home = extra && extra.home ? extra.home : "COL";
    row.away = extra && extra.away ? extra.away : "MIN";
    row.period = extra && extra.period ? extra.period : 1;
  }
  if (sport === "nba" || sport === "ncaab") {
    row.home = extra && extra.home ? extra.home : "LAL";
    row.away = extra && extra.away ? extra.away : "DEN";
  }
  return row;
}

function read(doc) {
  const node = doc.getElementById("situation");
  return {
    text: node.textContent,
    hidden: node.hidden === true,
    position: doc.getElementById("position").textContent
  };
}

function step(doc, id) {
  doc.getElementById(id).click();
}

const footballDoc = boot("nfl", [
  snap("nfl", {
    status: "pre",
    clock: "Q1 15:00",
    period: 1,
    possession: "away",
    down: 2,
    distance: 7,
    yardline: 35,
    timeouts: { NYG: 2, DEN: 3 }
  }),
  snap("nfl", {
    clock: "Q2 8:14",
    possession: "away",
    down: 2,
    distance: 7,
    yardline: 35,
    timeouts: { NYG: 2, DEN: 3 }
  }),
  snap("nfl", { clock: "Q2 7:40" }),
  snap("nfl", {
    status: "final",
    clock: "FINAL",
    possession: "away",
    down: 2,
    distance: 7,
    yardline: 35,
    timeouts: { NYG: 2, DEN: 3 }
  })
]);
const finalRead = read(footballDoc);
step(footballDoc, "step-back");
const bareRead = read(footballDoc);
step(footballDoc, "step-back");
const richRead = read(footballDoc);
step(footballDoc, "step-forward");
const afterRich = read(footballDoc);
step(footballDoc, "step-back");
step(footballDoc, "step-back");
const preRead = read(footballDoc);

const hockeyDoc = boot("nhl", [
  snap("nhl", { strength: "5v4", extra_attacker: true }),
  snap("nhl", {}),
  snap("nhl", { strength: "5v5" }),
  snap("nhl", { extra_attacker: true })
]);
const hockeyBoth = read(hockeyDoc);
step(hockeyDoc, "step-forward");
const hockeyNone = read(hockeyDoc);
step(hockeyDoc, "step-forward");
const hockeyStrength = read(hockeyDoc);
step(hockeyDoc, "step-forward");
const hockeyExtra = read(hockeyDoc);

const nbaDoc = boot("nba", [
  snap("nba", {}),
  snap("nba", { possession: "away", down: 2, distance: 7, yardline: 35 }),
  snap("nba", { status: "final", clock: "FINAL", possession: "away", down: 2, distance: 7, yardline: 35 }),
  snap("nba", { strength: "5v5" }),
  snap("nba", { extra_attacker: true }),
  snap("nba", { possession: "home" })
]);
const nbaEmpty = read(nbaDoc);
step(nbaDoc, "step-forward");
const nbaFootball = read(nbaDoc);
step(nbaDoc, "step-forward");
const nbaFinal = read(nbaDoc);
step(nbaDoc, "step-forward");
const nbaStrength = read(nbaDoc);
step(nbaDoc, "step-forward");
const nbaExtra = read(nbaDoc);
step(nbaDoc, "step-forward");
const nbaPartial = read(nbaDoc);

const ncaafDoc = boot("ncaaf", [
  snap("ncaaf", {
    possession: "away",
    down: 1,
    distance: 10,
    yardline: 25,
    timeouts: { NYG: 3, DEN: 3 }
  })
]);
const ncaahDoc = boot("ncaah", [
  snap("ncaah", { strength: "5v4", extra_attacker: false })
]);

console.log(JSON.stringify({
  final: finalRead,
  bare: bareRead,
  rich: richRead,
  afterRich: afterRich,
  pre: preRead,
  hockeyBoth: hockeyBoth,
  hockeyNone: hockeyNone,
  hockeyStrength: hockeyStrength,
  hockeyExtra: hockeyExtra,
  nbaEmpty: nbaEmpty,
  nbaFootball: nbaFootball,
  nbaFinal: nbaFinal,
  nbaStrength: nbaStrength,
  nbaExtra: nbaExtra,
  nbaPartial: nbaPartial,
  ncaaf: read(ncaafDoc),
  ncaah: read(ncaahDoc)
}));
"""
    probe_path = tmp_path / "situation_line.js"
    probe_path.write_text(probe, encoding="utf-8", newline="\n")
    completed = subprocess.run(
        [node, str(probe_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="strict",
    )
    report = json.loads(completed.stdout)
    football = "NYG ball, 2nd and 7, yardline 35 \u00b7 NYG 2, DEN 3"
    assert report["final"] == {"text": "", "hidden": True, "position": "FINAL"}
    assert report["bare"] == {"text": "", "hidden": True, "position": "Q2 7:40"}
    assert report["rich"] == {"text": football, "hidden": False, "position": "Q2 8:14"}
    assert report["afterRich"] == {"text": "", "hidden": True, "position": "Q2 7:40"}
    assert report["pre"] == {"text": "", "hidden": True, "position": "Q1 15:00"}
    assert report["hockeyBoth"]["text"] == "5v4 \u00b7 extra attacker"
    assert report["hockeyBoth"]["hidden"] is False
    assert report["hockeyNone"] == {"text": "", "hidden": True, "position": "P1 10:00"}
    assert report["hockeyStrength"]["text"] == "5v5"
    assert report["hockeyStrength"]["hidden"] is False
    assert report["hockeyExtra"]["text"] == "extra attacker"
    assert report["hockeyExtra"]["hidden"] is False
    assert report["nbaEmpty"]["text"] == ""
    assert report["nbaEmpty"]["hidden"] is True
    assert report["nbaFootball"]["text"] == "DEN ball, 2nd and 7, yardline 35"
    assert report["nbaFootball"]["hidden"] is False
    assert report["nbaFinal"]["text"] == ""
    assert report["nbaFinal"]["hidden"] is True
    assert report["nbaFinal"]["position"] == "FINAL"
    assert report["nbaStrength"]["text"] == "5v5"
    assert report["nbaExtra"]["text"] == "extra attacker"
    assert report["nbaPartial"]["text"] == ""
    assert report["nbaPartial"]["hidden"] is True
    assert report["ncaaf"]["text"] == "NYG ball, 1st and 10, yardline 25 \u00b7 NYG 3, DEN 3"
    assert report["ncaaf"]["hidden"] is False
    assert report["ncaah"]["text"] == "5v4"
    assert report["ncaah"]["hidden"] is False


def test_query_opens_nyg_den_falls_back_and_selects_live(tmp_path):
    node = shutil.which("node")
    assert node, "node is required to read the page query"
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

function liveFrame(over) {
  return Object.assign({
    sport: "nfl",
    clock: "Q1 10:00",
    wp: 0.5,
    home: "DEN",
    away: "NYG",
    home_score: 0,
    away_score: 0,
    status: "live",
    period: 1,
    seconds_remaining_period: 600,
    prior_home: 0.5
  }, over || {});
}

const liveRows = [
  liveFrame({}),
  liveFrame({
    clock: "Q2 5:00",
    period: 2,
    seconds_remaining_period: 300,
    home_score: 7,
    away_score: 3,
    wp: 0.42
  })
];

function liveSource(rows) {
  return "window.NFL_REPLAY = " + JSON.stringify(rows) + ";\nwindow.MSWP_LIVE = window.NFL_REPLAY;\n";
}

function http(status, body) {
  return { ok: status >= 200 && status < 300, status: status, body: body == null ? "" : String(body) };
}

function settle() {
  return new Promise((resolve) => setImmediate(resolve));
}

async function flush() {
  for (let i = 0; i < 8; i++) await settle();
}

function boot(options) {
  options = options || {};
  const calls = [];
  const fetches = [];
  const feed = { items: (options.feed || []).slice() };
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
  const location = {
    hostname: options.hostname || "127.0.0.1",
    protocol: options.protocol || "http:",
    search: options.search || ""
  };
  if (options.pathname) location.pathname = options.pathname;
  const sandbox = {
    console,
    setInterval: () => 1,
    clearInterval: () => {},
    getComputedStyle: () => ({ getPropertyValue: () => "#888888" }),
    localStorage: {
      getItem: (key) => (Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null),
      setItem: (key, value) => { store[key] = String(value); }
    },
    location: location,
    history: {
      replaceState: (_state, _title, url) => { calls.push(String(url)); }
    },
    fetch: (url) => {
      const address = String(url);
      fetches.push(address);
      if (address.indexOf("assets/colors/") === 0) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve([]),
          text: () => Promise.resolve("[]")
        });
      }
      if (options.hold) return new Promise(() => {});
      const item = feed.items.shift() || http(404, "");
      return Promise.resolve({
        ok: item.ok,
        status: item.status,
        text: () => Promise.resolve(item.body)
      });
    },
    document
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  const realAppend = body.appendChild.bind(body);
  body.appendChild = (node) => {
    const result = realAppend(node);
    if (node && node.tagName === "SCRIPT" && node.src) {
      const srcName = String(node.src);
      const rel = srcName.indexOf("widget/") === 0 ? srcName : path.join("widget", srcName);
      vm.runInContext(fs.readFileSync(path.join(process.cwd(), rel), "utf8"), sandbox);
      if (typeof node.onload === "function") node.onload();
    }
    return result;
  };
  function run(name) {
    vm.runInContext(fs.readFileSync(path.join("widget", name), "utf8"), sandbox);
  }
  run("manifest.js");
  run("colors.js");
  if (options.live) {
    vm.runInContext("window.MSWP_LIVE = " + JSON.stringify(options.live) + ";", sandbox);
  }
  run("widget.js");
  return { document, calls, fetches };
}

function buttons(doc, id) {
  return doc.getElementById(id).children.filter((child) => child.tagName === "BUTTON");
}

function clickSport(page, sport) {
  const button = buttons(page.document, "sports").find((child) => child.getAttribute("data-sport") === sport);
  if (!button) throw new Error("missing sport " + sport);
  button.click();
}

function clickFile(page, file) {
  const button = buttons(page.document, "games").find((child) => child.getAttribute("data-file") === file);
  if (!button) throw new Error("missing " + file);
  button.click();
}

function clickLive(page) {
  const button = buttons(page.document, "games").find((child) => child.getAttribute("data-live") === "true");
  if (!button) throw new Error("missing live");
  button.click();
}

function snap(page) {
  const doc = page.document;
  const scrub = doc.getElementById("scrub");
  const sports = buttons(doc, "sports");
  const games = buttons(doc, "games");
  const live = games.filter((button) => button.getAttribute("data-live") === "true");
  return {
    score: doc.getElementById("c-score").textContent,
    clock: doc.getElementById("c-clock").textContent,
    play: doc.getElementById("play").textContent,
    atEnd: scrub.value === scrub.max && Number(scrub.max) > 0,
    levelPro: doc.getElementById("level-pro").getAttribute("aria-pressed"),
    levelCollege: doc.getElementById("level-college").getAttribute("aria-pressed"),
    sport: sports.filter((button) => button.getAttribute("aria-pressed") === "true").map((button) => button.getAttribute("data-sport")),
    pressed: games.filter((button) => button.getAttribute("aria-pressed") === "true").map((button) => (
      button.getAttribute("data-live") === "true" ? "live" : button.getAttribute("data-file")
    )),
    liveCount: live.length,
    liveLabel: live.length ? live[0].textContent : "",
    gameRowHidden: doc.getElementById("game-row").hidden === true,
    calls: page.calls.slice(),
    fetches: page.fetches.slice()
  };
}

const nyg = boot({
  search: "?sport=NFL&game=NYG-DEN",
  pathname: "index.html",
  hold: true
});
const nygSnap = snap(nyg);
nyg.document.getElementById("level-college").click();
nyg.document.getElementById("level-pro").click();
const afterLevel = snap(nyg);
clickFile(nyg, "nfl_jax_den.js");
const afterJax = snap(nyg);
clickSport(nyg, "nba");
const afterNba = snap(nyg);

const jax = boot({ search: "?sport=nfl&game=jax-den", hold: true });
const mich = boot({ search: "?sport=ncaah&game=MiCh-DeN", hold: true });
const unknownGame = boot({ search: "?sport=ncaah&game=no-such", hold: true });
const unknownSport = boot({ search: "?sport=zzz&game=mich-den", hold: true });
const lal = boot({ search: "?sport=nba&game=den-lal", hold: true });
const waiting = boot({ search: "?sport=nfl&game=jax-den&live=1", hold: true });
const preset = boot({ search: "?live=1", live: liveRows, hold: true });
const otherHost = boot({
  hostname: "example.github.io",
  protocol: "https:",
  search: "?sport=nfl&game=nyg-den&live=1",
  live: liveRows,
  hold: true
});
const fileHost = boot({
  hostname: "localhost",
  protocol: "file:",
  search: "?sport=nfl&game=jax-den&live=1",
  live: liveRows,
  hold: true
});
const arrived = boot({
  search: "?sport=nfl&game=jax-den&live=1",
  feed: [http(200, liveSource(liveRows))]
});
const arrivedBefore = snap(arrived);
const missing = boot({
  search: "?sport=ncaah&game=mich-den&live=1",
  feed: [http(404, "")]
});
const missingBefore = snap(missing);

(async () => {
  await flush();
  const arrivedAfter = snap(arrived);
  const missingAfter = snap(missing);
  clickLive(arrived);
  const afterLiveClick = snap(arrived);
  clickFile(arrived, "nfl_jax_den.js");
  const afterArchiveClick = snap(arrived);
  console.log(JSON.stringify({
    nyg: nygSnap,
    afterLevel: afterLevel,
    afterJax: afterJax,
    afterNba: afterNba,
    jax: snap(jax),
    mich: snap(mich),
    unknownGame: snap(unknownGame),
    unknownSport: snap(unknownSport),
    lal: snap(lal),
    waiting: snap(waiting),
    preset: snap(preset),
    otherHost: snap(otherHost),
    fileHost: snap(fileHost),
    arrivedBefore: arrivedBefore,
    arrivedAfter: arrivedAfter,
    missingBefore: missingBefore,
    missingAfter: missingAfter,
    afterLiveClick: afterLiveClick,
    afterArchiveClick: afterArchiveClick
  }));
})().catch((err) => {
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
});
"""
    probe_path = tmp_path / "deep_link.js"
    probe_path.write_text(probe, encoding="utf-8", newline="\n")
    completed = subprocess.run(
        [node, str(probe_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="strict",
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    dash = "\u2013"
    nyg = f"NYG 32 {dash} DEN 33"
    jax = f"JAX 13 {dash} DEN 20"
    mich = f"MICH 3 {dash} DEN 4"
    live = f"NYG 3 {dash} DEN 7"

    def assert_open(row, score, sport, level):
        assert row["score"] == score
        assert row["clock"] == "FINAL"
        assert row["play"] == "Play"
        assert row["atEnd"] is True
        assert row["sport"] == [sport]
        if level == "pro":
            assert row["levelPro"] == "true"
            assert row["levelCollege"] == "false"
        else:
            assert row["levelPro"] == "false"
            assert row["levelCollege"] == "true"

    assert_open(report["nyg"], nyg, "nfl", "pro")
    assert report["nyg"]["pressed"] == ["nfl_nyg_den.js"]
    assert report["nyg"]["liveCount"] == 0
    assert report["nyg"]["calls"] == []
    assert report["nyg"]["gameRowHidden"] is False
    assert report["afterLevel"]["score"] == nyg
    assert report["afterLevel"]["calls"] == []
    assert report["afterJax"]["calls"] == ["index.html?sport=nfl&game=jax-den"]
    assert_open(report["afterJax"], jax, "nfl", "pro")
    assert report["afterJax"]["pressed"] == ["nfl_jax_den.js"]
    assert report["afterNba"]["calls"] == [
        "index.html?sport=nfl&game=jax-den",
        "index.html?sport=nba&game=den-lal",
    ]
    assert_open(report["afterNba"], report["afterNba"]["score"], "nba", "pro")
    assert "DEN" in report["afterNba"]["score"] and "LAL" in report["afterNba"]["score"]
    assert report["afterNba"]["gameRowHidden"] is True
    assert_open(report["jax"], jax, "nfl", "pro")
    assert report["jax"]["pressed"] == ["nfl_jax_den.js"]
    assert report["jax"]["calls"] == []
    assert_open(report["mich"], mich, "ncaah", "college")
    assert report["mich"]["gameRowHidden"] is True
    assert report["mich"]["liveCount"] == 0
    assert_open(report["lal"], report["lal"]["score"], "nba", "pro")
    assert "LAL" in report["lal"]["score"] and "DEN" in report["lal"]["score"]
    assert_open(report["unknownGame"], nyg, "nfl", "pro")
    assert "MICH" not in report["unknownGame"]["score"]
    assert report["unknownGame"]["pressed"] == ["nfl_nyg_den.js"]
    assert_open(report["unknownSport"], nyg, "nfl", "pro")
    assert "MICH" not in report["unknownSport"]["score"]
    assert report["unknownSport"]["pressed"] == ["nfl_nyg_den.js"]
    assert_open(report["waiting"], jax, "nfl", "pro")
    assert report["waiting"]["liveCount"] == 0
    assert report["waiting"]["pressed"] == ["nfl_jax_den.js"]
    assert report["preset"]["score"] == live
    assert report["preset"]["clock"] == "Q2 5:00"
    assert report["preset"]["play"] == "Play"
    assert report["preset"]["atEnd"] is True
    assert report["preset"]["sport"] == ["nfl"]
    assert report["preset"]["pressed"] == ["live"]
    assert report["preset"]["liveCount"] == 1
    assert report["preset"]["liveLabel"] == "NYG at DEN"
    assert report["preset"]["calls"] == []
    assert_open(report["otherHost"], nyg, "nfl", "pro")
    assert report["otherHost"]["liveCount"] == 0
    assert report["otherHost"]["fetches"] == ["assets/colors/nfl.json"]
    assert report["otherHost"]["score"] != live
    assert_open(report["fileHost"], jax, "nfl", "pro")
    assert report["fileHost"]["liveCount"] == 0
    assert report["fileHost"]["fetches"] == ["assets/colors/nfl.json"]
    assert all("follow.json" not in url for url in report["nyg"]["fetches"])
    assert all("follow.json" not in url for url in report["mich"]["fetches"])
    assert all("follow.json" not in url for url in report["otherHost"]["fetches"])
    assert_open(report["arrivedBefore"], jax, "nfl", "pro")
    assert report["arrivedBefore"]["liveCount"] == 0
    assert report["arrivedBefore"]["fetches"]
    assert report["arrivedBefore"]["fetches"][0] == "assets/colors/nfl.json"
    live_urls = [url for url in report["arrivedBefore"]["fetches"] if "live_replay.js" in url]
    assert live_urls[0].startswith("widget/live_replay.js?")
    assert "espn" not in report["arrivedBefore"]["fetches"][0]
    assert "http://" not in report["arrivedBefore"]["fetches"][0]
    assert "https://" not in report["arrivedBefore"]["fetches"][0]
    assert report["arrivedAfter"]["score"] == live
    assert report["arrivedAfter"]["clock"] == "Q2 5:00"
    assert report["arrivedAfter"]["play"] == "Play"
    assert report["arrivedAfter"]["pressed"] == ["live"]
    assert report["arrivedAfter"]["liveLabel"] == "NYG at DEN"
    assert report["arrivedAfter"]["calls"] == []
    assert_open(report["missingBefore"], mich, "ncaah", "college")
    assert_open(report["missingAfter"], mich, "ncaah", "college")
    assert report["missingAfter"]["liveCount"] == 0
    assert report["missingAfter"]["score"] != live
    assert report["afterLiveClick"]["calls"] == ["?sport=nfl&game=nyg-den&live=1"]
    assert report["afterLiveClick"]["score"] == live
    assert report["afterLiveClick"]["play"] == "Play"
    assert_open(report["afterArchiveClick"], jax, "nfl", "pro")
    assert report["afterArchiveClick"]["pressed"] == ["nfl_jax_den.js"]
    assert report["afterArchiveClick"]["calls"] == [
        "?sport=nfl&game=nyg-den&live=1",
        "?sport=nfl&game=jax-den",
    ]
    for row in report.values():
        for url in row["calls"]:
            assert "espn" not in url
            assert "http://" not in url and "https://" not in url
            assert url.startswith("?") or url.startswith("index.html?")


def test_localhost_slate_polls_above_the_archive_and_opens_a_board_card(tmp_path):
    node = shutil.which("node")
    assert node, "node is required to poll the slate"
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

function http(status, body) {
  return { ok: status >= 200 && status < 300, status: status, body: body == null ? "" : String(body) };
}

function settle() {
  return new Promise((resolve) => setImmediate(resolve));
}

async function flush() {
  for (let i = 0; i < 12; i++) await settle();
}

const slateRows = [
  { sport: "nfl", game_id: "401", away: "NYG", home: "DEN", status: "live", away_score: 3, home_score: 7, prior_home: 0.58 },
  { sport: "nfl", game_id: "402", away: "KC", home: "BUF", status: "final", away_score: 17, home_score: 14, prior_home: 0.62 },
  { sport: "nfl", game_id: "403", away: "LV", home: "PHI", status: "pre", away_score: 0, home_score: 0, prior_home: 0.5 },
  { sport: "nfl", game_id: "404", away: "SEA", home: "SF", status: "stale", away_score: 2, home_score: 1, prior_home: 0.41 },
  { sport: "nba", game_id: "555", away: "BOS", home: "NYK", status: "pre", away_score: 0, home_score: 0, prior_home: 0.5 },
  { sport: "ncaaf", game_id: "900", away: "COLO", home: "TTU", status: "pre", away_score: 0, home_score: 0, prior_home: 0.5 }
];

function slateSource(rows) {
  return "window.MSWP_SLATE = " + JSON.stringify(rows) + ";\n";
}

function liveSource() {
  const rows = [
    {
      sport: "nfl", clock: "Q1 10:00", wp: 0.5, home: "DEN", away: "NYG",
      home_score: 0, away_score: 0, status: "live", period: 1,
      seconds_remaining_period: 600, seconds_remaining_total: 3300,
      prior_home: 0.58, game_id: "401"
    },
    {
      sport: "nfl", clock: "Q2 5:00", wp: 0.42, home: "DEN", away: "NYG",
      home_score: 7, away_score: 3, status: "live", period: 2,
      seconds_remaining_period: 300, seconds_remaining_total: 2100,
      prior_home: 0.58, game_id: "401",
      possession: "away", down: 2, distance: 7, yardline: 35
    }
  ];
  return "window.NFL_REPLAY = " + JSON.stringify(rows) + ";\nwindow.MSWP_LIVE = window.NFL_REPLAY;\n";
}

function liveSourceFor(gameId) {
  const rows = [{
    sport: "nfl", clock: "Q3 1:00", wp: 0.33, home: "BUF", away: "KC",
    home_score: 14, away_score: 17, status: "live", period: 3,
    seconds_remaining_period: 60, seconds_remaining_total: 960,
    prior_home: 0.62, game_id: gameId,
    possession: "home", down: 1, distance: 10, yardline: 25
  }];
  return "window.NFL_REPLAY = " + JSON.stringify(rows) + ";\nwindow.MSWP_LIVE = window.NFL_REPLAY;\n";
}

function boot(options) {
  options = options || {};
  const calls = [];
  const fetches = [];
  const intervals = [];
  const slateItems = (options.slate || []).slice();
  const liveItems = (options.live || []).slice();
  const followItems = (options.follow || []).slice();
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
    setInterval: (fn, ms) => {
      intervals.push({ fn: fn, ms: ms });
      return intervals.length;
    },
    clearInterval: () => {},
    getComputedStyle: () => ({ getPropertyValue: () => "#888888" }),
    localStorage: {
      getItem: (key) => (Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null),
      setItem: (key, value) => { store[key] = String(value); }
    },
    location: {
      hostname: options.hostname || "127.0.0.1",
      protocol: options.protocol || "http:",
      pathname: "",
      search: options.search || "",
      hash: ""
    },
    history: {
      replaceState: (_state, _title, url) => { calls.push(String(url)); }
    },
    fetch: (url, init) => {
      const address = String(url);
      fetches.push({
        url: address,
        cache: init && init.cache ? init.cache : "",
        method: init && init.method ? String(init.method).toUpperCase() : "GET",
        body: init && init.body != null ? String(init.body) : ""
      });
      if (address.indexOf("assets/colors/") === 0) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve([]),
          text: () => Promise.resolve("[]")
        });
      }
      let item = null;
      if (address.indexOf("slate.js") >= 0) item = slateItems.shift();
      else if (address.indexOf("live_replay.js") >= 0) item = liveItems.shift();
      else if (address.indexOf("follow.json") >= 0) item = followItems.shift();
      else item = http(599, address);
      if (!item) item = http(404, "");
      return Promise.resolve({
        ok: item.ok,
        status: item.status,
        text: () => Promise.resolve(item.body)
      });
    },
    document
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  const realAppend = body.appendChild.bind(body);
  body.appendChild = (node) => {
    const result = realAppend(node);
    if (node && node.tagName === "SCRIPT" && node.src) {
      const srcName = String(node.src);
      const rel = srcName.indexOf("widget/") === 0 ? srcName : path.join("widget", srcName);
      vm.runInContext(fs.readFileSync(path.join(process.cwd(), rel), "utf8"), sandbox);
      if (typeof node.onload === "function") node.onload();
    }
    return result;
  };
  function run(name) {
    vm.runInContext(fs.readFileSync(path.join("widget", name), "utf8"), sandbox);
  }
  run("manifest.js");
  run("colors.js");
  run("widget.js");
  return { document, calls, fetches, intervals, slateItems, liveItems };
}

function buttons(doc, id) {
  return doc.getElementById(id).children.filter((child) => child.tagName === "BUTTON");
}

function chartCount(doc, id) {
  let count = 0;
  function walk(node) {
    (node.children || []).forEach((child) => {
      count += 1;
      walk(child);
    });
  }
  walk(doc.getElementById(id));
  return count;
}

function snap(page) {
  const doc = page.document;
  const situation = doc.getElementById("situation");
  const scrub = doc.getElementById("scrub");
  const live = buttons(doc, "games").filter((button) => button.getAttribute("data-live") === "true");
  const archive = buttons(doc, "games").filter((button) => button.getAttribute("data-file"));
  const slate = buttons(doc, "slate");
  return {
    score: doc.getElementById("c-score").textContent,
    clock: doc.getElementById("c-clock").textContent,
    play: doc.getElementById("play").textContent,
    position: doc.getElementById("position").textContent,
    situation: situation.textContent,
    situationHidden: situation.hidden === true,
    scrub: scrub.value,
    scrubMax: scrub.max,
    scoreNodes: chartCount(doc, "score-chart"),
    wpNodes: chartCount(doc, "wp-chart"),
    boardHidden: doc.getElementById("board").hidden === true,
    away: doc.getElementById("board-away").textContent,
    home: doc.getElementById("board-home").textContent,
    boardScore: doc.getElementById("board-score").textContent,
    status: doc.getElementById("board-status").textContent,
    prior: doc.getElementById("board-prior").textContent,
    slateHidden: doc.getElementById("slate-row").hidden === true,
    slateLabels: slate.map((button) => button.textContent),
    slateIds: slate.map((button) => button.getAttribute("data-slate-id")),
    slatePressed: slate.filter((button) => button.getAttribute("aria-pressed") === "true").map((button) => button.getAttribute("data-slate-id")),
    gameHidden: doc.getElementById("game-row").hidden === true,
    archive: archive.map((button) => ({ file: button.getAttribute("data-file"), label: button.textContent })),
    liveLabel: live.length ? live[0].textContent : "",
    livePressed: live.length ? live[0].getAttribute("aria-pressed") : "",
    sportPressed: buttons(doc, "sports").filter((button) => button.getAttribute("aria-pressed") === "true").map((button) => button.getAttribute("data-sport")),
    calls: page.calls.slice(),
    fetches: page.fetches.map((item) => ({
      url: item.url,
      cache: item.cache,
      method: item.method || "GET",
      body: item.body || ""
    }))
  };
}

function clickSport(page, sport) {
  const button = buttons(page.document, "sports").find((child) => child.getAttribute("data-sport") === sport);
  if (!button) throw new Error("missing sport " + sport);
  button.click();
}

function clickFile(page, file) {
  const button = buttons(page.document, "games").find((child) => child.getAttribute("data-file") === file);
  if (!button) throw new Error("missing " + file);
  button.click();
}

function clickSlate(page, id) {
  const button = buttons(page.document, "slate").find((child) => child.getAttribute("data-slate-id") === id);
  if (!button) throw new Error("missing slate " + id);
  button.click();
}

async function runPoll(page) {
  const polls = page.intervals.filter((entry) => entry.ms === 15000);
  if (polls.length !== 1) throw new Error("expected one 15s poll, saw " + polls.length);
  polls[0].fn();
  await flush();
}

(async () => {
  const page = boot({
    slate: [http(200, slateSource(slateRows))],
    live: [http(200, liveSource())]
  });
  await flush();
  const opened = snap(page);
  page.document.getElementById("play").click();
  const duringPlay = page.document.getElementById("play").textContent;
  clickSlate(page, "402");
  const card = snap(page);
  clickSlate(page, "401");
  const livePick = snap(page);
  clickFile(page, "nfl_nyg_den.js");
  const afterArchive = snap(page);
  clickSport(page, "nba");
  const nba = snap(page);
  page.document.getElementById("level-college").click();
  clickSport(page, "ncaaf");
  const college = snap(page);

  const shelf = boot({ slate: [http(200, slateSource(slateRows))], live: [] });
  await flush();
  const shown = snap(shelf);
  shelf.slateItems.push(http(200, "window.MSWP_SLATE = [];\n"));
  await runPoll(shelf);
  const emptied = snap(shelf);
  shelf.slateItems.push(http(200, slateSource(slateRows)));
  await runPoll(shelf);
  const back = snap(shelf);
  shelf.slateItems.push(http(404, ""));
  await runPoll(shelf);
  const missing = snap(shelf);

  const pages = boot({
    hostname: "example.github.io",
    protocol: "https:",
    search: "?sport=nba&game=den-lal&id=555",
    slate: [http(200, slateSource(slateRows))],
    live: [http(200, liveSource())]
  });
  await flush();
  const pagesSnap = snap(pages);

  const unknown = boot({
    search: "?sport=nba&game=den-lal&id=999",
    slate: [http(200, slateSource(slateRows))],
    live: [http(200, liveSource())]
  });
  await flush();
  const unknownSnap = snap(unknown);

  const idLive = boot({
    search: "?sport=nba&game=den-lal&id=401",
    slate: [http(200, slateSource(slateRows))],
    live: [http(200, liveSource())]
  });
  await flush();
  const idLiveSnap = snap(idLive);

  const idCard = boot({
    search: "?id=402",
    slate: [http(200, slateSource(slateRows))],
    live: [http(200, liveSource())]
  });
  await flush();
  const idCardSnap = snap(idCard);

  const joinPage = boot({
    slate: [http(200, slateSource(slateRows))],
    live: [http(200, liveSource())]
  });
  await flush();
  clickSlate(joinPage, "402");
  const waiting = snap(joinPage);
  const rescoredRows = slateRows.map((row) => Object.assign({}, row));
  rescoredRows[1] = Object.assign({}, rescoredRows[1], { away_score: 21, home_score: 16 });
  joinPage.slateItems.push(http(200, slateSource(rescoredRows)));
  joinPage.liveItems.push(http(200, liveSource()));
  await runPoll(joinPage);
  const rescored = snap(joinPage);
  joinPage.slateItems.push(http(200, slateSource(slateRows)));
  joinPage.liveItems.push(http(200, liveSourceFor("402")));
  await runPoll(joinPage);
  const joined = snap(joinPage);

  const collegeOnly = boot({
    slate: [http(200, slateSource(slateRows))],
    live: [http(200, liveSource())]
  });
  await flush();
  collegeOnly.document.getElementById("level-college").click();
  clickSport(collegeOnly, "ncaaf");
  const collegePosts = snap(collegeOnly);

  const followCard = boot({
    follow: [http(200, '{"sport":"nfl","game_id":"402"}')],
    slate: [http(200, slateSource(slateRows))],
    live: [http(200, liveSource())]
  });
  await flush();
  const followCardSnap = snap(followCard);
  followCard.slateItems.push(http(200, slateSource(slateRows)));
  followCard.liveItems.push(http(200, liveSourceFor("402")));
  await runPoll(followCard);
  const followJoined = snap(followCard);

  const followLive = boot({
    hostname: "localhost",
    follow: [http(200, '{"sport":"nfl","game_id":"401"}')],
    slate: [http(200, slateSource(slateRows))],
    live: [http(200, liveSource())]
  });
  await flush();
  const followLiveSnap = snap(followLive);

  const followNba = boot({
    follow: [http(200, '{"sport":"nba","game_id":"555"}')],
    slate: [http(200, slateSource(slateRows))],
    live: [http(200, liveSource())]
  });
  await flush();
  const followNbaSnap = snap(followNba);

  const queryBeats = boot({
    search: "?sport=nba&game=den-lal",
    follow: [http(200, '{"sport":"nfl","game_id":"402"}')],
    slate: [http(200, slateSource(slateRows))],
    live: [http(200, liveSource())]
  });
  await flush();
  const queryBeatsSnap = snap(queryBeats);

  const pagesBare = boot({
    hostname: "example.github.io",
    protocol: "https:",
    follow: [http(200, '{"sport":"nfl","game_id":"402"}')],
    slate: [http(200, slateSource(slateRows))],
    live: [http(200, liveSource())]
  });
  await flush();
  const pagesBareSnap = snap(pagesBare);

  const missingFollow = boot({
    follow: [http(404, "")],
    slate: [http(200, slateSource(slateRows))],
    live: [http(200, liveSource())]
  });
  await flush();
  const missingFollowSnap = snap(missingFollow);

  const unknownFollow = boot({
    follow: [http(200, '{"sport":"nfl","game_id":"999"}')],
    slate: [http(200, slateSource(slateRows))],
    live: [http(200, liveSource())]
  });
  await flush();
  const unknownFollowSnap = snap(unknownFollow);

  const badFollow = boot({
    follow: [http(200, "not-json")],
    slate: [http(200, slateSource(slateRows))],
    live: [http(404, "")]
  });
  await flush();
  const badFollowSnap = snap(badFollow);

  const collegeFile = boot({
    follow: [http(200, '{"sport":"ncaaf","game_id":"900"}')],
    slate: [http(200, slateSource(slateRows))],
    live: [http(200, liveSource())]
  });
  await flush();
  const collegeFileSnap = snap(collegeFile);

  const collegeQuery = boot({
    search: "?sport=ncaah&game=mich-den",
    follow: [http(200, '{"sport":"nfl","game_id":"402"}')],
    slate: [http(200, slateSource(slateRows))],
    live: [http(200, liveSource())]
  });
  await flush();
  const collegeQuerySnap = snap(collegeQuery);

  console.log(JSON.stringify({
    pollMs: page.intervals.filter((entry) => entry.ms === 15000).map((entry) => entry.ms),
    opened: opened,
    duringPlay: duringPlay,
    card: card,
    livePick: livePick,
    afterArchive: afterArchive,
    nba: nba,
    college: college,
    shown: shown,
    emptied: emptied,
    back: back,
    missing: missing,
    pages: pagesSnap,
    unknown: unknownSnap,
    idLive: idLiveSnap,
    idCard: idCardSnap,
    badge: page.document.getElementById("badge").textContent,
    waiting: waiting,
    rescored: rescored,
    joined: joined,
    collegePosts: collegePosts,
    followCard: followCardSnap,
    followJoined: followJoined,
    followLive: followLiveSnap,
    followNba: followNbaSnap,
    queryBeats: queryBeatsSnap,
    pagesBare: pagesBareSnap,
    missingFollow: missingFollowSnap,
    unknownFollow: unknownFollowSnap,
    badFollow: badFollowSnap,
    collegeFile: collegeFileSnap,
    collegeQuery: collegeQuerySnap,
    followBadge: followCard.document.getElementById("badge").textContent
  }));
})().catch((err) => {
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
});
"""
    probe_path = tmp_path / "slate_poll.js"
    probe_path.write_text(probe, encoding="utf-8", newline="\n")
    completed = subprocess.run(
        [node, str(probe_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="strict",
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    opened = report["opened"]
    slate_fetches = [item for item in opened["fetches"] if "slate.js" in item["url"]]
    assert slate_fetches
    assert report["pollMs"] == [15000]
    for item in opened["fetches"]:
        assert (
            item["url"].startswith("widget/slate.js?t=")
            or item["url"].startswith("widget/live_replay.js?t=")
            or item["url"] == "widget/follow.json"
            or item["url"].startswith("assets/colors/")
        )
        assert "espn" not in item["url"]
        assert "http://" not in item["url"] and "https://" not in item["url"]
        assert item["cache"] == "no-store"
    assert opened["slateLabels"] == [
        "NYG at DEN 3-7",
        "KC at BUF 17-14",
        "LV at PHI",
        "SEA at SF 2-1",
    ]
    assert "900" not in opened["slateIds"]
    assert opened["slateHidden"] is False
    assert len(opened["archive"]) > 1
    nyg = next(item for item in opened["archive"] if item["file"] == "nfl_nyg_den.js")
    assert nyg["label"] == "NYG at DEN"
    assert report["duringPlay"] == "Pause"
    card = report["card"]
    assert card["play"] == "Play"
    assert card["boardHidden"] is False
    assert card["away"] == "KC"
    assert card["home"] == "BUF"
    assert card["boardScore"] == "17-14"
    assert card["status"] == "final"
    assert card["prior"] == "Pregame BUF 62.00%"
    assert card["scoreNodes"] == 0
    assert card["wpNodes"] == 0
    assert card["situation"] == ""
    assert card["situationHidden"] is True
    assert card["liveLabel"] == "NYG at DEN"
    assert card["livePressed"] == "false"
    assert card["slatePressed"] == ["402"]
    assert card["calls"][-1] == "?sport=nfl&game=kc-buf&id=402"
    assert "live=1" not in card["calls"][-1]
    picked = report["livePick"]
    assert picked["boardHidden"] is True
    assert picked["clock"] == "Q2 5:00"
    assert picked["position"] == "Q2 5:00"
    assert "3" in picked["score"] and "7" in picked["score"]
    assert picked["scoreNodes"] > 0
    assert picked["wpNodes"] > 0
    assert picked["situation"] == "NYG ball, 2nd and 7, yardline 35"
    assert picked["situationHidden"] is False
    assert picked["scrub"] == picked["scrubMax"] == "1"
    assert picked["liveLabel"] == "NYG at DEN"
    assert picked["livePressed"] == "true"
    assert picked["slatePressed"] == ["401"]
    assert picked["calls"][-1] == "?sport=nfl&game=nyg-den&live=1&id=401"
    assert report["afterArchive"]["calls"][-1] == "?sport=nfl&game=nyg-den"
    assert "id=" not in report["afterArchive"]["calls"][-1]
    assert "live=1" not in report["afterArchive"]["calls"][-1]
    nba = report["nba"]
    assert nba["gameHidden"] is False
    assert nba["slateHidden"] is False
    assert nba["slateLabels"] == ["BOS at NYK"]
    assert nba["archive"] == [{"file": "nba_den_lal.js", "label": "DEN at LAL"}]
    assert nba["calls"][-1] == "?sport=nba&game=den-lal"
    assert "id=" not in nba["calls"][-1]
    assert report["college"]["slateLabels"] == []
    assert report["college"]["slateIds"] == []
    assert report["college"]["slateHidden"] is True
    assert report["shown"]["slateLabels"] == opened["slateLabels"]
    assert len(report["shown"]["archive"]) > 1
    assert report["emptied"]["slateLabels"] == []
    assert report["emptied"]["slateHidden"] is True
    assert report["emptied"]["archive"] == report["shown"]["archive"]
    assert report["back"]["slateLabels"] == opened["slateLabels"]
    assert report["missing"]["slateLabels"] == []
    assert report["missing"]["slateHidden"] is True
    assert report["missing"]["archive"] == report["shown"]["archive"]
    kept = next(item for item in report["missing"]["archive"] if item["file"] == "nfl_nyg_den.js")
    assert kept["label"] == "NYG at DEN"
    assert [item["url"] for item in report["pages"]["fetches"]] == ["assets/colors/nfl.json"]
    assert "NYG" in report["pages"]["score"]
    assert "LAL" not in report["pages"]["score"]
    assert "NYG" in report["unknown"]["score"]
    assert "LAL" not in report["unknown"]["score"]
    assert report["unknown"]["boardHidden"] is True
    assert report["unknown"]["calls"] == []
    assert report["idLive"]["clock"] == "Q2 5:00"
    assert report["idLive"]["boardHidden"] is True
    assert report["idLive"]["scoreNodes"] > 0
    assert report["idLive"]["calls"] == []
    assert "LAL" not in report["idLive"]["score"]
    assert report["idCard"]["away"] == "KC"
    assert report["idCard"]["home"] == "BUF"
    assert report["idCard"]["boardHidden"] is False
    assert report["idCard"]["scoreNodes"] == 0
    assert report["idCard"]["wpNodes"] == 0
    assert report["idCard"]["situation"] == ""
    assert report["idCard"]["calls"] == []
    assert report["badge"] == "V4"

    def posts(row):
        return [item for item in row["fetches"] if item["method"] == "POST"]

    card_posts = posts(card)
    assert len(card_posts) == 1
    assert card_posts[0]["url"] == "/follow"
    assert card_posts[0]["body"] == '{"sport":"nfl","game_id":"402"}'
    assert card_posts[0]["cache"] == "no-store"
    assert "espn" not in card_posts[0]["url"]
    assert "http://" not in card_posts[0]["url"] and "https://" not in card_posts[0]["url"]
    picked_posts = posts(picked)
    assert [item["body"] for item in picked_posts] == [
        '{"sport":"nfl","game_id":"402"}',
        '{"sport":"nfl","game_id":"401"}',
    ]
    assert [item["url"] for item in picked_posts] == ["/follow", "/follow"]
    college_posts = posts(report["college"])
    assert [item["body"] for item in college_posts] == [
        '{"sport":"nfl","game_id":"402"}',
        '{"sport":"nfl","game_id":"401"}',
    ]
    assert posts(report["collegePosts"]) == []
    for item in report["collegePosts"]["fetches"]:
        assert (
            item["url"].startswith("widget/slate.js?t=")
            or item["url"].startswith("widget/live_replay.js?t=")
            or item["url"] == "widget/follow.json"
            or item["url"].startswith("assets/colors/")
        )
        assert item["url"] != "/follow"
        assert "espn" not in item["url"]
    waiting = report["waiting"]
    assert waiting["boardHidden"] is False
    assert waiting["away"] == "KC"
    assert waiting["home"] == "BUF"
    assert waiting["boardScore"] == "17-14"
    assert waiting["scoreNodes"] == 0
    assert waiting["wpNodes"] == 0
    rescored = report["rescored"]
    assert rescored["boardHidden"] is False
    assert rescored["away"] == "KC"
    assert rescored["home"] == "BUF"
    assert rescored["boardScore"] == "21-16"
    assert rescored["status"] == "final"
    assert rescored["slateLabels"] == [
        "NYG at DEN 3-7",
        "KC at BUF 21-16",
        "LV at PHI",
        "SEA at SF 2-1",
    ]
    assert rescored["slatePressed"] == ["402"]
    assert rescored["scoreNodes"] == 0
    assert rescored["wpNodes"] == 0
    assert posts(waiting) == [{
        "url": "/follow",
        "cache": "no-store",
        "method": "POST",
        "body": '{"sport":"nfl","game_id":"402"}',
    }]
    joined = report["joined"]
    assert joined["boardHidden"] is True
    assert joined["clock"] == "Q3 1:00"
    assert joined["position"] == "Q3 1:00"
    assert "17" in joined["score"] and "14" in joined["score"]
    assert joined["scoreNodes"] > 0
    assert joined["wpNodes"] > 0
    assert joined["situation"] == "BUF ball, 1st and 10, yardline 25"
    assert joined["slatePressed"] == ["402"]
    assert posts(joined) == posts(waiting)
    for item in joined["fetches"]:
        assert "espn" not in item["url"]
        assert "http://" not in item["url"] and "https://" not in item["url"]
        assert (
            item["url"] == "/follow"
            or item["url"] == "widget/follow.json"
            or item["url"].startswith("widget/slate.js?t=")
            or item["url"].startswith("widget/live_replay.js?t=")
            or item["url"].startswith("assets/colors/")
        )

    def gets(row):
        return [item for item in row["fetches"] if item["url"] == "widget/follow.json"]

    follow_card = report["followCard"]
    assert gets(follow_card) == [{
        "url": "widget/follow.json",
        "cache": "no-store",
        "method": "GET",
        "body": "",
    }]
    assert posts(follow_card) == []
    assert follow_card["calls"] == []
    assert follow_card["boardHidden"] is False
    assert follow_card["away"] == "KC"
    assert follow_card["home"] == "BUF"
    assert follow_card["boardScore"] == "17-14"
    assert follow_card["status"] == "final"
    assert follow_card["slatePressed"] == ["402"]
    assert follow_card["sportPressed"] == ["nfl"]
    assert follow_card["scoreNodes"] == 0
    assert follow_card["wpNodes"] == 0
    assert follow_card["situation"] == ""
    assert "espn" not in follow_card["fetches"][0]["url"]
    assert "http://" not in follow_card["fetches"][0]["url"]
    assert "https://" not in follow_card["fetches"][0]["url"]
    follow_joined = report["followJoined"]
    assert follow_joined["boardHidden"] is True
    assert follow_joined["clock"] == "Q3 1:00"
    assert follow_joined["position"] == "Q3 1:00"
    assert "17" in follow_joined["score"] and "14" in follow_joined["score"]
    assert follow_joined["scoreNodes"] > 0
    assert follow_joined["wpNodes"] > 0
    assert follow_joined["situation"] == "BUF ball, 1st and 10, yardline 25"
    assert follow_joined["slatePressed"] == ["402"]
    assert follow_joined["sportPressed"] == ["nfl"]
    assert follow_joined["calls"] == []
    assert posts(follow_joined) == []
    follow_live = report["followLive"]
    assert follow_live["boardHidden"] is True
    assert follow_live["clock"] == "Q2 5:00"
    assert follow_live["position"] == "Q2 5:00"
    assert "3" in follow_live["score"] and "7" in follow_live["score"]
    assert follow_live["scoreNodes"] > 0
    assert follow_live["wpNodes"] > 0
    assert follow_live["situation"] == "NYG ball, 2nd and 7, yardline 35"
    assert follow_live["slatePressed"] == ["401"]
    assert follow_live["sportPressed"] == ["nfl"]
    assert follow_live["calls"] == []
    assert gets(follow_live) == gets(follow_card)
    assert posts(follow_live) == []
    follow_nba = report["followNba"]
    assert follow_nba["sportPressed"] == ["nba"]
    assert follow_nba["boardHidden"] is False
    assert follow_nba["away"] == "BOS"
    assert follow_nba["home"] == "NYK"
    assert follow_nba["status"] == "pre"
    assert follow_nba["slatePressed"] == ["555"]
    assert follow_nba["slateLabels"] == ["BOS at NYK"]
    assert follow_nba["scoreNodes"] == 0
    assert follow_nba["wpNodes"] == 0
    assert follow_nba["calls"] == []
    query_beats = report["queryBeats"]
    assert "LAL" in query_beats["score"] and "DEN" in query_beats["score"]
    assert query_beats["boardHidden"] is True
    assert query_beats["sportPressed"] == ["nba"]
    assert query_beats["slatePressed"] == []
    assert query_beats["calls"] == []
    assert gets(query_beats) == []
    assert "KC" not in query_beats["score"]
    pages_bare = report["pagesBare"]
    assert [item["url"] for item in pages_bare["fetches"]] == ["assets/colors/nfl.json"]
    assert gets(pages_bare) == []
    assert "NYG" in pages_bare["score"]
    assert "KC" not in pages_bare["score"]
    assert pages_bare["boardHidden"] is True
    assert pages_bare["sportPressed"] == ["nfl"]
    missing_follow = report["missingFollow"]
    assert "NYG" in missing_follow["score"] and "DEN" in missing_follow["score"]
    assert missing_follow["clock"] == "FINAL"
    assert missing_follow["boardHidden"] is True
    assert missing_follow["slatePressed"] == []
    assert missing_follow["sportPressed"] == ["nfl"]
    assert missing_follow["calls"] == []
    assert gets(missing_follow) == [{
        "url": "widget/follow.json",
        "cache": "no-store",
        "method": "GET",
        "body": "",
    }]
    assert "LAL" not in missing_follow["score"]
    unknown_follow = report["unknownFollow"]
    assert "NYG" in unknown_follow["score"] and "DEN" in unknown_follow["score"]
    assert unknown_follow["clock"] == "FINAL"
    assert unknown_follow["boardHidden"] is True
    assert unknown_follow["slatePressed"] == []
    assert unknown_follow["sportPressed"] == ["nfl"]
    assert gets(unknown_follow) == gets(missing_follow)
    bad_follow = report["badFollow"]
    assert "NYG" in bad_follow["score"]
    assert bad_follow["clock"] == "FINAL"
    assert bad_follow["boardHidden"] is True
    assert bad_follow["slatePressed"] == []
    college_file = report["collegeFile"]
    assert college_file["sportPressed"] == ["nfl"]
    assert "NYG" in college_file["score"]
    assert college_file["boardHidden"] is True
    assert college_file["slatePressed"] == []
    assert college_file["clock"] == "FINAL"
    assert gets(college_file) == gets(missing_follow)
    college_query = report["collegeQuery"]
    assert "MICH" in college_query["score"] and "DEN" in college_query["score"]
    assert college_query["sportPressed"] == ["ncaah"]
    assert college_query["boardHidden"] is True
    assert college_query["slatePressed"] == []
    assert gets(college_query) == []
    assert all("follow.json" not in item["url"] for item in college_query["fetches"])
    assert report["followBadge"] == "V4"
    assert report["badge"] == "V4"
    assert all("follow.json" not in item["url"] for item in report["pages"]["fetches"])
