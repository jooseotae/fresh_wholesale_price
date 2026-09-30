"""빠진 거래일을 찾아 소급 수집한다.

수집기는 '오늘'만 받는다. PC가 꺼져 있던 날은 그 날짜가 영구 결손이 된다
(2026-09-08 이 그랬다). 이 스크립트가 마감 실행 때 뒤를 돌아보며 메운다.

휴장일(일요일·공휴일)은 원본에 데이터 자체가 없어 매일 재시도하면 낭비다.
그래서 시도한 날짜는 결과와 무관하게 backfill_log 에 남기고 두 번 조회하지
않는다. 반대로 도중에 죽으면 아무것도 기록되지 않아 다음 실행에서 다시 집는다.

    python src/backfill.py              # 최근 7일
    python src/backfill.py --days 60    # 더 멀리
    python src/backfill.py --dry-run    # 무엇을 채울지만 보기
"""

import argparse
import datetime as dt
import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "prices.sqlite"
LOG_PATH = ROOT / "logs" / "collect.log"

SCHEMA = """
CREATE TABLE IF NOT EXISTS backfill_log (
  trade_date TEXT PRIMARY KEY,
  tried_at   TEXT,
  n_price    INTEGER,
  n_unit     INTEGER
);
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


def missing_dates(conn: sqlite3.Connection, days: int) -> list[dt.date]:
    """최근 days일 중 가격 데이터도 없고 시도 이력도 없는 날 (오래된 순).

    오늘은 제외한다 — 평시 수집이 맡는 몫이고, 아직 경매가 안 끝났을 수도 있다.
    """
    have = {d for (d,) in conn.execute("SELECT DISTINCT trade_date FROM price_detail")}
    tried = {d for (d,) in conn.execute("SELECT trade_date FROM backfill_log")}
    today = dt.date.today()
    out = [today - dt.timedelta(days=i) for i in range(days, 0, -1)]
    return [d for d in out if d.isoformat() not in have and d.isoformat() not in tried]


def run(script: str, date_str: str) -> bool:
    """수집기를 별도 프로세스로 돌린다. 인자 규약을 스케줄러와 똑같이 맞춘다."""
    cmd = [sys.executable, str(ROOT / "src" / script), "--date", date_str]
    rc = subprocess.run(cmd, cwd=ROOT).returncode
    if rc != 0:
        logging.warning("%s --date %s 실패 (rc=%d)", script, date_str, rc)
    return rc == 0


def n_rows(conn: sqlite3.Connection, table: str, trade_date: str) -> int:
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE trade_date=?", (trade_date,)
    ).fetchone()[0]


def main() -> int:
    ap = argparse.ArgumentParser(description="빠진 거래일 소급 수집")
    ap.add_argument("--days", type=int, default=7, help="며칠 전까지 돌아볼지 (기본 7)")
    ap.add_argument("--max", type=int, default=3, metavar="N",
                    help="한 번에 채울 최대 일수 (기본 3). 나머지는 다음 실행에서")
    ap.add_argument("--dry-run", action="store_true", help="채울 날짜만 출력")
    args = ap.parse_args()

    setup_logging()
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()

    try:
        targets = missing_dates(conn, args.days)
        if not targets:
            logging.info("소급 수집할 날짜 없음 (최근 %d일)", args.days)
            return 0

        logging.info("결손 %d일: %s", len(targets), ", ".join(d.isoformat() for d in targets))
        if args.dry_run:
            return 0

        filled = 0
        for day in targets[: args.max]:
            date_str = day.strftime("%Y%m%d")
            trade_date = day.isoformat()
            logging.info("--- 소급 수집 %s ---", trade_date)

            if not run("collect_bix5.py", date_str):
                continue
            n_price = n_rows(conn, "price_detail", trade_date)

            # 가격이 0행이면 휴장일이다. 150초짜리 규격 수집은 돌릴 필요가 없다.
            n_unit = 0
            if n_price:
                if run("collect_unit.py", date_str):
                    n_unit = n_rows(conn, "price_unit", trade_date)
                filled += 1
            else:
                logging.info("%s 데이터 없음 — 휴장일로 보고 재시도하지 않는다", trade_date)

            conn.execute(
                "INSERT OR REPLACE INTO backfill_log (trade_date,tried_at,n_price,n_unit) VALUES (?,?,?,?)",
                (trade_date, dt.datetime.now().isoformat(timespec="seconds"), n_price, n_unit),
            )
            conn.commit()
            logging.info("%s 완료: 가격 %d행 / 규격 %d행", trade_date, n_price, n_unit)

        rest = len(targets) - min(len(targets), args.max)
        logging.info("소급 수집 종료: %d일 채움%s", filled,
                     f", {rest}일은 다음 실행에서" if rest else "")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
