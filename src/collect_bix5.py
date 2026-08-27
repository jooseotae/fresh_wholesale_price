"""가락시장 BIX5 소스 수집기 — 품목별 가격(79 대표품목) + 반입물량(3부류).

호출 규약과 함정은 docs/SOURCES.md 참고. 요약하면:
  1) /shares/{SHARE} 를 GET 해서 JSESSIONID 를 받고
  2) /api/dashboards/{SHARE} 로 세션을 확정한 뒤
  3) /api/datasources/{DS} 에 파라미터를 **평문 최상위 JSON** 으로 POST 한다.
세션이 없으면 조용히 rows=0, 본문이 {} 면 낡은 고정 스냅샷이 돌아온다.

    python src/collect_bix5.py                  # 오늘
    python src/collect_bix5.py --date 20260821
    python src/collect_bix5.py --backfill 30
"""

import argparse
import datetime as dt
import http.cookiejar
import json
import logging
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "prices.sqlite"
LOG_PATH = ROOT / "logs" / "collect.log"

BASE = "https://db.garak.co.kr:9443"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) fresh-wholesale-price/2.0"
RETRIES, RETRY_WAIT = 3, 5

PRICE_SHARE = "4b29ed90716b37d7b99eace4d29583e9"
PRICE_DS = "40f2c32edec68ae89c0994c0f2d8dab6"

VOL_SHARE = "441930f5d481967fbd4219e7877f831e"
VOL_DS = {
    "과일류": "4b2801d94b9b66818372b68e2e5c00e3",
    "과일과채류": "4f80b6426bd339a18225666cae8c1147",
    "일반채소류": "4e6c2a512470813bbf0196e9b69a1518",
}
# 부류 → 자사 부문. 양곡은 별도 소스가 미확보라 아직 없다.
SECTOR_OF_BURYU = {"과일류": "청과", "과일과채류": "청과", "일반채소류": "채소"}

# 가격 소스에는 부문 정보가 없어 대표품목명으로 판별한다.
# 과일과채류(오이·호박·가지)는 자사 기준 채소로 넣는다 (build_v2 와 동일).
FRUIT_ITEMS = {
    "사과", "사과 부사", "사과 홍로", "사과 아오리", "배", "배 신고", "배 원황",
    "감귤", "감귤 하우스", "만감", "만감 한라봉", "만감 천혜향", "만감 레드향",
    "포도", "복숭아", "자두", "매실", "살구", "딸기",
    "참외", "수박", "멜론", "멜론 머스크", "멜론 파파야",
    "토마토", "방울토마토", "대추방울토마토",
    "바나나", "바나나 수입", "오렌지", "오렌지 네블", "파인애플", "골드파인애플",
    "망고", "아보카도", "자몽", "대추", "레몬", "체리", "블루베리", "무화과",
    "단감", "감", "홍시", "곶감", "키위",
}
FRUITVEG_TO_VEG_ITEMS = {"오이", "가시오이", "백다다기오이", "호박", "쥬키니호박", "늙은호박",
                         "단호박", "단호박(일반)", "가지"}


def sector_of_rptv(rptv_nm: str | None) -> str:
    """대표품목명으로 채소/청과 판별. 모르면 '채소' 로 떨어뜨린다 (일반채소류가 다수)."""
    if not rptv_nm:
        return "채소"
    if rptv_nm in FRUITVEG_TO_VEG_ITEMS:
        return "채소"
    if rptv_nm in FRUIT_ITEMS:
        return "청과"
    # 이름에 흔한 청과 키워드가 있으면 청과로
    for kw in ("바나나", "오렌지", "파인애플", "망고", "자몽", "체리", "포도", "복숭아",
               "자두", "사과", "배 ", "감귤", "만감", "토마토", "멜론", "수박", "참외",
               "딸기", "블루베리", "무화과", "키위", "감 ", "단감"):
        if kw in rptv_nm:
            return "청과"
    return "채소"

SCHEMA = """
CREATE TABLE IF NOT EXISTS price_detail (
  trade_date TEXT NOT NULL,
  rptv_nm    TEXT NOT NULL,      -- 대표품목명 (복숭아)
  item_cd    TEXT NOT NULL,      -- 품종코드
  item_nm    TEXT,               -- 품종명 (복숭아 미백(백))
  grade_cd   TEXT NOT NULL,      -- 0특 1상 2보통 3하
  grade_nm   TEXT,
  unit       TEXT,
  unit_qty   TEXT,
  mi_p INTEGER, av_p INTEGER, ma_p INTEGER,
  pav_rate TEXT, j7_rate TEXT, j365_rate TEXT,
  collected_at TEXT,
  PRIMARY KEY (trade_date, item_cd, grade_cd)
);

CREATE TABLE IF NOT EXISTS volume_daily (
  trade_date TEXT NOT NULL,
  buryu      TEXT NOT NULL,      -- 과일류 / 과일과채류 / 일반채소류
  sector     TEXT,               -- 청과 / 채소
  item_nm    TEXT NOT NULL,
  tot INTEGER, js_day INTEGER, js_week INTEGER,
  unit_cd TEXT,
  collected_at TEXT,
  PRIMARY KEY (trade_date, buryu, item_nm)
);

CREATE INDEX IF NOT EXISTS ix_pd_date ON price_detail (trade_date);
CREATE INDEX IF NOT EXISTS ix_pd_rptv ON price_detail (rptv_nm, trade_date);
CREATE INDEX IF NOT EXISTS ix_vd_date ON volume_daily (trade_date);
"""


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )


class Bix5Session:
    """share 하나당 세션 하나. 쿠키를 물고 있어야 데이터가 나온다."""

    def __init__(self, share_id: str, params: dict):
        self.share_id = share_id
        cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        self.opener.addheaders = [("User-Agent", UA)]
        qs = urllib.parse.quote(json.dumps(params))
        self.referer = f"{BASE}/shares/{share_id}?defaultParameter={qs}"
        self.opener.open(self.referer, timeout=40).read()
        self.opener.open(f"{BASE}/api/dashboards/{share_id}", timeout=40).read()

    def datasource(self, ds_id: str, params: dict) -> list[dict]:
        url = f"{BASE}/api/datasources/{ds_id}?dummy={int(time.time() * 1000)}"
        req = urllib.request.Request(
            url,
            data=json.dumps(params).encode("utf-8"),  # 평문 최상위 — 래핑하면 무시된다
            headers={"Content-Type": "application/json", "Referer": self.referer, "User-Agent": UA},
        )
        return json.loads(self.opener.open(req, timeout=90).read().decode("utf-8")).get("dataset", [])


def with_retry(fn, label: str):
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            return fn()
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last = exc
            logging.warning("%s 실패 (%d/%d): %s", label, attempt, RETRIES, exc)
            if attempt < RETRIES:
                time.sleep(RETRY_WAIT)
    raise RuntimeError(f"{label} 실패: {last}")


def as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def collect_prices(conn: sqlite3.Connection, date_str: str,
                   only_sector: str | None = None) -> int:
    """가격 수집. only_sector 를 주면 그 부문만 upsert (다른 부문은 건드리지 않음).

    같은 소스에 채소·청과가 섞여 오므로 부문별 스케줄 실행 시 부문 밖 값은
    저장하지 않는다. 이렇게 해야 08:00에 실행해도 미확정 청과값이 어제 값을
    덮어쓰지 않는다.
    """
    p = {"startDate": date_str, "endDate": date_str, "handlClssCd": "2"}
    rows = with_retry(lambda: Bix5Session(PRICE_SHARE, p).datasource(PRICE_DS, p), f"{date_str} 가격")
    if not rows:
        return 0
    if only_sector:
        rows = [r for r in rows if sector_of_rptv(r.get("RPTV_ITM_NM")) == only_sector]
        if not rows:
            return 0
    now = dt.datetime.now().isoformat(timespec="seconds")
    conn.executemany(
        """INSERT INTO price_detail
             (trade_date,rptv_nm,item_cd,item_nm,grade_cd,grade_nm,unit,unit_qty,
              mi_p,av_p,ma_p,pav_rate,j7_rate,j365_rate,collected_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT (trade_date,item_cd,grade_cd) DO UPDATE SET
             rptv_nm=excluded.rptv_nm, item_nm=excluded.item_nm, grade_nm=excluded.grade_nm,
             unit=excluded.unit, unit_qty=excluded.unit_qty,
             mi_p=excluded.mi_p, av_p=excluded.av_p, ma_p=excluded.ma_p,
             pav_rate=excluded.pav_rate, j7_rate=excluded.j7_rate, j365_rate=excluded.j365_rate,
             -- 값이 실제로 바뀌었을 때만 시각을 갱신한다 (미확정치 재수집으로 오해되지 않게)
             collected_at=CASE
               WHEN COALESCE(price_detail.av_p,-1) != COALESCE(excluded.av_p,-1)
                 OR COALESCE(price_detail.mi_p,-1) != COALESCE(excluded.mi_p,-1)
                 OR COALESCE(price_detail.ma_p,-1) != COALESCE(excluded.ma_p,-1)
                 OR COALESCE(price_detail.pav_rate,'') != COALESCE(excluded.pav_rate,'')
               THEN excluded.collected_at ELSE price_detail.collected_at
             END""",
        [
            (
                (r.get("INVEST_DT") or "").replace(".", "-"),
                r.get("RPTV_ITM_NM"), str(r.get("ITM_CD")), r.get("ITM_NM"),
                str(r.get("GRADE_CD")), r.get("G_NAME"), r.get("UNIT"), r.get("UNIT_QTY"),
                as_int(r.get("MI_P")), as_int(r.get("AV_P")), as_int(r.get("MA_P")),
                r.get("PAV_RATE"), r.get("J_7_RATE"), r.get("J_365_RATE"), now,
            )
            for r in rows
            if r.get("INVEST_DT") and r.get("ITM_CD") is not None
        ],
    )
    return len(rows)


def collect_volumes(conn: sqlite3.Connection, date_str: str,
                    only_sector: str | None = None) -> int:
    p = {"s_date": date_str, "s_unitcd": "t", "handlClssCd": "2"}
    sess = with_retry(lambda: Bix5Session(VOL_SHARE, p), f"{date_str} 반입물량 세션")
    trade_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    now = dt.datetime.now().isoformat(timespec="seconds")
    total = 0

    for buryu, ds_id in VOL_DS.items():
        if only_sector and SECTOR_OF_BURYU.get(buryu) != only_sector:
            continue
        rows = with_retry(lambda d=ds_id: sess.datasource(d, p), f"{date_str} {buryu}")
        items = [r for r in rows if r.get("구분") not in ("계", "합계") and r.get("구분")]
        conn.executemany(
            """INSERT INTO volume_daily
                 (trade_date,buryu,sector,item_nm,tot,js_day,js_week,unit_cd,collected_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT (trade_date,buryu,item_nm) DO UPDATE SET
                 sector=excluded.sector, tot=excluded.tot, js_day=excluded.js_day,
                 js_week=excluded.js_week, unit_cd=excluded.unit_cd,
                 collected_at=CASE
                   WHEN COALESCE(volume_daily.tot,-1) != COALESCE(excluded.tot,-1)
                     OR COALESCE(volume_daily.js_day,-1) != COALESCE(excluded.js_day,-1)
                   THEN excluded.collected_at ELSE volume_daily.collected_at
                 END""",
            [
                (
                    trade_date, buryu, SECTOR_OF_BURYU.get(buryu), r["구분"],
                    as_int(r.get("TOT")), as_int(r.get("JS_DAY")), as_int(r.get("JS_WEEK")),
                    r.get("UNIT_CD"), now,
                )
                for r in items
            ],
        )
        total += len(items)
    return total


def collect_one(conn: sqlite3.Connection, date_str: str,
                only_sector: str | None = None) -> tuple[int, int]:
    n_price = collect_prices(conn, date_str, only_sector)
    n_vol = collect_volumes(conn, date_str, only_sector)
    tag = f" ({only_sector}만)" if only_sector else ""
    logging.info("%s%s 가격 %d행 / 물량 %d행", date_str, tag, n_price, n_vol)
    return n_price, n_vol


def main() -> int:
    ap = argparse.ArgumentParser(description="BIX5 가격·반입물량 수집")
    ap.add_argument("--date", help="YYYYMMDD (기본: 오늘)")
    ap.add_argument("--backfill", type=int, metavar="N", help="기준일부터 N일 소급")
    ap.add_argument("--sector", choices=("채소", "청과"),
                    help="이 부문만 갱신 (다른 부문은 건드리지 않음)")
    args = ap.parse_args()

    setup_logging()
    base = dt.datetime.strptime(args.date, "%Y%m%d").date() if args.date else dt.date.today()
    targets = [base - dt.timedelta(days=i) for i in range(args.backfill or 1)]

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    tp = tv = failed = 0
    try:
        for i, day in enumerate(targets):
            try:
                a, b = collect_one(conn, day.strftime("%Y%m%d"), args.sector)
                tp += a
                tv += b
            except RuntimeError as exc:
                failed += 1
                logging.error("%s", exc)
            conn.commit()
            if len(targets) > 1:
                if i % 10 == 9:
                    logging.info("진행 %d/%d", i + 1, len(targets))
                time.sleep(0.5)
    finally:
        conn.close()

    logging.info("완료: 가격 %d행, 물량 %d행, 실패 %d일", tp, tv, failed)
    return 1 if failed and failed == len(targets) else 0


if __name__ == "__main__":
    sys.exit(main())
