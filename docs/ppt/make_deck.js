// 경영진 보고용 PPT 생성. 진행 상황이 바뀌면 이 파일을 고쳐서 다시 돌린다.
//   node docs/ppt/make_deck.js
const pptxgen = require("pptxgenjs");
const path = require("path");

const P = {
  forest: "2C5F2D",   // 주조색
  moss: "97BC62",     // 보조색
  cream: "F5F5F5",
  ink: "1B2419",
  muted: "6B7566",
  white: "FFFFFF",
  up: "B33A30",
  line: "DDE3D8",
};
const FH = "Cambria";      // 제목
const FB = "Calibri";      // 본문

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";               // 13.3 x 7.5
pres.author = "농산팀";
pres.title = "가락시장 도매시세 대시보드 구축";

const W = 13.3, H = 7.5, M = 0.7;

// ---------- 공통 헬퍼 ----------
function titleSlide(s, kicker, title, sub) {
  s.background = { color: P.forest };
  s.addText(kicker, { x: M, y: 2.05, w: 9, h: 0.34, fontFace: FB, fontSize: 13,
    color: P.moss, charSpacing: 3, bold: true });
  s.addText(title, { x: M, y: 2.5, w: 11.2, h: 1.5, fontFace: FH, fontSize: 44,
    bold: true, color: P.white, lineSpacing: 50 });
  s.addText(sub, { x: M, y: 4.15, w: 10.5, h: 0.9, fontFace: FB, fontSize: 16, color: P.cream });
}

function head(s, title, kicker) {
  s.background = { color: P.white };
  if (kicker) s.addText(kicker, { x: M, y: 0.5, w: 10, h: 0.3, fontFace: FB, fontSize: 12,
    bold: true, color: P.moss, charSpacing: 2.5 });
  s.addText(title, { x: M, y: kicker ? 0.82 : 0.6, w: 11.9, h: 0.72, fontFace: FH,
    fontSize: 33, bold: true, color: P.forest });
}

function foot(s, n) {
  s.addText("가락시장 도매시세 대시보드 · 2026-08-24", { x: M, y: H - 0.55, w: 8, h: 0.28,
    fontFace: FB, fontSize: 9.5, color: P.muted, margin: 0 });
  s.addText(String(n), { x: W - M - 0.6, y: H - 0.55, w: 0.6, h: 0.28, align: "right",
    fontFace: FB, fontSize: 9.5, color: P.muted, margin: 0 });
}

// 큰 숫자 카드
function statCard(s, x, y, w, value, label, note, accent) {
  s.addShape(pres.ShapeType.roundRect, { x, y, w, h: 1.72, rectRadius: 0.09,
    fill: { color: accent ? P.forest : P.cream }, line: { color: accent ? P.forest : P.line, width: 1 },
    shadow: { type: "outer", angle: 90, offset: 1, blur: 4, color: "000000", opacity: 0.07 } });
  s.addText(value, { x: x + 0.25, y: y + 0.24, w: w - 0.5, h: 0.72, fontFace: FH, fontSize: 34,
    bold: true, color: accent ? P.white : P.forest, margin: 0 });
  s.addText(label, { x: x + 0.25, y: y + 0.98, w: w - 0.5, h: 0.3, fontFace: FB, fontSize: 13,
    bold: true, color: accent ? P.moss : P.ink, margin: 0 });
  s.addText(note, { x: x + 0.25, y: y + 1.28, w: w - 0.5, h: 0.32, fontFace: FB, fontSize: 10.5,
    color: accent ? P.cream : P.muted, margin: 0 });
}

// 아이콘 대신 번호 원 + 제목/본문 행
function stepRow(s, x, y, w, num, title, body) {
  s.addShape(pres.ShapeType.ellipse, { x, y, w: 0.44, h: 0.44, fill: { color: P.forest } });
  s.addText(String(num), { x, y: y + 0.03, w: 0.44, h: 0.38, align: "center", fontFace: FH,
    fontSize: 16, bold: true, color: P.white, margin: 0 });
  s.addText(title, { x: x + 0.62, y: y - 0.02, w: w - 0.62, h: 0.32, fontFace: FB, fontSize: 15,
    bold: true, color: P.ink, margin: 0 });
  s.addText(body, { x: x + 0.62, y: y + 0.3, w: w - 0.62, h: 0.62, fontFace: FB, fontSize: 12,
    color: P.muted, margin: 0, lineSpacing: 16 });
}

let pageNo = 0;
const next = () => { pageNo += 1; return pageNo; };

// ============ 1. 표지 ============
{
  const s = pres.addSlide();
  titleSlide(s, "농산 부문 · 프로젝트 현황 보고",
    "가락시장 도매시세\n데일리 대시보드 구축",
    "매출·손실 '결과'만 보던 일일 리포트에, 그 원인인 '도매 시세'를 붙입니다.\n2026-08-24 기준 · 1일차 진행 보고");
  s.addText("서울시농수산식품공사 유통정보시스템 연동", { x: M, y: 5.5, w: 9, h: 0.3,
    fontFace: FB, fontSize: 12, color: P.moss, italic: true });
  s.addNotes("1일 만에 P0(운영 가능한 최소 제품)를 배포하고, P1 데이터 소스까지 확보한 상태입니다.");
}

// ============ 2. 한 장 요약 ============
{
  const s = pres.addSlide(); head(s, "한 장 요약", "EXECUTIVE SUMMARY");
  statCard(s, M, 1.75, 2.85, "79종", "시세 조회 품목", "당초 12종 → 6.6배 확대", true);
  statCard(s, M + 3.05, 1.75, 2.85, "209", "품종 단위 가격", "복숭아만 33품종");
  statCard(s, M + 6.10, 1.75, 2.85, "매일 14:00", "자동 갱신", "사람 개입 없음");
  statCard(s, M + 9.15, 1.75, 2.85, "0원", "추가 비용", "무인증 공개 데이터");

  s.addText("무엇이 달라지나", { x: M, y: 3.75, w: 11.9, h: 0.34, fontFace: FB, fontSize: 15,
    bold: true, color: P.forest });
  stepRow(s, M, 4.2, 5.6, 1, "선행지표를 확보했습니다",
    "기존 매출·손실율 리포트는 이미 벌어진 결과만 보여줍니다. 도매 시세는 그 결과가 만들어지기 전에 움직입니다.");
  stepRow(s, M, 5.35, 5.6, 2, "계절 품목이 자동으로 따라옵니다",
    "반입량 상위 품목을 자동 선정하므로, 복숭아·포도 철이 지나면 목록이 스스로 바뀝니다.");
  stepRow(s, M + 6.1, 4.2, 5.9, 3, "3단계로 파고들 수 있습니다",
    "전체 → 청과·채소 → 품목별 품종 단위까지. 각 단계에 검색과 그래프가 붙어 있습니다.");
  stepRow(s, M + 6.1, 5.35, 5.9, 4, "자사 MC 코드와 축을 맞췄습니다",
    "가락 품목을 자재그룹 코드에 매핑해 기존 리포트와 나란히 읽을 수 있습니다.");
  foot(s, next());
}

// ============ 3. 배경 ============
{
  const s = pres.addSlide(); head(s, "왜 필요한가", "BACKGROUND");
  s.addText("현재 농산팀이 매일 보는 리포트는 두 가지입니다. 둘 다 '이미 일어난 일'입니다.",
    { x: M, y: 1.62, w: 11.9, h: 0.35, fontFace: FB, fontSize: 14.5, color: P.ink });

  const cards = [
    ["기존 · 매출 대시보드", "총매출액 · 실매출액 · 매출총이익률", "부문(채소/청과/양곡) → MC 자재그룹", "결과"],
    ["기존 · 손실율 대시보드", "마크다운 · 폐기로스 · 재고차이 · 매가변경", "MC 손실율 등락 TOP10", "결과"],
    ["신규 · 도매시세 대시보드", "가락시장 경락가 · 반입물량", "품목 → 품종 · 등급 단위", "원인"],
  ];
  cards.forEach(function (c, i) {
    const x = M + i * 4.08, isNew = i === 2;
    s.addShape(pres.ShapeType.roundRect, { x, y: 2.25, w: 3.78, h: 2.5, rectRadius: 0.09,
      fill: { color: isNew ? P.forest : P.cream }, line: { color: isNew ? P.forest : P.line, width: 1 } });
    s.addText(c[3], { x: x + 0.25, y: 2.45, w: 1.4, h: 0.3, fontFace: FB, fontSize: 10.5, bold: true,
      color: isNew ? P.moss : P.muted, charSpacing: 2, margin: 0 });
    s.addText(c[0], { x: x + 0.25, y: 2.8, w: 3.28, h: 0.38, fontFace: FB, fontSize: 15, bold: true,
      color: isNew ? P.white : P.ink, margin: 0 });
    s.addText(c[1], { x: x + 0.25, y: 3.25, w: 3.28, h: 0.75, fontFace: FB, fontSize: 12,
      color: isNew ? P.cream : P.muted, margin: 0, lineSpacing: 16 });
    s.addText(c[2], { x: x + 0.25, y: 4.05, w: 3.28, h: 0.55, fontFace: FB, fontSize: 11,
      color: isNew ? P.moss : P.muted, italic: true, margin: 0, lineSpacing: 15 });
  });

  s.addShape(pres.ShapeType.roundRect, { x: M, y: 5.05, w: 11.9, h: 1.05, rectRadius: 0.09,
    fill: { color: "FBEEEC" }, line: { color: "E8C9C4", width: 1 } });
  s.addText([
    { text: "지금의 공백  ", options: { bold: true, color: P.up } },
    { text: "배추 도매가가 사흘째 오르고 있어도, 매가·발주를 바꿀 근거는 매출과 손실이 망가진 다음에야 숫자로 보입니다. 그 사이의 시간이 곧 손실입니다.",
      options: { color: P.ink } },
  ], { x: M + 0.3, y: 5.25, w: 11.3, h: 0.7, fontFace: FB, fontSize: 13.5, margin: 0, lineSpacing: 19 });
  foot(s, next());
}

// ============ 4. 무엇을 만들었나 ============
{
  const s = pres.addSlide(); head(s, "무엇을 만들었나", "DELIVERABLE");
  s.addText("바탕화면 아이콘 하나. 열면 3단계로 파고듭니다.",
    { x: M, y: 1.62, w: 11.9, h: 0.35, fontFace: FB, fontSize: 14.5, color: P.ink });

  const levels = [
    ["1단계 · 전체", "총 반입량과 부문 비중, 급등락 품목 건수를 한눈에",
     "· 핵심 지표 4종\n· 부문별 반입량 TOP10 막대\n· 주요 품목 등락 다이버징 막대"],
    ["2단계 · 청과 / 채소", "부문을 눌러 들어가면 그 부문 전 품목",
     "· 품목 검색창\n· 반입량 TOP10 · 가격 등락\n· 품목 전체 표 (물량·가격·전일비)"],
    ["3단계 · 품목별", "품목을 누르면 품종 단위까지",
     "· 품종·규격 검색창\n· 가격 추이 · 반입량 추이 선그래프\n· 품종별 최저·평균·최고 / 7일·1년 전"],
  ];
  levels.forEach(function (L, i) {
    const x = M + i * 4.08;
    s.addShape(pres.ShapeType.roundRect, { x, y: 2.2, w: 3.78, h: 3.35, rectRadius: 0.09,
      fill: { color: P.white }, line: { color: P.line, width: 1.2 },
      shadow: { type: "outer", angle: 90, offset: 1, blur: 5, color: "000000", opacity: 0.08 } });
    s.addShape(pres.ShapeType.ellipse, { x: x + 0.25, y: 2.42, w: 0.4, h: 0.4, fill: { color: P.forest } });
    s.addText(String(i + 1), { x: x + 0.25, y: 2.45, w: 0.4, h: 0.34, align: "center", fontFace: FH,
      fontSize: 15, bold: true, color: P.white, margin: 0 });
    s.addText(L[0], { x: x + 0.75, y: 2.44, w: 2.85, h: 0.36, fontFace: FB, fontSize: 14.5,
      bold: true, color: P.forest, margin: 0 });
    s.addText(L[1], { x: x + 0.25, y: 2.95, w: 3.28, h: 0.6, fontFace: FB, fontSize: 12,
      color: P.muted, margin: 0, lineSpacing: 16 });
    s.addText(L[2], { x: x + 0.25, y: 3.6, w: 3.28, h: 1.7, fontFace: FB, fontSize: 12,
      color: P.ink, margin: 0, lineSpacing: 19 });
  });
  s.addText("표시 방식: 지표 카드 · 가로 막대 · 다이버징 막대 · 선그래프 · 정렬 가능한 표 · 검색 필터",
    { x: M, y: 5.75, w: 11.9, h: 0.35, fontFace: FB, fontSize: 12.5, color: P.muted, italic: true });
  foot(s, next());
}

// ============ 5. 데이터 확보 (차트) ============
{
  const s = pres.addSlide(); head(s, "데이터 커버리지", "DATA");
  s.addText("당초 확보한 공개 API는 12품목 고정이었습니다. 추가 조사로 79종까지 넓혔습니다.",
    { x: M, y: 1.62, w: 11.9, h: 0.35, fontFace: FB, fontSize: 14.5, color: P.ink });

  s.addChart(pres.ChartType.bar, [{
    name: "조회 가능 품목 수",
    labels: ["1차 소스 (주요품목)", "2차 소스 (품목별 가격)"],
    values: [12, 79],
  }], {
    x: M, y: 2.15, w: 6.4, h: 3.4,
    barDir: "bar", chartColors: [P.moss, P.forest], varyColors: true,
    showTitle: true, title: "대표품목 조회 범위", titleFontFace: FB, titleFontSize: 13, titleColor: P.forest,
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontFace: FB, dataLabelFontSize: 12,
    dataLabelColor: P.ink,
    catAxisLabelFontFace: FB, catAxisLabelFontSize: 11, catAxisLabelColor: P.muted,
    valAxisLabelFontFace: FB, valAxisLabelFontSize: 10, valAxisLabelColor: P.muted,
    valGridLine: { color: P.line, size: 1 }, catGridLine: { style: "none" },
    showLegend: false, barGapWidthPct: 60,
  });

  const facts = [
    ["품종 단위까지 확보", "209품종. 복숭아 33 · 포도 6 · 자두 7품종을 각각 따로 봅니다."],
    ["반입물량 3부류", "과일류 26 · 과일과채류 9 · 일반채소류 86품목, 톤 단위 일별."],
    ["로그인 불필요", "공개 데이터라 계정·인증키·비용이 들지 않습니다."],
    ["과거 소급 가능", "날짜를 지정해 과거 데이터를 받아올 수 있어 추이 분석이 됩니다."],
  ];
  facts.forEach(function (f, i) {
    const y = 2.3 + i * 0.85;
    s.addText(f[0], { x: M + 6.9, y, w: 5, h: 0.3, fontFace: FB, fontSize: 13.5, bold: true,
      color: P.forest, margin: 0 });
    s.addText(f[1], { x: M + 6.9, y: y + 0.3, w: 5, h: 0.5, fontFace: FB, fontSize: 11.5,
      color: P.muted, margin: 0, lineSpacing: 15 });
  });
  foot(s, next());
}

// ============ 6. 검증 ============
{
  const s = pres.addSlide(); head(s, "계절성 검증", "VALIDATION");
  s.addText("'시즌 품목을 자동으로 따라간다'가 실제로 되는지, 서로 다른 세 시점으로 교차 확인했습니다.",
    { x: M, y: 1.62, w: 11.9, h: 0.35, fontFace: FB, fontSize: 14.5, color: P.ink });

  s.addChart(pres.ChartType.bar, [
    { name: "8월 21일", labels: ["복숭아", "포도", "자두", "감귤", "딸기"], values: [381, 194, 54, 0, 0] },
    { name: "2월 24일", labels: ["복숭아", "포도", "자두", "감귤", "딸기"], values: [0, 49, 0, 234, 199] },
  ], {
    x: M, y: 2.2, w: 7.5, h: 3.5,
    barDir: "col", chartColors: [P.forest, P.moss],
    showTitle: true, title: "청과 반입량 비교 (톤)", titleFontFace: FB, titleFontSize: 13, titleColor: P.forest,
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontFace: FB, dataLabelFontSize: 10,
    dataLabelColor: P.ink,
    catAxisLabelFontFace: FB, catAxisLabelFontSize: 11, catAxisLabelColor: P.muted,
    valAxisLabelFontFace: FB, valAxisLabelFontSize: 10, valAxisLabelColor: P.muted,
    valGridLine: { color: P.line, size: 1 }, catGridLine: { style: "none" },
    showLegend: true, legendPos: "t", legendFontFace: FB, legendFontSize: 11, legendColor: P.muted,
  });

  s.addShape(pres.ShapeType.roundRect, { x: M + 8.0, y: 2.2, w: 3.9, h: 3.5, rectRadius: 0.09,
    fill: { color: P.cream }, line: { color: P.line, width: 1 } });
  s.addText("읽는 법", { x: M + 8.25, y: 2.42, w: 3.4, h: 0.3, fontFace: FB, fontSize: 13.5,
    bold: true, color: P.forest, margin: 0 });
  s.addText("같은 로직으로 뽑았는데 8월에는 복숭아·포도·자두가, 2월에는 감귤·딸기가 상위에 올라옵니다.\n\n품목 목록을 사람이 관리할 필요가 없다는 뜻입니다. 계절이 바뀌면 대시보드가 스스로 바뀝니다.\n\n2025년 12월 시점으로도 한 번 더 확인했습니다 (감귤 465톤).",
    { x: M + 8.25, y: 2.8, w: 3.4, h: 2.7, fontFace: FB, fontSize: 12, color: P.ink,
      margin: 0, lineSpacing: 17 });
  foot(s, next());
}

// ============ 7. 자동화 ============
{
  const s = pres.addSlide(); head(s, "자동 갱신 구조", "AUTOMATION");
  s.addText("경매는 당일 저녁부터 다음날 새벽에 끝납니다. 과일류 확정 시각 이후인 14:00에 한 번 돌립니다.",
    { x: M, y: 1.62, w: 11.9, h: 0.35, fontFace: FB, fontSize: 14.5, color: P.ink });

  const flow = [
    ["매일 14:00", "작업 스케줄러가 자동 실행"],
    ["수집", "가격 · 반입물량 · 뉴스"],
    ["누적", "로컬 DB에 이력 저장"],
    ["생성", "대시보드 파일 재작성"],
    ["확인", "바탕화면 아이콘 클릭"],
  ];
  flow.forEach(function (f, i) {
    const x = M + i * 2.45;
    s.addShape(pres.ShapeType.roundRect, { x, y: 2.35, w: 2.1, h: 1.5, rectRadius: 0.09,
      fill: { color: i === 0 ? P.forest : P.white }, line: { color: i === 0 ? P.forest : P.line, width: 1.2 } });
    s.addText(f[0], { x: x + 0.15, y: 2.6, w: 1.8, h: 0.4, align: "center", fontFace: FB, fontSize: 14,
      bold: true, color: i === 0 ? P.white : P.forest, margin: 0 });
    s.addText(f[1], { x: x + 0.15, y: 3.05, w: 1.8, h: 0.6, align: "center", fontFace: FB, fontSize: 11,
      color: i === 0 ? P.cream : P.muted, margin: 0, lineSpacing: 14 });
    if (i < flow.length - 1) s.addText("›", { x: x + 2.12, y: 2.85, w: 0.32, h: 0.45, align: "center",
      fontFace: FB, fontSize: 22, color: P.moss, margin: 0 });
  });

  s.addText("안정성 장치", { x: M, y: 4.25, w: 11.9, h: 0.34, fontFace: FB, fontSize: 15,
    bold: true, color: P.forest });
  stepRow(s, M, 4.7, 3.75, 1, "수집 실패해도 화면은 살아 있음",
    "마지막 정상 데이터를 유지하고 화면 상단에 실패 배너를 띄웁니다.");
  stepRow(s, M + 4.08, 4.7, 3.75, 2, "휴장일 자동 판별",
    "휴장일에는 직전 거래일 값이 반복됩니다. 이를 감지해 집계에서 제외합니다.");
  stepRow(s, M + 8.16, 4.7, 3.75, 3, "재실행해도 중복 없음",
    "같은 날짜를 여러 번 수집해도 데이터가 어긋나지 않습니다.");
  foot(s, next());
}

// ============ 8. 진행 현황 ============
{
  const s = pres.addSlide(); head(s, "진행 현황과 다음 단계", "ROADMAP");

  const rows = [
    ["완료", "P0 · 최소 운영본", "12품목 자동 수집 · 대시보드 · 스케줄러 · 1년치 이력 확보", "100%"],
    ["완료", "P1 · 데이터 확대", "79 대표품목 / 209품종 · 반입물량 3부류 · 뉴스 연동", "100%"],
    ["완료", "P1 · 드릴다운 UI", "3단계 드릴다운 · 검색 · 5종 시각화", "100%"],
    ["진행", "양곡 거래정보", "백미 10kg · 주요 잡곡류. 소스 구조 확인 중", "조사"],
    ["예정", "가격지수 · 거래동향", "가락시장 가격지수, 주간 거래동향 지표 편입", "대기"],
    ["예정", "자사 실적 결합", "시세와 손실율을 한 화면에서 비교", "대기"],
  ];

  const colX = [M, M + 1.15, M + 4.3, M + 10.9];
  s.addText("상태", { x: colX[0], y: 1.75, w: 1.1, h: 0.3, fontFace: FB, fontSize: 11, bold: true, color: P.muted, margin: 0 });
  s.addText("과제", { x: colX[1], y: 1.75, w: 3.0, h: 0.3, fontFace: FB, fontSize: 11, bold: true, color: P.muted, margin: 0 });
  s.addText("내용", { x: colX[2], y: 1.75, w: 6.4, h: 0.3, fontFace: FB, fontSize: 11, bold: true, color: P.muted, margin: 0 });
  s.addText("진척", { x: colX[3], y: 1.75, w: 1.0, h: 0.3, fontFace: FB, fontSize: 11, bold: true, color: P.muted, margin: 0 });

  rows.forEach(function (r, i) {
    const y = 2.15 + i * 0.72;
    const done = r[0] === "완료";
    s.addShape(pres.ShapeType.roundRect, { x: M, y, w: 11.9, h: 0.62, rectRadius: 0.06,
      fill: { color: i % 2 ? P.white : P.cream }, line: { color: P.line, width: 0.6 } });
    s.addShape(pres.ShapeType.roundRect, { x: colX[0] + 0.12, y: y + 0.15, w: 0.72, h: 0.32, rectRadius: 0.05,
      fill: { color: done ? P.forest : "5E8C4A" } });
    s.addText(r[0], { x: colX[0] + 0.12, y: y + 0.18, w: 0.72, h: 0.26, align: "center", fontFace: FB,
      fontSize: 10.5, bold: true, color: P.white, margin: 0 });
    s.addText(r[1], { x: colX[1], y: y + 0.17, w: 3.0, h: 0.3, fontFace: FB, fontSize: 12.5,
      bold: true, color: P.ink, margin: 0 });
    s.addText(r[2], { x: colX[2], y: y + 0.18, w: 6.4, h: 0.3, fontFace: FB, fontSize: 11.5,
      color: P.muted, margin: 0 });
    s.addText(r[3], { x: colX[3], y: y + 0.17, w: 1.0, h: 0.3, fontFace: FB, fontSize: 11.5,
      bold: true, color: done ? P.forest : P.muted, margin: 0 });
  });

  s.addText("1일차 기준. 이 문서는 프로젝트 종료까지 진행에 맞춰 갱신합니다.",
    { x: M, y: 6.5, w: 11.9, h: 0.3, fontFace: FB, fontSize: 11.5, color: P.muted, italic: true });
  foot(s, next());
}

// ============ 9. 리스크 ============
{
  const s = pres.addSlide(); head(s, "리스크와 대응", "RISK");

  const risks = [
    ["공개 API 의존", "공사가 사이트를 개편하면 수집이 멈출 수 있습니다.",
     "수집 실패를 화면과 로그로 즉시 알리고, 마지막 정상 데이터를 유지합니다. 호출 규약은 문서로 남겨 복구를 빠르게 합니다."],
    ["품종 교체 구간의 급등락", "햇과일이 나오는 시점에 전일대비가 수백 %로 찍힙니다.",
     "데이터 오류가 아니라 실제 경락가 변화입니다. 품종 단위로 내려가 확인할 수 있게 3단계 드릴다운을 두었습니다."],
    ["소물량 품목의 착시", "3톤짜리 품목의 +120%는 의사결정에 도움이 안 됩니다.",
     "급등락 집계를 반입량 상위 30품목으로 제한해 노이즈를 걸러냅니다."],
    ["자료 이용 범위", "공사 고지상 계약·납품·손해배상 증빙으로는 쓸 수 없습니다.",
     "내부 판단 참고용으로만 씁니다. 대시보드 하단에 상시 명시했습니다."],
  ];

  risks.forEach(function (r, i) {
    const x = M + (i % 2) * 6.1, y = 1.8 + Math.floor(i / 2) * 2.35;
    s.addShape(pres.ShapeType.roundRect, { x, y, w: 5.8, h: 2.1, rectRadius: 0.09,
      fill: { color: P.white }, line: { color: P.line, width: 1.2 } });
    s.addText(r[0], { x: x + 0.28, y: y + 0.22, w: 5.24, h: 0.32, fontFace: FB, fontSize: 14,
      bold: true, color: P.up, margin: 0 });
    s.addText(r[1], { x: x + 0.28, y: y + 0.58, w: 5.24, h: 0.5, fontFace: FB, fontSize: 11.5,
      color: P.ink, margin: 0, lineSpacing: 15 });
    s.addText([
      { text: "대응  ", options: { bold: true, color: P.forest } },
      { text: r[2], options: { color: P.muted } },
    ], { x: x + 0.28, y: y + 1.12, w: 5.24, h: 0.85, fontFace: FB, fontSize: 11, margin: 0, lineSpacing: 15 });
  });
  foot(s, next());
}

// ============ 10. 마무리 ============
{
  const s = pres.addSlide();
  s.background = { color: P.forest };
  s.addText("정리", { x: M, y: 1.6, w: 9, h: 0.34, fontFace: FB, fontSize: 13, color: P.moss,
    charSpacing: 3, bold: true });
  s.addText("결과를 보던 리포트에\n원인을 붙였습니다", { x: M, y: 2.05, w: 11.2, h: 1.5,
    fontFace: FH, fontSize: 38, bold: true, color: P.white, lineSpacing: 46 });

  const pts = [
    "추가 비용 없이, 공개 데이터만으로 79 대표품목 · 209품종의 도매 시세를 매일 자동 확보",
    "반입량 기준 자동 선정이라 계절이 바뀌어도 사람이 품목을 관리할 필요가 없음",
    "전체에서 품종까지 3단계로 파고들 수 있어, 이상 신호의 원인을 그 자리에서 확인",
  ];
  pts.forEach(function (t, i) {
    s.addShape(pres.ShapeType.ellipse, { x: M, y: 4.05 + i * 0.62, w: 0.16, h: 0.16, fill: { color: P.moss } });
    s.addText(t, { x: M + 0.4, y: 3.95 + i * 0.62, w: 11, h: 0.4, fontFace: FB, fontSize: 14,
      color: P.cream, margin: 0 });
  });
  s.addText("다음 보고: 양곡 거래정보 편입 및 가격지수 연동", { x: M, y: 6.2, w: 11, h: 0.34,
    fontFace: FB, fontSize: 12.5, color: P.moss, italic: true });
}

const out = path.join(__dirname, "가락시장_도매시세_대시보드_현황보고.pptx");
pres.writeFile({ fileName: out }).then(function () { console.log("생성 완료:", out); });
