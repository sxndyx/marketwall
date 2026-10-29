"use strict";
/* Market Wall: rotating seasonality / trend / news display.
   URL options: ?view=overview|heatmap|focus|almanac|longterm|news|actions|model  (pin one view)
                ?group=energy (with view=focus)  ?dwell=25 (seconds per view)
                ?theme=dark|light|auto  ?colors=classic (green/red instead of blue/red)
   Keys: ← → step, space pause, 1-9 and 0 jump to a view, f fullscreen. */

const $ = (s, r = document) => r.querySelector(s);
const params = new URLSearchParams(location.search);
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const DWELL = Math.max(5, +params.get("dwell") || 25);
const VIEW_NAMES = {
  overview: "Overview", sentiment: "Market sentiment", events: "News & events radar", heatmap: "Seasonality map",
  focus: "Sector focus", almanac: "S&P 500 month by month", longterm: "Long-term trends", news: "Sector news tone",
  actions: "Actionables", model: "How the odds work",
};
const VIEW_KEYS = Object.keys(VIEW_NAMES);

const theme = params.get("theme") || "dark";
if (theme === "auto") delete document.documentElement.dataset.theme;
else document.documentElement.dataset.theme = theme;
if (params.get("colors") === "classic") document.documentElement.dataset.colors = "classic";

const S = { data: null, playlist: [], pos: 0, paused: false, started: 0, charts: [], focusGroups: [] };

/* ------------------------------------------------------------------ formatting */
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const minus = (s) => s.replace("-", "−");
const pct = (x, nd = 1, sign = true) => {
  if (x == null) return "–";
  if (Math.abs(x * 100) < 0.5 * 10 ** -nd) x = 0;
  return minus((sign && x > 0 ? "+" : "") + (x * 100).toFixed(nd) + "%");
};
const pp = (x) => (x == null ? "–" : Math.round(x * 100) + "%");
const px = (x) => (x == null ? "–" : x >= 1000 ? x.toLocaleString("en-US", { maximumFractionDigits: 0 })
  : x >= 100 ? x.toFixed(1) : x.toFixed(2));
const dir = (x, eps = 0.0005) => (x == null ? "flat" : x > eps ? "up" : x < -eps ? "down" : "flat");
const glyph = (x, eps) => { const d = dir(x, eps); return `<i class="g ${d}">${{ up: "▲", down: "▼", flat: "●" }[d]}</i>`; };
const delta = (x, nd = 1) => `<span class="num">${glyph(x)}${pct(x, nd)}</span>`;
const sigGlyph = (v) => `<i class="g ${v > 0 ? "up" : v < 0 ? "down" : "flat"}">${v > 0 ? "▲" : v < 0 ? "▼" : "●"}</i>`;
const ymLabel = (ym) => `${MONTHS[+ym.slice(5, 7) - 1]} ${ym.slice(0, 4)}`;
const rem = () => parseFloat(getComputedStyle(document.documentElement).fontSize);
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

/* ------------------------------------------------------------------ color: OKLab diverging scale */
function hexRgb(h) { h = h.replace("#", ""); return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255); }
const toLin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const toSrgb = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
function oklab(hex) {
  const [r, g, b] = hexRgb(hex).map(toLin);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}
function fromOklab([L, a, b]) {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3, m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3,
    s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const rgb = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
  return "#" + rgb.map((c) => Math.round(Math.min(1, Math.max(0, toSrgb(c))) * 255).toString(16).padStart(2, "0")).join("");
}
let PAL = null;
function palette() {
  PAL = { up: css("--up"), down: css("--down"), mid: css("--mid"), ink: css("--ink"), ink2: css("--ink-2"),
    muted: css("--muted"), grid: css("--grid"), base: css("--base"), surface: css("--surface"), s2: css("--surface-2"),
    s1c: css("--s1"), s2c: css("--s2"), s3c: css("--s3"), hl: css("--hl") };
  PAL.labUp = oklab(PAL.up); PAL.labDown = oklab(PAL.down); PAL.labMid = oklab(PAL.mid);
}
function divColor(v, cap) {
  if (v == null) return PAL.s2;
  const t = Math.min(1, Math.abs(v) / cap) ** 0.85;
  const pole = v >= 0 ? PAL.labUp : PAL.labDown;
  return fromOklab(PAL.labMid.map((m, i) => m + (pole[i] - m) * t));
}
function inkOn(hex) {
  const [r, g, b] = hexRgb(hex).map(toLin);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.3 ? "#0b0b0b" : "#ffffff";
}

/* ------------------------------------------------------------------ svg charts */
const chart = (fn, cls = "") => { S.charts.push(fn); return `<div class="chart ${cls}" data-c="${S.charts.length - 1}"></div>`; };
const svg = (w, h, inner) => `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${inner}</svg>`;

function vbar(x, y0, y1, w, r) {
  // bar from baseline y0 to data end y1, rounded only at the data end
  r = Math.min(r, w / 2, Math.abs(y1 - y0));
  if (Math.abs(y1 - y0) < 0.5) return `M${x},${y0}h${w}`;
  const s = y1 < y0 ? 1 : -1;
  return `M${x},${y0}V${y1 + s * r}Q${x},${y1} ${x + r},${y1}H${x + w - r}Q${x + w},${y1} ${x + w},${y1 + s * r}V${y0}Z`;
}

function niceTicks(lo, hi, n = 4) {
  const span = hi - lo || Math.abs(hi) || 1;
  const step0 = span / n, mag = 10 ** Math.floor(Math.log10(step0)), f = step0 / mag;
  const step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

/* Diverging columns from a zero baseline. items: {label, v, tip, hl} */
function colBars(items, o = {}) {
  return (w, h) => {
    const R = rem(), fs = (o.fs || 0.72) * R;
    const vals = items.map((d) => d.v ?? 0);
    const labelled = o.valueLabels === "all" ? items : o.valueLabels === "hl" ? items.filter((d) => d.hl) : [];
    const top = labelled.some((d) => d.v >= 0) ? fs * 1.6 : 4;
    const bottom = (o.xLabels === false ? 2 : fs * 1.8) + (labelled.some((d) => d.v < 0) ? fs * 1.5 : 0);
    const cap = o.cap ?? Math.max(1e-9, ...vals.map(Math.abs));
    let hiV = o.symmetric ? cap : Math.max(0, ...vals), loV = o.symmetric ? -cap : Math.min(0, ...vals);
    if (o.domain) [loV, hiV] = o.domain;
    const span = hiV - loV || 1, ph = h - top - bottom;
    const y = (v) => top + ((hiV - Math.max(loV, Math.min(hiV, v))) / span) * ph;
    const band = w / items.length, bw = Math.min(o.maxW || 24, band * 0.62), y0 = y(0);
    let s = "";
    items.forEach((d, i) => {
      if (d.hl) s += `<rect x="${i * band + 1}" y="0" width="${band - 2}" height="${h}" rx="${0.3 * R}" fill="${PAL.s2}"/>`;
    });
    s += `<line x1="0" x2="${w}" y1="${y0}" y2="${y0}" stroke="${PAL.base}" stroke-width="1"/>`;
    items.forEach((d, i) => {
      const x = i * band + (band - bw) / 2;
      if (d.v != null) s += `<path d="${vbar(x, y0, y(d.v), bw, 4)}" fill="${d.v >= 0 ? PAL.up : PAL.down}"/>`;
      const showV = d.v != null && (o.valueLabels === "all" || (o.valueLabels === "hl" && d.hl));
      if (showV) {
        const yy = d.v >= 0 ? y(d.v) - fs * 0.45 : y(d.v) + fs * 1.15;
        s += `<text x="${x + bw / 2}" y="${yy}" text-anchor="middle" font-size="${fs}" fill="${PAL.ink2}" font-weight="${d.hl ? 650 : 400}">${o.fmt ? o.fmt(d.v) : pct(d.v)}</text>`;
      }
      if (o.xLabels !== false) {
        s += `<text x="${i * band + band / 2}" y="${h - fs * 0.45}" text-anchor="middle" font-size="${fs}" fill="${d.hl ? PAL.ink : PAL.muted}" font-weight="${d.hl ? 700 : 400}">${esc(d.label)}</text>`;
      }
      if (d.tip) s += `<rect x="${i * band}" y="0" width="${band}" height="${h}" fill="transparent" data-tip="${esc(d.tip)}"/>`;
    });
    return svg(w, h, s);
  };
}

/* Lines on one y-axis. series: {pts:[[x,y]], color, width, area, endLabel} ; o: {xTicks:[[x,label]], yFmt, zero} */
function lineChart(series, o = {}) {
  return (w, h) => {
    const R = rem(), fs = 0.72 * R;
    const all = series.flatMap((s) => s.pts.filter((p) => p[1] != null));
    if (!all.length) return "";
    let x0 = Math.min(...all.map((p) => p[0])), x1 = Math.max(...all.map((p) => p[0]));
    if (o.xMax != null) x1 = Math.max(x1, o.xMax);
    let lo = Math.min(...all.map((p) => p[1])), hi = Math.max(...all.map((p) => p[1]));
    if (o.zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    const padY = (hi - lo) * 0.08 || Math.abs(hi) * 0.1 || 1; lo -= padY; hi += padY;
    if (o.yDomain) [lo, hi] = o.yDomain;
    const ticks = niceTicks(lo, hi, o.yTicks || 4);
    const whole = ticks.every((t) => Number.isInteger(t));
    const yf = o.yFmt || ((v) => (whole ? v.toLocaleString("en-US") : px(v)));
    const left = Math.max(...ticks.map((t) => yf(t).length)) * fs * 0.62 + 8;
    const right = o.endPad ?? fs * 4.5, top = 6, bottom = fs * 1.9;
    const X = (v) => left + ((v - x0) / (x1 - x0 || 1)) * (w - left - right);
    const Y = (v) => top + ((hi - v) / (hi - lo)) * (h - top - bottom);
    let s = "";
    (o.bands || []).forEach((b) => {
      s += `<rect x="${left}" y="${Y(b.to)}" width="${w - right - left}" height="${Y(b.from) - Y(b.to)}" fill="${b.color}" opacity="0.1"/>`;
      if (b.label) s += `<text x="${left + 6}" y="${(Y(b.to) + Y(b.from)) / 2 + fs * 0.35}" font-size="${fs * 0.9}" fill="${PAL.muted}">${esc(b.label)}</text>`;
    });
    ticks.forEach((t) => {
      s += `<line x1="${left}" x2="${w - right}" y1="${Y(t)}" y2="${Y(t)}" stroke="${t === 0 && o.zero ? PAL.base : PAL.grid}" stroke-width="1"/>`;
      s += `<text x="${left - 6}" y="${Y(t) + fs * 0.35}" text-anchor="end" font-size="${fs}" fill="${PAL.muted}">${yf(t)}</text>`;
    });
    (o.xTicks || []).forEach(([v, lab]) => {
      s += `<text x="${X(v)}" y="${h - fs * 0.4}" text-anchor="middle" font-size="${fs}" fill="${PAL.muted}">${esc(lab)}</text>`;
    });
    series.forEach((se) => {
      const pts = se.pts.filter((p) => p[1] != null);
      if (!pts.length) return;
      const d = pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
      if (se.area) {
        const base = Y(Math.max(lo, o.zero ? 0 : lo));
        s += `<path d="${d}L${X(pts.at(-1)[0])},${base}L${X(pts[0][0])},${base}Z" fill="${se.color}" opacity="0.1"/>`;
      }
      if (!se.noLine) s += `<path d="${d}" fill="none" stroke="${se.color}" stroke-width="${se.width || 2}" stroke-linejoin="round" stroke-linecap="round"/>`;
      const last = pts.at(-1);
      if (se.dots) pts.forEach((p, i) => { s += `<circle cx="${X(p[0])}" cy="${Y(p[1])}" r="${se.r || 5}" fill="${se.color}" stroke="${PAL.surface}" stroke-width="2"${se.dotTips ? ` data-tip="${esc(se.dotTips[i])}"` : ""}/>`; });
      if (se.endDot !== false) s += `<circle cx="${X(last[0])}" cy="${Y(last[1])}" r="4.5" fill="${se.color}" stroke="${PAL.surface}" stroke-width="2"/>`;
      if (se.endLabel) s += `<text x="${X(last[0]) + 9}" y="${Y(last[1]) + fs * 0.35}" font-size="${fs * 1.1}" font-weight="650" fill="${PAL.ink}">${esc(se.endLabel)}</text>`;
      if (se.tips) pts.forEach((p, i) => {
        const xa = i ? (X(pts[i - 1][0]) + X(p[0])) / 2 : X(p[0]) - 4, xb = i < pts.length - 1 ? (X(pts[i + 1][0]) + X(p[0])) / 2 : X(p[0]) + 4;
        s += `<rect x="${xa}" y="0" width="${xb - xa}" height="${h - bottom}" fill="transparent" data-tip="${esc(se.tips[i] || "")}"/>`;
      });
    });
    return svg(w, h, s);
  };
}

function sparkline(vals, color) {
  return (w, h) => {
    const v = vals.filter((x) => x != null);
    if (v.length < 2) return "";
    const lo = Math.min(...v), hi = Math.max(...v), pad = 5;
    const X = (i) => pad + (i / (v.length - 1)) * (w - 2 * pad), Y = (x) => pad + ((hi - x) / (hi - lo || 1)) * (h - 2 * pad);
    const d = v.map((x, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(x).toFixed(1)}`).join("");
    return svg(w, h, `<path d="${d}" fill="none" stroke="${color}" stroke-width="1.75" stroke-linejoin="round"/>
      <circle cx="${X(v.length - 1)}" cy="${Y(v.at(-1))}" r="3.5" fill="${color}" stroke="${PAL.surface}" stroke-width="2"/>`);
  };
}

function renderCharts() {
  document.querySelectorAll(".chart[data-c]").forEach((el) => {
    const fn = S.charts[+el.dataset.c];
    const w = el.clientWidth, h = el.clientHeight;
    if (fn && w > 10 && h > 10) el.innerHTML = fn(w, h);
  });
}

/* ------------------------------------------------------------------ shared bits */
const D = () => S.data;
const inst = (sym) => D().instruments[sym];
const groupById = (id) => D().groups.find((g) => g.id === id);
const upcoming = () => D().upcoming_months;

function seasonItems(i, h = 1) {
  const up = upcoming().slice(0, h === 1 ? 3 : 3);
  return i.season["1"].map((m, k) => ({
    label: MONTHS[k][0], v: m ? m.mean : null, hl: up.includes(k + 1),
    tip: m ? `${MONTHS_LONG[k]}: avg ${pct(m.mean)}, median ${pct(m.median)}, up ${pp(m.win)} of ${m.n} years` : "",
  }));
}

function waterfall(o) {
  if (!o) return "";
  const rows = [{ name: "Base rate", v: o.base, abs: true }, ...o.steps.map((s) => ({ name: s.name[0].toUpperCase() + s.name.slice(1), v: s.delta, h: s.heuristic }))];
  const scale = 0.12; // ±12pp spans the half-bar
  let out = `<div class="wf">`;
  rows.forEach((r) => {
    let bar;
    if (r.abs) bar = `<i style="left:0;width:${(r.v * 100).toFixed(1)}%;background:${PAL.base}"></i><i style="left:50%;width:1px;background:${PAL.ink2}"></i>`;
    else {
      const wdt = Math.min(50, (Math.abs(r.v) / scale) * 50);
      bar = `<i style="left:${r.v >= 0 ? 50 : 50 - wdt}%;width:${Math.max(wdt, 0.6)}%;background:${r.v >= 0 ? PAL.up : PAL.down}"></i><i style="left:50%;width:1px;background:${PAL.base}"></i>`;
    }
    out += `<span class="ink2">${r.name}${r.h ? "*" : ""}</span><span class="bar">${bar}</span><span class="v">${r.abs ? pp(r.v) : minus((r.v >= 0 ? "+" : "") + (r.v * 100).toFixed(1)) + "pp"}</span>`;
  });
  out += `<span><b>Odds up</b></span><span></span><span class="v"><b>${pp(o.p)}</b></span></div>`;
  return out;
}

function sigRow(sigs) {
  return `<div class="sigs">${(sigs || []).map((s) => `<span data-tip="${esc(s.tip)}">${sigGlyph(s.v)}${s.k}</span>`).join("")}</div>`;
}

const KIND = { tailwind: ["▲", "Tailwind", "Tailwinds"], headwind: ["▼", "Headwind", "Headwinds"], watch: ["◆", "Watch", "Watch list"], risk: ["⚠", "Risk", "Risks"] };

function actItem(a, tag) {
  return `<div class="act"><span class="ic ${a.kind}">${KIND[a.kind][0]}</span><div>
    <div class="t">${tag ? `<span class="kind">${esc(tag)}</span>` : `<span class="kind">${KIND[a.kind][1]}</span>`}${esc(a.text)}</div>
    ${a.why ? `<div class="w">${esc(a.why)}</div>` : ""}</div></div>`;
}

function toneColor(v) { return divColor(v, 0.3); }

/* ------------------------------------------------------------------ views */
function vOverview() {
  const d = D(), mk = groupById("market"), sp = inst("^GSPC"), nar = mk?.narrative, spx = d.sp500;
  const st = nar?.stats;
  let story = `<div class="kicker">Seasonal outlook${nar ? " · " + esc(nar.label) : ""}</div>`;
  if (st) {
    story += `<div class="headline">Historically, the S&P 500 has risen in <b>${esc(nar.label)}</b> in <b>${pp(st.win)}</b> of years since ${st.first}, averaging <b>${pct(st.mean)}</b>.</div>
      <div class="why"><b>Why:</b> ${esc(nar.why)}</div>`;
  } else {
    const st0 = d.status;
    if (st0.errors?.length) {
      story += `<div class="headline">Couldn't download ${st0.loaded ? "the S&P 500 history" : "any market data"}</div>
        <div class="why">${st0.hint ? `<b>Likely cause:</b> ${esc(st0.hint)}<br>` : ""}<span class="muted small">First error: ${esc(st0.errors[0])}</span></div>`;
    } else story += `<div class="headline">Waiting for S&P 500 history…</div>`;
  }
  const facts = [];
  if (spx) {
    const yr = +d.today.slice(0, 4), phase = yr % 4;
    const mid = spx.midterm?.next12;
    if (phase === 2 && mid) {
      facts.push(`<b>${Math.round(mid.win * mid.n)} of ${mid.n}</b>midterm years since ${spx.since} saw the S&P higher 12 months after the election (avg ${pct(mid.mean)}, worst ${pct(mid.worst)} in ${mid.worst_year})`);
    } else {
      const c = spx.cycle.find((x) => x.current);
      if (c) facts.push(`<b>${pp(c.win)}</b>of ${c.phase.toLowerCase()} years were up for the S&P (avg ${pct(c.mean)})`);
    }
    const p = spx.paths, cur = p.current, i = cur.length - 1;
    if (i >= 0) facts.push(`<b>${pct(cur[i])}</b>S&P year-to-date vs ${pct(p.all[i])} in a typical year and ${pct(p.same_cycle[i])} in a typical ${p.cycle_name} year by ${MONTHS[i]}`);
    const nm = spx.almanac[upcoming()[0] - 1];
    facts.push(`<b>${pp(nm.win)}</b>of ${MONTHS_LONG[nm.m - 1]}s since ${spx.since} were up for the S&P (avg ${pct(nm.mean)})`);
  }
  story += `<div class="facts">${facts.map((f) => `<div class="fact">${f}</div>`).join("")}</div>`;

  let odds = `<div class="kicker">Odds the S&P 500 is higher</div>`;
  const o3 = sp?.odds?.["3"];
  if (o3) {
    const o1 = sp.odds["1"], o6 = sp.odds["6"];
    odds += `<div class="row"><div><div class="big">${pp(o3.p)}</div><div class="verdict">${esc(o3.verdict)} · over ${esc(o3.window)}</div></div>
      <div class="side">${[o1, o6].filter(Boolean).map((o) => `<div><b>${pp(o.p)}</b><span class="muted small">${esc(o.window)}</span></div>`).join("")}</div></div>
      ${waterfall(o3)}`;
  } else odds += `<div class="muted">Not enough data yet.</div>`;

  const tiles = d.groups.map(tile).join("") + calTile();
  return `<div class="ov"><div class="hero"><div class="card story">${story}</div><div class="card odds">${odds}</div></div>
    <div class="tiles">${tiles}</div></div>`;
}

function tile(g) {
  if (!g.primary) {
    return `<div class="card tile empty"><div class="top"><span class="name">${esc(g.name)}</span><span class="tick">${g.members.slice(0, 3).join(" · ")}</span></div>
      <div class="lbl">${D().status.errors?.length ? "Couldn't download prices" : "Waiting for price data"}</div></div>`;
  }
  const i = inst(g.primary), o = i.odds["3"], s = i.snap;
  return `<div class="card tile">
    <div class="top"><span class="name">${esc(g.name)}</span><span class="tick">${esc(i.sym)} · ${esc(i.name)}</span></div>
    <div class="mid">${o ? `<span class="pct">${pp(o.p)}</span><span class="lbl">odds up<br>${esc(o.window)}</span>` : `<span class="lbl">no odds</span>`}
      <span class="px">${px(s.price)}<br>${delta(s.m1)} <span class="muted">1M</span></span></div>
    ${chart(colBars(seasonItems(i), { valueLabels: "none", fs: 0.6 }))}
    ${sigRow(i.signals)}</div>`;
}

function calTile() {
  const ev = D().calendar.slice(0, 5);
  return `<div class="card tile"><div class="top"><span class="name">Coming up</span><span class="tick">next ${ev.length ? ev.at(-1).days : 0} days</span></div>
    <div class="cal">${ev.map((e) => `<div class="ev ${e.major ? "major" : ""}"><span class="d">${e.days === 0 ? "today" : e.days + "d"}</span><span>${esc(e.label)}</span></div>`).join("")}</div></div>`;
}

/* Split sector groups into pages of at most `limit` instrument rows, keeping groups whole. */
function pages(syms, limit = 16) {
  const gs = D().groups.map((g) => ({ g, n: syms(g).length })).filter((x) => x.n);
  const total = gs.reduce((a, x) => a + x.n, 0);
  const nPages = Math.max(1, Math.ceil(total / limit)), per = total / nPages, out = [[]];
  let acc = 0;
  gs.forEach((x) => {
    if (acc + x.n / 2 > per * out.length && out.length < nPages) out.push([]);
    out.at(-1).push(x.g.id); acc += x.n;
  });
  return out;
}
const heatSyms = (g) => g.available.filter((s) => inst(s).season?.["1"]);

function vHeatmap(part = 0) {
  const d = D(), up = upcoming(), ids = pages(heatSyms)[part] || [];
  const rows = [];
  d.groups.filter((g) => ids.includes(g.id)).forEach((g) => {
    const syms = heatSyms(g);
    if (!syms.length) return;
    rows.push({ group: g.name });
    syms.forEach((s) => rows.push({ sym: s }));
  });
  const nInst = rows.filter((r) => r.sym).length, twoLine = nInst <= 16;
  const cap = 0.03;
  let t = `<table class="hm" style="height:${nInst > 9 ? "100%" : "auto"}"><colgroup><col style="width:15rem">${MONTHS.map(() => "<col>").join("")}<col style="width:12rem"></colgroup>
    <thead><tr><th></th>${MONTHS.map((m, k) => `<th class="${up.includes(k + 1) ? "up3" : ""}">${m}</th>`).join("")}<th style="text-align:left;padding-left:.6rem">Next 3 mo</th></tr></thead><tbody>`;
  rows.forEach((r) => {
    if (r.group) { t += `<tr class="grp"><td class="gname" colspan="14">${esc(r.group)}</td></tr>`; return; }
    const i = inst(r.sym), s1 = i.season["1"], s3 = i.season["3"][up[0] - 1];
    t += `<tr style="${nInst > 9 ? "" : "height:4.2rem"}"><td class="lab"><b>${esc(i.sym)}</b> <span class="ink2">${esc(i.name)}</span></td>`;
    s1.forEach((m, k) => {
      const bg = divColor(m?.mean, cap), fg = inkOn(bg), hl = up.includes(k + 1) ? "up3" : "";
      t += `<td class="${hl}" style="background:${bg};color:${fg}" data-tip="${esc(m ? `${i.sym} ${MONTHS_LONG[k]}: avg ${pct(m.mean)}, up ${pp(m.win)} of ${m.n} years (${m.first}–${m.last})` : "")}">${m ? pct(m.mean, 1) : "–"}${twoLine && m ? `<span class="w">${pp(m.win)} up</span>` : ""}</td>`;
    });
    t += `<td class="next small">${s3 ? `<b>${pp(s3.win)}</b> up · avg ${pct(s3.mean)}<br><span class="muted tiny">${esc(s3.label)}, ${s3.n} yrs</span>` : "–"}</td></tr>`;
  });
  t += `</tbody></table>`;
  const ramp = `linear-gradient(90deg, ${[-1, -0.5, -0.25, 0, 0.25, 0.5, 1].map((v) => divColor(v * cap, cap)).join(",")})`;
  return `<div class="hm-wrap"><div class="hm-head"><div><div class="kicker">Month by month, every sector</div>
      <h2>Average return by calendar month${twoLine ? " · % of years up" : ""}</h2></div>
      <div class="legend"><span>${pct(-cap, 0)}</span><span class="ramp" style="background:${ramp}"></span><span>${pct(cap, 0)}</span>
      <span class="muted">· outlined = next 3 months · S&P since ${d.sp500?.since ?? 1950}, others full history</span></div></div>
    <div style="min-height:0;overflow:hidden">${t}</div></div>`;
}

function vFocus(g) {
  const i = inst(g.primary), s = i.snap, up = upcoming();
  const head = `<div class="fx-head"><div><div class="kicker">Sector focus · ${esc(g.name)}</div><h2>${esc(i.name)} <span class="muted" style="font-weight:500">${esc(i.sym)}</span></h2>
      <div class="meta">${px(s.price)} · as of ${esc(s.asof)} · ${esc(i.source)}${i.monthly_kind === "average" && !/average/i.test(i.source) ? " (monthly averages)" : ""}</div></div>
    <div class="chg">${[["1D", s.d1], ["1M", s.m1], ["3M", s.m3], ["YTD", s.ytd], ["1Y", s.y1], ["10Y/yr", s.y10a]]
      .filter(([, v]) => v != null).map(([k, v]) => `<div><b>${delta(v)}</b><span>${k}</span></div>`).join("")}</div></div>`;

  // price + 10-month average
  const sp = s.spark, pts = sp.map((p, k) => [k, p[1]]);
  const sma = sp.map((p, k) => [k, k >= 9 ? sp.slice(k - 9, k + 1).reduce((a, b) => a + b[1], 0) / 10 : null]);
  const xt = sp.map((p, k) => [k, p[0]]).filter(([, ym]) => ym.endsWith("-01")).map(([k, ym]) => [k, ym.slice(0, 4)]);
  const priceChart = lineChart([
    { pts: sma, color: PAL.muted, width: 1.5, endDot: false },
    { pts, color: PAL.s1c, area: true, endLabel: px(s.price), tips: sp.map((p, k) => `${ymLabel(p[0])}: ${px(p[1])}${sma[k][1] ? ` · 10-mo avg ${px(sma[k][1])}` : ""}`) },
  ], { xTicks: xt });

  const members = g.available.map((sym) => {
    const m = inst(sym), ms = m.snap, o = m.odds["3"];
    return `<tr><td><b>${esc(sym)}</b> <span class="muted">${esc(m.name)}</span></td><td>${px(ms.price)}</td><td>${delta(ms.m1)}</td><td>${delta(ms.m3)}</td><td>${delta(ms.ytd)}</td><td>${delta(ms.y1)}</td><td>${o ? pp(o.p) : "–"}</td></tr>`;
  }).join("");
  const missing = g.members.filter((m) => !g.available.includes(m));

  const nar = g.narrative || g.narratives[0];
  const ns = nar?.stats;
  const recent = ns ? colBars(ns.recent.map(([y, r]) => ({ label: "'" + String(y).slice(2), v: r, tip: `${y}: ${pct(r)}` })), { valueLabels: "none", fs: 0.62 }) : null;

  const o = i.odds;
  const oddsCard = o["3"] ? `<div class="card"><div class="kicker">Odds ${esc(i.sym)} is higher</div>
      <div class="row" style="display:flex;gap:1.6rem;align-items:flex-end;margin:.3rem 0">
      ${["1", "3", "6"].filter((h) => o[h]).map((h) => `<div><div style="font-size:${h === "3" ? 2.6 : 1.5}rem;font-weight:650;line-height:1">${pp(o[h].p)}</div><span class="muted small">${esc(o[h].window)}</span></div>`).join("")}
      <div class="verdict" style="margin-left:auto">${esc(o["3"].verdict)}</div></div>${waterfall(o["3"])}</div>` : "";

  const news = g.news;
  let newsCard = `<div class="card"><div class="kicker">News tone</div>`;
  if (news) {
    newsCard += `<div style="display:flex;gap:1.2rem;margin:.35rem 0 .5rem">${["1M", "3M", "6M", "YTD"].map((k) => {
      const w = news.windows[k];
      return `<div><b style="font-size:1.2rem">${w ? minus((w.mean >= 0 ? "+" : "") + w.mean.toFixed(2)) : "–"}</b><div class="muted tiny">${k} · ${w ? w.n : 0}</div></div>`;
    }).join("")}</div><div class="heads">${news.latest.slice(0, 4).map(headline).join("")}</div>`;
  } else newsCard += `<p class="muted small" style="margin:.4rem 0 0">No headlines: Google News isn't reachable from this machine.</p>`;
  newsCard += `</div>`;

  return `<div class="fx">${head}
    <div class="col c1" style="grid-template-rows:1fr auto">
      <div class="card" style="display:grid;grid-template-rows:auto 1fr;gap:.4rem"><div class="kicker">5-year price · grey = 10-month average (trend line)</div>${chart(priceChart)}</div>
      <div class="card"><table class="mem"><thead><tr><th>Ticker</th><th>Price</th><th>1M</th><th>3M</th><th>YTD</th><th>1Y</th><th>Odds 3M</th></tr></thead><tbody>${members}</tbody></table>
      ${missing.length ? `<div class="muted tiny" style="margin-top:.35rem">No data yet: ${missing.join(", ")}</div>` : ""}</div>
    </div>
    <div class="col" style="grid-template-rows:1fr auto">
      <div class="card" style="display:grid;grid-template-rows:auto 1fr;gap:.4rem"><div class="kicker">Average return by month · since ${esc(i.history_from)} · highlighted = next 3 months</div>
        ${chart(colBars(i.season["1"].map((m, k) => ({ label: MONTHS[k], v: m?.mean, hl: up.includes(k + 1), tip: m ? `${MONTHS_LONG[k]}: avg ${pct(m.mean)}, up ${pp(m.win)} of ${m.n} yrs` : "" })), { valueLabels: "hl" }))}</div>
      ${nar ? `<div class="card narr"><div class="kicker">${esc(nar.label)} pattern</div><h3>${esc(nar.title)}</h3><p>${esc(nar.why)}</p>
        ${ns ? `<div class="stat-row"><div><b>${pp(ns.win)}</b><span>of ${ns.n} years up</span></div><div><b>${pct(ns.mean)}</b><span>average</span></div><div><b>${pct(ns.median)}</b><span>median</span></div><div><b>${pct(ns.worst)}</b><span>worst</span></div></div>
        <div class="muted tiny" style="margin-top:.5rem">Last ${ns.recent.length} years in ${esc(nar.label)}</div><div style="height:5.2rem">${chart(recent)}</div>` : ""}</div>` : ""}
    </div>
    <div class="col" style="grid-template-rows:auto 1fr auto">
      ${oddsCard}
      <div class="card"><div class="kicker">Actionables</div><div class="acts" style="margin-top:.45rem">${(g.actionables || []).slice(0, 6).map((a) => actItem(a)).join("") || `<span class="muted">No strong signals.</span>`}</div></div>
      ${newsCard}
    </div></div>`;
}

function headline(h) {
  return `<div class="head"><span class="dot" style="background:${toneColor(h.score)}"></span><div>${esc(h.title)}
    <div class="src">${esc(h.source || "")} · ${esc(h.date)} · tone ${minus((h.score >= 0 ? "+" : "") + h.score.toFixed(2))}</div></div></div>`;
}

function vAlmanac() {
  const spx = D().sp500, up = upcoming();
  if (!spx) return `<div class="empty-state"><h2>No S&P 500 history yet</h2></div>`;
  const dom = [Math.min(0, ...spx.almanac.map((a) => a.mean)), Math.max(0, ...spx.almanac.map((a) => a.mean))];
  const months = spx.almanac.map((a) => `<div class="card mo ${up.includes(a.m) ? "up3" : ""}">
      <div class="mn">${a.name}</div>${chart(colBars([{ label: "", v: a.mean, tip: `${MONTHS_LONG[a.m - 1]}: avg ${pct(a.mean)}, median ${pct(a.median)}, up ${pp(a.win)} of ${a.n} years` }], { valueLabels: "none", xLabels: false, domain: dom, maxW: 28 }))}
      <div><div class="mv num">${pct(a.mean)}</div><div class="mw">${pp(a.win)} of years up</div></div><div class="note">${esc(a.note)}</div></div>`).join("");

  const p = spx.paths, xt = MONTHS.map((m, k) => [k + 1, m]);
  const mk = (arr) => [[0, 0], ...arr.map((v, k) => [k + 1, v])];
  const yr = D().today.slice(0, 4);
  const path = lineChart([
    { pts: mk(p.all), color: PAL.muted, width: 2, endDot: false },
    { pts: mk(p.same_cycle), color: PAL.s2c, width: 2, endDot: false },
    { pts: mk(p.current), color: PAL.s1c, width: 2.5, endLabel: pct(p.current.at(-1)),
      tips: ["Start", ...p.current.map((v, k) => `${MONTHS[k]} ${yr}: ${pct(v)} YTD · typical ${pct(p.all[k])} · typical ${p.cycle_name} ${pct(p.same_cycle[k])}`)] },
  ], { xTicks: xt, yFmt: (v) => pct(v, 0), zero: true, xMax: 12 });

  const cyc = spx.cycle;
  const cycChart = colBars(cyc.map((c) => ({ label: c.phase, v: c.mean, hl: c.current, tip: `${c.phase} years: avg ${pct(c.mean)}, up ${pp(c.win)} of ${c.n}` })), { valueLabels: "all", fs: 0.68 });
  const mid = spx.midterm;
  const midChart = mid?.next12 ? colBars(mid.next12.years.map(([y, r]) => ({ label: "'" + String(y).slice(2), v: r, tip: `${y} midterm → +12 months: ${pct(r)}` })), { valueLabels: "none", fs: 0.58 }) : null;

  return `<div class="alm"><div><div class="kicker">S&P 500 · ${spx.since}–${yr}${spx.monthly_kind === "average" ? " · monthly-average prices" : ""}</div>
      <h2 style="font-size:1.5rem">What each month has historically done <span class="muted" style="font-weight:400;font-size:1rem">· outlined = next 3 months</span></h2></div>
    <div class="months">${months}</div>
    <div class="alm-bottom">
      <div class="card" style="display:grid;grid-template-rows:auto auto 1fr;gap:.35rem"><div class="kicker">${yr} so far vs history (cumulative, from Dec 31)</div>
        <div class="legend-row"><span><i style="background:${PAL.s1c}"></i>${yr}</span><span><i style="background:${PAL.muted}"></i>Typical year (${p.n_all})</span><span><i style="background:${PAL.s2c}"></i>Typical ${p.cycle_name} year (${p.n_cycle})</span></div>${chart(path)}</div>
      <div class="card" style="display:grid;grid-template-rows:auto auto 1fr;gap:.35rem"><div class="kicker">Presidential cycle · average calendar-year return</div>
        <div class="small ink2">${yr} is a <b>${esc(cyc.find((c) => c.current)?.phase.toLowerCase() || "")}</b> year. Year 3 (pre-election) has been the strongest: up ${pp(cyc[2].win)} of the time.</div>${chart(cycChart)}</div>
      <div class="card" style="display:grid;grid-template-rows:auto auto 1fr;gap:.35rem"><div class="kicker">After midterm elections · Oct → Oct</div>
        ${mid?.next12 ? `<div class="small ink2"><b style="font-size:1.7rem;color:var(--ink)">${Math.round(mid.next12.win * mid.next12.n)}/${mid.next12.n}</b> times higher 12 months later · avg ${pct(mid.next12.mean)} · Q4 of midterm years up ${pp(mid.q4.win)} (avg ${pct(mid.q4.mean)})</div>${chart(midChart)}` : ""}</div>
    </div></div>`;
}

function vLongterm(part = 0) {
  const d = D(), ids = pages((g) => g.available)[part] || [];
  let t = `<table class="lt"><thead><tr><th>Instrument</th><th style="width:9rem">5 years</th><th>Price</th><th>1Y</th><th>3Y /yr</th><th>5Y /yr</th><th>10Y /yr</th><th>20Y /yr</th><th>From high</th><th>Worst drawdown</th><th>Volatility</th><th>vs 10-mo avg</th></tr></thead><tbody>`;
  d.groups.filter((g) => ids.includes(g.id)).forEach((g) => {
    if (!g.available.length) return;
    t += `<tr class="grp"><td colspan="12">${esc(g.name)}</td></tr>`;
    g.available.forEach((sym) => {
      const i = inst(sym), s = i.snap;
      t += `<tr><td><b>${esc(sym)}</b> <span class="ink2">${esc(i.name)}</span></td><td style="height:1.7rem;padding:0">${chart(sparkline(s.spark.map((p) => p[1]), PAL.s1c))}</td>
        <td class="num">${px(s.price)}</td><td>${delta(s.y1)}</td><td>${delta(s.y3a)}</td><td>${delta(s.y5a)}</td><td>${delta(s.y10a)}</td><td>${delta(s.y20a)}</td>
        <td class="num">${pct(s.dd)}</td><td class="num">${pct(s.max_dd, 0)} <span class="muted">(${s.max_dd_year ?? "–"})</span></td><td class="num">${pct(s.vol, 0, false)}</td><td>${delta(s.vs_sma10)}</td></tr>`;
    });
  });
  t += `</tbody></table>`;
  const missing = part === pages((g) => g.available).length - 1 ? d.status.missing.filter((s) => s !== "SPY") : [];
  return `<div style="display:grid;grid-template-rows:auto 1fr;gap:.7rem;height:100%"><div><div class="kicker">Long-term view</div><h2 style="font-size:1.5rem">Annualised returns, drawdowns and trend</h2></div>
    <div class="card" style="overflow:hidden">${t}${missing.length ? `<div class="muted tiny" style="margin-top:.5rem">Not loaded: ${missing.join(", ")}</div>` : ""}</div></div>`;
}

function vNews() {
  const d = D(), gs = d.groups.filter((g) => g.news);
  if (!gs.length) {
    return `<div class="empty-state"><div class="kicker">News pulse</div><h2>No headlines yet</h2>
      <p>Headline tone comes from Google News RSS (<code>news.google.com</code>), one query per sector per month, plus <code>yfinance</code> ticker news.
      None came back on the last refresh. Once they do, each sector gets tone scores for 1M / 3M / 6M / YTD and they tilt the odds by up to ±7 points.</p>
      ${d.status.news_error ? `<p class="small"><b>Last error:</b> ${esc(d.status.news_error)}</p>` : ""}</div>`;
  }
  let t = `<table class="lt"><thead><tr><th>Sector</th><th style="width:9rem">12-month tone</th>${["1M", "3M", "6M", "YTD"].map((k) => `<th>${k}</th>`).join("")}<th>vs norm</th></tr></thead><tbody>`;
  gs.forEach((g) => {
    const n = g.news;
    t += `<tr><td><b>${esc(g.name)}</b></td><td style="height:1.7rem;padding:0">${chart(sparkline(n.monthly.map((m) => m[1]), PAL.ink2))}</td>`;
    ["1M", "3M", "6M", "YTD"].forEach((k) => {
      const w = n.windows[k], bg = w ? toneColor(w.mean) : PAL.s2;
      t += `<td style="background:${bg};color:${inkOn(bg)};text-align:center" data-tip="${w ? `${w.n} headlines · ${pp(w.pos)} positive · ${pp(w.neg)} negative` : ""}">${w ? minus((w.mean >= 0 ? "+" : "") + w.mean.toFixed(2)) : "–"}</td>`;
    });
    t += `<td>${g.news_tilt == null ? "–" : sigGlyph(g.news_tilt >= 0.25 ? 1 : g.news_tilt <= -0.25 ? -1 : 0) + minus((g.news_tilt >= 0 ? "+" : "") + g.news_tilt.toFixed(2))}</td></tr>`;
  });
  t += `</tbody></table>`;
  const all = gs.flatMap((g) => g.news.latest.map((h) => ({ ...h, g: g.name }))).sort((a, b) => b.date.localeCompare(a.date)).slice(0, 14);
  return `<div class="split"><div class="card" style="display:grid;grid-template-rows:auto auto 1fr;gap:.6rem"><div class="kicker">Headline tone by sector · −1 bearish … +1 bullish</div>
      <p class="small ink2" style="margin:0">Scored with a finance word list. Tone measures mood, not meaning: "oil jumps" reads positive even for airlines. "vs norm" compares recent tone with the sector's own 12-month average.</p>${t}</div>
    <div class="card"><div class="kicker">Latest headlines</div><div class="heads" style="margin-top:.5rem">${all.map((h) => headline({ ...h, source: `${h.g} · ${h.source}` })).join("")}</div></div></div>`;
}

function vActions() {
  const d = D(), cols = { tailwind: [], watch: [], headwind: [], risk: [] };
  d.groups.forEach((g) => (g.actionables || []).forEach((a) => cols[a.kind].push({ ...a, tag: `${g.name} · ${g.primary}` })));
  return `<div class="cols4">${Object.entries(cols).map(([k, items]) => `<div class="card"><h3><span class="ic ${k}">${KIND[k][0]}</span>${KIND[k][2]} <span class="muted small" style="font-weight:400">${items.length}</span></h3>
    ${items.slice(0, 9).map((a) => `<div class="item"><div class="tag">${esc(a.tag)}</div>${esc(a.text)}${a.why ? `<div class="w">${esc(a.why)}</div>` : ""}</div>`).join("") || `<div class="muted small">None right now.</div>`}</div>`).join("")}</div>`;
}

function vModel() {
  const m = D().model, hs = ["1", "3", "6"].filter((h) => m.horizons[h]);
  if (!hs.length) return `<div class="empty-state"><h2>Model not fitted yet</h2></div>`;
  const cards = hs.map((h) => {
    const e = m.horizons[h], mx = 0.3;
    const bar = (lab, v, col) => `<span class="ink2">${lab}</span><span class="bar"><i style="left:0;width:${(v / mx) * 100}%;background:${col}"></i></span><span class="v">${v.toFixed(3)}</span>`;
    const cal = lineChart([
      { pts: [[0.3, 0.3], [0.8, 0.8]], color: PAL.base, width: 1, endDot: false },
      { pts: e.calibration.map((c) => [c.predicted, c.observed]), color: PAL.s1c, width: 1.5, dots: true, endDot: false,
        tips: e.calibration.map((c) => `Predicted ${pp(c.predicted)} → happened ${pp(c.observed)} (${c.n} cases)`) },
    ], { yFmt: (v) => pp(v), xTicks: [[0.3, "30%"], [0.5, "50%"], [0.7, "70%"]], endPad: 10 });
    const better = e.skill_vs_base > 0.005;
    return `<div class="card" style="display:grid;grid-template-rows:auto auto auto 1fr;gap:.45rem"><div class="kicker">${h}-month horizon · tested on ${e.split_year}+ (${e.n_test} cases)</div>
      <div class="wf" style="grid-template-columns:7.5rem 1fr 3.4rem">${bar("This model", e.brier_model, PAL.s1c)}${bar("Base rate only", e.brier_base, PAL.muted)}${bar("Coin flip", e.brier_coin, PAL.base)}</div>
      <div class="small ink2">Error score (Brier; lower is better). ${better ? `The model beat the plain base rate by ${pct(e.skill_vs_base, 1, false)}.` : `<b>No edge over the base rate</b>: seasonality + trend barely improve on “it goes up ${pp(e.test_up_rate)} of the time”.`} Called direction right ${pp(e.hit_rate)} of the time.</div>
      <div style="display:grid;grid-template-rows:auto 1fr;min-height:0"><div class="muted tiny">Calibration: predicted odds (x) vs how often it actually rose (y); diagonal = perfect</div>${chart(cal)}</div></div>`;
  }).join("");
  const w = m.horizons[hs.find((h) => h === "3") || hs[0]].weights;
  return `<div class="model"><div class="card explain"><div><div class="kicker">How the odds are made</div>
      <h2 style="font-size:1.4rem;margin:.2rem 0 .6rem">A logistic model, fitted on history and tested on years it never saw</h2>
      <p>For each instrument and month since 1928, it asks: given the <b>base rate</b> (how often this instrument rose over any ${hs.join("/")}-month stretch), the <b>seasonality</b> of the coming window, the <b>trend</b> (price vs its 10-month average) and <b>momentum</b> (12-month return), how often was it higher afterwards? Only data available at the time is used.</p>
      <p><b>News tone</b> (*) is added on top as a small nudge (±7 points at most). It is not backtested: there is no free archive of historical headlines to test it on.</p></div>
      <div><div class="kicker">Reading the numbers</div>
      <p>66% means: in comparable setups the price was higher about two times in three. It is still wrong one time in three. Most of the number is the base rate, because markets rise more often than they fall.</p>
      <p class="small">3-month weights: ${m.features.map((f, k) => `${f} ${w[k] >= 0 ? "+" : "−"}${Math.abs(w[k]).toFixed(2)}`).join(" · ")}. Pooled over ${m.pooled.length} series: ${m.pooled.join(", ")}.</p></div></div>
    ${cards}</div>`;
}

/* ------------------------------------------------------------------ sentiment & events */
function monthTicks(dates, every = 2) {
  const out = [];
  let last = "";
  dates.forEach((d, k) => { const m = d.slice(0, 7); if (m !== last) { if (last) out.push([k, m]); last = m; } });
  return out.filter((_, i) => i % every === 0)
    .map(([k, m]) => [k, m.endsWith("-01") ? `Jan '${m.slice(2, 4)}` : MONTHS[+m.slice(5, 7) - 1]]);
}
const ZONE_CAPS = [[25, "Extreme fear"], [45, "Fear"], [55, "Neutral"], [75, "Greed"], [101, "Extreme greed"]];
const zoneOf = (v) => (v == null ? "–" : ZONE_CAPS.find(([c]) => v < c)[1]);

function gaugeBar(v) {
  const stops = [0, 25, 45, 55, 75, 100].map((x) => `${divColor(x - 50, 50)} ${x}%`).join(",");
  return `<div><div class="gbar" style="background:linear-gradient(90deg,${stops})"><i style="left:${v}%"></i></div>
    <div class="gscale"><span>0 · extreme fear</span><span>50 · neutral</span><span>extreme greed · 100</span></div></div>`;
}

function vSentiment() {
  const s = D().sentiment;
  if (!s) {
    return `<div class="empty-state"><div class="kicker">Market sentiment</div><h2>Not enough data for the sentiment gauge yet</h2>
      <p>It needs daily prices for the S&P 500, the VIX and the sector ETFs from Yahoo Finance.</p></div>`;
  }
  const ser = s.series, dates = ser.map((r) => r[0]), xt = monthTicks(dates);
  const at = new Map(dates.map((d, i) => [d, i]));
  const hist = s.history.filter((h) => at.has(h.date));
  const good = hist.filter((h) => h.kind === "tailwind" || h.kind === "watch");
  const bad = hist.filter((h) => h.kind === "headwind" || h.kind === "risk");
  const tipFor = (h) => `${h.date}: ${h.title}${h.m3 != null ? ` · S&P ${pct(h.m3)} 3 months later`
    : h.m1 != null ? ` · S&P ${pct(h.m1)} 1 month later` : " · too recent to score"}`;
  const gaugeChart = lineChart([{ pts: ser.map((r, i) => [i, r[1]]), color: PAL.ink, width: 2, endLabel: String(Math.round(s.value)),
    tips: ser.map((r) => `${r[0]}: gauge ${r[1] ?? "–"} (${zoneOf(r[1])})`) }],
  { yDomain: [0, 100], yFmt: (v) => String(v), xTicks: xt,
    bands: [{ from: 0, to: 25, color: PAL.down, label: "Extreme fear" }, { from: 75, to: 100, color: PAL.up, label: "Extreme greed" }] });
  const marks = (list, color) => ({ pts: list.map((h) => [at.get(h.date), ser[at.get(h.date)][2]]), color, dots: true, noLine: true,
    endDot: false, r: 6, dotTips: list.map(tipFor) });
  const spxChart = lineChart([
    { pts: ser.map((r, i) => [i, r[2]]), color: PAL.ink2, width: 1.75, endLabel: px(ser.at(-1)[2]), tips: ser.map((r) => `${r[0]}: S&P 500 ${px(r[2])}`) },
    marks(good, PAL.up), marks(bad, PAL.down)], { xTicks: xt });

  const comps = s.components.map((c) => `<div class="comp${c.score == null ? " off" : ""}" data-tip="${esc(c.desc)}">
      <div><b>${esc(c.name)}</b><div class="muted tiny cdesc">${esc(c.desc)}</div></div>
      <div class="small ink2">${esc(c.text)}</div>
      <div class="cbar">${c.score == null ? "" : `<i style="width:${c.score}%;background:${divColor(c.score - 50, 50)}"></i>`}<span class="mid"></span></div>
      <b class="num">${c.score == null ? "–" : Math.round(c.score)}</b></div>`).join("");

  const sigs = [...s.signals].sort((a, b) => b.active - a.active).map((x) => {
    const r3 = x.m3;
    return `<div class="act${x.active ? "" : " dim"}"><span class="ic ${x.kind}">${KIND[x.kind][0]}</span><div>
      <div class="t">${x.active ? `<span class="kind">Active now</span>` : ""}${esc(x.title)}</div>
      <div class="w">${esc(x.why)}</div>
      <div class="w">${x.events ? `Fired ${x.events}× since ${s.first.slice(0, 4)}${r3 ? `: S&P up ${pp(r3.up)} of the time 3 months later, avg ${pct(r3.avg)}` : ""}${x.last ? ` · last ${x.last}` : ""}` : "Hasn't fired in this history"}</div></div></div>`;
  }).join("");

  const row = (lab, z, cur) => `<tr class="${cur ? "cur" : ""}"><td>${esc(lab)}</td><td>${z.days.toLocaleString("en-US")}</td>
    <td>${z.m1 ? pp(z.m1.up) : "–"}</td><td>${z.m1 ? delta(z.m1.avg) : "–"}</td><td>${z.m3 ? pp(z.m3.up) : "–"}</td><td>${z.m3 ? delta(z.m3.avg) : "–"}</td></tr>`;
  const bt = `<table class="lt bt"><thead><tr><th>Gauge reading</th><th>Days</th><th>Up 1M later</th><th>Avg 1M</th><th>Up 3M later</th><th>Avg 3M</th></tr></thead>
    <tbody>${s.zones.map((z) => row(z.zone, z, z.current)).join("")}${row("All days", s.baseline, false)}</tbody></table>`;

  return `<div class="sx">
    <div class="sx-head"><div><div class="kicker">Market sentiment · built from prices · as of ${esc(s.asof)}</div><h2>Fear & greed gauge</h2></div>
      <div class="muted small">${s.available}/8 components · each scored against its own past year</div></div>
    <div class="card" style="display:grid;grid-template-rows:auto auto 1fr auto 1fr;gap:.35rem">
      <div style="display:flex;align-items:flex-end;gap:1.4rem"><div class="big">${Math.round(s.value)}</div>
        <div><div style="font-size:1.4rem;font-weight:650">${esc(s.zone)}</div><div class="ink2 small">${s.chg_1w != null ? `${delta(s.chg_1w / 100, 0).replace("%", " pts")} in a week` : ""}${s.chg_1m != null ? ` · ${delta(s.chg_1m / 100, 0).replace("%", " pts")} in a month` : ""}</div></div></div>
      ${gaugeBar(s.value)}
      ${chart(gaugeChart)}
      <div class="legend-row"><span><i style="background:${PAL.ink2}"></i>S&P 500</span><span><i style="background:${PAL.up};height:.6rem;width:.6rem;border-radius:50%"></i>bullish signal</span><span><i style="background:${PAL.down};height:.6rem;width:.6rem;border-radius:50%"></i>bearish signal</span><span class="muted">hover a dot for what followed</span></div>
      ${chart(spxChart)}
    </div>
    <div class="col" style="grid-template-rows:auto 1fr">
      <div class="card"><div class="kicker">Components (0 fear … 100 greed)</div>${comps}</div>
      <div class="card"><div class="kicker">What the S&P did next, by gauge reading · since ${esc(s.first.slice(0, 4))}</div>${bt}
        <div class="muted tiny" style="margin-top:.4rem">Every trading day counts, so neighbouring days overlap: read these as tendencies, not independent trials.</div></div>
    </div>
    <div class="card"><div class="kicker">Inflection signals</div><div class="acts" style="margin-top:.45rem">${sigs}</div></div>
  </div>`;
}

const STATUS = { Spike: ["⚡", "var(--crit)"], Elevated: ["▲", "var(--warn)"], Normal: ["●", "var(--muted)"], Quiet: ["○", "var(--muted)"] };

function vEvents() {
  const r = D().radar, st = D().status;
  if (!r) {
    return `<div class="empty-state"><div class="kicker">News & events radar</div><h2>No news coverage data yet</h2>
      <p>Coverage and tone come from the GDELT global news database (<code>api.gdeltproject.org</code>), with Google News as a fallback for headlines.</p>
      ${st.events_error ? `<p class="small"><b>Last error:</b> ${esc(st.events_error)}</p>` : ""}</div>`;
  }
  const themes = [...r.themes].sort((a, b) => (b.attention ?? 0) - (a.attention ?? 0));
  const rows = themes.map((t) => `<tr>
      <td><b>${esc(t.name)}</b></td>
      <td style="height:2.1rem;padding:0;width:10rem">${t.volume.length ? chart(sparkline(t.volume.map((v) => v[1]), PAL.ink2)) : ""}</td>
      <td class="num">${t.attention != null ? t.attention.toFixed(1) + "×" : "–"}</td>
      <td>${t.status ? `<span style="color:${STATUS[t.status][1]}">${STATUS[t.status][0]}</span> ${t.status}` : "–"}</td>
      <td>${t.tone_trend ? `${sigGlyph(t.tone_trend === "improving" ? 1 : t.tone_trend === "worsening" ? -1 : 0)}${t.tone_trend}` : "–"}</td>
      <td class="hl-cell">${t.headlines.slice(0, 2).map((h) => `<div>${esc(h.title)} <span class="muted tiny">${esc(h.source || "")} · ${esc(h.date.slice(5))}</span></div>`).join("")}</td></tr>`).join("");
  const idx = r.index;
  let mood = "";
  if (idx.length > 10) {
    const m = Math.max(0.5, ...idx.map((x) => Math.abs(x[1]))) * 1.15, now = idx.at(-1)[1], wk = idx.at(-8)?.[1];
    mood = `<div class="card" style="display:grid;grid-template-rows:auto auto 1fr;gap:.35rem"><div class="kicker">News mood index · 90 days</div>
      <div class="small ink2"><b style="font-size:1.6rem;color:var(--ink)">${minus((now >= 0 ? "+" : "") + now.toFixed(2))}</b>
        ${now >= 0 ? "better" : "worse"} than the usual tone for these themes${wk != null ? ` · ${minus((now - wk >= 0 ? "+" : "") + (now - wk).toFixed(2))} in a week` : ""}</div>
      ${chart(lineChart([{ pts: idx.map((x, i) => [i, x[1]]), color: PAL.ink, width: 2, tips: idx.map((x) => `${x[0]}: ${x[1]}`) }],
        { yDomain: [-m, m], zero: true, yFmt: (v) => v.toFixed(1), xTicks: monthTicks(idx.map((x) => x[0]), 1),
          bands: [{ from: 0, to: m, color: PAL.up, label: "Better than usual" }, { from: -m, to: 0, color: PAL.down, label: "Worse than usual" }] }))}</div>`;
  }
  const by = Object.fromEntries(r.themes.map((t) => [t.id, t]));
  const hot = [...new Set([...r.alerts, ...r.tone_shifts])].map((id) => by[id]);
  const alerts = hot.map((t) => `<div class="item"><div class="tag">${t.status ? `<span style="color:${STATUS[t.status][1]}">${STATUS[t.status][0]}</span> ` : ""}${esc(t.name)} · coverage ${t.attention ?? "–"}× normal · tone ${esc(t.tone_trend || "–")}</div>
      ${t.headlines.slice(0, 2).map((h) => `<div>${esc(h.title)} <span class="muted tiny">${esc(h.source || "")} · ${esc(h.date)}</span></div>`).join("")}</div>`).join("")
    || `<div class="muted small">No theme is spiking or shifting tone right now.</div>`;
  return `<div class="ev-grid">
    <div class="card" style="overflow:hidden"><div class="kicker">News & events radar · ${esc(r.source)}</div>
      <p class="small ink2" style="margin:.3rem 0 .5rem">Coverage = the theme's share of all news vs its own last 2 months (2× or more = a major event). Tone = average article tone over 7 days vs the previous 2 months.</p>
      <table class="lt ev"><thead><tr><th>Theme</th><th>Coverage, 90 days</th><th>vs normal</th><th>Status</th><th>Tone</th><th>Latest headlines</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="col" style="grid-template-rows:1fr auto">${mood}<div class="card"><div class="kicker">Alerts</div>${alerts}</div></div>
  </div>`;
}

/* ------------------------------------------------------------------ chrome */
function buildPlaylist() {
  const d = D();
  S.focusGroups = d.groups.filter((g) => g.primary);
  const pin = params.get("view");
  if (pin && VIEW_NAMES[pin]) {
    const g = params.get("group");
    S.playlist = [{ v: pin, part: +(params.get("part") || 1) - 1, parts: 1, g: g && groupById(g)?.primary ? g : S.focusGroups[0]?.id }];
    return;
  }
  const hp = pages(heatSyms).length, lp = pages((g) => g.available).length;
  const base = [["overview"], ["sentiment"], ["heatmap", 0], ["events"], ["almanac"], ["longterm", 0], ["actions"], ["heatmap", 1],
    ["news"], ["longterm", 1], ["model"]]
    .filter(([v, part]) => !(v === "heatmap" && part >= hp) && !(v === "longterm" && part >= lp));
  const pl = [];
  let fi = 0;
  base.forEach(([v, part]) => {
    if (v === "almanac" && !d.sp500) return;
    pl.push({ v, part: part || 0, parts: v === "heatmap" ? hp : v === "longterm" ? lp : 1 });
    if (S.focusGroups.length) { pl.push({ v: "focus", g: S.focusGroups[fi % S.focusGroups.length].id }); fi++; }
  });
  // make sure every sector gets a turn
  while (fi < S.focusGroups.length) { pl.push({ v: "focus", g: S.focusGroups[fi].id }); fi++; }
  S.playlist = pl;
}

function render() {
  if (!S.data) return;
  palette();
  S.charts = [];
  const item = S.playlist[S.pos % S.playlist.length];
  let html, title = VIEW_NAMES[item.v];
  try {
    switch (item.v) {
      case "overview": html = vOverview(); break;
      case "heatmap": html = vHeatmap(item.part); break;
      case "focus": { const g = groupById(item.g); html = g ? vFocus(g) : vOverview(); title = `Sector focus · ${g?.name}`; break; }
      case "almanac": html = vAlmanac(); break;
      case "longterm": html = vLongterm(item.part); break;
      case "news": html = vNews(); break;
      case "actions": html = vActions(); break;
      case "model": html = vModel(); break;
      case "sentiment": html = vSentiment(); break;
      case "events": html = vEvents(); break;
    }
  } catch (e) {
    console.error(e);
    html = `<div class="empty-state"><h2>Couldn't draw this view</h2><p>${esc(e.message)}</p></div>`;
  }
  $("#main").innerHTML = `<div class="view">${html}</div>`;
  S.title = item.parts > 1 ? `${title} · ${item.part + 1} of ${item.parts}` : title;
  showTitle();
  $("#dots").innerHTML = VIEW_KEYS.filter((k) => S.playlist.some((p) => p.v === k)).map((k) =>
    `<button class="${k === item.v ? "on" : ""}" data-v="${k}" title="${VIEW_NAMES[k]}" aria-label="${VIEW_NAMES[k]}"></button>`).join("");
  requestAnimationFrame(renderCharts);
  S.started = performance.now();
}

function renderStatus() {
  const d = D(), st = d.status;
  const ok = st.loaded >= st.total - 2, newsOk = st.news_groups > 0;
  const asof = Object.values(d.instruments).map((i) => i.snap.asof).sort().at(-1) || "";
  const sv = d.sentiment;
  $("#status").innerHTML = `${sv ? `<span class="pill" data-tip="Market sentiment gauge: 0 = extreme fear, 100 = extreme greed"><i style="background:${divColor(sv.value - 50, 50)}"></i>Sentiment ${Math.round(sv.value)} · ${esc(sv.zone)}</span>` : ""}
    <span>Data to ${esc(asof)}</span>
    <span class="pill" data-tip="${esc(st.missing.length ? (st.hint ? st.hint + " " : "") + "Not loaded: " + st.missing.join(", ") : "All series loaded")}"><i style="background:${ok ? "var(--good)" : "var(--warn)"}"></i>${st.loaded}/${st.total} series</span>
    <span class="pill" data-tip="${esc(st.news_error || "")}"><i style="background:${newsOk ? "var(--good)" : "var(--warn)"}"></i>${newsOk ? `news ${st.news_groups}/${st.news_total}` : "news offline"}</span>`;
  const tape = Object.values(d.instruments).filter((i) => i.sym !== "SPY").map((i) => {
    const ch = i.snap.d1 ?? i.snap.m1, lab = i.snap.d1 != null ? "1D" : "1M";
    return `<span><b>${esc(i.name)}</b>${px(i.snap.price)} ${delta(ch)} <span class="muted">${lab}</span></span>`;
  });
  const heads = d.groups.filter((g) => g.news).flatMap((g) => g.news.latest.slice(0, 2).map((h) => `<span class="hl">${esc(g.name)}: ${esc(h.title)}</span>`));
  const rad = d.radar, byId = Object.fromEntries((rad?.themes || []).map((t) => [t.id, t]));
  const alerts = (rad?.alerts || []).map((id) => byId[id]).map((t) =>
    `<span class="hl">⚡ ${esc(t.name)}: coverage ${t.attention}× normal${t.headlines[0] ? " · " + esc(t.headlines[0].title) : ""}</span>`);
  const items = [...alerts, ...tape, ...heads].join("");
  const el = $("#tape");
  el.innerHTML = items;
  el.style.animationDuration = Math.max(40, (tape.length + heads.length * 3) * 4) + "s";
}

function clock() {
  const now = new Date();
  const local = now.toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const ny = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "short", hour: "numeric", minute: "2-digit", hour12: false }).formatToParts(now);
  const get = (t) => ny.find((p) => p.type === t)?.value;
  const mins = +get("hour") % 24 * 60 + +get("minute"), wd = get("weekday");
  const open = !["Sat", "Sun"].includes(wd) && mins >= 570 && mins < 960;
  $("#clock").textContent = `${local} · New York ${get("hour").padStart(2, "0")}:${get("minute")} · NYSE ${open ? "open" : "closed"}`;
}

function tick() {
  if (!S.data || S.playlist.length < 2) { $("#progress").style.width = "0"; return; }
  const el = (performance.now() - S.started) / 1000;
  $("#progress").style.width = S.paused ? "0" : Math.min(100, (el / DWELL) * 100) + "%";
  if (!S.paused && el >= DWELL) step(1);
}

function step(n) { S.pos = (S.pos + n + S.playlist.length) % S.playlist.length; render(); }
function jump(v) {
  const L = S.playlist.length;
  for (let k = 1; k <= L; k++) { const p = (S.pos + k) % L; if (S.playlist[p].v === v) { S.pos = p; render(); return; } }
}

async function load() {
  try {
    const r = await fetch("/api/data", { cache: "no-store" });
    if (r.status === 503) {
      const st = await (await fetch("/api/status")).json();
      $("#main").innerHTML = `<div class="empty-state"><h2>Building the first data snapshot…</h2><p class="small muted" style="text-align:left;white-space:pre-line">${esc((st.log || []).slice(-8).join("\n"))}</p></div>`;
      setTimeout(load, 3000);
      return;
    }
    const d = await r.json();
    const fresh = !S.data || d.generated_at !== S.data.generated_at;
    S.data = d;
    if (fresh) {
      const cur = S.playlist[S.pos];
      buildPlaylist();
      const keep = cur ? S.playlist.findIndex((p) => p.v === cur.v && p.g === cur.g && p.part === cur.part) : -1;
      S.pos = keep >= 0 ? keep : 0;
      palette(); renderStatus(); render();
    }
  } catch (e) {
    console.error(e);
    if (!S.data) $("#main").innerHTML = `<div class="empty-state"><h2>Can't reach the data server</h2><p>Start it with <code>python3 server.py</code>.</p></div>`;
  }
  setTimeout(load, 5 * 60 * 1000);
}

/* ------------------------------------------------------------------ events */
function showTitle() { $("#vtitle").textContent = (S.title || "") + (S.paused ? " · paused" : ""); }
function togglePause() { S.paused = !S.paused; S.started = performance.now(); showTitle(); }

// Capture phase, so nothing else on the page can swallow the keys. PageUp/PageDown are what
// presentation clickers send.
window.addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey || !S.data) return;
  const k = e.key;
  if (["ArrowRight", "ArrowDown", "PageDown", "n", "j"].includes(k)) step(1);
  else if (["ArrowLeft", "ArrowUp", "PageUp", "p", "k"].includes(k)) step(-1);
  else if (k === " " || k === "Spacebar") togglePause();
  else if (k === "f") document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
  else if (/^[0-9]$/.test(k)) jump(VIEW_KEYS[(+k + 9) % 10]);
  else return;
  e.preventDefault();
}, true);
document.addEventListener("click", (e) => {
  const b = e.target.closest(".dots button");
  if (b) jump(b.dataset.v);
  else if (e.target.closest("#prev")) step(-1);
  else if (e.target.closest("#next")) step(1);
  else if (e.target.closest("#vtitle")) togglePause();
});
let touchX = null, touchY = null;
document.addEventListener("touchstart", (e) => { touchX = e.touches[0].clientX; touchY = e.touches[0].clientY; }, { passive: true });
document.addEventListener("touchend", (e) => {
  if (touchX == null) return;
  const dx = e.changedTouches[0].clientX - touchX, dy = e.changedTouches[0].clientY - touchY;
  if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) step(dx < 0 ? 1 : -1);
  touchX = null;
}, { passive: true });
let idleT;
function wake() { document.body.classList.remove("idle"); clearTimeout(idleT); idleT = setTimeout(() => document.body.classList.add("idle"), 3000); }
document.addEventListener("pointerdown", wake);
document.addEventListener("mousemove", (e) => {
  wake();
  const t = e.target.closest("[data-tip]"), tip = $("#tip");
  if (t && t.dataset.tip) {
    tip.textContent = t.dataset.tip; tip.style.display = "block";
    const r = tip.getBoundingClientRect();
    tip.style.left = Math.min(innerWidth - r.width - 8, e.clientX + 14) + "px";
    tip.style.top = Math.min(innerHeight - r.height - 8, e.clientY + 14) + "px";
  } else tip.style.display = "none";
});
let rz;
addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { if (S.data) render(); }, 200); });
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => S.data && (palette(), renderStatus(), render()));

clock(); setInterval(clock, 15000);
wake();
setInterval(tick, 250);
load();
