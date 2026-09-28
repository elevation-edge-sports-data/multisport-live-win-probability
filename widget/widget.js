// Displays window.NFL_REPLAY, window.NHL_REPLAY, window.NBA_REPLAY,
// window.NCAAF_REPLAY, window.NCAAH_REPLAY, and window.NCAAB_REPLAY.
// Each value was produced by the Python pack for that sport. This file
// does not estimate win probability and does not load a remote replay.

(function (root) {
  "use strict";

  var QUARTER_SECONDS = 900;
  var NFL_OT_SECONDS = 600;
  var HOCKEY_PERIOD_SECONDS = 1200;
  var NBA_QUARTER_SECONDS = 720;
  var NBA_OT_SECONDS = 300;
  var NCAAB_HALF_SECONDS = 1200;
  var NCAAB_OT_SECONDS = 300;
  // One extra-period snapshot stays thinner than a regulation column.
  // More snapshots widen the single OT pane. 2OT stays inside that pane.
  var OT_PANE_FLOOR = 0.38;

  function regulationCount(sport) {
    if (sport === "nhl" || sport === "ncaah") return 3;
    if (sport === "ncaab") return 2;
    return 4;
  }

  function frameIsOvertime(frame, sport) {
    if (sport === "nhl" || sport === "ncaah") {
      if (Number(frame.period) > 3) return true;
    } else if (sport === "ncaab") {
      if (Number(frame.period) > 2) return true;
    } else if (Number(frame.period) > 4) {
      return true;
    }
    var status = String(frame.status || "").trim().toLowerCase();
    if (status === "ot" || status === "overtime") return true;
    return /(?:^|[^A-Za-z0-9])\d*OT\b/.test(String(frame.clock || ""));
  }

  function layoutBands(rows, sport) {
    var nReg = regulationCount(sport);
    var counts = [];
    var otCount = 0;
    var i;
    for (i = 0; i < nReg; i++) counts.push(0);
    for (i = 0; i < rows.length; i++) {
      if (frameIsOvertime(rows[i], sport)) {
        otCount += 1;
      } else {
        var period = Number(rows[i].period);
        if (period >= 1 && period <= nReg) counts[period - 1] += 1;
      }
    }
    var sum = 0;
    var used = 0;
    for (i = 0; i < nReg; i++) {
      if (counts[i] > 0) {
        sum += counts[i];
        used += 1;
      }
    }
    var typical = used === 0 ? 1 : sum / used;
    var otWidth = 0;
    if (otCount > 0) otWidth = Math.max(OT_PANE_FLOOR, otCount / typical);
    var layout = {
      otCount: otCount,
      otWidth: otWidth,
      span: nReg + otWidth,
      regulation: nReg
    };
    // A final sudden-death goal ends the period. Do not keep the unused
    // clock after that goal, or the series stops short of the right edge.
    if (otWidth > 0 && timedFinalOvertime(rows, sport)) {
      var maxPos = 0;
      var j;
      for (j = 0; j < rows.length; j++) {
        var pos = bandPosition(rows[j], rows, layout, sport);
        if (pos > maxPos) maxPos = pos;
      }
      if (maxPos > nReg && maxPos < layout.span) layout.span = maxPos;
    }
    return layout;
  }

  function timedFinalOvertime(rows, sport) {
    if (sport !== "nfl" && sport !== "nhl" && sport !== "ncaah" && sport !== "nba" && sport !== "ncaab") {
      return false;
    }
    if (!rows || !rows.length) return false;
    var last = rows[rows.length - 1];
    return String(last.status || "").toLowerCase() === "final" && frameIsOvertime(last, sport);
  }

  function otOrdinal(frame, rows) {
    var seen = 0;
    var i;
    for (i = 0; i < rows.length; i++) {
      if (!frameIsOvertime(rows[i])) continue;
      if (rows[i] === frame) return seen;
      seen += 1;
    }
    return 0;
  }

  function regulationPosition(frame, sport) {
    if (sport === "nhl" || sport === "ncaah") return hockeyRegulationPosition(frame);
    var length = sport === "nba" ? NBA_QUARTER_SECONDS : sport === "ncaab" ? NCAAB_HALF_SECONDS : QUARTER_SECONDS;
    var maxPeriod = sport === "ncaab" ? 2 : 4;
    var period = Number(frame.period);
    if (!(period >= 1)) period = 1;
    if (period > maxPeriod) period = maxPeriod;
    var remaining = Number(frame.seconds_remaining_period);
    if (!isFinite(remaining)) remaining = length;
    if (remaining < 0) remaining = 0;
    if (remaining > length) remaining = length;
    return (period - 1) + (length - remaining) / length;
  }

  function hockeyRegulationPosition(frame) {
    var period = Number(frame.period);
    if (!(period >= 1)) period = 1;
    if (period > 3) period = 3;
    var remaining = Number(frame.seconds_remaining_period);
    if (!isFinite(remaining)) remaining = HOCKEY_PERIOD_SECONDS;
    if (remaining < 0) remaining = 0;
    if (remaining > HOCKEY_PERIOD_SECONDS) remaining = HOCKEY_PERIOD_SECONDS;
    return (period - 1) + (HOCKEY_PERIOD_SECONDS - remaining) / HOCKEY_PERIOD_SECONDS;
  }

  function timedOtFraction(frame, rows, sport, otSeconds) {
    var periods = [];
    var i;
    for (i = 0; i < rows.length; i++) {
      if (!frameIsOvertime(rows[i], sport)) continue;
      var period = Number(rows[i].period);
      if (periods.indexOf(period) === -1) periods.push(period);
    }
    periods.sort(function (a, b) { return a - b; });
    if (periods.length === 0) periods.push(Number(frame.period) || 5);
    var pIndex = periods.indexOf(Number(frame.period));
    if (pIndex < 0) pIndex = 0;
    var remaining = Number(frame.seconds_remaining_period);
    if (!isFinite(remaining)) remaining = 0;
    if (remaining < 0) remaining = 0;
    if (remaining > otSeconds) remaining = otSeconds;
    var within = (otSeconds - remaining) / otSeconds;
    var slot = (pIndex + 0.12 + 0.76 * within) / periods.length;
    if (slot < 0.02) slot = 0.02;
    if (slot > 0.98) slot = 0.98;
    return slot;
  }

  function nflOtFraction(frame, rows) {
    return timedOtFraction(frame, rows, "nfl", NFL_OT_SECONDS);
  }

  function ncaafOtFraction(frame, rows, layout) {
    if (layout.otCount <= 1) return 0.5;
    return (otOrdinal(frame, rows) + 1) / (layout.otCount + 1);
  }

  function bandPosition(frame, rows, layout, sport) {
    var origin = layout && layout.regulation ? layout.regulation : 4;
    if (!frameIsOvertime(frame, sport)) return regulationPosition(frame, sport);
    var frac = sport === "nfl"
      ? nflOtFraction(frame, rows)
      : (sport === "nhl" || sport === "ncaah")
        ? timedOtFraction(frame, rows, sport, HOCKEY_PERIOD_SECONDS)
        : sport === "nba"
          ? timedOtFraction(frame, rows, "nba", NBA_OT_SECONDS)
          : sport === "ncaab"
            ? timedOtFraction(frame, rows, "ncaab", NCAAB_OT_SECONDS)
            : ncaafOtFraction(frame, rows, layout);
    return origin + frac * layout.otWidth;
  }

  root.mswpBands = {
    QUARTER_SECONDS: QUARTER_SECONDS,
    NFL_OT_SECONDS: NFL_OT_SECONDS,
    HOCKEY_PERIOD_SECONDS: HOCKEY_PERIOD_SECONDS,
    OT_PANE_FLOOR: OT_PANE_FLOOR,
    frameIsOvertime: frameIsOvertime,
    layoutBands: layoutBands,
    bandPosition: bandPosition
  };

  if (!root.document || !root.document.getElementById) return;

  var frames = root.NFL_REPLAY;
  var sportName = "nfl";
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

  var plot = { width: 640, height: 200, left: 44, right: 16, top: 16, bottom: 28 };

  function writePrior() {
    var pregame = frames[0].prior_home;
    var pregameHome = pregame > 0.5;
    var pregameName = pregameHome ? frames[0].home : frames[0].away;
    var pregamePct = (pregameHome ? pregame : 1 - pregame) * 100;
    document.getElementById("prior").textContent =
      "Pregame " + pregameName + " " + pregamePct.toFixed(2) + "%";
  }

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
    var docRoot = document.documentElement;
    function paint(fillName, inkName, value) {
      if (value) {
        docRoot.style.setProperty(fillName, value);
        docRoot.style.setProperty(inkName, value);
      } else {
        docRoot.style.removeProperty(fillName);
        docRoot.style.removeProperty(inkName);
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
    text("c-score", frame.away + " " + frame.away_score + " – " + frame.home + " " + frame.home_score);
    text("c-wp", homePct + "%");
    paintTicker(frame);
    applyLogo("c-home-logo", frame.home_logo);
    applyLogo("c-away-logo", frame.away_logo);

    text("e-clock", frame.clock);
    text("e-home-pct", homePct);
    text("e-away-pct", awayPct);
    text("e-home-name", frame.home);
    text("e-away-name", frame.away);
    text("e-home-score", String(frame.home_score));
    text("e-away-score", String(frame.away_score));
    applyLogo("e-home-logo", frame.home_logo);
    applyLogo("e-away-logo", frame.away_logo);
  }

  function applyLogo(id, path) {
    var img = document.getElementById(id);
    if (!path) {
      img.hidden = true;
      img.removeAttribute("src");
      return;
    }
    if (img.getAttribute("src") !== path) {
      img.setAttribute("src", path);
    }
    img.hidden = false;
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

  function markSport(selectedId) {
    ["sport-nfl", "sport-ncaaf", "sport-nhl", "sport-ncaah", "sport-nba", "sport-ncaab"].forEach(function (id) {
      var button = document.getElementById(id);
      if (!button) return;
      var on = id === selectedId;
      if (on) button.classList.add("is-selected");
      else button.classList.remove("is-selected");
      if (!button.disabled) button.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function framesFor(next) {
    if (next === "ncaaf") return root.NCAAF_REPLAY;
    if (next === "nhl") return root.NHL_REPLAY;
    if (next === "ncaah") return root.NCAAH_REPLAY;
    if (next === "nba") return root.NBA_REPLAY;
    if (next === "ncaab") return root.NCAAB_REPLAY;
    return root.NFL_REPLAY;
  }

  function loadSport(next) {
    var nextFrames = framesFor(next);
    if (!Array.isArray(nextFrames) || nextFrames.length === 0) return;
    if (next === sportName) return;
    setPlaying(false);
    sportName = next;
    frames = nextFrames;
    scrub.max = String(frames.length - 1);
    writePrior();
    markSport("sport-" + next);
    show(openingIndex(frames));
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

  document.getElementById("sport-nfl").addEventListener("click", function () {
    loadSport("nfl");
  });

  document.getElementById("sport-ncaaf").addEventListener("click", function () {
    loadSport("ncaaf");
  });

  document.getElementById("sport-nhl").addEventListener("click", function () {
    loadSport("nhl");
  });

  document.getElementById("sport-ncaah").addEventListener("click", function () {
    loadSport("ncaah");
  });

  document.getElementById("sport-nba").addEventListener("click", function () {
    loadSport("nba");
  });

  document.getElementById("sport-ncaab").addEventListener("click", function () {
    loadSport("ncaab");
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

  function xAt(pos, span) {
    var width = plot.width - plot.left - plot.right;
    var t = span === 0 ? 0 : pos / span;
    if (t < 0) t = 0;
    if (t > 1) t = 1;
    return plot.left + t * width;
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
    var layout = layoutBands(frames, sportName);
    var shown = frames.slice(0, currentIndex + 1);
    function xOf(frame) {
      return xAt(bandPosition(frame, frames, layout, sportName), layout.span);
    }
    var homeColor = cssVar("--home");
    var awayColor = cssVar("--away");
    var muted = cssVar("--muted");
    var gold = cssVar("--gold");
    drawScore(shown, xOf, layout, homeColor, awayColor, muted, gold);
    drawWinProbability(shown, xOf, layout, homeColor, awayColor, muted, gold);
  }

  function drawBands(svg, layout, muted) {
    if (sportName === "nhl" || sportName === "ncaah") {
      drawHockeyBands(svg, layout, muted);
      return;
    }
    var span = layout.span;
    var nReg = layout.regulation || 4;
    var edges = [];
    var bi;
    for (bi = 1; bi < nReg; bi++) edges.push(bi);
    if (layout.otWidth > 0) edges.push(nReg);
    edges.forEach(function (at) {
      var x = xAt(at, span);
      svg.appendChild(svgEl("line", {
        x1: String(x),
        x2: String(x),
        y1: String(plot.top),
        y2: String(plot.height - plot.bottom),
        stroke: muted,
        "stroke-width": "1",
        "stroke-dasharray": "2 3",
        "data-series": "period-rail",
        "data-band": at === nReg ? "OT" : (sportName === "ncaab" ? "H" + at : "Q" + at)
      }));
    });
    var labels = [];
    for (bi = 0; bi < nReg; bi++) {
      labels.push({
        at: bi + 0.5,
        text: sportName === "ncaab" ? "H" + (bi + 1) : "Q" + (bi + 1)
      });
    }
    if (layout.otWidth > 0) {
      var otEnd = Math.min(nReg + layout.otWidth, layout.span);
      labels.push({ at: nReg + (otEnd - nReg) / 2, text: "OT" });
    }
    labels.forEach(function (item) {
      var caption = svgEl("text", {
        x: String(xAt(item.at, span)),
        y: String(plot.height - 8),
        fill: muted,
        "font-size": "11",
        "font-family": "Segoe UI, Helvetica Neue, sans-serif",
        "text-anchor": "middle",
        "data-series": "period-label",
        "data-band": item.text
      });
      caption.textContent = item.text;
      svg.appendChild(caption);
    });
  }

  function drawHockeyBands(svg, layout, muted) {
    var span = layout.span;
    var edges = [1, 2];
    if (layout.otWidth > 0) edges.push(3);
    edges.forEach(function (at) {
      var x = xAt(at, span);
      svg.appendChild(svgEl("line", {
        x1: String(x),
        x2: String(x),
        y1: String(plot.top),
        y2: String(plot.height - plot.bottom),
        stroke: muted,
        "stroke-width": "1",
        "stroke-dasharray": "2 3",
        "data-series": "period-rail",
        "data-band": at === 3 ? "OT" : "P" + at
      }));
    });
    var labels = [
      { at: 0.5, text: "P1" },
      { at: 1.5, text: "P2" },
      { at: 2.5, text: "P3" }
    ];
    if (layout.otWidth > 0) {
      var otEnd = Math.min(3 + layout.otWidth, layout.span);
      labels.push({ at: 3 + (otEnd - 3) / 2, text: "OT" });
    }
    labels.forEach(function (item) {
      var caption = svgEl("text", {
        x: String(xAt(item.at, span)),
        y: String(plot.height - 8),
        fill: muted,
        "font-size": "11",
        "font-family": "Segoe UI, Helvetica Neue, sans-serif",
        "text-anchor": "middle",
        "data-series": "period-label",
        "data-band": item.text
      });
      caption.textContent = item.text;
      svg.appendChild(caption);
    });
  }

  function drawLegendName(svg, x, y, color, name, series, detail, anchor) {
    var align = anchor || "start";
    var swatchX = align === "end" ? x - 8 : x;
    var textX = align === "end" ? x - 12 : x + 12;
    svg.appendChild(svgEl("rect", {
      x: String(swatchX),
      y: String(y - 8),
      width: "8",
      height: "8",
      rx: "1",
      fill: color,
      "data-series": series + "-swatch"
    }));
    var caption = svgEl("text", {
      x: String(textX),
      y: String(y),
      fill: cssVar("--ink"),
      "font-size": "11",
      "font-family": "Segoe UI, Helvetica Neue, sans-serif",
      "text-anchor": align,
      "data-series": series
    });
    caption.textContent = detail ? name + "  " + detail : name;
    svg.appendChild(caption);
  }

  function drawScore(shown, xOf, layout, homeColor, awayColor, muted, gold) {
    var svg = document.getElementById("score-chart");
    clearSvg(svg);
    drawBands(svg, layout, muted);
    var scoreMax = 1;
    frames.forEach(function (frame) {
      scoreMax = Math.max(scoreMax, frame.home_score, frame.away_score);
    });
    var baseline = yAt(0, 0, scoreMax);
    svg.appendChild(svgEl("line", {
      x1: String(xAt(0, layout.span)),
      x2: String(xAt(layout.span, layout.span)),
      y1: String(baseline),
      y2: String(baseline),
      stroke: muted,
      "stroke-width": "1"
    }));
    axisLabel(svg, plot.left - 8, yAt(scoreMax, 0, scoreMax) + 4, String(scoreMax), "end");
    axisLabel(svg, plot.left - 8, baseline, "0", "end");
    stepSeries(svg, shown, xOf, scoreMax, "home_score", "home-score", homeColor);
    stepSeries(svg, shown, xOf, scoreMax, "away_score", "away-score", awayColor);
    var currentFrame = shown[shown.length - 1];
    playhead(svg, xOf(currentFrame), gold);
    drawLegendName(svg, plot.left + 6, plot.top + 14, awayColor, frames[0].away, "legend-away", String(currentFrame.away_score));
    drawLegendName(svg, plot.width - plot.right - 6, plot.top + 14, homeColor, frames[0].home, "legend-home", String(currentFrame.home_score), "end");
  }

  function stepSeries(svg, shown, xOf, scoreMax, field, series, color) {
    var d = "";
    shown.forEach(function (frame, i) {
      var x = xOf(frame);
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

  function drawWinProbability(shown, xOf, layout, homeColor, awayColor, muted, gold) {
    var svg = document.getElementById("wp-chart");
    clearSvg(svg);
    drawBands(svg, layout, muted);
    var colors = { home: homeColor, away: awayColor, neutral: muted };
    var mid = yAtLow(0.5, 0, 1);
    svg.appendChild(svgEl("line", {
      x1: String(xAt(0, layout.span)),
      x2: String(xAt(layout.span, layout.span)),
      y1: String(mid),
      y2: String(mid),
      stroke: muted,
      "stroke-width": "1",
      "data-series": "wp-rail"
    }));
    axisLabel(svg, plot.left - 8, yAtLow(0, 0, 1) + 4, "0", "end");
    axisLabel(svg, plot.left - 8, mid + 4, "50", "end");
    axisLabel(svg, plot.left - 8, yAtLow(1, 0, 1), "100", "end");

    var points = shown.map(function (frame) {
      return { x: xOf(frame), p: frame.wp };
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
    drawLegendName(svg, plot.left + 6, plot.top + 14, awayColor, frames[0].away, "legend-away", formatAwayPercent(currentFrame) + "%");
    drawLegendName(svg, plot.width - plot.right - 6, plot.height - plot.bottom - 4, homeColor, frames[0].home, "legend-home", formatHomePercent(currentFrame) + "%", "end");
  }

  writePrior();
  show(openingIndex(frames));
})(typeof window !== "undefined" ? window : this);
