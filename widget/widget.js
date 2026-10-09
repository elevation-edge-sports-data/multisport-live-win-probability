// Displays one rendered replay chosen from window.MSWP_MANIFEST.
// Each replay was produced by the Python pack for that sport. This file
// does not estimate win probability. On 127.0.0.1 or localhost it reads
// widget/live_replay.js and widget/slate.js. A pro slate click on that host POSTs
// /follow. On that host, when the query does not already choose a game,
// it also GETs widget/follow.json once. If that pro sport and game_id are
// on the slate, the page opens that row. GitHub Pages is / and does not
// request follow.json. College does not read it. Club colors for the
// selected sport are assets/colors/{sport}.json, one file per league,
// keyed by sport and id. id is the logo filename stem. Logos on a frame
// are assets/logos/{sport}/{abbr}.png and applyLogo uses that string as-is.
// The page query selects a manifest game (sport and game=away-home).
// live=1 selects Live on this host when that file has frames.
// id= selects a slate event on this host. A query string wins over the file.

(function (root) {
  "use strict";

  var QUARTER_SECONDS = 900;
  var NFL_OT_SECONDS = 600;
  var HOCKEY_PERIOD_SECONDS = 1200;
  var NBA_QUARTER_SECONDS = 720;
  var NBA_OT_SECONDS = 300;
  var NCAAB_HALF_SECONDS = 1200;
  var NCAAB_OT_SECONDS = 300;

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

  // One pane per period. A regulation period is one equal share. An extra
  // period is that share times the fraction of the period that elapsed.
  // The first extra period is OT, then 2OT, then 3OT. A regulation replay
  // has no OT pane. Labels stay on the chart axis.
  function maxExtraOrdinal(rows, sport) {
    var highest = 0;
    var i;
    if (!rows) return 0;
    for (i = 0; i < rows.length; i++) {
      if (!frameIsOvertime(rows[i], sport)) continue;
      var ordinal = extraOrdinal(rows[i], sport);
      if (ordinal > highest) highest = ordinal;
    }
    return highest;
  }

  function framesForExtra(rows, sport, ordinal) {
    var group = [];
    var i;
    if (!rows) return group;
    for (i = 0; i < rows.length; i++) {
      if (!frameIsOvertime(rows[i], sport)) continue;
      if (extraOrdinal(rows[i], sport) !== ordinal) continue;
      group.push(rows[i]);
    }
    return group;
  }

  // Timed extra periods use the furthest clock in the replay. College
  // overtime stays at 0:00, so those snaps are ordered and the pane is
  // only the fraction of a share that order fills.
  function extraPaneWidth(rows, sport, ordinal) {
    var group = framesForExtra(rows, sport, ordinal);
    var length = otLength(sport);
    var maxFrac = 0;
    var i;
    if (!group.length) return 1;
    if (!(length > 0)) {
      if (group.length === 1) return 0.5;
      return group.length / (group.length + 1);
    }
    for (i = 0; i < group.length; i++) {
      var frac = clockFraction(group[i], length);
      if (frac > maxFrac) maxFrac = frac;
    }
    return maxFrac;
  }

  function layoutBands(rows, sport) {
    var nReg = regulationCount(sport);
    var extra = maxExtraOrdinal(rows, sport);
    var extras = [];
    var widths = [];
    var span = 0;
    var i;
    for (i = 0; i < nReg; i++) {
      widths.push(1);
      span += 1;
    }
    for (i = 1; i <= extra; i++) {
      var width = extraPaneWidth(rows, sport, i);
      extras.push(i);
      widths.push(width);
      span += width;
    }
    return {
      regulation: nReg,
      extras: extras,
      widths: widths,
      paneCount: nReg + extra,
      span: span
    };
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

  function otLength(sport) {
    if (sport === "nhl" || sport === "ncaah") return HOCKEY_PERIOD_SECONDS;
    if (sport === "nba") return NBA_OT_SECONDS;
    if (sport === "ncaab") return NCAAB_OT_SECONDS;
    if (sport === "nfl") return NFL_OT_SECONDS;
    return 0;
  }

  function clockFraction(frame, length) {
    var remaining = Number(frame.seconds_remaining_period);
    if (!isFinite(remaining)) remaining = length;
    if (remaining < 0) remaining = 0;
    if (remaining > length) remaining = length;
    if (!(length > 0)) return 0;
    return (length - remaining) / length;
  }

  function untimedExtraFraction(frame, rows, sport, ordinal) {
    var group = [];
    var i;
    for (i = 0; i < rows.length; i++) {
      if (!frameIsOvertime(rows[i], sport)) continue;
      if (extraOrdinal(rows[i], sport) !== ordinal) continue;
      group.push(rows[i]);
    }
    if (group.length <= 1) return 0.5;
    var idx = group.indexOf(frame);
    if (idx < 0) idx = 0;
    return (idx + 1) / (group.length + 1);
  }

  function paneStart(layout, sport, slot) {
    var nReg = layout && layout.regulation ? layout.regulation : regulationCount(sport);
    var start = 0;
    var i;
    var count = nReg + slot;
    if (layout && layout.widths && layout.widths.length) {
      for (i = 0; i < count && i < layout.widths.length; i++) start += layout.widths[i];
      return start;
    }
    return nReg + slot;
  }

  function bandPosition(frame, rows, layout, sport) {
    var nReg = layout && layout.regulation ? layout.regulation : regulationCount(sport);
    if (!frameIsOvertime(frame, sport)) return regulationPosition(frame, sport);
    var ordinal = extraOrdinal(frame, sport);
    if (ordinal < 1) ordinal = 1;
    var extras = layout && layout.extras && layout.extras.length ? layout.extras : [ordinal];
    var slot = extras.indexOf(ordinal);
    if (slot < 0) slot = 0;
    var length = otLength(sport);
    var frac = length > 0
      ? clockFraction(frame, length)
      : untimedExtraFraction(frame, rows, sport, ordinal);
    var width = layout && layout.widths ? layout.widths[nReg + slot] : 1;
    if (!(width > 0)) width = 0;
    if (frac > width) frac = width;
    return paneStart(layout, sport, slot) + frac;
  }

  function extraOrdinal(frame, sport) {
    var fromClock = 0;
    var match = String(frame && frame.clock || "").match(/(?:^|[^A-Za-z0-9])(\d*)OT\b/);
    if (match) fromClock = match[1] ? Number(match[1]) : 1;
    var fromPeriod = 0;
    var period = Number(frame && frame.period);
    if (period > regulationCount(sport)) fromPeriod = period - regulationCount(sport);
    var status = String(frame && frame.status || "").trim().toLowerCase();
    var fromStatus = (status === "ot" || status === "overtime") ? 1 : 0;
    var n = fromClock;
    if (fromPeriod > n) n = fromPeriod;
    if (fromStatus > n) n = fromStatus;
    return n;
  }

  function paneName(ordinal) {
    var n = Number(ordinal);
    if (n <= 1) return "OT";
    return String(n) + "OT";
  }

  function overtimeLabel(rows, sport) {
    var highest = maxExtraOrdinal(rows, sport);
    if (highest <= 0) return "";
    return paneName(highest);
  }

  function axisLabels(rows, sport, layout) {
    var labels = [];
    var nReg = layout && layout.regulation ? layout.regulation : regulationCount(sport);
    var widths = layout && layout.widths ? layout.widths : null;
    var cursor = 0;
    var bi;
    for (bi = 0; bi < nReg; bi++) {
      var width = widths ? widths[bi] : 1;
      var text = (sport === "nhl" || sport === "ncaah")
        ? "P" + (bi + 1)
        : sport === "ncaab"
          ? "H" + (bi + 1)
          : "Q" + (bi + 1);
      labels.push({ at: cursor + width / 2, text: text });
      cursor += width;
    }
    var extras = layout && layout.extras ? layout.extras : [];
    var ei;
    for (ei = 0; ei < extras.length; ei++) {
      var extraWidth = widths ? widths[nReg + ei] : 1;
      labels.push({ at: cursor + extraWidth / 2, text: paneName(extras[ei]) });
      cursor += extraWidth;
    }
    return labels;
  }

  root.mswpBands = {
    QUARTER_SECONDS: QUARTER_SECONDS,
    NFL_OT_SECONDS: NFL_OT_SECONDS,
    HOCKEY_PERIOD_SECONDS: HOCKEY_PERIOD_SECONDS,
    frameIsOvertime: frameIsOvertime,
    layoutBands: layoutBands,
    bandPosition: bandPosition,
    paneName: paneName,
    overtimeLabel: overtimeLabel,
    axisLabels: axisLabels
  };

  // Light golds count as near-white on the off-white page. Swatch dedup stays
  // stricter so Gold, Silver, and White remain separate tiles.
  var LIGHT_LUMINANCE = 0.35;
  var DARK_LUMINANCE = 0.03;
  var PANEL_CONTRAST_MIN = 1.2;
  var SWATCH_NAMES = {
    "#0B2265": "Navy",
    "#A71930": "Red",
    "#FB4F14": "Orange",
    "#002244": "Navy",
    "#FF4C00": "Orange",
    "#041E42": "Navy",
    "#6F263D": "Burgundy",
    "#236192": "Blue",
    "#0E2240": "Navy",
    "#FEC524": "Gold",
    "#552583": "Purple",
    "#FDB927": "Gold",
    "#CFB87C": "Gold",
    "#A2A4A3": "Silver",
    "#FFFFFF": "White",
    "#000000": "Black",
    "#CC0000": "Red",
    "#FFCB05": "Maize",
    "#00274C": "Blue",
    "#8B2332": "Crimson",
    "#C24E1C": "Orange",
    "#0021A5": "Blue",
    "#FA4616": "Orange"
  };

  function normalizeHex(value) {
    if (typeof value !== "string") return null;
    var hex = value.trim().toUpperCase();
    if (!hex) return null;
    if (hex.charAt(0) !== "#") hex = "#" + hex;
    if (/^#[0-9A-F]{3}$/.test(hex)) {
      hex = "#" + hex.charAt(1) + hex.charAt(1) +
        hex.charAt(2) + hex.charAt(2) +
        hex.charAt(3) + hex.charAt(3);
    }
    if (!/^#[0-9A-F]{6}$/.test(hex)) return null;
    return hex;
  }

  function rgbOf(hex) {
    var n = parseInt(hex.slice(1), 16);
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
  }

  function linearChannel(value) {
    var channel = value / 255;
    if (channel <= 0.04045) return channel / 12.92;
    return Math.pow((channel + 0.055) / 1.055, 2.4);
  }

  function luminance(hex) {
    var color = rgbOf(hex);
    return 0.2126 * linearChannel(color.r) +
      0.7152 * linearChannel(color.g) +
      0.0722 * linearChannel(color.b);
  }

  function contrast(a, b) {
    var left = luminance(a);
    var right = luminance(b);
    var hi = left > right ? left : right;
    var lo = left > right ? right : left;
    return (hi + 0.05) / (lo + 0.05);
  }

  function isLight(hex) {
    return luminance(hex) >= LIGHT_LUMINANCE;
  }

  function isDark(hex) {
    return luminance(hex) <= DARK_LUMINANCE;
  }

  function isStrictNearWhite(hex) {
    var color = rgbOf(hex);
    return color.r >= 236 && color.g >= 236 && color.b >= 236;
  }

  function isStrictNearBlack(hex) {
    var color = rgbOf(hex);
    return color.r <= 28 && color.g <= 28 && color.b <= 28;
  }

  function panelHex(theme) {
    return theme === "offwhite" ? "#F7F7F7" : "#262626";
  }

  function tooClose(hex, panel) {
    return contrast(hex, panel) < PANEL_CONTRAST_MIN;
  }

  function inkFor(fill) {
    var dark = "#1A1A1A";
    var light = "#F2F2F2";
    if (!fill) return light;
    return contrast(fill, dark) >= contrast(fill, light) ? dark : light;
  }

  function nearDuplicate(a, b) {
    if (a === b) return true;
    if (isStrictNearBlack(a) && isStrictNearBlack(b)) return true;
    if (isStrictNearWhite(a) && isStrictNearWhite(b)) return true;
    return false;
  }

  function swatchName(hex) {
    if (SWATCH_NAMES[hex]) return SWATCH_NAMES[hex];
    if (isStrictNearWhite(hex)) return "White";
    if (isStrictNearBlack(hex)) return "Black";
    var color = rgbOf(hex);
    var max = Math.max(color.r, color.g, color.b);
    var min = Math.min(color.r, color.g, color.b);
    if (max - min < 16) return "Gray";
    var hue;
    var span = max - min;
    if (max === color.r) hue = ((color.g - color.b) / span) % 6;
    else if (max === color.g) hue = (color.b - color.r) / span + 2;
    else hue = (color.r - color.g) / span + 4;
    hue *= 60;
    if (hue < 0) hue += 360;
    if (hue < 20 || hue >= 345) return "Red";
    if (hue < 45) return "Orange";
    if (hue < 70) return "Gold";
    if (hue < 160) return "Green";
    if (hue < 250) return "Blue";
    if (hue < 290) return "Purple";
    return "Red";
  }

  var COLOR_SPORTS = ["nfl", "nhl", "nba", "ncaaf", "ncaah", "ncaab"];

  function clubStem(row) {
    if (!row || typeof row !== "object") return "";
    if (typeof row.abbreviation === "string" && row.abbreviation.trim()) {
      return row.abbreviation.trim();
    }
    if (row.id != null && String(row.id).trim()) return String(row.id).trim();
    return "";
  }

  function normalizeClub(row, sport) {
    var stem = clubStem(row);
    var aliases = row && Array.isArray(row.aliases) ? row.aliases : [];
    var source = row && (row.source || row.color_source) ? (row.source || row.color_source) : null;
    return {
      sport: String(sport || (row && row.sport) || "").toLowerCase(),
      id: stem,
      aliases: aliases,
      primary: row && row.primary ? row.primary : null,
      secondary: row && row.secondary ? row.secondary : null,
      white: row && row.white ? row.white : null,
      black: row && row.black ? row.black : null,
      source: source,
      as_of: row && row.as_of ? row.as_of : null
    };
  }

  function sportHasColors(sport) {
    var rows = root.MSWP_COLORS || [];
    var key = String(sport || "").toLowerCase();
    var i;
    for (i = 0; i < rows.length; i++) {
      if (String(rows[i].sport).toLowerCase() === key) return true;
    }
    return false;
  }

  function ingestColors(sport, rows) {
    var key = String(sport || "").toLowerCase();
    var next = [];
    var existing = root.MSWP_COLORS || [];
    var i;
    if (!Array.isArray(rows)) return;
    for (i = 0; i < existing.length; i++) {
      if (String(existing[i].sport).toLowerCase() !== key) next.push(existing[i]);
    }
    for (i = 0; i < rows.length; i++) {
      var club = normalizeClub(rows[i], key);
      if (!club.id) continue;
      next.push(club);
    }
    root.MSWP_COLORS = next;
  }

  function findClub(sport, name) {
    var rows = root.MSWP_COLORS || [];
    var key = String(name || "").trim().toUpperCase();
    var i;
    var aliases;
    var a;
    for (i = 0; i < rows.length; i++) {
      if (String(rows[i].sport).toLowerCase() !== String(sport || "").toLowerCase()) continue;
      if (String(rows[i].id).toUpperCase() === key) return rows[i];
      aliases = rows[i].aliases || [];
      for (a = 0; a < aliases.length; a++) {
        if (String(aliases[a]).toUpperCase() === key) return rows[i];
      }
    }
    return null;
  }

  root.mswpColors = {
    ingest: ingestColors,
    normalizeClub: normalizeClub,
    sportHasColors: sportHasColors
  };

  function buildSwatches(club) {
    var list = [];
    function hasNear(hex) {
      var i;
      for (i = 0; i < list.length; i++) {
        if (nearDuplicate(list[i].hex, hex)) return true;
      }
      return false;
    }
    function push(hex) {
      list.push({ hex: hex, name: swatchName(hex) });
    }
    if (!club) return list;
    var primary = normalizeHex(club.primary);
    var secondary = normalizeHex(club.secondary);
    if (primary) push(primary);
    if (secondary && !hasNear(secondary)) push(secondary);
    var white = normalizeHex(club.white);
    if (white && !hasNear(white)) push(white);
    var black = normalizeHex(club.black);
    if (black && !hasNear(black)) push(black);
    return list;
  }

  function resolutionOrder(club, theme) {
    var present = {};
    var swatches = buildSwatches(club);
    var i;
    for (i = 0; i < swatches.length; i++) present[swatches[i].hex] = true;
    var prefs = [club && club.primary, club && club.secondary];
    if (theme === "offwhite") {
      var black = normalizeHex(club && club.black);
      if (black) prefs.push(black);
    }
    prefs.push(club && club.white);
    var order = [];
    for (i = 0; i < prefs.length; i++) {
      var hex = normalizeHex(prefs[i]);
      if (!hex || !present[hex] || order.indexOf(hex) !== -1) continue;
      order.push(hex);
    }
    return order;
  }

  function pairOk(away, home, theme) {
    var panel = panelHex(theme);
    if (!away || !home) return false;
    if (away === home) return false;
    if (theme === "charcoal" && isDark(away) && isDark(home)) return false;
    if (theme === "offwhite" && isLight(away) && isLight(home)) return false;
    if (tooClose(away, panel) || tooClose(home, panel)) return false;
    return true;
  }

  function acceptable(candidate, locked, theme) {
    if (!candidate || !locked) return false;
    if (candidate === locked) return false;
    if (theme === "charcoal" && isDark(candidate) && isDark(locked)) return false;
    if (theme === "offwhite" && isLight(candidate) && isLight(locked)) return false;
    if (tooClose(candidate, panelHex(theme))) return false;
    return true;
  }

  function firstMatching(club, theme, locked, test) {
    var order = resolutionOrder(club, theme);
    var i;
    for (i = 0; i < order.length; i++) {
      if (test(order[i], locked, theme)) return order[i];
    }
    return null;
  }

  function repairPair(awayClub, homeClub, theme, away, home, keepSide) {
    if (pairOk(away, home, theme)) return { away: away, home: home };
    if (keepSide === "away") {
      return {
        away: away,
        home: firstMatching(homeClub, theme, away, acceptable) || home
      };
    }
    if (keepSide === "home") {
      return {
        away: firstMatching(awayClub, theme, home, acceptable) || away,
        home: home
      };
    }
    var panel = panelHex(theme);
    var awayClose = !!away && tooClose(away, panel);
    var homeClose = !!home && tooClose(home, panel);
    var moved;
    if (awayClose && !homeClose) {
      moved = firstMatching(awayClub, theme, home, pairOk);
      if (moved) return { away: moved, home: home };
    }
    if (homeClose && !awayClose) {
      moved = firstMatching(homeClub, theme, away, pairOk);
      if (moved) return { away: away, home: moved };
    }
    moved = firstMatching(awayClub, theme, home, pairOk);
    if (moved) return { away: moved, home: home };
    moved = firstMatching(homeClub, theme, away, pairOk);
    if (moved) return { away: away, home: moved };
    moved = firstMatching(awayClub, theme, home, acceptable);
    if (moved) return { away: moved, home: home };
    moved = firstMatching(homeClub, theme, away, acceptable);
    if (moved) return { away: away, home: moved };
    return { away: away, home: home };
  }

  function resolveDefaults(awayClub, homeClub, theme) {
    var awayOrder = resolutionOrder(awayClub, theme);
    var homeOrder = resolutionOrder(homeClub, theme);
    return repairPair(
      awayClub,
      homeClub,
      theme,
      awayOrder[0] || null,
      homeOrder[0] || null,
      null
    );
  }

  function resolveChange(awayClub, homeClub, theme, awayHex, homeHex, keepSide, nextHex) {
    var away = normalizeHex(awayHex);
    var home = normalizeHex(homeHex);
    if (keepSide === "away") away = normalizeHex(nextHex);
    if (keepSide === "home") home = normalizeHex(nextHex);
    return repairPair(awayClub, homeClub, theme, away, home, keepSide);
  }

  function restorePair(awayClub, homeClub, theme, savedAway, savedHome) {
    var awayList = buildSwatches(awayClub);
    var homeList = buildSwatches(homeClub);
    function known(list, hex) {
      var normalized = normalizeHex(hex);
      var i;
      if (!normalized) return null;
      for (i = 0; i < list.length; i++) {
        if (list[i].hex === normalized) return normalized;
      }
      return null;
    }
    var away = known(awayList, savedAway);
    var home = known(homeList, savedHome);
    if (!away || !home) return resolveDefaults(awayClub, homeClub, theme);
    return { away: away, home: home };
  }

  function swatchesForTheme(saved, theme) {
    if (!saved || (theme !== "charcoal" && theme !== "offwhite")) return null;
    var nested = saved[theme];
    if (nested && typeof nested === "object" && nested.awaySwatch && nested.homeSwatch) {
      return { homeSwatch: nested.homeSwatch, awaySwatch: nested.awaySwatch };
    }
    if (!saved.charcoal && !saved.offwhite && saved.awaySwatch && saved.homeSwatch) {
      return { homeSwatch: saved.homeSwatch, awaySwatch: saved.awaySwatch };
    }
    return null;
  }

  function appearanceRecord(existing, theme, away, home) {
    var record = {};
    function copyNested(name) {
      var slot = existing && existing[name];
      if (!slot || typeof slot !== "object" || !slot.awaySwatch || !slot.homeSwatch) return;
      record[name] = { homeSwatch: slot.homeSwatch, awaySwatch: slot.awaySwatch };
    }
    copyNested("charcoal");
    copyNested("offwhite");
    if (theme === "charcoal" || theme === "offwhite") {
      record[theme] = { homeSwatch: home, awaySwatch: away };
    }
    return record;
  }

  root.mswpAppearance = {
    normalizeHex: normalizeHex,
    buildSwatches: buildSwatches,
    resolutionOrder: resolutionOrder,
    resolveDefaults: resolveDefaults,
    resolveChange: resolveChange,
    restorePair: restorePair,
    swatchesForTheme: swatchesForTheme,
    appearanceRecord: appearanceRecord,
    findClub: findClub,
    inkFor: inkFor
  };

  var BADGE_TEXT = "V4";
  var SPORT_ORDER = ["nfl", "nhl", "nba", "ncaaf", "ncaah", "ncaab"];
  var PRO_SPORTS = SPORT_ORDER.slice(0, 3);
  var COLLEGE_SPORTS = SPORT_ORDER.slice(3);

  function levelForSport(sport) {
    if (PRO_SPORTS.indexOf(sport) >= 0) return "pro";
    if (COLLEGE_SPORTS.indexOf(sport) >= 0) return "college";
    return "";
  }

  function sportsForLevel(level) {
    return level === "college" ? COLLEGE_SPORTS : PRO_SPORTS;
  }

  // Either side named Harbor is the nfl_sample prototype. It stays out of
  // the game buttons. The replay file itself can still be opened.
  function listedGame(entry) {
    var home = String(entry && entry.home || "").trim().toLowerCase();
    var away = String(entry && entry.away || "").trim().toLowerCase();
    return home !== "harbor" && away !== "harbor";
  }

  function gamesForSport(entries, sport) {
    var out = [];
    var i;
    if (!entries) return out;
    for (i = 0; i < entries.length; i++) {
      if (entries[i].sport === sport && listedGame(entries[i])) out.push(entries[i]);
    }
    return out;
  }

  function gamesForLevel(entries, level) {
    var out = [];
    var i;
    if (!entries) return out;
    for (i = 0; i < entries.length; i++) {
      if (levelForSport(entries[i].sport) === level && listedGame(entries[i])) out.push(entries[i]);
    }
    return out;
  }

  function bindingName(sport) {
    if (sport === "nfl") return "NFL_REPLAY";
    if (sport === "ncaaf") return "NCAAF_REPLAY";
    if (sport === "nhl") return "NHL_REPLAY";
    if (sport === "ncaah") return "NCAAH_REPLAY";
    if (sport === "nba") return "NBA_REPLAY";
    if (sport === "ncaab") return "NCAAB_REPLAY";
    return "";
  }

  function readSportFrames(scope, sport) {
    var name = bindingName(sport);
    if (!name || !scope) return null;
    var rows = scope[name];
    if (!Array.isArray(rows) || rows.length === 0) return null;
    return rows;
  }

  root.MSWP_BADGE = BADGE_TEXT;
  root.mswpPicker = {
    levelForSport: levelForSport,
    sportsForLevel: sportsForLevel,
    gamesForSport: gamesForSport,
    gamesForLevel: gamesForLevel,
    bindingName: bindingName,
    readSportFrames: readSportFrames
  };

  if (!root.document || !root.document.getElementById) return;

  var badge = document.getElementById("badge");
  if (badge) badge.textContent = BADGE_TEXT;

  var manifest = Array.isArray(root.MSWP_MANIFEST) ? root.MSWP_MANIFEST.slice() : [];
  var frames = [];
  var sportName = "nfl";
  var currentFile = "";
  var levelName = "pro";
  var themeName = "charcoal";
  var awaySwatch = null;
  var homeSwatch = null;
  var loadToken = 0;
  var frameCache = {};
  var colorLoads = {};
  var liveFrames = null;
  var liveSport = "";
  var liveAway = "";
  var liveHome = "";
  var liveHidden = true;
  var liveMissing = false;
  var viewingLive = false;
  var preferLive = false;
  var liveGameId = "";
  var livePollSerial = 0;
  var liveSettled = false;
  var slateRows = [];
  var slateReady = false;
  var slateSettled = false;
  var slatePollSerial = 0;
  var viewingBoard = false;
  var boardRow = null;
  var preferId = "";
  var queryOwned = false;
  var collegeBoot = false;
  var followBlocked = false;
  var followWant = null;
  var followSettled = false;
  var LIVE_POLL_MS = 15000;
  var stage = document.getElementById("stage");
  if (!manifest.length) {
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

  function formatPriorText(prior, away, home) {
    var pregame = Number(prior);
    if (!isFinite(pregame)) pregame = 0.5;
    var pregameHome = pregame > 0.5;
    var pregameName = pregameHome ? home : away;
    var pregamePct = (pregameHome ? pregame : 1 - pregame) * 100;
    return "Pregame " + pregameName + " " + pregamePct.toFixed(2) + "%";
  }

  function writePrior() {
    document.getElementById("prior").textContent = formatPriorText(
      frames[0].prior_home,
      frames[0].away,
      frames[0].home
    );
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

  function applyTeamColors() {
    var docRoot = document.documentElement;
    function paint(fillName, inkName, value) {
      if (value) {
        docRoot.style.setProperty(fillName, value);
        docRoot.style.setProperty(inkName, inkFor(value));
      } else {
        docRoot.style.removeProperty(fillName);
        docRoot.style.removeProperty(inkName);
      }
    }
    paint("--home", "--home-ink", homeSwatch);
    paint("--away", "--away-ink", awaySwatch);
  }

  function clubForSide(side) {
    var frame = frames[0];
    var name = frame[side];
    var found = findClub(sportName, name);
    if (found) return found;
    var painted = side === "home" ? frame.home_color : frame.away_color;
    return {
      sport: sportName,
      id: name,
      aliases: [],
      primary: painted || (side === "home" ? "#1f8f86" : "#c94b32"),
      secondary: null,
      white: "#FFFFFF",
      black: null
    };
  }

  function storageKey() {
    return "mswp:" + sportName + ":" + frames[0].away + ":" + frames[0].home;
  }

  function readAppearance() {
    try {
      var raw = localStorage.getItem(storageKey());
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return null;
      return parsed;
    } catch (err) {
      return null;
    }
  }

  function writeTheme() {
    try {
      localStorage.setItem("mswp:theme", themeName);
    } catch (err) {}
  }

  function writeAppearance() {
    if (!frames.length || viewingBoard) return;
    try {
      var record = appearanceRecord(readAppearance(), themeName, awaySwatch, homeSwatch);
      localStorage.setItem(storageKey(), JSON.stringify(record));
    } catch (err) {}
  }

  function renderSwatchRow(id, club, selected) {
    var row = document.getElementById(id);
    var swatches = buildSwatches(club);
    var i;
    row.textContent = "";
    for (i = 0; i < swatches.length; i++) {
      var swatch = swatches[i];
      var button = document.createElement("button");
      var mark = document.createElement("span");
      button.type = "button";
      button.className = "swatch";
      button.setAttribute("data-hex", swatch.hex);
      button.setAttribute("aria-label", swatch.name);
      button.setAttribute("title", swatch.name);
      button.setAttribute("aria-pressed", swatch.hex === selected ? "true" : "false");
      button.style.background = swatch.hex;
      button.style.color = inkFor(swatch.hex);
      mark.className = "swatch-check";
      mark.setAttribute("aria-hidden", "true");
      mark.textContent = "\u2713";
      button.appendChild(mark);
      row.appendChild(button);
    }
  }

  function renderAppearance() {
    document.documentElement.setAttribute("data-theme", themeName);
    document.getElementById("theme-dark").setAttribute(
      "aria-pressed",
      themeName === "charcoal" ? "true" : "false"
    );
    document.getElementById("theme-light").setAttribute(
      "aria-pressed",
      themeName === "offwhite" ? "true" : "false"
    );
    if (!frames.length) return;
    document.getElementById("away-swatch-label").textContent = "Away " + frames[0].away;
    document.getElementById("home-swatch-label").textContent = "Home " + frames[0].home;
    renderSwatchRow("away-swatches", clubForSide("away"), awaySwatch);
    renderSwatchRow("home-swatches", clubForSide("home"), homeSwatch);
    applyTeamColors();
  }

  function colorFile(sport) {
    return "assets/colors/" + sport + ".json";
  }

  function logoUrl(sport, abbr) {
    var sportKey = String(sport || "").trim().toLowerCase();
    var name = String(abbr == null ? "" : abbr).trim();
    if (COLOR_SPORTS.indexOf(sportKey) < 0 || !name) return "";
    if (name.indexOf("/") >= 0 || name.indexOf("\\") >= 0 || name.indexOf("..") >= 0) return "";
    return "assets/logos/" + sportKey + "/" + encodeURIComponent(name) + ".png";
  }

  function ensureColors(sport) {
    var key = String(sport || "").toLowerCase();
    if (COLOR_SPORTS.indexOf(key) < 0) return;
    if (colorLoads[key]) return;
    if (typeof root.fetch !== "function") return;
    colorLoads[key] = true;
    var pending;
    try {
      pending = root.fetch(colorFile(key), { cache: "no-store" });
    } catch (err) {
      colorLoads[key] = false;
      return;
    }
    Promise.resolve(pending).then(function (response) {
      if (!response || !response.ok || typeof response.json !== "function") return null;
      return response.json();
    }).then(function (rows) {
      if (!rows) return;
      ingestColors(key, rows);
      if (sportName === key && frames.length && !viewingBoard) loadMatchupAppearance();
    }).catch(function () {
      colorLoads[key] = false;
    });
  }

  function loadMatchupAppearance() {
    ensureColors(sportName);
    if (!frames.length) {
      renderAppearance();
      return;
    }
    var slot = swatchesForTheme(readAppearance(), themeName);
    var pair = slot
      ? restorePair(
        clubForSide("away"),
        clubForSide("home"),
        themeName,
        slot.awaySwatch,
        slot.homeSwatch
      )
      : resolveDefaults(clubForSide("away"), clubForSide("home"), themeName);
    awaySwatch = pair.away;
    homeSwatch = pair.home;
    renderAppearance();
  }

  function swatchHex(target) {
    var node = target;
    while (node && node !== document) {
      if (node.getAttribute && node.getAttribute("data-hex")) return node.getAttribute("data-hex");
      node = node.parentNode;
    }
    return null;
  }

  function chooseSwatch(side, hex) {
    if (!frames.length || viewingBoard) return;
    var resolved = resolveChange(
      clubForSide("away"),
      clubForSide("home"),
      themeName,
      awaySwatch,
      homeSwatch,
      side,
      hex
    );
    awaySwatch = resolved.away;
    homeSwatch = resolved.home;
    writeAppearance();
    renderAppearance();
    show(index);
  }

  function setTheme(next) {
    if (next !== "charcoal" && next !== "offwhite") return;
    if (next === themeName) return;
    writeAppearance();
    themeName = next;
    writeTheme();
    loadMatchupAppearance();
    show(index);
  }

  function show(nextIndex) {
    if (viewingBoard || !frames.length) return;
    index = nextIndex;
    var frame = frames[index];
    var homePct = formatHomePercent(frame);
    var awayPct = formatAwayPercent(frame);
    applyTeamColors();
    drawCharts(index);
    scrub.value = String(index);
    var clock = clockLabel(frame);
    text("position", clock);
    paintSituation(frame);

    text("c-clock", clock);
    text("c-score", frame.away + " " + frame.away_score + " – " + frame.home + " " + frame.home_score);
    text("c-wp", homePct + "%");
    paintTicker(frame);
    applyLogo("c-home-logo", frame.home_logo);
    applyLogo("c-away-logo", frame.away_logo);

    text("e-clock", clock);
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
    if (typeof path !== "string") path = "";
    if (!path) {
      img.hidden = true;
      img.removeAttribute("src");
      return;
    }
    if (img.getAttribute("src") === path) return;
    img.hidden = true;
    img.onerror = function () {
      if (img.getAttribute("src") !== path) return;
      img.hidden = true;
      img.removeAttribute("src");
    };
    img.onload = function () {
      if (img.getAttribute("src") === path) img.hidden = false;
    };
    img.setAttribute("src", path);
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

  function defaultEntry() {
    var nfl = gamesForSport(manifest, "nfl");
    if (nfl.length) return nfl[0];
    if (manifest.length) return manifest[0];
    return null;
  }

  function renderLevel() {
    var proButton = document.getElementById("level-pro");
    var collegeButton = document.getElementById("level-college");
    proButton.setAttribute("aria-pressed", levelName === "pro" ? "true" : "false");
    collegeButton.setAttribute("aria-pressed", levelName === "college" ? "true" : "false");
    proButton.classList.toggle("is-selected", levelName === "pro");
    collegeButton.classList.toggle("is-selected", levelName === "college");
  }

  function renderSports() {
    var row = document.getElementById("sports");
    var sports = sportsForLevel(levelName);
    var i;
    row.textContent = "";
    for (i = 0; i < sports.length; i++) {
      var sport = sports[i];
      var button = document.createElement("button");
      var on = sport === sportName && levelForSport(sportName) === levelName;
      button.type = "button";
      button.className = on ? "sport is-selected" : "sport";
      button.setAttribute("data-sport", sport);
      button.setAttribute("aria-pressed", on ? "true" : "false");
      button.textContent = sport.toUpperCase();
      row.appendChild(button);
    }
  }

  function hostAllowsLive() {
    var loc = root.location;
    if (!loc) return false;
    if (String(loc.protocol || "") === "file:") return false;
    var host = String(loc.hostname || "").toLowerCase();
    return host === "127.0.0.1" || host === "localhost";
  }

  function clockLabel(frame) {
    var clock = frame && frame.clock != null ? String(frame.clock) : "";
    var stale = String(frame && frame.status || "").toLowerCase() === "stale";
    if (viewingLive && liveMissing) stale = true;
    if (!stale) return clock;
    return clock + " STALE";
  }

  // The situation line is the current snapshot only. Pregame and final
  // stay blank. A snapshot that omitted these keys stays blank.
  function paintSituation(frame) {
    var line = situationLine(frame);
    var node = document.getElementById("situation");
    node.textContent = line;
    node.hidden = line === "";
  }

  function situationLine(frame) {
    if (!frame) return "";
    var status = String(frame.status || "").toLowerCase();
    if (status === "pre" || status === "final") return "";
    if (sportName === "nfl" || sportName === "ncaaf") return footballSituation(frame);
    if (sportName === "nhl" || sportName === "ncaah") return hockeySituation(frame);
    if (sportName === "nba" || sportName === "ncaab") return basketballSituation(frame);
    return "";
  }

  function fieldPresent(value) {
    return value !== undefined && value !== null && value !== "";
  }

  function footballSituation(frame) {
    if (
      !fieldPresent(frame.possession) ||
      !fieldPresent(frame.down) ||
      !fieldPresent(frame.distance) ||
      !fieldPresent(frame.yardline)
    ) {
      return "";
    }
    var name = possessingName(frame);
    if (!name) return "";
    var line = name + " ball, " + downOrdinal(frame.down) + " and " +
      frame.distance + ", yardline " + frame.yardline;
    var suffix = timeoutSuffix(frame);
    if (suffix) line += suffix;
    return line;
  }

  function possessingName(frame) {
    var token = String(frame.possession == null ? "" : frame.possession).trim();
    var lower = token.toLowerCase();
    if (lower === "away") return String(frame.away || "");
    if (lower === "home") return String(frame.home || "");
    return token;
  }

  function downOrdinal(down) {
    var n = Number(down);
    if (n === 1) return "1st";
    if (n === 2) return "2nd";
    if (n === 3) return "3rd";
    if (n === 4) return "4th";
    return String(down);
  }

  function timeoutSuffix(frame) {
    var timeouts = frame.timeouts;
    if (timeouts == null || typeof timeouts !== "object") return "";
    var awayCount = timeoutCount(timeouts, frame.away, "away");
    var homeCount = timeoutCount(timeouts, frame.home, "home");
    if (awayCount == null || homeCount == null) return "";
    return " \u00b7 " + frame.away + " " + awayCount + ", " + frame.home + " " + homeCount;
  }

  function timeoutCount(timeouts, abbr, side) {
    if (Object.prototype.hasOwnProperty.call(timeouts, abbr) && timeouts[abbr] != null) {
      return timeouts[abbr];
    }
    if (Object.prototype.hasOwnProperty.call(timeouts, side) && timeouts[side] != null) {
      return timeouts[side];
    }
    return null;
  }

  function hockeySituation(frame) {
    var strength = fieldPresent(frame.strength) ? String(frame.strength) : "";
    var extra = frame.extra_attacker === true;
    if (strength && extra) return strength + " \u00b7 extra attacker";
    if (strength) return strength;
    if (extra) return "extra attacker";
    return "";
  }

  function basketballSituation(frame) {
    if (!situationPresent(frame)) return "";
    var football = footballSituation(frame);
    if (football) return football;
    return hockeySituation(frame);
  }

  function situationPresent(frame) {
    return fieldPresent(frame.possession) ||
      fieldPresent(frame.down) ||
      fieldPresent(frame.distance) ||
      fieldPresent(frame.yardline) ||
      frame.timeouts != null ||
      fieldPresent(frame.strength) ||
      frame.extra_attacker != null;
  }

  function liveControlVisible() {
    return liveHidden === false &&
      !!liveFrames &&
      liveFrames.length > 0 &&
      liveSport === sportName &&
      levelForSport(sportName) === levelName;
  }

  // The live file still assigns the archive binding. Read it on a side
  // window so that assignment cannot replace the loaded replay.
  function liveGameIdOf(rows) {
    var i;
    for (i = 0; i < rows.length; i++) {
      if (!rows[i] || rows[i].game_id == null) continue;
      var id = String(rows[i].game_id).trim();
      if (id) return id;
    }
    return "";
  }

  function describeLive(rows) {
    if (!Array.isArray(rows) || rows.length === 0) return null;
    var first = rows[0];
    if (!first || typeof first !== "object") return null;
    var sport = String(first.sport || "").trim();
    var away = String(first.away || "").trim();
    var home = String(first.home || "").trim();
    if (!sport || !away || !home) return null;
    return {
      rows: rows,
      sport: sport,
      away: away,
      home: home,
      gameId: liveGameIdOf(rows)
    };
  }

  function readAssignment(source) {
    if (source == null) return null;
    var text = String(source);
    if (!text.trim()) return null;
    var box = {};
    try {
      var run = new Function("window", text);
      run(box);
    } catch (err) {
      return null;
    }
    return box;
  }

  function readLiveAssignment(source) {
    var box = readAssignment(source);
    if (!box) return null;
    return describeLive(box.MSWP_LIVE);
  }

  function normalizeSlate(rows) {
    var out = [];
    var i;
    for (i = 0; i < rows.length; i++) {
      var row = rows[i];
      if (!row || typeof row !== "object") continue;
      var sport = String(row.sport || "").trim().toLowerCase();
      var gameId = String(row.game_id == null ? "" : row.game_id).trim();
      var away = String(row.away || "").trim();
      var home = String(row.home || "").trim();
      var status = String(row.status || "").trim().toLowerCase();
      var prior = Number(row.prior_home);
      if (PRO_SPORTS.indexOf(sport) < 0) continue;
      if (!gameId || !away || !home) continue;
      if (!isFinite(prior)) prior = 0.5;
      out.push({
        sport: sport,
        gameId: gameId,
        away: away,
        home: home,
        status: status,
        awayScore: row.away_score,
        homeScore: row.home_score,
        priorHome: prior
      });
    }
    return out;
  }

  function readSlateRows(source) {
    var box = readAssignment(source);
    if (!box || !Array.isArray(box.MSWP_SLATE)) return null;
    return normalizeSlate(box.MSWP_SLATE);
  }

  function findSlateRow(gameId) {
    var id = String(gameId == null ? "" : gameId).trim();
    var i;
    if (!id) return null;
    for (i = 0; i < slateRows.length; i++) {
      if (slateRows[i].gameId === id) return slateRows[i];
    }
    return null;
  }

  function slateRowsForSport(sport) {
    var out = [];
    var i;
    if (levelName !== "pro") return out;
    if (PRO_SPORTS.indexOf(sport) < 0) return out;
    for (i = 0; i < slateRows.length; i++) {
      if (slateRows[i].sport === sport) out.push(slateRows[i]);
    }
    return out;
  }

  function slateButtonLabel(row) {
    var label = row.away + " at " + row.home;
    if (row.status === "live" || row.status === "final" || row.status === "stale") {
      label += " " + row.awayScore + "-" + row.homeScore;
    }
    return label;
  }

  function slateButtonOn(row) {
    if (viewingBoard && boardRow && boardRow.gameId === row.gameId) return true;
    if (viewingLive && liveGameId && liveGameId === row.gameId) return true;
    return false;
  }

  function liveHasThisGame() {
    return !!(
      preferId &&
      liveGameId &&
      liveGameId === preferId &&
      liveFrames &&
      liveFrames.length &&
      !liveHidden
    );
  }

  function noteLiveMissing() {
    liveHidden = true;
    liveSettled = true;
    if (liveFrames && liveFrames.length) {
      liveMissing = true;
      if (viewingLive) show(index);
    }
    renderGames();
    resolvePreferredId();
  }

  function noteLiveEmpty() {
    liveHidden = true;
    liveSettled = true;
    renderGames();
    resolvePreferredId();
  }

  function installLive(parsed) {
    liveFrames = parsed.rows;
    liveSport = parsed.sport;
    liveAway = parsed.away;
    liveHome = parsed.home;
    liveGameId = parsed.gameId || "";
    liveHidden = false;
    liveMissing = false;
    liveSettled = true;
  }

  function applyLivePayload(parsed) {
    var wasOnLast = viewingLive && frames.length > 0 && index === frames.length - 1;
    var sameGame = viewingLive &&
      parsed.sport === liveSport &&
      parsed.away === liveAway &&
      parsed.home === liveHome;
    installLive(parsed);
    if (preferId && parsed.gameId === preferId) {
      preferId = "";
      preferLive = false;
      selectLive(false);
      return;
    }
    if (preferId) {
      resolvePreferredId();
      if (!viewingLive) renderGames();
      return;
    }
    if (preferLive) {
      preferLive = false;
      selectLive(false);
      return;
    }
    if (!viewingLive) {
      renderGames();
      return;
    }
    frames = liveFrames;
    scrub.max = String(frames.length - 1);
    if (!sameGame) {
      setPlaying(false);
      sportName = liveSport;
      if (levelForSport(sportName)) levelName = levelForSport(sportName);
      writePrior();
      loadMatchupAppearance();
      renderPicker();
      show(frames.length - 1);
      return;
    }
    if (wasOnLast) show(frames.length - 1);
    else {
      if (index > frames.length - 1) index = frames.length - 1;
      show(index);
    }
    renderGames();
  }

  function noteSlateMissing() {
    slateRows = [];
    slateReady = false;
    slateSettled = true;
    renderSlate();
    renderGames();
    resolvePreferredId();
    resolveFollowBoot();
  }

  function applySlateRows(rows) {
    slateRows = rows;
    slateReady = true;
    slateSettled = true;
    if (viewingBoard && boardRow) {
      var updated = findSlateRow(boardRow.gameId);
      if (updated) {
        boardRow = updated;
        paintBoard(updated);
      }
    }
    renderSlate();
    renderGames();
    resolvePreferredId();
    resolveFollowBoot();
  }

  function requestScript(fileName, serial) {
    var stem = fileName === "slate.js" ? "widget/slate.js?" : "widget/live_replay.js?";
    return root.fetch(stem + "t=" + Date.now() + "-" + serial, { cache: "no-store" });
  }

  // The click selects the row. This POST does not write a file. College
  // rows are not on the board, and this host is the only one that sends.
  function postFollow(row) {
    if (!hostAllowsLive() || typeof root.fetch !== "function") return;
    if (!row || PRO_SPORTS.indexOf(row.sport) < 0 || !row.gameId) return;
    var body = JSON.stringify({ sport: row.sport, game_id: row.gameId });
    try {
      var pending = root.fetch("/follow", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body,
        cache: "no-store"
      });
      if (pending && typeof pending.catch === "function") pending.catch(function () {});
    } catch (err) {}
  }

  function pollScript(fileName, onText, onMissing) {
    var pending;
    try {
      pending = requestScript(fileName, fileName === "slate.js" ? slatePollSerial : livePollSerial);
    } catch (err) {
      onMissing();
      return;
    }
    Promise.resolve(pending).then(function (response) {
      if (!response || !response.ok || typeof response.text !== "function") {
        onMissing();
        return null;
      }
      return response.text();
    }).then(function (text) {
      if (text == null) return;
      onText(text);
    }).catch(function () {
      onMissing();
    });
  }

  function pollLive() {
    if (!hostAllowsLive() || typeof root.fetch !== "function") return;
    livePollSerial += 1;
    pollScript("live_replay.js", function (text) {
      var parsed = readLiveAssignment(text);
      if (!parsed) {
        noteLiveEmpty();
        return;
      }
      applyLivePayload(parsed);
    }, noteLiveMissing);
  }

  function pollSlate() {
    if (!hostAllowsLive() || typeof root.fetch !== "function") return;
    slatePollSerial += 1;
    pollScript("slate.js", function (text) {
      var rows = readSlateRows(text);
      if (!rows) {
        noteSlateMissing();
        return;
      }
      applySlateRows(rows);
    }, noteSlateMissing);
  }

  // widget/follow.json is a static file on this host. One GET at boot.
  // A query string, a college page, and any other host skip it.
  function readFollowPayload(text) {
    var data;
    try {
      data = JSON.parse(String(text || ""));
    } catch (err) {
      return null;
    }
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    var sport = String(data.sport == null ? "" : data.sport).trim().toLowerCase();
    var gameId = String(data.game_id == null ? "" : data.game_id).trim();
    if (PRO_SPORTS.indexOf(sport) < 0 || !gameId) return null;
    return { sport: sport, gameId: gameId };
  }

  function findFollowRow(want) {
    var i;
    if (!want) return null;
    for (i = 0; i < slateRows.length; i++) {
      if (slateRows[i].sport === want.sport && slateRows[i].gameId === want.gameId) {
        return slateRows[i];
      }
    }
    return null;
  }

  // The archive game stays until this file names a pro slate row. The same
  // live path then draws charts, or the board card when the live file is
  // still on another game. Boot does not rewrite the URL.
  function resolveFollowBoot() {
    var row;
    if (queryOwned || followBlocked || collegeBoot || levelName === "college") return;
    if (!followSettled || !followWant) return;
    if (!slateSettled || !slateReady) return;
    row = findFollowRow(followWant);
    if (!row) {
      followWant = null;
      return;
    }
    if (viewingBoard && boardRow && boardRow.gameId === row.gameId) return;
    if (viewingLive && liveGameId === row.gameId) return;
    selectSlate(row, false);
  }

  function readFollowFile() {
    var pending;
    if (!hostAllowsLive() || typeof root.fetch !== "function") return;
    if (queryOwned || collegeBoot || levelName === "college") return;
    try {
      pending = root.fetch("widget/follow.json", { method: "GET", cache: "no-store" });
    } catch (err) {
      followSettled = true;
      return;
    }
    Promise.resolve(pending).then(function (response) {
      if (!response || !response.ok || typeof response.text !== "function") return null;
      return response.text();
    }).then(function (text) {
      followSettled = true;
      if (text == null) return;
      if (queryOwned || followBlocked || collegeBoot || levelName === "college") return;
      followWant = readFollowPayload(text);
      resolveFollowBoot();
    }).catch(function () {
      followSettled = true;
    });
  }

  function startHostPolls() {
    if (!hostAllowsLive() || typeof root.fetch !== "function") return;
    readFollowFile();
    pollLive();
    pollSlate();
    root.setInterval(function () {
      pollLive();
      pollSlate();
    }, LIVE_POLL_MS);
  }

  function showReplayChrome() {
    viewingBoard = false;
    document.getElementById("board").hidden = true;
    document.getElementById("charts").hidden = false;
    document.getElementById("stage").hidden = false;
    document.getElementById("transport").hidden = false;
  }

  function clearCharts() {
    clearSvg(document.getElementById("score-chart"));
    clearSvg(document.getElementById("wp-chart"));
  }

  function showBoardChrome() {
    viewingBoard = true;
    document.getElementById("board").hidden = false;
    document.getElementById("charts").hidden = true;
    document.getElementById("stage").hidden = true;
    document.getElementById("transport").hidden = true;
    clearCharts();
    var situation = document.getElementById("situation");
    situation.textContent = "";
    situation.hidden = true;
    text("position", "");
  }

  function paintBoard(row) {
    var prior = formatPriorText(row.priorHome, row.away, row.home);
    text("board-away", row.away);
    text("board-home", row.home);
    text("board-score", String(row.awayScore) + "-" + String(row.homeScore));
    text("board-status", row.status);
    text("board-prior", prior);
    text("prior", prior);
  }

  function showBoard(row, fromClick) {
    if (!row) return;
    var sameCard = viewingBoard && boardRow && boardRow.gameId === row.gameId;
    if (!sameCard) loadToken += 1;
    setPlaying(false);
    viewingLive = false;
    boardRow = row;
    sportName = row.sport;
    currentFile = "";
    if (levelForSport(sportName)) levelName = levelForSport(sportName);
    showBoardChrome();
    paintBoard(row);
    renderPicker();
    if (fromClick !== false) writeQuery(row.sport, row.away, row.home, false, row.gameId);
    // writeQuery clears the id. Keep it so a later live file with this
    // game uses the existing live path. Until then the board card stays.
    preferId = row.gameId;
  }

  function selectLive(fromClick) {
    if (!liveFrames || !liveFrames.length || liveHidden) return;
    preferLive = false;
    loadToken += 1;
    setPlaying(false);
    viewingLive = true;
    boardRow = null;
    showReplayChrome();
    sportName = liveSport;
    currentFile = "";
    frames = liveFrames;
    scrub.max = String(frames.length - 1);
    if (levelForSport(sportName)) levelName = levelForSport(sportName);
    writePrior();
    renderPicker();
    loadMatchupAppearance();
    show(frames.length - 1);
    if (fromClick !== false) writeQuery(liveSport, liveAway, liveHome, true, liveGameId);
  }

  function selectSlate(row, fromClick) {
    if (!row) return;
    if (
      liveGameId &&
      row.gameId === liveGameId &&
      liveFrames &&
      liveFrames.length &&
      !liveHidden
    ) {
      selectLive(fromClick);
      return;
    }
    showBoard(row, fromClick);
  }

  function resolvePreferredId() {
    var row;
    if (!preferId) return;
    if (liveHasThisGame()) {
      preferId = "";
      preferLive = false;
      selectLive(false);
      return;
    }
    row = findSlateRow(preferId);
    if (row && slateReady) {
      if (!viewingBoard || !boardRow || boardRow.gameId !== row.gameId) {
        showBoard(row, false);
      } else {
        boardRow = row;
        paintBoard(row);
      }
      return;
    }
    if (slateReady && liveSettled && !row) {
      preferId = "";
      preferLive = false;
      loadGame(defaultEntry());
    }
  }

  function renderSlate() {
    var row = document.getElementById("slate");
    var level = document.getElementById("slate-row");
    var rows = slateRowsForSport(sportName);
    var i;
    if (!row) return;
    row.textContent = "";
    if (level) level.hidden = rows.length === 0;
    for (i = 0; i < rows.length; i++) {
      var item = rows[i];
      var button = document.createElement("button");
      var on = slateButtonOn(item);
      button.type = "button";
      button.className = on ? "sport is-selected" : "sport";
      button.setAttribute("data-slate-id", item.gameId);
      button.setAttribute("aria-pressed", on ? "true" : "false");
      button.textContent = slateButtonLabel(item);
      row.appendChild(button);
    }
  }

  function renderGames() {
    var row = document.getElementById("games");
    var level = document.getElementById("game-row");
    var entries = gamesForSport(manifest, sportName);
    var onLevel = levelForSport(sportName) === levelName;
    var showSlate = slateRowsForSport(sportName).length > 0;
    var showArchive = onLevel && (entries.length > 1 || (showSlate && entries.length === 1));
    var showLive = liveControlVisible();
    var show = showArchive || showLive;
    var i;
    row.textContent = "";
    if (level) level.hidden = !show;
    if (!show) return;
    if (showArchive) {
      for (i = 0; i < entries.length; i++) {
        var entry = entries[i];
        var button = document.createElement("button");
        var on = !viewingLive && !viewingBoard && entry.file === currentFile;
        button.type = "button";
        button.className = on ? "sport is-selected" : "sport";
        button.setAttribute("data-file", entry.file);
        button.setAttribute("aria-pressed", on ? "true" : "false");
        button.textContent = entry.label;
        row.appendChild(button);
      }
    }
    if (showLive) {
      var liveButton = document.createElement("button");
      var liveOn = viewingLive;
      liveButton.type = "button";
      liveButton.className = liveOn ? "sport is-selected" : "sport";
      liveButton.setAttribute("data-live", "true");
      liveButton.setAttribute("aria-pressed", liveOn ? "true" : "false");
      liveButton.textContent = liveAway + " at " + liveHome;
      row.appendChild(liveButton);
    }
  }

  function renderPicker() {
    renderLevel();
    renderSports();
    renderSlate();
    renderGames();
  }

  function useFrames(entry, rows) {
    setPlaying(false);
    viewingLive = false;
    boardRow = null;
    showReplayChrome();
    sportName = entry && entry.sport ? entry.sport : sportName;
    currentFile = entry && entry.file ? entry.file : "";
    frames = rows;
    scrub.max = String(frames.length - 1);
    if (levelForSport(sportName)) levelName = levelForSport(sportName);
    writePrior();
    renderPicker();
    loadMatchupAppearance();
    show(openingIndex(frames));
  }

  function replaySrc(file) {
    var name = String(file || "");
    if (!name || name.indexOf("/") >= 0 || name.indexOf("\\") >= 0) return name;
    return "widget/" + name;
  }

  function loadGame(entry) {
    if (!entry || !entry.file) return;
    if (entry.file === currentFile && frames.length) {
      useFrames(entry, frames);
      return;
    }
    setPlaying(false);
    if (frameCache[entry.file]) {
      useFrames(entry, frameCache[entry.file]);
      return;
    }
    var token = ++loadToken;
    var script = document.createElement("script");
    script.src = replaySrc(entry.file);
    script.onload = function () {
      if (token !== loadToken) return;
      var rows = readSportFrames(root, entry.sport);
      if (!rows) return;
      frameCache[entry.file] = rows;
      useFrames(entry, rows);
    };
    document.body.appendChild(script);
  }

  playButton.addEventListener("click", function () {
    if (viewingBoard) return;
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
    if (viewingBoard) return;
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
    if (viewingBoard) return;
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

  function attrFrom(event, name) {
    var node = event.target;
    while (node && node !== document) {
      if (node.getAttribute && node.getAttribute(name)) return node.getAttribute(name);
      node = node.parentNode;
    }
    return "";
  }

  document.getElementById("level-pro").addEventListener("click", function () {
    levelName = "pro";
    renderPicker();
  });

  document.getElementById("level-college").addEventListener("click", function () {
    levelName = "college";
    followBlocked = true;
    renderPicker();
  });

  document.getElementById("sports").addEventListener("click", function (event) {
    var sport = attrFrom(event, "data-sport");
    if (!sport) return;
    var games = gamesForSport(manifest, sport);
    if (!games.length) return;
    followBlocked = true;
    writeQuery(games[0].sport, games[0].away, games[0].home, false);
    loadGame(games[0]);
  });

  document.getElementById("games").addEventListener("click", function (event) {
    if (attrFrom(event, "data-live")) {
      followBlocked = true;
      selectLive();
      return;
    }
    var file = attrFrom(event, "data-file");
    if (!file) return;
    var i;
    followBlocked = true;
    for (i = 0; i < manifest.length; i++) {
      if (manifest[i].file === file && listedGame(manifest[i])) {
        writeQuery(manifest[i].sport, manifest[i].away, manifest[i].home, false);
        loadGame(manifest[i]);
      }
    }
  });

  document.getElementById("slate").addEventListener("click", function (event) {
    var id = attrFrom(event, "data-slate-id");
    if (!id) return;
    var row = findSlateRow(id);
    if (!row) return;
    followBlocked = true;
    selectSlate(row);
    postFollow(row);
  });

  document.getElementById("theme-dark").addEventListener("click", function () {
    setTheme("charcoal");
  });

  document.getElementById("theme-light").addEventListener("click", function () {
    setTheme("offwhite");
  });

  document.getElementById("away-swatches").addEventListener("click", function (event) {
    var hex = swatchHex(event.target);
    if (hex) chooseSwatch("away", hex);
  });

  document.getElementById("home-swatches").addEventListener("click", function (event) {
    var hex = swatchHex(event.target);
    if (hex) chooseSwatch("home", hex);
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

  function isNearWhite(color) {
    var hex = normalizeHex(color);
    return !!hex && isStrictNearWhite(hex);
  }

  function capStroke(color) {
    if (themeName === "offwhite" && isNearWhite(color)) return cssVar("--ink");
    return cssVar("--card");
  }

  function appendSeriesPath(svg, attrs) {
    if (themeName === "offwhite" && isNearWhite(attrs.stroke)) {
      var edge = {};
      Object.keys(attrs).forEach(function (key) {
        edge[key] = attrs[key];
      });
      edge.stroke = cssVar("--ink");
      edge["stroke-width"] = "4";
      edge["data-edge"] = "ink";
      svg.appendChild(svgEl("path", edge));
    }
    svg.appendChild(svgEl("path", attrs));
  }

  function endCap(svg, x, y, color, line) {
    svg.appendChild(svgEl("circle", {
      cx: String(x),
      cy: String(y),
      r: "4.5",
      fill: color,
      stroke: capStroke(color),
      "stroke-width": "1",
      "data-series": "end-cap",
      "data-line": line
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
    if (viewingBoard) {
      clearCharts();
      return;
    }
    var layout = layoutBands(frames, sportName);
    var shown = frames.slice(0, currentIndex + 1);
    function xOf(frame) {
      return xAt(bandPosition(frame, frames, layout, sportName), layout.span);
    }
    var homeColor = cssVar("--home");
    var awayColor = cssVar("--away");
    var muted = cssVar("--muted");
    drawScore(shown, xOf, layout, homeColor, awayColor, muted);
    drawWinProbability(shown, xOf, layout, homeColor, awayColor, muted);
  }

  function drawBands(svg, layout, muted) {
    var span = layout.span;
    var labels = axisLabels(frames, sportName, layout);
    var widths = layout.widths || [];
    var cursor = 0;
    var i;
    for (i = 0; i < widths.length - 1; i++) {
      cursor += widths[i];
      var x = xAt(cursor, span);
      svg.appendChild(svgEl("line", {
        x1: String(x),
        x2: String(x),
        y1: String(plot.top),
        y2: String(plot.height - plot.bottom),
        stroke: muted,
        "stroke-width": "1",
        "stroke-dasharray": "2 3",
        "data-series": "period-rail",
        "data-band": labels[i + 1] ? labels[i + 1].text : ""
      }));
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

  function drawScore(shown, xOf, layout, homeColor, awayColor, muted) {
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
    stepSeries(svg, shown, xOf, scoreMax, "away_score", "away-score", awayColor);
    stepSeries(svg, shown, xOf, scoreMax, "home_score", "home-score", homeColor);
    var currentFrame = shown[shown.length - 1];
    drawLegendName(svg, plot.left + 6, plot.top + 14, awayColor, frames[0].away, "legend-away", String(currentFrame.away_score));
    drawLegendName(svg, plot.width - plot.right - 6, plot.top + 14, homeColor, frames[0].home, "legend-home", String(currentFrame.home_score), "end");
  }

  function stepSeries(svg, shown, xOf, scoreMax, field, series, color) {
    var d = "";
    var lastX = 0;
    var lastY = 0;
    if (!shown.length) return;
    shown.forEach(function (frame, i) {
      var x = xOf(frame);
      var y = yAt(frame[field], 0, scoreMax);
      lastX = x;
      lastY = y;
      d += i === 0 ? "M " + x + " " + y : " H " + x + " V " + y;
    });
    appendSeriesPath(svg, {
      d: d,
      fill: "none",
      stroke: color,
      "stroke-width": "2",
      "stroke-linejoin": "round",
      "data-series": series
    });
    endCap(svg, lastX, lastY, color, series);
  }

  function drawWinProbability(shown, xOf, layout, homeColor, awayColor, muted) {
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
        appendSeriesPath(svg, {
          d: "M " + piece.x0 + " " + y0 + " L " + piece.x1 + " " + y1,
          fill: "none",
          stroke: colors[piece.tone],
          "stroke-width": "2",
          "data-series": "wp-line",
          "data-tone": piece.tone
        });
      });
    }
    var current = points[points.length - 1];
    endCap(svg, current.x, yAtLow(current.p, 0, 1), colors[sideOf(current.p)], "wp");
    var currentFrame = shown[shown.length - 1];
    drawLegendName(svg, plot.left + 6, plot.top + 14, awayColor, frames[0].away, "legend-away", formatAwayPercent(currentFrame) + "%");
    drawLegendName(svg, plot.width - plot.right - 6, plot.height - plot.bottom - 4, homeColor, frames[0].home, "legend-home", formatHomePercent(currentFrame) + "%", "end");
  }

  var initialTheme = document.documentElement.getAttribute("data-theme");
  if (initialTheme === "offwhite" || initialTheme === "charcoal") themeName = initialTheme;

  function presetSport() {
    var found = "";
    var i;
    for (i = 0; i < SPORT_ORDER.length; i++) {
      if (!readSportFrames(root, SPORT_ORDER[i])) continue;
      if (found) return "";
      found = SPORT_ORDER[i];
    }
    return found;
  }

  function decodePart(value) {
    var text = String(value == null ? "" : value).replace(/\+/g, " ");
    try {
      return decodeURIComponent(text);
    } catch (err) {
      return text;
    }
  }

  function readQuery() {
    var loc = root.location;
    var search = loc && loc.search != null ? String(loc.search) : "";
    if (search.charAt(0) === "?") search = search.slice(1);
    var out = {};
    if (!search) return out;
    var parts = search.split("&");
    var i;
    for (i = 0; i < parts.length; i++) {
      if (!parts[i]) continue;
      var eq = parts[i].indexOf("=");
      var rawKey = eq < 0 ? parts[i] : parts[i].slice(0, eq);
      var rawValue = eq < 0 ? "" : parts[i].slice(eq + 1);
      out[decodePart(rawKey)] = decodePart(rawValue);
    }
    return out;
  }

  function gameSlug(away, home) {
    return String(away == null ? "" : away).trim().toLowerCase() + "-" +
      String(home == null ? "" : home).trim().toLowerCase();
  }

  // sport is one of the six ids. game is away-home for that sport.
  // A missing or unknown pair falls back to the ordinary default.
  function entryFromQuery(params) {
    var hasSport = Object.prototype.hasOwnProperty.call(params, "sport");
    var hasGame = Object.prototype.hasOwnProperty.call(params, "game");
    if (!hasSport && !hasGame) return { kind: "absent" };
    var sport = String(params.sport == null ? "" : params.sport).trim().toLowerCase();
    var game = String(params.game == null ? "" : params.game).trim().toLowerCase();
    if (SPORT_ORDER.indexOf(sport) < 0 || !game) return { kind: "fallback" };
    var games = gamesForSport(manifest, sport);
    var i;
    for (i = 0; i < games.length; i++) {
      if (gameSlug(games[i].away, games[i].home) === game) {
        return { kind: "match", entry: games[i] };
      }
    }
    return { kind: "fallback" };
  }

  function writeQuery(sport, away, home, live, slateId) {
    preferLive = false;
    preferId = "";
    var history = root.history;
    if (!history || typeof history.replaceState !== "function") return;
    var loc = root.location || {};
    var path = loc.pathname != null ? String(loc.pathname) : "";
    var hash = loc.hash != null ? String(loc.hash) : "";
    var query = "?sport=" + encodeURIComponent(String(sport || "").trim().toLowerCase()) +
      "&game=" + encodeURIComponent(gameSlug(away, home));
    if (live) query += "&live=1";
    if (slateId) query += "&id=" + encodeURIComponent(String(slateId));
    try {
      history.replaceState(null, "", path + query + hash);
    } catch (err) {}
  }

  function bootFromQuery() {
    var params = readQuery();
    var requested = entryFromQuery(params);
    var requestedId = String(params.id == null ? "" : params.id).trim();
    var liveAsked = String(params.live == null ? "" : params.live).trim() === "1";
    var preset = presetSport();
    // A query string wins, so this boot does not read follow.json for it.
    queryOwned = !!(
      requestedId ||
      liveAsked ||
      requested.kind === "match" ||
      requested.kind === "fallback"
    );
    collegeBoot = (requested.kind === "match" && levelForSport(requested.entry.sport) === "college") ||
      (!queryOwned && levelForSport(preset) === "college");
    // live=1 is ignored unless this host is the one that serves the file.
    preferLive = liveAsked && hostAllowsLive();
    if (requestedId && !hostAllowsLive()) {
      loadGame(defaultEntry());
      return;
    }
    if (requestedId && hostAllowsLive()) {
      preferId = requestedId;
      var seededForId = describeLive(root.MSWP_LIVE);
      if (seededForId && seededForId.gameId === requestedId) {
        installLive(seededForId);
        preferId = "";
        preferLive = false;
        selectLive(false);
        return;
      }
    }
    if (preferLive && !preferId) {
      var seeded = describeLive(root.MSWP_LIVE);
      if (seeded) {
        installLive(seeded);
        selectLive(false);
        return;
      }
    }
    if (requested.kind === "match") {
      loadGame(requested.entry);
      return;
    }
    if (requested.kind === "fallback") {
      loadGame(defaultEntry());
      return;
    }
    if (preset) {
      useFrames({ sport: preset, file: "" }, readSportFrames(root, preset));
      return;
    }
    loadGame(defaultEntry());
  }

  renderPicker();
  bootFromQuery();
  startHostPolls();
})(typeof window !== "undefined" ? window : this);
