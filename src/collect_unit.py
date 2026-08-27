"""규격(단위)별 + 산지별 경락가격 수집 — 품목별 세부 경락정보.

기존 collect_bix5 의 '품목별가격'은 품종당 대표 규격 하나만 준다.
이 소스는 같은 품종이라도 규격별로 나뉜다 (가지 5kg상자 / 8kg상자 등 47품종).
전년 대비 가격도 함께 온다.

한계: 전 품목 일괄 조회가 안 된다. 품종×규격 조합마다 개별 요청이 필요해
271회를 돌린다. 세션은 하나만 열어 재사용한다.

    python src/collect_unit.py                  # 오늘 (규격별 + 산지별)
    python src/collect_unit.py --date 20260826
    python src/collect_unit.py --limit 10       # 소량 시험
    python src/collect_unit.py --no-region      # 규격별만 (절반 시간)
"""

import argparse
import datetime as dt
import http.cookiejar
import json
import logging
import re
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

GARAK = "https://www.garak.co.kr"
BIX = "https://db.garak.co.kr:9443"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) fresh-wholesale-price/2.1"

ITEM_LIST_EP = "/youtong/G1000462/dashboard/getAllTypeListOriginAjax.do"
ITEM_LIST_REF = GARAK + "/youtong/G1000462/dashboard/typeDetailOrigin.do"

SHARE_AVG = "4ee3e775b0d8399aa0c010f4d5eb28d6"   # 품목 평균가 (규격별)
DS_AVG = "40b1536a3620f5559aee46dea7493b69"     # 최고/최저/평균 + 전일 + 전년
DS_GRADE = "463f86bb3474d27fb54ce6ee3b2b0bd1"   # 등급별 평균가

SHARE_REGION = "42d1bbeb088352899f4258d5bca0adca"   # 지역별(산지) 가격
DS_REGION = "4d06530096924d3fb22266885bc31487"      # 산지명이 열로 오는 피벗

RETRIES, RETRY_WAIT, PAUSE = 3, 4, 0.25

SCHEMA = """
CREATE TABLE IF NOT EXISTS price_unit (
  trade_date TEXT NOT NULL,
  item_cd    TEXT NOT NULL,
  unit       TEXT NOT NULL,      -- 5kg상자
  unit_qty   TEXT,               -- 5
  item_nm    TEXT,
  low_p  INTEGER, avg_p  INTEGER, max_p INTEGER,
  prev_avg INTEGER, yoy_avg INTEGER,
  prev_pct REAL,   yoy_pct REAL,
  collected_at TEXT,
  PRIMARY KEY (trade_date, item_cd, unit)
);
CREATE INDEX IF NOT EXISTS ix_pu_date ON price_unit (trade_date);
CREATE INDEX IF NOT EXISTS ix_pu_item ON price_unit (item_cd, trade_date);

CREATE TABLE IF NOT EXISTS price_region (
  trade_date TEXT NOT NULL,
  item_cd    TEXT NOT NULL,
  unit       TEXT NOT NULL,
  region     TEXT NOT NULL,      -- 전남 해남군
  item_nm    TEXT,
  low_p INTEGER, avg_p INTEGER, max_p INTEGER,
  collected_at TEXT,
  PRIMARY KEY (trade_date, item_cd, unit, region)
);
CREATE INDEX IF NOT EXISTS ix_pr_date ON price_region (trade_date);
CREATE INDEX IF NOT EXISTS ix_pr_item ON price_region (item_cd, trade_date);
"""

_NUM = re.compile(r"-?[\d,]+\.?\d*")


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )


def num(s) -> int | None:
    """'30,000' / '+15,373.3' / '-' → int 또는 None."""
    if s is None:
        return None
    m = _NUM.search(str(s))
    if not m:
        return None
    try:
        return int(round(float(m.group().replace(",", ""))))
    except ValueError:
        return None


def fetch_items(date_str: str) -> list[dict]:
    """농산(clssPrefix=2) 품종×규격 조합 목록."""
    body = json.dumps({"stdDate": date_str, "endDate": date_str, "mrktDiv": "1"}).encode()
    req = urllib.request.Request(
        GARAK + ITEM_LIST_EP, data=body,
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": UA,
                 "X-Requested-With": "XMLHttpRequest", "Referer": ITEM_LIST_REF})
    with urllib.request.urlopen(req, timeout=40) as r:
        rows = json.loads(r.read().decode("utf-8"))
    return [x for x in rows if x.get("clssPrefix") == "2" and x.get("unit")]


class Session:
    """share 하나로 세션을 열고 271회 재사용한다."""

    def __init__(self, share: str, seed_params: dict):
        cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        self.op.addheaders = [("User-Agent", UA)]
        self.ref = f"{BIX}/shares/{share}?defaultParameter=" + urllib.parse.quote(json.dumps(seed_params))
        self.op.open(self.ref, timeout=40).read()
        self.op.open(f"{BIX}/api/dashboards/{share}", timeout=40).read()

    def query(self, ds: str, params: dict) -> list[dict]:
        req = urllib.request.Request(
            f"{BIX}/api/datasources/{ds}?dummy={int(time.time() * 1000)}",
            data=json.dumps(params).encode("utf-8"),   # 평문 최상위 — 래핑하면 무시된다
            headers={"Content-Type": "application/json", "Referer": self.ref, "User-Agent": UA})
        with self.op.open(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8")).get("dataset", [])


def parse_avg(rows: list[dict]) -> dict | None:
    """최고가/최저가/평균가 3행을 하나로 접는다."""
    got = {}
    for r in rows:
        key = (r.get("가격") or "").strip()
        if key in ("최고가", "최저가", "평균가"):
            got[key] = r
    if "평균가" not in got:
        return None
    a = got["평균가"]
    cur, prev, yoy = num(a.get("금일가격")), num(a.get("전일가격")), num(a.get("전년가격"))
    return {
        "low_p": num(got.get("최저가", {}).get("금일가격")),
        "avg_p": cur,
        "max_p": num(got.get("최고가", {}).get("금일가격")),
        "prev_avg": prev, "yoy_avg": yoy,
        "prev_pct": ((cur - prev) / prev * 100) if cur and prev else None,
        "yoy_pct": ((cur - yoy) / yoy * 100) if cur and yoy else None,
    }


def parse_region(rows: list[dict]) -> list[dict]:
    """산지명이 열(COL2~COL6)로 오는 피벗을 산지당 한 행으로 편다.

    COL1 이 '가격'인 행에 산지명이, '최고가/최저가/평균가' 행에 값이 들어 있다.
    한 번에 최대 5개 산지만 온다 (소스 자체의 제한).
    """
    head = next((r for r in rows if (r.get("COL1") or "").strip() == "가격"), None)
    if not head:
        return []
    vals = {(r.get("COL1") or "").strip(): r for r in rows}
    out = []
    for col in ("COL2", "COL3", "COL4", "COL5", "COL6"):
        region = (head.get(col) or "").strip()
        if not region:
            continue
        avg = num(vals.get("평균가", {}).get(col))
        if avg is None:
            continue
        out.append({"region": region, "low_p": num(vals.get("최저가", {}).get(col)),
                    "avg_p": avg, "max_p": num(vals.get("최고가", {}).get(col))})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="규격별 경락가격 수집")
    ap.add_argument("--date", help="YYYYMMDD (기본: 오늘)")
    ap.add_argument("--limit", type=int, help="앞에서 N개만 (시험용)")
    ap.add_argument("--no-region", action="store_true", help="산지별을 건너뛴다")
    ap.add_argument("--sector", choices=("채소", "청과"),
                    help="이 부문 품목만 갱신")
    args = ap.parse_args()

    setup_logging()
    date_str = args.date or dt.date.today().strftime("%Y%m%d")
    trade_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

    items = fetch_items(date_str)
    if args.sector:
        # collect_bix5 의 sector_of_rptv 를 재사용해 품목명으로 걸러낸다
        from collect_bix5 import sector_of_rptv
        items = [it for it in items
                 if sector_of_rptv(it.get("rptvItmNm") or it.get("itmNm")) == args.sector]
    if args.limit:
        items = items[: args.limit]
    logging.info("규격별 수집 시작: %s / %d조합", date_str, len(items))

    seed = {"mrktDiv": "1", "startDate": date_str, "endDate": date_str, "handlClssCd": "2",
            "selectedItmCd": "", "selectedRptvItmCd": "", "selectedItmNm": "", "unitQty": ""}
    sess = Session(SHARE_AVG, seed)
    sess_reg = None if args.no_region else Session(SHARE_REGION, seed)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    now = dt.datetime.now().isoformat(timespec="seconds")

    saved = empty = failed = reg_saved = 0
    t0 = time.time()
    for i, it in enumerate(items, 1):
        cd, unit, uq = str(it["itmCd"]), it["unit"], str(it.get("unitQty") or "")
        p = dict(seed, selectedItmCd=cd, selectedRptvItmCd=str(it.get("rptvItmCd") or cd), unitQty=uq)

        rows = None
        for attempt in range(1, RETRIES + 1):
            try:
                rows = sess.query(DS_AVG, p)
                break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                if attempt == RETRIES:
                    failed += 1
                    logging.warning("%s %s %s 실패: %s", cd, it.get("itmNm"), unit, exc)
                else:
                    time.sleep(RETRY_WAIT)
        if rows is None:
            continue

        rec = parse_avg(rows)
        if not rec or rec["avg_p"] is None:
            empty += 1
        else:
            conn.execute(
                """INSERT INTO price_unit
                     (trade_date,item_cd,unit,unit_qty,item_nm,low_p,avg_p,max_p,
                      prev_avg,yoy_avg,prev_pct,yoy_pct,collected_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (trade_date,item_cd,unit) DO UPDATE SET
                     unit_qty=excluded.unit_qty, item_nm=excluded.item_nm,
                     low_p=excluded.low_p, avg_p=excluded.avg_p, max_p=excluded.max_p,
                     prev_avg=excluded.prev_avg, yoy_avg=excluded.yoy_avg,
                     prev_pct=excluded.prev_pct, yoy_pct=excluded.yoy_pct,
                     collected_at=CASE
                       WHEN COALESCE(price_unit.avg_p,-1) != COALESCE(excluded.avg_p,-1)
                         OR COALESCE(price_unit.low_p,-1) != COALESCE(excluded.low_p,-1)
                         OR COALESCE(price_unit.max_p,-1) != COALESCE(excluded.max_p,-1)
                       THEN excluded.collected_at ELSE price_unit.collected_at
                     END""",
                (trade_date, cd, unit, uq, it.get("itmNm"), rec["low_p"], rec["avg_p"], rec["max_p"],
                 rec["prev_avg"], rec["yoy_avg"], rec["prev_pct"], rec["yoy_pct"], now))
            saved += 1

        # 산지별 — 같은 파라미터로 다른 데이터소스를 한 번 더 부른다
        if sess_reg is not None:
            try:
                regs = parse_region(sess_reg.query(DS_REGION, p))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
                regs = []
            if regs:
                conn.executemany(
                    """INSERT INTO price_region
                         (trade_date,item_cd,unit,region,item_nm,low_p,avg_p,max_p,collected_at)
                       VALUES (?,?,?,?,?,?,?,?,?)
                       ON CONFLICT (trade_date,item_cd,unit,region) DO UPDATE SET
                         item_nm=excluded.item_nm, low_p=excluded.low_p,
                         avg_p=excluded.avg_p, max_p=excluded.max_p,
                         collected_at=CASE
                           WHEN COALESCE(price_region.avg_p,-1) != COALESCE(excluded.avg_p,-1)
                             OR COALESCE(price_region.low_p,-1) != COALESCE(excluded.low_p,-1)
                             OR COALESCE(price_region.max_p,-1) != COALESCE(excluded.max_p,-1)
                           THEN excluded.collected_at ELSE price_region.collected_at
                         END""",
                    [(trade_date, cd, unit, g["region"], it.get("itmNm"),
                      g["low_p"], g["avg_p"], g["max_p"], now) for g in regs])
                reg_saved += len(regs)

        if i % 40 == 0:
            conn.commit()
            logging.info("진행 %d/%d (%.0f초)", i, len(items), time.time() - t0)
        time.sleep(PAUSE)

    conn.commit()
    conn.close()
    logging.info("완료: 규격 %d / 산지 %d / 빈값 %d / 실패 %d (%.0f초)",
                 saved, reg_saved, empty, failed, time.time() - t0)
    return 1 if saved == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
