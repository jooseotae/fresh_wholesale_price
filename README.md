# 가락시장 도매시세 대시보드

서울시농수산식품공사 유통정보시스템에서 농산 담당 품목의 도매시세를 매일 자동으로 받아
정적 HTML 대시보드로 만든다. 설계 배경과 범위는 [docs/PRD.md](docs/PRD.md) 참고.

## 쓰는 법

바탕화면의 **`가락시세 대시보드`** 를 더블클릭하면 열린다. 끝이다.
데이터는 매일 **14:00** 에 작업 스케줄러가 알아서 갱신한다.

대시보드 상단에서 **부문**(채소/청과)과 **품목**(드롭다운, 전일 변동률 내림차순)을 골라
보고 싶은 것만 남길 수 있다. 선택은 브라우저에 저장돼 다음에 열 때도 유지된다.

## 수동 실행

```bash
C:\workspace\fresh_wholesale_price\run_daily.cmd
```

개별 실행:

```bash
python src/collect.py              # 오늘 수집
python src/collect.py --date 20260821
python src/collect.py --backfill 400
python src/build.py --open         # 대시보드 생성 후 브라우저로 열기
```

의존성은 없다. Python 표준 라이브러리만 쓴다.

## 구조

```
src/collect_bix5.py  가격 79 대표품목 + 반입물량 3부류  (주력)
src/collect_news.py  게시판 뉴스
src/collect.py       주요품목 12종 (P0 소스, 1년치 이력 유지용)
src/build_v2.py      DB -> out/dashboard.html
src/template.html    대시보드 템플릿 (수정은 여기서)
config/items.json    12종 ↔ 자사 MC 매핑
run_daily.cmd        스케줄러 진입점
docs/SOURCES.md      API 호출 규약 — 반드시 읽을 것
docs/worklog/        날짜별 작업 일지
docs/ppt/            경영진 보고 PPT + 생성 스크립트
```

## 대시보드 사용법

**드릴다운 3단계** — 전체 → 청과/채소 → 품목별 품종

- 1단계에서 부문 카드를 클릭하면 2단계로
- 2단계에서 품목 행을 클릭하면 3단계로 (붉은 안내 문구 + 행 오른쪽 `›` 표시)
- 왼쪽 위 **← 돌아가기** 버튼으로 상위 단계 복귀
- 2단계는 품목 검색, 3단계는 품종·규격 검색 (`천도 10kg` 처럼 조합 검색 가능)

## 데이터

- 출처: `POST https://www.garak.co.kr/youtong/bigDataAnalyzesList.do` (인증 불필요)
- 경매(정가수의) 상장거래, **등급 상** 기준
- 현재 보유: 2025-07-21 ~ (12품목, 전년 동기 비교 가능)

## 알아둘 것

**품목은 12종 고정이다.** 공사가 노출하는 주요품목 목록이며, 13개월치를 확인한 결과
계절에 따라 교체되지 않는다. 수박·참외·딸기·포도·버섯류 등으로 넓히려면 다른 소스를
뚫어야 한다 (PRD P1).

다만 공사가 나중에 품목을 바꾸더라도 **대시보드는 자동으로 따라간다.** `config/items.json`
은 허용목록이 아니라 매핑 레이어라서, 모르는 품목이 나타나면 `MC 미매핑` 으로 표시하고
상단에 배너로 알린다. 그때 매핑만 추가하면 된다.

**휴장일 처리** — API는 휴장일에 직전 거래일 값을 그대로 되돌려준다. 페이로드 해시가
직전일과 같으면 `is_carry=1` 로 표시하고 집계·차트에서 제외한다.

**품종 교체 구간의 급등락** — 예를 들어 햇사과가 나오기 시작하면 전일대비가 수백 %로
찍힌다. 데이터 오류가 아니라 실제 경락가 변화지만, 같은 품목의 연속 시세로 읽으면 안 된다.

**이용 제한** — 사이트 고지에 따라 이 자료는 내부 참고용이며, 계약·납품·사실조회 등의
근거·증빙자료로 사용할 수 없다.

## 자동 실행 관리

```bash
schtasks /query /tn "가락시세 대시보드" /fo LIST
```

```bash
schtasks /delete /tn "가락시세 대시보드" /f
```

## 배포 (Vercel)

1. GitHub에서 이 저장소를 만든 뒤 최초 1회만 수동 푸시 (인증 팝업 완료용)
   ```bash
   git push -u origin main
   ```
2. Vercel에서 이 GitHub 저장소를 Import — 프레임워크 자동 감지, 별도 설정 불필요
3. `vercel.json` 이 루트 URL에 `out/dashboard.html` 을 서빙

이후에는 `run_daily.cmd` 가 매일 14:00에
1) 데이터 수집 → 2) 대시보드 재생성 → 3) `data/prices.sqlite` 와 `out/dashboard.html` 을
자동 커밋·푸시 → 4) Vercel이 자동 재배포합니다.

**주의:** Git Credential Manager 인증이 살아있어야 자동 푸시가 됩니다.
자격 만료 시 `git push` 를 한 번 수동 실행해 재인증하세요.
