"""Static widget contract: three sports, two views, no second model."""

from __future__ import annotations

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
    assert 'src="nfl_jax_den.js"' in html
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
    assert [text.strip() for _, text in sports] == ["NFL", "CFB next", "NHL soon"]
    assert "disabled" not in sports[0][0]
    assert "disabled" in sports[1][0] and "disabled" in sports[2][0]
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
    assert ">V1<" in html
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
    assert "elapsed_seconds" in script
    assert "frame.home_score" in script or "home_score" in script
    assert "frame.wp" in script
    assert "wp-rail" in script
    assert "NormalDist" not in script
    assert "Home win probability" not in html
    assert "function snapshotIsOvertime" in script
    assert "Number(frame.period) > 4" in script
    assert '=== "ot"' in script
    assert 'label: "Q1"' in script and 'label: "Q4"' in script
    assert 'label: "OT"' in script
    assert "replayReachesOvertime(frames)" in script
