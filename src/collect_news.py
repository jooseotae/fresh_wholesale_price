"""농산물 뉴스 수집 — 유통정보시스템 게시판.

가락시장이 직접 올리는 시황·동향 자료를 모은다. 대시보드 하단에 기준일 ±3일
범위로 노출한다.

    python src/collect_news.py [--pages 3]
"""

import argparse
import datetime as dt
import html as html_mod
import logging
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "prices.sqlite"
LOG_PATH = ROOT / "logs" / "collect.log"

BASE = "https://www.garak.co.kr"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) fresh-wholesale-price/2.0"

BOARDS = {
    "동향·전망": "/youtong/G1000343/board/list.do",
    "유통자료실": "/youtong/G1000344/board/list.do",
}
# 시황과 무관한 연재물은 제외한다.
SKIP = re.compile(r"웹소설|공모전|이벤트 당첨")

SCHEMA = """
CREATE TABLE IF NOT EXISTS news (
  atc_sn TEXT PRIMARY KEY,
  board  TEXT,
  title  TEXT,
  dept   TEXT,
  posted TEXT,          -- YYYY-MM-DD
  url    TEXT,
  collected_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_news_posted ON news (posted);
"""

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_LINK = re.compile(r'href="([^"]*view\.do[^"]*)"')
_DATE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
_SN = re.compile(r"atcSn=(\d+)")
_TAG = re.compile(r"<[^>]+>")


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def parse_board(board: str, path: str, page: int) -> list[dict]:
    url = f"{BASE}{path}?pageIndex={page}"
    out = []
    for row in _ROW.findall(fetch(url)):
        link = _LINK.search(row)
        date = _DATE.search(row)
        if not link or not date:
            continue
        sn = _SN.search(html_mod.unescape(link.group(1)))
        if not sn:
            continue

        # 셀 단위로 쪼개서 제목 칸만 뽑는다. 통째로 태그를 지우면 번호·조회수가 섞인다.
        cells = [
            re.sub(r"\s+", " ", html_mod.unescape(_TAG.sub(" ", c))).strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        ]
        # 게시판에 번호 칸이 없어 제목이 첫 칸이다. 부서·날짜·첨부·조회수 칸만 걸러낸다.
        title = next(
            (
                c for c in cells
                if len(c) > 5
                and not _DATE.search(c)
                and not c.endswith("팀")
                and not c.startswith("첨부파일")
                and not re.fullmatch(r"[\d,]+", c)
            ),
            "",
        )
        if not title or SKIP.search(title):
            continue

        out.append({
            "atc_sn": sn.group(1), "board": board, "title": title,
            "dept": next((c for c in cells if c.endswith("팀")), None),
            "posted": date.group(1),
            "url": f"{BASE}{path.rsplit('/', 1)[0]}/view.do?atcSn={sn.group(1)}",
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="농산물 뉴스 수집")
    ap.add_argument("--pages", type=int, default=3, help="게시판별로 읽을 페이지 수")
    args = ap.parse_args()

    setup_logging()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    now = dt.datetime.now().isoformat(timespec="seconds")
    total = failed = 0
    try:
        for board, path in BOARDS.items():
            for page in range(1, args.pages + 1):
                try:
                    rows = parse_board(board, path, page)
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    failed += 1
                    logging.warning("%s p%d 실패: %s", board, page, exc)
                    continue
                conn.executemany(
                    """INSERT INTO news (atc_sn,board,title,dept,posted,url,collected_at)
                       VALUES (?,?,?,?,?,?,?)
                       ON CONFLICT (atc_sn) DO UPDATE SET
                         title=excluded.title, posted=excluded.posted, url=excluded.url,
                         collected_at=excluded.collected_at""",
                    [(r["atc_sn"], r["board"], r["title"], r["dept"], r["posted"], r["url"], now)
                     for r in rows],
                )
                total += len(rows)
                time.sleep(0.3)
        conn.commit()
    finally:
        conn.close()

    logging.info("뉴스 %d건 저장 (실패 %d)", total, failed)
    return 1 if total == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
