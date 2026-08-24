"""수집된 시세로 정적 대시보드 HTML을 만든다 (PRD F1~F5).

    python src/build.py            # out/dashboard.html 생성
    python src/build.py --open     # 생성 후 브라우저로 열기

표준 라이브러리만 사용한다. 산출물은 자체 완결형이라 파일 하나만 옮기면
어디서든 열린다.
"""

import argparse
import datetime as dt
import html
import json
import sqlite3
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "prices.sqlite"
CONFIG_PATH = ROOT / "config" / "items.json"
OUT_PATH = ROOT / "out" / "dashboard.html"

STALE_DAYS = 3  # 마지막 거래일이 이보다 오래되면 갱신 실패로 간주 (F13)

# 품목 필터. f-string 밖에 둬서 중괄호를 이스케이프하지 않아도 되게 한다.
SCRIPT = """
<script>
(function () {
  var KEY = 'garak-dash-items';
  var boxes = Array.prototype.slice.call(document.querySelectorAll('.item-cb'));
  var sectorChips = Array.prototype.slice.call(document.querySelectorAll('.chip.sector'));
  var all = boxes.map(function (c) { return c.dataset.item; });
  var sectorOf = {};
  boxes.forEach(function (c) { sectorOf[c.dataset.item] = c.dataset.sector; });

  var sel;
  try {
    var saved = JSON.parse(localStorage.getItem(KEY));
    // 저장된 선택 중 지금도 존재하는 품목만 살린다 (품목 구성이 바뀌어도 안전)
    sel = Array.isArray(saved) ? saved.filter(function (i) { return all.indexOf(i) > -1; }) : all.slice();
    if (!sel.length) sel = all.slice();
  } catch (e) { sel = all.slice(); }

  function has(i) { return sel.indexOf(i) > -1; }

  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(sel)); } catch (e) {}
  }

  function apply() {
    document.querySelectorAll('tr[data-item]').forEach(function (tr) {
      tr.hidden = !has(tr.dataset.item);
    });

    var shownAlerts = 0;
    document.querySelectorAll('.alert-card[data-item]').forEach(function (el) {
      var on = has(el.dataset.item);
      el.hidden = !on;
      if (on) shownAlerts++;
    });

    var grid = document.getElementById('alertGrid');
    var none = document.getElementById('alertNone');
    if (grid) grid.hidden = shownAlerts === 0;
    if (none) none.hidden = shownAlerts > 0;

    document.getElementById('tableWrap').hidden = sel.length === 0;
    document.getElementById('emptyMsg').hidden = sel.length > 0;

    boxes.forEach(function (c) { c.checked = has(c.dataset.item); });
    document.getElementById('ddCount').textContent = sel.length + ' / ' + all.length;
    sectorChips.forEach(function (c) {
      var kids = all.filter(function (i) { return sectorOf[i] === c.dataset.sector; });
      c.classList.toggle('on', kids.length > 0 && kids.every(has));
    });

    var counts = {};
    sel.forEach(function (i) { counts[sectorOf[i]] = (counts[sectorOf[i]] || 0) + 1; });
    var parts = Object.keys(counts).map(function (s) { return s + ' ' + counts[s]; });
    document.getElementById('countLabel').textContent =
      '선택 ' + sel.length + '품목' + (parts.length ? ' (' + parts.join(' / ') + ')' : '');

    save();
  }

  boxes.forEach(function (c) {
    c.addEventListener('change', function () {
      var i = c.dataset.item;
      if (c.checked) { if (!has(i)) sel = sel.concat([i]); }
      else sel = sel.filter(function (x) { return x !== i; });
      apply();
    });
  });

  // 드롭다운 바깥을 누르면 닫는다
  var dd = document.getElementById('itemDd');
  document.addEventListener('click', function (e) {
    if (dd.open && !dd.contains(e.target)) dd.open = false;
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && dd.open) dd.open = false;
  });

  sectorChips.forEach(function (c) {
    c.addEventListener('click', function () {
      var kids = all.filter(function (i) { return sectorOf[i] === c.dataset.sector; });
      if (kids.every(has)) sel = sel.filter(function (i) { return kids.indexOf(i) === -1; });
      else sel = sel.concat(kids.filter(function (i) { return !has(i); }));
      apply();
    });
  });

  document.getElementById('selAll').addEventListener('click', function () { sel = all.slice(); apply(); });
  document.getElementById('selNone').addEventListener('click', function () { sel = []; apply(); });

  apply();
})();
</script>
"""


# --------------------------------------------------------------------------- 데이터

def load_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def load_series(conn: sqlite3.Connection, item_cd: str, days: int) -> list[tuple[str, int]]:
    """휴장일(is_carry)을 제외한 (일자, 평균가) 시계열."""
    rows = conn.execute(
        """SELECT trade_date, avg_price FROM price_daily
           WHERE item_cd=? AND is_carry=0 AND avg_price IS NOT NULL
           ORDER BY trade_date DESC LIMIT ?""",
        (item_cd, days),
    ).fetchall()
    return list(reversed(rows))


def load_latest(conn: sqlite3.Connection, item_cd: str) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT * FROM price_daily
           WHERE item_cd=? AND is_carry=0 ORDER BY trade_date DESC LIMIT 1""",
        (item_cd,),
    ).fetchone()


def load_year_ago(conn: sqlite3.Connection, item_cd: str, ref_date: str) -> int | None:
    """전년 동일 시점의 평균가. 정확히 같은 날이 없으면 전후 5일 내 최근접."""
    ref = dt.date.fromisoformat(ref_date).replace(year=dt.date.fromisoformat(ref_date).year - 1)
    row = conn.execute(
        """SELECT avg_price, ABS(JULIANDAY(trade_date) - JULIANDAY(?)) AS d
           FROM price_daily
           WHERE item_cd=? AND is_carry=0 AND avg_price IS NOT NULL AND d <= 5
           ORDER BY d LIMIT 1""",
        (ref.isoformat(), item_cd),
    ).fetchone()
    return row[0] if row else None


def pct_change(avg: int | None, gap: int | None) -> float | None:
    """전일대비 변동률. gap은 '전일대비 증감액'이므로 전일가 = avg - gap."""
    if avg is None or gap is None:
        return None
    prev = avg - gap
    return None if prev <= 0 else gap / prev * 100


def discover_items(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """최신 거래일에 실제로 존재하는 품목을 DB에서 찾아온다.

    config는 허용목록이 아니라 '이름·MC 매핑' 레이어다. 공사가 노출 품목을
    바꾸면 매핑이 없어도 대시보드에 자동으로 나타난다 (미매핑으로 표시).
    """
    latest = conn.execute(
        "SELECT MAX(trade_date) FROM price_daily WHERE is_carry=0"
    ).fetchone()[0]
    if latest is None:
        return []
    return conn.execute(
        """SELECT item_cd, item_nm FROM price_daily
           WHERE trade_date=? AND is_carry=0 ORDER BY item_cd""",
        (latest,),
    ).fetchall()


def build_rows(conn: sqlite3.Connection, cfg: dict) -> tuple[list[dict], str | None, list[str]]:
    defaults = cfg["defaults"]
    mapping = {str(i["item_cd"]): i for i in cfg["items"]}
    out: list[dict] = []
    latest_date: str | None = None
    unmapped: list[str] = []

    for item_cd, item_nm in discover_items(conn):
        cfg_item = mapping.get(item_cd)
        if cfg_item is None:
            cfg_item = {
                "item_cd": item_cd, "label": item_nm or item_cd,
                "mc_cd": "—", "mc_nm": "MC 미매핑", "buy_grp": "DBA", "sector": "미분류",
            }
            unmapped.append(f"{item_cd} {item_nm}")
        elif not cfg_item.get("watch", True):
            continue
        item = cfg_item

        cur = load_latest(conn, item_cd)
        if cur is None:
            continue
        keys = [d[0] for d in conn.execute("SELECT * FROM price_daily LIMIT 0").description]
        cur = dict(zip(keys, cur))
        if latest_date is None or cur["trade_date"] > latest_date:
            latest_date = cur["trade_date"]

        series = load_series(conn, item["item_cd"], defaults["chart_days"])
        yoy_avg = load_year_ago(conn, item["item_cd"], cur["trade_date"])
        pct = pct_change(cur["avg_price"], cur["price_gap"])
        yoy_pct = (cur["avg_price"] - yoy_avg) / yoy_avg * 100 if yoy_avg else None

        out.append({
            **item,
            "trade_date": cur["trade_date"],
            "unit_nm": cur["unit_nm"],
            "grade_nm": cur["grade_nm"],
            "low": cur["low_price"], "avg": cur["avg_price"], "max": cur["max_price"],
            "gap": cur["price_gap"], "pct": pct,
            "yoy_avg": yoy_avg, "yoy_pct": yoy_pct,
            "series": series,
            "threshold": item.get("alert_pct", defaults["alert_pct"]),
        })

    out.sort(key=lambda r: abs(r["pct"] or 0), reverse=True)
    return out, latest_date, unmapped


# --------------------------------------------------------------------------- 렌더링

def sparkline(series: list[tuple[str, int]], up: bool) -> str:
    """30일 평균가 추이 인라인 SVG."""
    if len(series) < 2:
        return '<div class="spark-empty">데이터 부족</div>'
    vals = [v for _, v in series]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    w, h, pad = 260, 52, 4
    step = w / (len(vals) - 1)
    pts = " ".join(
        f"{i * step:.1f},{pad + (h - 2 * pad) * (1 - (v - lo) / span):.1f}"
        for i, v in enumerate(vals)
    )
    cls = "up" if up else "down"
    last_x, last_y = pts.split()[-1].split(",")
    return (
        f'<svg class="spark {cls}" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" '
        f'aria-label="최근 {len(vals)}거래일 평균가 추이">'
        f'<polyline points="{pts}"/>'
        f'<circle cx="{last_x}" cy="{last_y}" r="2.8"/></svg>'
    )


def fmt(n: int | None) -> str:
    return "—" if n is None else f"{n:,}"


def fmt_pct(p: float | None, sign: bool = True) -> str:
    if p is None:
        return "—"
    return f"{p:+.1f}%" if sign else f"{p:.1f}%"


def cls_of(p: float | None) -> str:
    if p is None:
        return "flat"
    return "up" if p > 0 else "down" if p < 0 else "flat"


def render_alert_card(r: dict) -> str:
    return f"""      <div class="alert-card {cls_of(r['pct'])}" data-item="{r['item_cd']}" data-sector="{html.escape(r['sector'])}">
        <div class="alert-name">{html.escape(r['label'])}</div>
        <div class="alert-pct">{fmt_pct(r['pct'])}</div>
        <div class="alert-sub">평균 {fmt(r['avg'])}원 / {html.escape(r['unit_nm'] or '')}
          <span class="gap">{fmt_pct(None) if r['gap'] is None else f"{r['gap']:+,}원"}</span></div>
      </div>"""


def render_row(r: dict) -> str:
    return f"""        <tr data-item="{r['item_cd']}" data-sector="{html.escape(r['sector'])}">
          <td class="c-item">
            <span class="item-name">{html.escape(r['label'])}</span>
            <span class="mc">{html.escape(r['mc_cd'])} {html.escape(r['mc_nm'])}</span>
          </td>
          <td class="c-sector"><span class="badge {r['buy_grp']}">{html.escape(r['sector'])}</span></td>
          <td class="c-unit">{html.escape(r['unit_nm'] or '—')} · {html.escape(r['grade_nm'] or '')}</td>
          <td class="num">{fmt(r['low'])}</td>
          <td class="num strong">{fmt(r['avg'])}</td>
          <td class="num">{fmt(r['max'])}</td>
          <td class="num {cls_of(r['pct'])}">{'—' if r['gap'] is None else f"{r['gap']:+,}"}</td>
          <td class="num {cls_of(r['pct'])} strong">{fmt_pct(r['pct'])}</td>
          <td class="num {cls_of(r['yoy_pct'])}">{fmt_pct(r['yoy_pct'])}</td>
          <td class="c-spark">{sparkline(r['series'], (r['pct'] or 0) >= 0)}</td>
        </tr>"""


def render(rows: list[dict], latest_date: str | None, generated: str, stale: bool,
           unmapped: list[str]) -> str:
    alerts = [r for r in rows if r["pct"] is not None and abs(r["pct"]) >= r["threshold"]]
    veg = sum(1 for r in rows if r["buy_grp"] == "DBA")

    banner = ""
    if stale:
        banner += (f'<div class="banner err">⚠ 갱신 실패 — 마지막 확인 거래일이 '
                   f'<b>{latest_date or "없음"}</b> 입니다. logs/collect.log 를 확인하세요.</div>')
    if unmapped:
        names = html.escape(", ".join(unmapped))
        banner += (f'<div class="banner warn">신규 품목이 감지되었습니다: <b>{names}</b><br>'
                   f'config/items.json 에 자사 MC 매핑을 추가하면 부문·MC가 함께 표시됩니다.</div>')

    # 경보 카드는 전부 렌더링하고, 필터에 따라 JS가 보이고 감춘다.
    alert_block = (
        '<div class="alert-grid" id="alertGrid">'
        + "\n".join(render_alert_card(r) for r in alerts)
        + "</div>\n"
        + '  <div class="alert-none" id="alertNone" hidden>선택한 품목 중 임계치를 넘은 품목이 없습니다.</div>'
    )

    sectors: list[str] = []
    for r in rows:
        if r["sector"] not in sectors:
            sectors.append(r["sector"])

    sector_chips = "\n".join(
        f'      <button type="button" class="chip sector" data-sector="{html.escape(s)}">'
        f'{html.escape(s)} <span class="n">{sum(1 for r in rows if r["sector"] == s)}</span></button>'
        for s in sectors
    )
    # 드롭다운은 전일 변동률 내림차순 (급등 → 급락) 으로 배치한다.
    by_pct = sorted(rows, key=lambda x: (x["pct"] is None, -(x["pct"] or 0)))
    item_options = "\n".join(
        f'          <label class="dd-opt" data-sector="{html.escape(r["sector"])}">'
        f'<input type="checkbox" class="item-cb" data-item="{r["item_cd"]}" '
        f'data-sector="{html.escape(r["sector"])}">'
        f'<span class="dd-nm">{html.escape(r["label"])}</span>'
        f'<span class="dd-pct {cls_of(r["pct"])}">{fmt_pct(r["pct"])}</span></label>'
        for r in by_pct
    )

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>가락시장 도매시세 — 농산</title>
<style>
:root {{
  --bg:#f6f7f9; --card:#fff; --ink:#16191d; --muted:#6b7280; --line:#e3e6ea;
  --up:#d0342c; --down:#1257c4; --flat:#6b7280;
  --dba:#2f7d4f; --dca:#b26a00; --dia:#5b53b8;
  --shadow:0 1px 2px rgba(16,24,40,.06),0 1px 3px rgba(16,24,40,.1);
}}
@media (prefers-color-scheme:dark) {{
  :root {{ --bg:#14171a; --card:#1c2024; --ink:#e8eaed; --muted:#9aa3ad; --line:#2b3136;
           --up:#ff6b60; --down:#6ea8ff; --dba:#5cbb82; --dca:#e0a03c; --dia:#9b93f0;
           --shadow:0 1px 3px rgba(0,0,0,.4); }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:28px 22px 60px; background:var(--bg); color:var(--ink);
  font:14px/1.55 "Pretendard","Malgun Gothic",-apple-system,system-ui,sans-serif;
  -webkit-font-smoothing:antialiased; }}
.wrap {{ max-width:1180px; margin:0 auto; }}
h1 {{ font-size:21px; font-weight:700; margin:0 0 4px; letter-spacing:-.2px; }}
.meta {{ color:var(--muted); font-size:12.5px; margin-bottom:22px; }}
.meta b {{ color:var(--ink); font-weight:600; }}
h2 {{ font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:.6px;
  color:var(--muted); margin:26px 0 11px; }}
.banner {{ padding:11px 14px; border-radius:8px; margin-bottom:18px; font-size:13px; }}
.banner.err {{ background:#fdecec; color:#8c1d18; border:1px solid #f3c0bd; }}
.banner.warn {{ background:#fff6e0; color:#6b4a00; border:1px solid #f0d79a; }}
.banner + .banner {{ margin-top:-8px; }}
@media (prefers-color-scheme:dark) {{
  .banner.err {{ background:#3a1b1a; color:#ffb4ab; border-color:#5c2a27; }}
  .banner.warn {{ background:#33290f; color:#f5cd6b; border-color:#544218; }}
}}

.filters {{ background:var(--card); border:1px solid var(--line); border-radius:11px;
  padding:13px 15px; box-shadow:var(--shadow); margin-bottom:6px; }}
.filter-row {{ display:flex; align-items:center; flex-wrap:wrap; gap:6px; }}
.filter-row + .filter-row {{ margin-top:10px; padding-top:10px; border-top:1px solid var(--line); }}
.flabel {{ font-size:11.5px; font-weight:650; color:var(--muted); letter-spacing:.4px;
  min-width:34px; margin-right:4px; }}
.chip {{ font:inherit; font-size:12.5px; padding:4px 11px; border-radius:20px; cursor:pointer;
  border:1px solid var(--line); background:transparent; color:var(--ink);
  transition:background .12s,border-color .12s,opacity .12s; }}
.chip:hover {{ border-color:var(--muted); }}
.chip.on {{ background:var(--ink); color:var(--card); border-color:var(--ink); font-weight:600; }}
.chip .n {{ opacity:.55; font-size:11px; margin-left:2px; }}
.chip.sector.on .n {{ opacity:.7; }}
.spacer {{ flex:1 1 auto; }}

.dd {{ position:relative; }}
.dd > summary {{ list-style:none; cursor:pointer; font-size:12.5px; padding:5px 12px;
  border:1px solid var(--line); border-radius:8px; display:inline-flex; align-items:center; gap:7px;
  user-select:none; }}
.dd > summary::-webkit-details-marker {{ display:none; }}
.dd > summary::after {{ content:"▾"; font-size:10px; color:var(--muted); }}
.dd[open] > summary {{ border-color:var(--muted); }}
.dd > summary:hover {{ border-color:var(--muted); }}
.dd-count {{ font-size:11.5px; color:var(--muted); font-variant-numeric:tabular-nums; }}
.dd-panel {{ position:absolute; z-index:20; top:calc(100% + 5px); left:0; min-width:262px;
  max-height:340px; overflow-y:auto; background:var(--card); border:1px solid var(--line);
  border-radius:9px; box-shadow:0 8px 24px rgba(16,24,40,.16); padding:5px; }}
@media (prefers-color-scheme:dark) {{ .dd-panel {{ box-shadow:0 8px 24px rgba(0,0,0,.55); }} }}
.dd-hint {{ font-size:10.5px; color:var(--muted); padding:5px 9px 6px; letter-spacing:.3px;
  border-bottom:1px solid var(--line); margin-bottom:3px; }}
.dd-opt {{ display:flex; align-items:center; gap:9px; padding:6px 9px; border-radius:6px;
  cursor:pointer; font-size:13px; }}
.dd-opt:hover {{ background:var(--bg); }}
.dd-opt input {{ margin:0; accent-color:var(--dba); width:14px; height:14px; cursor:pointer; }}
.dd-nm {{ flex:1 1 auto; }}
.dd-pct {{ font-size:12px; font-variant-numeric:tabular-nums; font-weight:600; }}
.link {{ font:inherit; font-size:12px; color:var(--muted); background:none; border:none;
  cursor:pointer; padding:4px 6px; text-decoration:underline; text-underline-offset:2px; }}
.link:hover {{ color:var(--ink); }}
.empty {{ background:var(--card); border:1px solid var(--line); border-radius:11px;
  padding:22px; text-align:center; color:var(--muted); box-shadow:var(--shadow); }}

.alert-grid {{ display:grid; gap:11px; grid-template-columns:repeat(auto-fill,minmax(184px,1fr)); }}
.alert-card {{ background:var(--card); border:1px solid var(--line); border-left:4px solid var(--flat);
  border-radius:9px; padding:13px 15px; box-shadow:var(--shadow); }}
.alert-card.up {{ border-left-color:var(--up); }}
.alert-card.down {{ border-left-color:var(--down); }}
.alert-name {{ font-weight:650; font-size:14.5px; }}
.alert-pct {{ font-size:25px; font-weight:700; letter-spacing:-.5px; margin:2px 0 3px;
  font-variant-numeric:tabular-nums; }}
.alert-card.up .alert-pct {{ color:var(--up); }}
.alert-card.down .alert-pct {{ color:var(--down); }}
.alert-sub {{ font-size:12px; color:var(--muted); }}
.alert-sub .gap {{ margin-left:5px; }}
.alert-none {{ background:var(--card); border:1px solid var(--line); border-radius:9px;
  padding:15px; color:var(--muted); box-shadow:var(--shadow); }}

.table-wrap {{ background:var(--card); border:1px solid var(--line); border-radius:11px;
  box-shadow:var(--shadow); overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; min-width:900px; }}
th {{ text-align:left; font-size:11.5px; font-weight:650; color:var(--muted); letter-spacing:.3px;
  padding:11px 13px; border-bottom:1px solid var(--line); white-space:nowrap; }}
td {{ padding:11px 13px; border-bottom:1px solid var(--line); vertical-align:middle; }}
tr:last-child td {{ border-bottom:none; }}
th.num, td.num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
td.strong {{ font-weight:650; }}
.item-name {{ font-weight:600; display:block; }}
.mc {{ font-size:11px; color:var(--muted); font-variant-numeric:tabular-nums; }}
.badge {{ display:inline-block; padding:1px 7px; border-radius:20px; font-size:11px; font-weight:600;
  border:1px solid currentColor; }}
.badge.DBA {{ color:var(--dba); }} .badge.DCA {{ color:var(--dca); }} .badge.DIA {{ color:var(--dia); }}
.c-unit {{ font-size:12px; color:var(--muted); white-space:nowrap; }}
.up {{ color:var(--up); }} .down {{ color:var(--down); }} .flat {{ color:var(--flat); }}
.c-spark {{ width:270px; padding:6px 13px; }}
.spark {{ width:260px; height:52px; display:block; }}
.spark polyline {{ fill:none; stroke-width:1.7; vector-effect:non-scaling-stroke;
  stroke-linejoin:round; stroke-linecap:round; }}
.spark.up polyline, .spark.up circle {{ stroke:var(--up); fill:none; }}
.spark.down polyline, .spark.down circle {{ stroke:var(--down); fill:none; }}
.spark circle {{ stroke-width:1.7; }}
.spark-empty {{ font-size:11.5px; color:var(--muted); }}
footer {{ margin-top:26px; font-size:11.5px; color:var(--muted); line-height:1.7; }}
footer b {{ color:var(--ink); }}
</style>
</head>
<body>
<div class="wrap">
  <h1>가락시장 도매시세 · 농산</h1>
  <div class="meta">
    기준 거래일 <b>{latest_date or "—"}</b> &nbsp;·&nbsp; 갱신 {generated}
    &nbsp;·&nbsp; <span id="countLabel">감시 {len(rows)}품목 (채소 {veg} / 청과 {len(rows) - veg})</span>
    &nbsp;·&nbsp; 단위: 원, 등급 상
  </div>
  {banner}

  <div class="filters">
    <div class="filter-row">
      <span class="flabel">부문</span>
{sector_chips}
      <span class="spacer"></span>
      <button type="button" class="link" id="selAll">전체 선택</button>
      <button type="button" class="link" id="selNone">전체 해제</button>
    </div>
    <div class="filter-row">
      <span class="flabel">품목</span>
      <details class="dd" id="itemDd">
        <summary>
          <span id="ddLabel">품목 선택</span>
          <span class="dd-count" id="ddCount"></span>
        </summary>
        <div class="dd-panel">
          <div class="dd-hint">전일 변동률 내림차순</div>
{item_options}
        </div>
      </details>
    </div>
  </div>

  <h2>오늘의 경보 · 전일대비 ±10% 초과</h2>
  {alert_block}

  <h2>담당 품목 시세</h2>
  <div class="empty" id="emptyMsg" hidden>선택된 품목이 없습니다. 위에서 품목을 골라주세요.</div>
  <div class="table-wrap" id="tableWrap">
    <table>
      <thead>
        <tr>
          <th>품목 / 자사 MC</th><th>부문</th><th>단위·등급</th>
          <th class="num">최저</th><th class="num">평균</th><th class="num">최고</th>
          <th class="num">전일대비</th><th class="num">전일%</th><th class="num">전년비</th>
          <th>최근 30거래일 평균가</th>
        </tr>
      </thead>
      <tbody>
{chr(10).join(render_row(r) for r in rows)}
      </tbody>
    </table>
  </div>

  <footer>
    출처: 서울시농수산식품공사 유통정보시스템 (garak.co.kr) · 경매(정가수의) 상장거래 기준, 등급 <b>상</b><br>
    본 자료는 <b>내부 참고용</b>입니다. 사이트 고지에 따라 계약·납품·사실조회 등의 근거·증빙자료로 사용할 수 없습니다.<br>
    휴장일은 직전 거래일 값이 반복되므로 집계에서 제외했습니다. 과일류는 경매시간 특성상 오전 11시 이후 값이 변동될 수 있습니다.
  </footer>
</div>
{SCRIPT}
</body>
</html>
"""


# --------------------------------------------------------------------------- 진입점

def main() -> int:
    ap = argparse.ArgumentParser(description="대시보드 HTML 생성")
    ap.add_argument("--open", action="store_true", help="생성 후 브라우저로 열기")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not DB_PATH.exists():
        print("데이터베이스가 없습니다. 먼저 src/collect.py 를 실행하세요.", file=sys.stderr)
        return 1

    cfg = load_config()
    conn = sqlite3.connect(DB_PATH)
    try:
        rows, latest_date, unmapped = build_rows(conn, cfg)
    finally:
        conn.close()

    if not rows:
        print("표시할 데이터가 없습니다.", file=sys.stderr)
        return 1

    stale = bool(latest_date) and (dt.date.today() - dt.date.fromisoformat(latest_date)).days > STALE_DAYS
    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(render(rows, latest_date, generated, stale, unmapped), encoding="utf-8")
    print(f"생성 완료: {OUT_PATH}  ({len(rows)}품목, 기준일 {latest_date})")

    if args.open:
        webbrowser.open(OUT_PATH.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
