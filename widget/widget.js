// Displays window.NFL_REPLAY. Each wp was produced by Python compute_wp
// (the football pack). This file does not estimate win probability.

(function () {
  "use strict";

  var frames = window.NFL_REPLAY;
  var stage = document.getElementById("stage");
  if (!Array.isArray(frames) || frames.length === 0) {
    stage.textContent = "Replay file is missing.";
    return;
  }

  var app = document.getElementById("app");
  var playButton = document.getElementById("play");
  var scrub = document.getElementById("scrub");
  var index = 0;
  var timer = null;

  scrub.max = String(frames.length - 1);
  var pregame = frames[0].prior_home;
  var pregameHome = pregame > 0.5;
  var pregameName = pregameHome ? frames[0].home : frames[0].away;
  var pregamePct = (pregameHome ? pregame : 1 - pregame) * 100;
  document.getElementById("prior").textContent =
    "Pregame " + pregameName + " " + pregamePct.toFixed(2) + "%";

  var plot = { width: 640, height: 200, left: 44, right: 16, top: 16, bottom: 28 };

  function formatHomePercent(frame) {
    if (frame.status === "final") {
      if (frame.wp >= 1) return "100";
      if (frame.wp <= 0) return "0";
    }
    return (frame.wp * 100).toFixed(2);
  }

  function formatAwayPercent(frame) {
    if (frame.status === "final") {
      if (frame.wp >= 1) return "0";
      if (frame.wp <= 0) return "100";
    }
    return ((1 - frame.wp) * 100).toFixed(2);
  }

  function text(id, value) {
    document.getElementById(id).textContent = value;
  }

  function openingIndex(rows) {
    var last = rows[rows.length - 1];
    if (last.status === "final") return rows.length - 1;
    return 0;
  }

  function applyTeamColors(frame) {
    var root = document.documentElement;
    function paint(fillName, inkName, value) {
      if (value) {
        root.style.setProperty(fillName, value);
        root.style.setProperty(inkName, value);
      } else {
        root.style.removeProperty(fillName);
        root.style.removeProperty(inkName);
      }
    }
    paint("--home", "--home-ink", frame.home_color);
    paint("--away", "--away-ink", frame.away_color);
  }

  function show(nextIndex) {
    index = nextIndex;
    var frame = frames[index];
    var homePct = formatHomePercent(frame);
    var awayPct = formatAwayPercent(frame);
    applyTeamColors(frame);
    drawCharts(index);
    scrub.value = String(index);
    text("position", frame.clock + " · " + (index + 1) + "/" + frames.length);

    text("c-clock", frame.clock);
    text("c-score", frame.home + " " + frame.home_score + " – " + frame.away + " " + frame.away_score);
    text("c-wp", homePct + "%");
    paintTicker(frame);

    text("e-clock", frame.clock);
    text("e-home-pct", homePct);
    text("e-away-pct", awayPct);
    text("e-home-name", frame.home);
    text("e-away-name", frame.away);
    text("e-home-score", String(frame.home_score));
    text("e-away-score", String(frame.away_score));
  }

  function paintTicker(frame) {
    var homeBar = document.getElementById("c-home-bar");
    var awayBar = document.getElementById("c-away-bar");
    var decidedHome = frame.status === "final" && frame.wp >= 1;
    var decidedAway = frame.status === "final" && frame.wp <= 0;
    if (decidedHome || decidedAway) {
      homeBar.style.flex = decidedHome ? "1 1 0" : "0 0 0";
      awayBar.style.flex = decidedAway ? "1 1 0" : "0 0 0";
      homeBar.style.minWidth = "0";
      awayBar.style.minWidth = "0";
      return;
    }
    homeBar.style.flex = frame.wp + " 1 0";
    awayBar.style.flex = (1 - frame.wp) + " 1 0";
    homeBar.style.minWidth = "";
    awayBar.style.minWidth = "";
  }

  function setPlaying(playing) {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
    if (!playing) {
      playButton.textContent = "Play";
      return;
    }
    playButton.textContent = "Pause";
    timer = setInterval(function () {
      if (index >= frames.length - 1) {
        setPlaying(false);
        return;
      }
      var next = index + 1;
      show(next);
      if (next >= frames.length - 1) {
        setPlaying(false);
      }
    }, 1000);
  }

  playButton.addEventListener("click", function () {
    if (timer !== null) {
      setPlaying(false);
      return;
    }
    if (index >= frames.length - 1) {
      show(0);
    }
    setPlaying(true);
  });

  function step(delta) {
    setPlaying(false);
    var next = index + delta;
    if (next < 0) next = 0;
    if (next > frames.length - 1) next = frames.length - 1;
    if (next !== index) show(next);
  }

  document.getElementById("step-forward").addEventListener("click", function () {
    step(1);
  });

  document.getElementById("step-back").addEventListener("click", function () {
    step(-1);
  });

  scrub.addEventListener("input", function () {
    var next = Number(scrub.value);
    if (next !== index) {
      show(next);
    }
  });

  document.querySelectorAll("[data-view-choice]").forEach(function (button) {
    button.addEventListener("click", function () {
      app.dataset.view = button.getAttribute("data-view-choice");
      document.querySelectorAll("[data-view-choice]").forEach(function (other) {
        other.setAttribute("aria-pressed", other === button ? "true" : "false");
      });
    });
  });

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function svgEl(name, attrs) {
    var el = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.keys(attrs).forEach(function (key) {
      el.setAttribute(key, attrs[key]);
    });
    return el;
  }

  function clearSvg(svg) {
    while (svg.firstChild) {
      svg.removeChild(svg.firstChild);
    }
  }

  function xAt(elapsed, elapsedMax) {
    var span = plot.width - plot.left - plot.right;
    var t = elapsedMax === 0 ? 0 : elapsed / elapsedMax;
    return plot.left + t * span;
  }

  function yAt(value, valueMin, valueMax) {
    var span = plot.height - plot.top - plot.bottom;
    var t = valueMax === valueMin ? 0 : (value - valueMin) / (valueMax - valueMin);
    return plot.top + (1 - t) * span;
  }

  function yAtLow(value, valueMin, valueMax) {
    var span = plot.height - plot.top - plot.bottom;
    var t = valueMax === valueMin ? 0 : (value - valueMin) / (valueMax - valueMin);
    return plot.top + t * span;
  }

  function formatElapsed(seconds) {
    var minutes = Math.floor(seconds / 60);
    var secs = seconds % 60;
    return minutes + ":" + (secs < 10 ? "0" : "") + secs;
  }

  function axisLabel(svg, x, y, value, anchor) {
    var label = svgEl("text", {
      x: String(x),
      y: String(y),
      fill: cssVar("--muted"),
      "font-size": "11",
      "text-anchor": anchor || "middle"
    });
    label.textContent = value;
    svg.appendChild(label);
  }

  function playhead(svg, x, color) {
    svg.appendChild(svgEl("line", {
      x1: String(x),
      x2: String(x),
      y1: String(plot.top),
      y2: String(plot.height - plot.bottom),
      stroke: color,
      "stroke-width": "1.25",
      "data-series": "playhead"
    }));
  }

  function sideOf(winProbability) {
    if (winProbability > 0.5) return "home";
    if (winProbability < 0.5) return "away";
    return "neutral";
  }

  function splitPiece(start, end) {
    var startSide = sideOf(start.p);
    var endSide = sideOf(end.p);
    if (startSide !== "neutral" && endSide !== "neutral" && startSide !== endSide) {
      var t = (0.5 - start.p) / (end.p - start.p);
      var xCross = start.x + t * (end.x - start.x);
      return [
        { x0: start.x, p0: start.p, x1: xCross, p1: 0.5, tone: startSide },
        { x0: xCross, p0: 0.5, x1: end.x, p1: end.p, tone: endSide }
      ];
    }
    return [{
      x0: start.x,
      p0: start.p,
      x1: end.x,
      p1: end.p,
      tone: startSide === "neutral" ? endSide : startSide
    }];
  }

  function drawCharts(currentIndex) {
    var elapsedMax = frames[frames.length - 1].elapsed_seconds;
    var shown = frames.slice(0, currentIndex + 1);
    var homeColor = cssVar("--home");
    var awayColor = cssVar("--away");
    var muted = cssVar("--muted");
    var gold = cssVar("--gold");
    drawScore(shown, elapsedMax, homeColor, awayColor, muted, gold);
    drawWinProbability(shown, elapsedMax, homeColor, awayColor, muted, gold);
  }

  var QUARTER_SECONDS = 900;

  function snapshotIsOvertime(frame) {
    if (Number(frame.period) > 4) return true;
    return String(frame.status || "").trim().toLowerCase() === "ot";
  }

  function replayReachesOvertime(rows) {
    var i;
    for (i = 0; i < rows.length; i++) {
      if (snapshotIsOvertime(rows[i])) return true;
    }
    return false;
  }

  function periodMarks(elapsedMax) {
    var marks = [
      { at: QUARTER_SECONDS, label: "Q1" },
      { at: QUARTER_SECONDS * 2, label: "Q2" },
      { at: QUARTER_SECONDS * 3, label: "Q3" },
      { at: QUARTER_SECONDS * 4, label: "Q4" }
    ].filter(function (rail) {
      return rail.at <= elapsedMax + 0.01;
    });
    if (replayReachesOvertime(frames) && QUARTER_SECONDS * 4 <= elapsedMax + 0.01) {
      marks.push({ at: QUARTER_SECONDS * 4, label: "OT" });
    }
    return marks;
  }

  function drawPeriodRails(svg, elapsedMax, muted) {
    periodMarks(elapsedMax).forEach(function (rail) {
      var x = xAt(rail.at, elapsedMax);
      svg.appendChild(svgEl("line", {
        x1: String(x),
        x2: String(x),
        y1: String(plot.top),
        y2: String(plot.height - plot.bottom),
        stroke: muted,
        "stroke-width": "1",
        "stroke-dasharray": "2 3",
        "data-series": "period-rail",
        "data-rail": rail.label
      }));
    });
  }

  function drawPeriodLabels(svg, elapsedMax, muted) {
    periodMarks(elapsedMax).forEach(function (rail) {
      var x = xAt(rail.at, elapsedMax);
      var atEdge = x > plot.width - plot.right - 18;
      var caption = svgEl("text", {
        x: String(atEdge ? x - 3 : x + 3),
        y: String(plot.top + (rail.label === "OT" ? 21 : 10)),
        fill: muted,
        "font-size": "9",
        "font-family": "Segoe UI, Helvetica Neue, sans-serif",
        "text-anchor": atEdge ? "end" : "start",
        "data-series": "period-label",
        "data-rail": rail.label
      });
      caption.textContent = rail.label;
      svg.appendChild(caption);
    });
  }

  function drawLegendName(svg, x, y, color, name, series, detail) {
    svg.appendChild(svgEl("rect", {
      x: String(x),
      y: String(y - 8),
      width: "8",
      height: "8",
      rx: "1",
      fill: color,
      "data-series": series + "-swatch"
    }));
    var caption = svgEl("text", {
      x: String(x + 12),
      y: String(y),
      fill: cssVar("--ink"),
      "font-size": "11",
      "font-family": "Segoe UI, Helvetica Neue, sans-serif",
      "text-anchor": "start",
      "data-series": series
    });
    caption.textContent = detail ? name + "  " + detail : name;
    svg.appendChild(caption);
  }

  function drawScore(shown, elapsedMax, homeColor, awayColor, muted, gold) {
    var svg = document.getElementById("score-chart");
    clearSvg(svg);
    drawPeriodRails(svg, elapsedMax, muted);
    var scoreMax = 1;
    frames.forEach(function (frame) {
      scoreMax = Math.max(scoreMax, frame.home_score, frame.away_score);
    });
    var baseline = yAt(0, 0, scoreMax);
    svg.appendChild(svgEl("line", {
      x1: String(xAt(0, elapsedMax)),
      x2: String(xAt(elapsedMax, elapsedMax)),
      y1: String(baseline),
      y2: String(baseline),
      stroke: muted,
      "stroke-width": "1"
    }));
    axisLabel(svg, plot.left - 8, yAt(scoreMax, 0, scoreMax) + 4, String(scoreMax), "end");
    axisLabel(svg, plot.left - 8, baseline, "0", "end");
    axisLabel(svg, xAt(0, elapsedMax), plot.height - 8, "0:00", "start");
    axisLabel(svg, xAt(elapsedMax, elapsedMax), plot.height - 8, formatElapsed(elapsedMax), "end");
    stepSeries(svg, shown, elapsedMax, scoreMax, "home_score", "home-score", homeColor);
    stepSeries(svg, shown, elapsedMax, scoreMax, "away_score", "away-score", awayColor);
    var currentFrame = shown[shown.length - 1];
    playhead(svg, xAt(currentFrame.elapsed_seconds, elapsedMax), gold);
    drawPeriodLabels(svg, elapsedMax, muted);
    drawLegendName(svg, plot.left + 6, plot.top + 14, awayColor, frames[0].away, "legend-away", String(currentFrame.away_score));
    drawLegendName(svg, plot.left + 6, plot.top + 32, homeColor, frames[0].home, "legend-home", String(currentFrame.home_score));
  }

  function stepSeries(svg, shown, elapsedMax, scoreMax, field, series, color) {
    var d = "";
    shown.forEach(function (frame, i) {
      var x = xAt(frame.elapsed_seconds, elapsedMax);
      var y = yAt(frame[field], 0, scoreMax);
      d += i === 0 ? "M " + x + " " + y : " H " + x + " V " + y;
    });
    svg.appendChild(svgEl("path", {
      d: d,
      fill: "none",
      stroke: color,
      "stroke-width": "2",
      "stroke-linejoin": "round",
      "data-series": series
    }));
  }

  function drawWinProbability(shown, elapsedMax, homeColor, awayColor, muted, gold) {
    var svg = document.getElementById("wp-chart");
    clearSvg(svg);
    drawPeriodRails(svg, elapsedMax, muted);
    var colors = { home: homeColor, away: awayColor, neutral: muted };
    var mid = yAtLow(0.5, 0, 1);
    svg.appendChild(svgEl("line", {
      x1: String(xAt(0, elapsedMax)),
      x2: String(xAt(elapsedMax, elapsedMax)),
      y1: String(mid),
      y2: String(mid),
      stroke: muted,
      "stroke-width": "1",
      "data-series": "wp-rail"
    }));
    axisLabel(svg, plot.left - 8, yAtLow(0, 0, 1) + 4, "0", "end");
    axisLabel(svg, plot.left - 8, mid + 4, "50", "end");
    axisLabel(svg, plot.left - 8, yAtLow(1, 0, 1), "100", "end");
    axisLabel(svg, xAt(0, elapsedMax), plot.height - 8, "0:00", "start");
    axisLabel(svg, xAt(elapsedMax, elapsedMax), plot.height - 8, formatElapsed(elapsedMax), "end");

    var points = shown.map(function (frame) {
      return { x: xAt(frame.elapsed_seconds, elapsedMax), p: frame.wp };
    });
    for (var i = 1; i < points.length; i++) {
      splitPiece(points[i - 1], points[i]).forEach(function (piece) {
        var y0 = yAtLow(piece.p0, 0, 1);
        var y1 = yAtLow(piece.p1, 0, 1);
        if (piece.tone !== "neutral") {
          svg.appendChild(svgEl("path", {
            d: "M " + piece.x0 + " " + y0 +
              " L " + piece.x1 + " " + y1 +
              " L " + piece.x1 + " " + mid +
              " L " + piece.x0 + " " + mid + " Z",
            fill: colors[piece.tone],
            "fill-opacity": "0.28",
            stroke: "none",
            "data-series": "wp-fill",
            "data-tone": piece.tone
          }));
        }
        svg.appendChild(svgEl("path", {
          d: "M " + piece.x0 + " " + y0 + " L " + piece.x1 + " " + y1,
          fill: "none",
          stroke: colors[piece.tone],
          "stroke-width": "2",
          "data-series": "wp-line",
          "data-tone": piece.tone
        }));
      });
    }
    var current = points[points.length - 1];
    svg.appendChild(svgEl("circle", {
      cx: String(current.x),
      cy: String(yAtLow(current.p, 0, 1)),
      r: "3.5",
      fill: colors[sideOf(current.p)],
      "data-series": "wp-mark"
    }));
    var currentFrame = shown[shown.length - 1];
    playhead(svg, current.x, gold);
    drawPeriodLabels(svg, elapsedMax, muted);
    drawLegendName(svg, plot.left + 6, plot.top + 14, awayColor, frames[0].away, "legend-away", formatAwayPercent(currentFrame) + "%");
    drawLegendName(svg, plot.left + 6, plot.height - plot.bottom - 4, homeColor, frames[0].home, "legend-home", formatHomePercent(currentFrame) + "%");
  }

  show(openingIndex(frames));
})();
