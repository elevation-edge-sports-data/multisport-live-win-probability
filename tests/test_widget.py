"""Static widget contract: three sports, two views, no second model."""

from __future__ import annotations

import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

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


def test_widget_has_three_sports_and_two_views_and_no_remote_feed():
    html = (WIDGET / "index.html").read_text(encoding="utf-8")
    css = (WIDGET / "widget.css").read_text(encoding="utf-8")
    script = (WIDGET / "widget.js").read_text(encoding="utf-8")
    page = html.lower()
    assert "espn" not in page
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
    assert 'src="nfl_jax_den.js"' in html
    assert 'src="cfb_cu_gt.js"' in html
    assert 'src="nhl_col_min_g5.js"' in html
    assert 'src="cfb_replay.js"' not in html
    assert (WIDGET / "nfl_replay.js").is_file()
    assert "Harbor" not in script and "Red Oak" not in script
    assert "frame.home_color" in script or "home_color" in script
    assert "away_color" in script
    assert "--home: #1f8f86" in css
    assert "--away: #c94b32" in css
    demo = (WIDGET / "nfl_jax_den.js").read_text(encoding="utf-8").lower()
    assert "espn" not in demo
    assert "fetch(" not in demo
    assert "https://" not in demo and "http://" not in demo
    assert "margin_sd" not in script
    assert "college hockey" not in page

    parser = _Buttons()
    parser.feed(html)
    sports = [item for item in parser.buttons if "sport" in item[0].get("class", "")]
    views = [item for item in parser.buttons if "data-view-choice" in item[0]]
    assert [text.strip() for _, text in sports] == ["NFL", "CFB", "NHL"]
    assert "disabled" not in sports[0][0]
    assert "disabled" not in sports[1][0]
    assert "disabled" not in sports[2][0]
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
    assert "NBA" not in sport_text
    assert "CBB" not in html
    assert "college hockey" not in (html + css + script).lower()
    assert html.index("title-line") < html.index("data-view-choice") < html.index('class="toolbar"')
    assert ">V2<" in html
    assert ">V0<" not in html
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
    assert 'text: "Q1"' in script and 'text: "Q4"' in script
    assert 'text: "OT"' in script
    assert 'text: "2OT"' not in script
    assert "OT_PANE_FLOOR" in script
    assert "function bandPosition" in script
    assert "function loadSport" in script
    assert "root.NFL_REPLAY" in script and "root.CFB_REPLAY" in script
    assert "root.NHL_REPLAY" in script
    assert 'text: "P1"' in script and 'text: "P3"' in script
    assert 'getElementById("sport-cfb").addEventListener("click"' in script
    assert 'getElementById("sport-nhl").addEventListener("click"' in script
    assert 'loadSport("cfb")' in script
    assert 'loadSport("nhl")' in script
    for path in WIDGET.rglob("*"):
        if path.suffix.lower() not in {".html", ".js", ".css"}:
            continue
        text = path.read_text(encoding="utf-8").lower()
        assert "espn" not in text, path.name
        assert "fetch(" not in text, path.name
        assert "https://" not in text, path.name
        bare = text.replace("http://www.w3.org/2000/svg", "")
        assert "http://" not in bare, path.name
    cfb_logos = sorted(path.name for path in (WIDGET / "logos" / "cfb").iterdir())
    assert cfb_logos == ["COLO.png", "GT.png"]


def test_period_bands_put_overtime_in_one_pane_right_of_q4():
    node = shutil.which("node")
    assert node, "node is required to check the chart geometry"
    probe = r"""
const fs = require("fs");
const vm = require("vm");
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("widget/widget.js", "utf8"), sandbox);
const bands = sandbox.mswpBands;
const text = fs.readFileSync("widget/cfb_replay.js", "utf8");
const frames = JSON.parse(text.slice(text.indexOf("["), text.lastIndexOf("]") + 1));
const layout = bands.layoutBands(frames);
const placed = frames.map((frame) => ({
  period: frame.period,
  x: bands.bandPosition(frame, frames, layout, "cfb")
}));
const q4 = placed.filter((row) => row.period === 4).map((row) => row.x);
const ot = placed.filter((row) => row.period === 5).map((row) => row.x);
const two = placed.filter((row) => row.period === 6).map((row) => row.x);
const nfl = [
  {period: 4, seconds_remaining_period: 0, status: "live", clock: "Q4 0:00"},
  {period: 5, seconds_remaining_period: 600, status: "live", clock: "OT 10:00"},
  {period: 5, seconds_remaining_period: 0, status: "live", clock: "OT 0:00"},
  {period: 6, seconds_remaining_period: 600, status: "live", clock: "2OT 10:00"}
];
const nflLayout = bands.layoutBands(nfl);
const nflX = nfl.map((frame) => bands.bandPosition(frame, nfl, nflLayout, "nfl"));
const empty = [
  {period: 1, seconds_remaining_period: 900, status: "live", clock: "Q1 15:00"},
  {period: 4, seconds_remaining_period: 450, status: "live", clock: "Q4 7:30"}
];
const emptyLayout = bands.layoutBands(empty);
console.log(JSON.stringify({
  span: layout.span,
  otWidth: layout.otWidth,
  q4max: Math.max(...q4),
  otmin: Math.min(...ot),
  otmax: Math.max(...ot),
  twomin: Math.min(...two),
  twomax: Math.max(...two),
  nfl: nflX,
  nflSpan: nflLayout.span,
  emptySpan: emptyLayout.span,
  emptyQ4: bands.bandPosition(empty[1], empty, emptyLayout, "nfl")
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
    assert report["q4max"] <= 4
    assert report["otmin"] > 4
    assert report["twomin"] > report["otmax"]
    assert report["twomax"] < report["span"]
    assert 0 < report["otWidth"] < report["span"]
    q4_end, ot_start, ot_end, two_start = report["nfl"]
    assert q4_end <= 4
    assert ot_start > 4
    assert ot_end > ot_start
    assert two_start > ot_end
    assert two_start < report["nflSpan"]
    assert report["emptySpan"] == 4
    assert 3 < report["emptyQ4"] < 4


def test_hockey_period_bands_are_three_columns_plus_one_ot_pane():
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
console.log(JSON.stringify({
  bareSpan: bare.span,
  bareOt: bare.otWidth,
  span: layout.span,
  otWidth: layout.otWidth,
  otCount: layout.otCount,
  p3: placed[2],
  otStart: placed[3],
  otGoal: placed[4],
  finalX: placed[5],
  footballSpan: football.span
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
    assert report["bareSpan"] == 3
    assert report["bareOt"] == 0
    assert report["otCount"] == 3
    assert report["otWidth"] >= 0.38
    assert report["span"] == 3 + report["otWidth"]
    assert report["p3"] == 3
    assert report["otStart"] > 3
    assert report["otGoal"] > report["otStart"]
    assert report["finalX"] == report["otGoal"]
    assert report["finalX"] < report["span"]
    assert report["footballSpan"] == 4
    node = shutil.which("node")
    assert node, "node is required to check the chart geometry"
    probe = r"""
const fs = require("fs");
const vm = require("vm");
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("widget/widget.js", "utf8"), sandbox);
const bands = sandbox.mswpBands;
const text = fs.readFileSync("widget/cfb_cu_gt.js", "utf8");
const frames = JSON.parse(text.slice(text.indexOf("["), text.lastIndexOf("]") + 1));
const layout = bands.layoutBands(frames);
const overtime = frames.filter((frame) => bands.frameIsOvertime(frame));
console.log(JSON.stringify({
  span: layout.span,
  otWidth: layout.otWidth,
  otCount: layout.otCount,
  overtime: overtime.length,
  periods: [...new Set(frames.map((frame) => frame.period))]
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
    assert report["otWidth"] == 0
    assert report["otCount"] == 0
    assert report["overtime"] == 0
    assert report["periods"] == [1, 2, 3, 4]
