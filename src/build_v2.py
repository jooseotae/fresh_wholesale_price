"""드릴다운 대시보드 생성 — 전체 → 청과/채소 → 품목별.

    python src/build_v2.py [--open]

데이터는 JSON으로 인라인 삽입하고 드릴다운·차트는 브라우저에서 그린다.
파일 하나로 완결되므로 서버가 필요 없다.
"""

import argparse
import datetime as dt
import json
import re
import sqlite3
import statistics
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "prices.sqlite"
OUT_PATH = ROOT / "out" / "dashboard.html"
TEMPLATE = ROOT / "src" / "template.html"

SERIES_DAYS = 30
TOP_N = 10

# "14,906(98.6%)" → 전일가 14906, 비율 98.6
_RATE = re.compile(r"^([\d,]+)\(([\d.]+)%\)")


def parse_rate(s: str | None, av_p: int | None = None) -> float | None:
    """전일대비 변동률(%). 100%가 보합이므로 -100 한다.

    전일가가 당일 평균가와 정확히 같으면 '전일 자료 없음'을 뜻하는 기본값이라
    변동률로 치지 않는다. 이 행들을 섞으면 대표품목 중앙값이 0%로 눌린다.
    """
    if not s:
        return None
    m = _RATE.match(s.strip())
    if not m:
        return None
    try:
        prev, ratio = int(m.group(1).replace(",", "")), float(m.group(2))
    except ValueError:
        return None
    if ratio == 0:
        return None
    if av_p is not None and prev == av_p:
        return None
    return ratio - 100.0


def latest_date(conn: sqlite3.Connection, table: str) -> str | None:
    col = "tot" if table == "volume_daily" else "av_p"
    return conn.execute(
        f"SELECT MAX(trade_date) FROM {table} WHERE {col} IS NOT NULL AND {col} > 0"
    ).fetchone()[0]


# 가락 '과일과채류' 부류는 자사 부문 기준으로 갈린다.
# 토마토·참외·수박·멜론·딸기 = 청과(DCA), 오이·호박·가지 = 채소(DBA).
# (자사 MC 코드: 토마토 010205·참외 010202·메론 010203·수박 010204 = 청과 /
#  오이 020302·호박 020303·과채기타 = 채소)
FRUITVEG_TO_VEG = {"오이", "호박", "애호박", "쥬키니호박", "가지"}


def sector_of(buryu: str, item_nm: str) -> str:
    if buryu == "일반채소류":
        return "채소"
    if buryu == "과일류":
        return "청과"
    if buryu == "과일과채류":
        return "채소" if item_nm in FRUITVEG_TO_VEG else "청과"
    return "채소"


def load_volumes(conn: sqlite3.Connection, date: str) -> list[dict]:
    rows = conn.execute(
        """SELECT buryu, item_nm, tot, js_day, js_week
           FROM volume_daily WHERE trade_date=? AND tot IS NOT NULL AND tot > 0
           ORDER BY tot DESC""",
        (date,),
    ).fetchall()
    out = []
    for buryu, nm, tot, jsd, jsw in rows:
        out.append({
            "sector": sector_of(buryu, nm), "buryu": buryu, "item": nm,
            "tot": tot, "prev": jsd, "week": jsw,
            "volPct": ((tot - jsd) / jsd * 100) if jsd else None,
        })
    return out


def rep_variety(conn: sqlite3.Connection, rptv: str) -> tuple[str, str] | None:
    """대표품목을 대표할 품종 = 최근 기간에 가장 자주 거래된 품종 (등급 상)."""
    row = conn.execute(
        """SELECT item_cd, item_nm, COUNT(*) c FROM price_detail
           WHERE rptv_nm=? AND grade_cd='1' AND av_p > 0
           GROUP BY item_cd ORDER BY c DESC, item_cd LIMIT 1""",
        (rptv,),
    ).fetchone()
    return (row[0], row[1]) if row else None


_QTY = re.compile(r"^([\d.]+)")


def unit_price(avg: int | None, unit: str | None, unit_qty) -> tuple[int, str] | None:
    """단위단가 = 평균가 ÷ 포장 수량. 포장 규격이 달라도 비교 가능한 값.

    "10kg상자"(qty 10) → 원/kg, "50개"(qty 50) → 원/개 식으로 기준 단위를 붙인다.
    """
    if avg is None or not unit:
        return None
    try:
        qty = float(unit_qty) if unit_qty else float(_QTY.match(unit).group(1))
    except (TypeError, ValueError, AttributeError):
        return None
    if qty <= 0:
        return None
    if "kg" in unit.lower():
        base = "kg"
    elif "개" in unit:
        base = "개"
    else:  # 속·단·g단 등: 규격 앞 숫자를 떼고 남은 라벨
        base = re.sub(r"^[\d.]+", "", unit) or "단위"
    return round(avg / qty), base


def load_prices(conn: sqlite3.Connection, date: str) -> dict[str, dict]:
    """대표품목별 요약. 변동률은 품종별 전일대비의 중앙값을 쓴다.

    품종마다 단위(4kg상자/10kg망대…)가 달라 절대가 평균은 의미가 없다.
    반면 전일대비 비율은 단위와 무관하므로 대표품목 단위로 합칠 수 있다.
    """
    rows = conn.execute(
        """SELECT rptv_nm, item_cd, item_nm, unit, mi_p, av_p, ma_p, pav_rate, j7_rate, j365_rate, unit_qty
           FROM price_detail WHERE trade_date=? AND grade_cd='1' AND av_p > 0""",
        (date,),
    ).fetchall()

    grouped: dict[str, list] = {}
    for r in rows:
        grouped.setdefault(r[0], []).append(r)

    out: dict[str, dict] = {}
    for rptv, items in grouped.items():
        pcts = [p for p in (parse_rate(i[7], i[5]) for i in items) if p is not None]
        rep = rep_variety(conn, rptv)
        rep_row = next((i for i in items if rep and i[1] == rep[0]), items[0])
        up = unit_price(rep_row[5], rep_row[3], rep_row[10])
        out[rptv] = {
            "rptv": rptv,
            "pricePct": statistics.median(pcts) if pcts else None,
            "nVariety": len(items),
            "repName": rep_row[2], "repUnit": rep_row[3],
            "repLow": rep_row[4], "repAvg": rep_row[5], "repMax": rep_row[6],
            "unitPrice": up[0] if up else None, "unitBase": up[1] if up else None,
            "varieties": sorted(
                [
                    {"cd": i[1], "nm": i[2], "unit": i[3], "low": i[4], "avg": i[5],
                     "max": i[6], "pct": parse_rate(i[7], i[5]), "j7": i[8], "j365": i[9],
                     "up": (lambda u: {"v": u[0], "b": u[1]} if u else None)(unit_price(i[5], i[3], i[10]))}
                    for i in items
                ],
                key=lambda x: -(x["avg"] or 0),
            ),
        }
    return out


def load_series(conn: sqlite3.Connection, rptv_list: list[str]) -> dict[str, dict]:
    """대표품목별 가격·물량 시계열. 가격은 대표 품종의 평균가를 쓴다."""
    out: dict[str, dict] = {}
    for rptv in rptv_list:
        rep = rep_variety(conn, rptv)
        price: list[list] = []
        if rep:
            price = [
                [d, v] for d, v in conn.execute(
                    """SELECT trade_date, av_p FROM price_detail
                       WHERE item_cd=? AND grade_cd='1' AND av_p > 0
                       ORDER BY trade_date DESC LIMIT ?""",
                    (rep[0], SERIES_DAYS),
                ).fetchall()
            ][::-1]
        vol = [
            [d, v] for d, v in conn.execute(
                """SELECT trade_date, tot FROM volume_daily
                   WHERE item_nm=? AND tot IS NOT NULL AND tot > 0
                   ORDER BY trade_date DESC LIMIT ?""",
                (rptv, SERIES_DAYS),
            ).fetchall()
        ][::-1]
        out[rptv] = {"repNm": rep[1] if rep else None, "price": price, "volume": vol}
    return out


def load_news(conn: sqlite3.Connection, ref: str | None, span: int = 3) -> tuple[list[dict], int]:
    """기준일 ±span일 이내의 게시물.

    게시물이 매일 올라오지 않으므로 ±3일이 너무 얇으면 ±7일까지 넓히고,
    넓혔다는 사실을 대시보드에 표시한다.
    """
    def window(days: int) -> list[dict]:
        base = dt.date.fromisoformat(ref)
        rows = conn.execute(
            """SELECT posted, board, title, url FROM news
               WHERE posted BETWEEN ? AND ? ORDER BY posted DESC, atc_sn DESC""",
            ((base - dt.timedelta(days=days)).isoformat(),
             (base + dt.timedelta(days=days)).isoformat()),
        ).fetchall()
        return [{"posted": a, "board": b, "title": c, "url": d} for a, b, c, d in rows]

    if ref:
        for days in (span, 7, 14):
            rows = window(days)
            if len(rows) >= 4 or (rows and days == 14):
                return rows, days

    rows = conn.execute(
        "SELECT posted, board, title, url FROM news ORDER BY posted DESC LIMIT 8"
    ).fetchall()
    return [{"posted": a, "board": b, "title": c, "url": d} for a, b, c, d in rows], 0


def build_payload(conn: sqlite3.Connection) -> dict:
    vdate = latest_date(conn, "volume_daily")
    pdate = latest_date(conn, "price_detail")
    if not vdate and not pdate:
        raise SystemExit("데이터가 없습니다. src/collect_bix5.py 를 먼저 실행하세요.")

    volumes = load_volumes(conn, vdate) if vdate else []
    prices = load_prices(conn, pdate) if pdate else {}

    # 반입량 기준으로 품목을 엮는다. 가격이 없는 품목도 물량은 보여준다.
    for v in volumes:
        p = prices.get(v["item"])
        v["pricePct"] = p["pricePct"] if p else None
        v["repName"] = p["repName"] if p else None
        v["repUnit"] = p["repUnit"] if p else None
        v["repAvg"] = p["repAvg"] if p else None
        v["unitPrice"] = p["unitPrice"] if p else None
        v["unitBase"] = p["unitBase"] if p else None
        v["nVariety"] = p["nVariety"] if p else 0

    sectors: dict[str, list] = {}
    for v in volumes:
        sectors.setdefault(v["sector"] or "기타", []).append(v)

    # 시계열은 각 부문 TOP N + 가격이 있는 품목만 (파일 크기 관리)
    need = set()
    for items in sectors.values():
        need.update(x["item"] for x in items[:TOP_N])
    need.update(k for k in prices if any(v["item"] == k for v in volumes[:40]))

    news_rows, news_span = load_news(conn, pdate or vdate)

    return {
        "volumeDate": vdate,
        "priceDate": pdate,
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sectors": sectors,
        "prices": prices,
        "series": load_series(conn, sorted(need)),
        "news": news_rows,
        "newsSpan": news_span,
        "topN": TOP_N,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    conn = sqlite3.connect(DB_PATH)
    try:
        payload = build_payload(conn)
    finally:
        conn.close()

    # 플레이스홀더의 `null` 까지 함께 치환해야 한다. 남기면 문법 오류가 난다.
    tpl = TEMPLATE.read_text(encoding="utf-8")
    marker = "/*__DATA__*/ null"
    if marker not in tpl:
        raise SystemExit(f"템플릿에서 {marker!r} 를 찾지 못했습니다.")
    html = tpl.replace(marker, json.dumps(payload, ensure_ascii=False))
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")

    n_items = sum(len(v) for v in payload["sectors"].values())
    print(f"생성 완료: {OUT_PATH}")
    print(f"  물량 기준일 {payload['volumeDate']} / 가격 기준일 {payload['priceDate']}")
    print(f"  부문 {len(payload['sectors'])}개, 품목 {n_items}개, 대표품목 가격 {len(payload['prices'])}종")

    if args.open:
        webbrowser.open(OUT_PATH.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
