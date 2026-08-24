"""가락시장 도매시세 수집기 (PRD D1 소스).

표준 라이브러리만 사용한다. 별도 설치 불필요.

    python src/collect.py                  # 오늘 수집
    python src/collect.py --date 20260821  # 특정일 수집
    python src/collect.py --backfill 400   # 오늘부터 400일 소급 (전년 동기 비교용)

휴장일에는 API가 직전 거래일 데이터를 그대로 되돌려준다. 이를 페이로드
해시로 감지해 is_carry=1 로 표시하고, 대시보드는 이런 행을 제외한다.
"""

import argparse
import datetime as dt
import hashlib
import json
import logging
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "prices.sqlite"
LOG_PATH = ROOT / "logs" / "collect.log"

ENDPOINT = "https://www.garak.co.kr/youtong/bigDataAnalyzesList.do"
MARKET = "garak"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) fresh-wholesale-price/1.0"
RETRIES = 3
RETRY_WAIT = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS price_daily (
  trade_date   TEXT NOT NULL,
  market       TEXT NOT NULL DEFAULT 'garak',
  item_cd      TEXT NOT NULL,
  item_nm      TEXT,
  unit_nm      TEXT,
  grade_nm     TEXT NOT NULL,
  low_price    INTEGER,
  avg_price    INTEGER,
  max_price    INTEGER,
  price_gap    INTEGER,
  volume       INTEGER,
  is_carry     INTEGER NOT NULL DEFAULT 0,
  collected_at TEXT,
  PRIMARY KEY (trade_date, market, item_cd, grade_nm)
);

CREATE TABLE IF NOT EXISTS fetch_log (
  fetch_date   TEXT PRIMARY KEY,
  payload_hash TEXT,
  n_rows       INTEGER,
  is_carry     INTEGER NOT NULL DEFAULT 0,
  fetched_at   TEXT
);

CREATE INDEX IF NOT EXISTS ix_price_item_date ON price_daily (item_cd, trade_date);
"""


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(sys.stdout, "reconfigure"):  # 콘솔이 cp949여도 한글이 깨지지 않도록
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def fetch(date_str: str) -> list[dict]:
    """지정일의 시세를 가져온다. 네트워크 오류는 재시도한다."""
    body = json.dumps({"selectedDate": date_str}).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": UA},
    )
    last_err: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_err = exc
            logging.warning("%s 수집 실패 (%d/%d): %s", date_str, attempt, RETRIES, exc)
            if attempt < RETRIES:
                time.sleep(RETRY_WAIT)
    raise RuntimeError(f"{date_str} 수집 실패: {last_err}")


def payload_hash(rows: list[dict]) -> str:
    return hashlib.md5(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def store(conn: sqlite3.Connection, date_str: str, rows: list[dict]) -> int:
    """upsert. 같은 날짜를 다시 수집해도 중복되지 않는다 (F12)."""
    trade_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    now = dt.datetime.now().isoformat(timespec="seconds")
    conn.executemany(
        """INSERT INTO price_daily
             (trade_date, market, item_cd, item_nm, unit_nm, grade_nm,
              low_price, avg_price, max_price, price_gap, volume, collected_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?)
           ON CONFLICT (trade_date, market, item_cd, grade_nm) DO UPDATE SET
             item_nm=excluded.item_nm, unit_nm=excluded.unit_nm,
             low_price=excluded.low_price, avg_price=excluded.avg_price,
             max_price=excluded.max_price, price_gap=excluded.price_gap,
             collected_at=excluded.collected_at""",
        [
            (
                trade_date, MARKET, str(r.get("itmCd")), r.get("itmNm"), r.get("unitNm"),
                r.get("grdNm") or "", r.get("lowPrice"), r.get("avgPrice"),
                r.get("maxPrice"), r.get("avgPriceGap"), now,
            )
            for r in rows
        ],
    )
    conn.execute(
        """INSERT INTO fetch_log (fetch_date, payload_hash, n_rows, is_carry, fetched_at)
           VALUES (?,?,?,0,?)
           ON CONFLICT (fetch_date) DO UPDATE SET
             payload_hash=excluded.payload_hash, n_rows=excluded.n_rows,
             fetched_at=excluded.fetched_at""",
        (trade_date, payload_hash(rows), len(rows), now),
    )
    return len(rows)


def mark_carry(conn: sqlite3.Connection) -> int:
    """직전 수집일과 페이로드가 동일한 날짜를 휴장일(carry-forward)로 표시한다.

    백필이 역순으로 들어와도 되도록 매번 전체를 다시 계산한다.
    """
    log = conn.execute("SELECT fetch_date, payload_hash FROM fetch_log ORDER BY fetch_date").fetchall()
    prev_hash = None
    carried: list[str] = []
    fresh: list[str] = []
    for date, phash in log:
        (carried if phash == prev_hash else fresh).append(date)
        prev_hash = phash
    for flag, dates in ((1, carried), (0, fresh)):
        if dates:
            marks = ",".join("?" * len(dates))
            conn.execute(f"UPDATE fetch_log SET is_carry={flag} WHERE fetch_date IN ({marks})", dates)
            conn.execute(f"UPDATE price_daily SET is_carry={flag} WHERE trade_date IN ({marks})", dates)
    return len(carried)


def collect_one(conn: sqlite3.Connection, date_str: str) -> int:
    rows = fetch(date_str)
    if not rows:
        logging.info("%s 데이터 없음 (빈 응답)", date_str)
        return 0
    n = store(conn, date_str, rows)
    logging.info("%s %d건 저장", date_str, n)
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="가락시장 도매시세 수집")
    ap.add_argument("--date", help="수집할 날짜 YYYYMMDD (기본: 오늘)")
    ap.add_argument("--backfill", type=int, metavar="N", help="기준일부터 N일 소급 수집")
    args = ap.parse_args()

    setup_logging()
    base = dt.datetime.strptime(args.date, "%Y%m%d").date() if args.date else dt.date.today()
    targets = [base - dt.timedelta(days=i) for i in range(args.backfill or 1)]

    conn = connect()
    total = failed = 0
    try:
        for i, day in enumerate(targets):
            try:
                total += collect_one(conn, day.strftime("%Y%m%d"))
            except RuntimeError as exc:
                failed += 1
                logging.error("%s", exc)
            if len(targets) > 1:
                conn.commit()
                if i % 20 == 19:
                    logging.info("진행 %d/%d", i + 1, len(targets))
                time.sleep(0.3)  # 서버 배려
        carried = mark_carry(conn)
        conn.commit()
    finally:
        conn.close()

    logging.info("완료: %d건 저장, 휴장일 %d일, 실패 %d일", total, carried, failed)
    if failed and failed == len(targets):
        logging.error("전체 수집 실패 — 대시보드는 마지막 정상 데이터를 유지합니다")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
