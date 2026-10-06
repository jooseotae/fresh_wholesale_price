"""농산물 뉴스 수집 — 유통정보시스템 게시판 + 농업 전문지 RSS.

두 갈래를 모은다.

  공사   가락시장이 직접 올리는 시황·동향 자료 (게시판 HTML)
  언론   농업 전문지 4곳의 RSS

전문지 RSS 는 전 분야 기사를 통째로 주므로(축산·정책·행사 포함) 걸러야 한다.
category 태그가 없어 제목·본문 키워드로 판정한다. 조건은 세 가지다.

  1. 시황 신호어가 있을 것      — 가격·수급·작황·출하 등. 없으면 시세 기사가 아니다
  2. 농산 품목/분야가 있을 것   — 품목명은 DB 의 대표품목에서 그대로 끌어온다.
                                 취급 품목이 바뀌면 필터도 따라 바뀐다
  3. 잡음이 아닐 것             — 행사·인사·시상·사설, 그리고 축산 전용 기사

실측 기준 200건 중 약 10% 가 통과한다. 느슨하게 잡으면 농협 행사 기사가
대부분을 차지해 뉴스란이 쓸모없어진다.

    python src/collect_news.py [--pages 3] [--no-rss]
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

# 농업 전문지 RSS. 네 곳 모두 같은 CMS 라 item 구조와 링크 형식이 동일하다.
FEEDS = {
    "한국농어민신문": "https://www.agrinet.co.kr/rss/allArticle.xml",
    "농수축산신문": "https://www.aflnews.co.kr/rss/allArticle.xml",
    "한국농정신문": "https://www.ikpnews.net/rss/allArticle.xml",
    "농업인신문": "https://www.nongupin.co.kr/rss/allArticle.xml",
}

# 1) 시황 신호어 — 가격이 움직인다는 이야기인가
SIGNAL = re.compile(
    r"도매|경락|가락시장|온라인도매|시세|가격|값|수급|작황|출하|반입|산지폐기|공급과잉|"
    r"폭등|폭락|급등|급락|과잉|비축|수입산|관세|물가|할인지원|계약재배|저장량|생산량|"
    r"재배면적|수확량|강세|약세|상승세|하락세"
)
# 2) 농산 분야어 — 품목명은 DB 에서 합쳐 넣는다 (produce_pattern)
PRODUCE_BASE = r"농산물|청과|과일|과채|채소|원예|엽채|근채|양념채소|시설재배|노지"
# 3) 잡음 — 행사·인사·시상·오피니언
NOISE = re.compile(
    r"수상|기념|수료|채용|일손|체결|개최|총회|이사회|위촉|임명|취임|간담회|워크숍|견학|"
    r"발대|준공|기공|협약|캠페인|부고|인사동정|사진|화보|기부|성금|장학|봉사|나눔|전달|"
    r"꾸러미|축제|대회|선발|사설|기고|시론|논단|칼럼|연재|독자|만평"
)
# 축산 전용 기사 — 이 대시보드는 농산(과일·채소) 담당용이다
LIVESTOCK = re.compile(
    r"한우|한돈|양돈|축협|낙농|젖소|우유|계란|산란계|육계|돼지|소고기|돼지고기|닭고기|"
    r"염소|가축|축산|사료|구제역|조류인플루엔자|살처분|도축"
)

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
_SAFE_URL = re.compile(r"https?://", re.I)


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


def produce_pattern(conn: sqlite3.Connection) -> re.Pattern:
    """대표품목명 + 분야어로 '농산 기사인가'를 판정할 정규식.

    품목명을 DB 에서 끌어오므로 공사가 노출 품목을 바꾸면 필터도 같이 바뀐다.
    긴 이름부터 걸어야 '쪽파'가 '파'에 먼저 먹히지 않는다.
    """
    try:
        names = {
            r for (r,) in conn.execute(
                "SELECT DISTINCT rptv_nm FROM price_detail "
                "WHERE trade_date >= date('now','-60 day')"
            ) if r and len(r) >= 2
        }
    except sqlite3.OperationalError:
        names = set()
    parts = sorted(map(re.escape, names), key=len, reverse=True)
    return re.compile("|".join(parts + [PRODUCE_BASE]) if parts else PRODUCE_BASE)


def _tag(item: str, name: str) -> str:
    m = re.search(r"<%s>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</%s>" % (name, name), item, re.S)
    return re.sub(r"\s+", " ", html_mod.unescape(m.group(1))).strip() if m else ""


def parse_feed(outlet: str, url: str, produce: re.Pattern) -> tuple[list[dict], int]:
    """RSS 를 읽어 농산 시황 기사만 남긴다. (통과분, 전체건수)"""
    body = fetch(url)
    out, seen = [], 0
    for item in re.findall(r"<item>(.*?)</item>", body, re.S):
        seen += 1
        title = _tag(item, "title")
        link = _tag(item, "link")
        posted = _tag(item, "pubDate")[:10]
        # 이 link 는 외신 RSS 가 주는 값이고 그대로 href 에 들어간다.
        # http(s) 가 아니면 버린다 — javascript: 가 섞여 들어오면 클릭 한 번에
        # 대시보드에서 스크립트가 돈다.
        if not (title and link and _DATE.fullmatch(posted) and _SAFE_URL.match(link)):
            continue

        blob = title + " " + _tag(item, "description")[:400]
        if NOISE.search(title) or LIVESTOCK.search(title):
            continue
        if not SIGNAL.search(blob) or not produce.search(blob):
            continue
        # 본문에만 걸린 기사는 버린다. 헤드라인이 농산이거나 가격 이야기여야
        # 실제 시황 기사다. 이 조건 하나로 연재물·사설·기관 홍보가 걸러진다.
        if not (SIGNAL.search(title) or produce.search(title)):
            continue

        # 일부 매체는 기사 링크를 http 로 준다. 같은 주소가 https 로도 열리므로
        # 승격해 둔다 (사용자가 클릭해 이동하는 구간을 평문으로 두지 않는다).
        link = re.sub(r"^http://", "https://", link, flags=re.I)

        idx = re.search(r"idxno=(\d+)", link)
        out.append({
            "atc_sn": "rss:%s:%s" % (outlet, idx.group(1) if idx else abs(hash(link))),
            "board": outlet, "title": title, "dept": _tag(item, "author") or None,
            "posted": posted, "url": link,
        })
    return out, seen


def main() -> int:
    ap = argparse.ArgumentParser(description="농산물 뉴스 수집")
    ap.add_argument("--pages", type=int, default=3, help="게시판별로 읽을 페이지 수")
    ap.add_argument("--no-rss", action="store_true", help="전문지 RSS 를 건너뛴다")
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

        n_rss = 0
        if not args.no_rss:
            produce = produce_pattern(conn)
            for outlet, url in FEEDS.items():
                try:
                    rows, seen = parse_feed(outlet, url, produce)
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    failed += 1
                    logging.warning("%s RSS 실패: %s", outlet, exc)
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
                n_rss += len(rows)
                logging.info("  %s %d/%d건 통과", outlet, len(rows), seen)
                time.sleep(0.3)
            total += n_rss

        conn.commit()
    finally:
        conn.close()

    logging.info("뉴스 %d건 저장 (공사 %d / 언론 %d, 실패 %d)",
                 total, total - n_rss, n_rss, failed)
    return 1 if total == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
