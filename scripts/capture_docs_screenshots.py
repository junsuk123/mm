#!/usr/bin/env python3
"""Render documentation screenshots without changing participant/session data."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT_DIR = ROOT / "docs" / "screenshots"
CROPPED_SCREENSHOT_DIR = SCREENSHOT_DIR / "crops"
CHROME = shutil.which("google-chrome") or shutil.which("chromium")


def chrome_screenshot(html_path: Path, output_path: Path, width: int, height: int) -> None:
    if not CHROME:
        raise RuntimeError("Google Chrome or Chromium is required")
    last_error: Exception | None = None
    for attempt in range(3):
        with tempfile.TemporaryDirectory(prefix="mm-chrome-profile.") as profile_dir:
            try:
                subprocess.run(
                    [
                        CHROME,
                        "--headless",
                        "--no-sandbox",
                        "--disable-gpu",
                        "--disable-dev-shm-usage",
                        "--disable-background-networking",
                        "--disable-extensions",
                        "--no-first-run",
                        f"--user-data-dir={profile_dir}",
                        "--hide-scrollbars",
                        f"--window-size={width},{height}",
                        f"--screenshot={output_path}",
                        html_path.as_uri(),
                    ],
                    check=True,
                    timeout=20,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            except (subprocess.SubprocessError, OSError) as error:
                last_error = error
                if output_path.exists() and output_path.stat().st_size > 0:
                    return
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"Failed to capture {output_path.name}") from last_error


def replace_dom_ready(html: str, injection: str) -> str:
    needle = "      loadUserFolders();\n    });"
    if needle not in html:
        raise RuntimeError("Admin DOM-ready block was not found")
    return html.replace(
        needle,
        "      loadUserFolders();\n" + injection + "\n    });",
    )


def crop_screenshot(
    source_path: Path,
    output_path: Path,
    box: tuple[int, int, int, int],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as source:
        left, top, right, bottom = box
        if not (
            0 <= left < right <= source.width
            and 0 <= top < bottom <= source.height
        ):
            raise ValueError(
                f"Invalid crop {box} for {source_path.name} "
                f"({source.width}x{source.height})"
            )
        source.crop(box).save(output_path, optimize=True)


def create_feature_crops() -> None:
    pc_source = SCREENSHOT_DIR / "pc-dashboard.png"
    pc_crops = {
        "pc-session-settings.png": (8, 53, 432, 524),
        "pc-mobile-qr-link.png": (8, 523, 432, 905),
        "pc-participants-results.png": (440, 53, 934, 905),
        "pc-cli-process.png": (942, 53, 1592, 185),
        "pc-group-insight.png": (942, 185, 1592, 905),
    }
    for filename, box in pc_crops.items():
        crop_screenshot(
            pc_source,
            CROPPED_SCREENSHOT_DIR / filename,
            box,
        )

    mobile_crops = {
        "mobile-user-meal.png": (
            "mobile-01-entry.png",
            (8, 61, 480, 143),
        ),
        "mobile-category-selection.png": (
            "mobile-01-entry.png",
            (8, 151, 480, 542),
        ),
        "mobile-food-selection.png": (
            "mobile-02-recent-food.png",
            (8, 151, 480, 486),
        ),
        "mobile-preference-and-submit.png": (
            "mobile-07-ready.png",
            (8, 151, 480, 899),
        ),
        "mobile-previous-feedback.png": (
            "mobile-09-previous-feedback.png",
            (25, 370, 475, 542),
        ),
        "mobile-final-recommendation.png": (
            "mobile-10-result.png",
            (25, 315, 475, 600),
        ),
        "mobile-naver-route.png": (
            "mobile-11-naver-route.png",
            (0, 0, 480, 820),
        ),
    }
    for filename, (source_name, box) in mobile_crops.items():
        crop_screenshot(
            SCREENSHOT_DIR / source_name,
            CROPPED_SCREENSHOT_DIR / filename,
            box,
        )


def qr_preview_svg() -> str:
    """Build a deterministic QR-like preview without external packages."""
    size = 29
    cells = [[False for _ in range(size)] for _ in range(size)]

    def finder(left: int, top: int) -> None:
        for y in range(7):
            for x in range(7):
                cells[top + y][left + x] = (
                    x in (0, 6)
                    or y in (0, 6)
                    or (2 <= x <= 4 and 2 <= y <= 4)
                )

    finder(0, 0)
    finder(size - 7, 0)
    finder(0, size - 7)
    for y in range(size):
        for x in range(size):
            in_finder_zone = (
                (x < 8 and y < 8)
                or (x >= size - 8 and y < 8)
                or (x < 8 and y >= size - 8)
            )
            if not in_finder_zone and ((x * 11 + y * 7 + x * y) % 5 in (0, 1)):
                cells[y][x] = True

    rects = "".join(
        f'<rect x="{x}" y="{y}" width="1" height="1"/>'
        for y, row in enumerate(cells)
        for x, filled in enumerate(row)
        if filled
    )
    return (
        f'<svg viewBox="-2 -2 {size + 4} {size + 4}" '
        'xmlns="http://www.w3.org/2000/svg" aria-label="문서용 QR 미리보기">'
        f'<rect x="-2" y="-2" width="{size + 4}" height="{size + 4}" fill="white"/>'
        f'<g fill="#173958">{rects}</g></svg>'
    )


def build_admin_preview() -> str:
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    html = html.replace(
        '<script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>',
        "",
    )
    demo = json.loads((ROOT / "dataset" / "demo_session.json").read_text(encoding="utf-8"))
    participants = demo["participants"]
    members = [[0, 1, 4, 5, 8, 9], [2, 3, 6, 7]]
    restaurants = [
        {
            "name": "숙성부심 군자본점",
            "food": "구이/고기류",
            "category": "한식",
            "score": 0.667,
            "distance_m": 415,
            "walking_minutes": 7,
            "review_rank": 1,
            "matched_terms": ["한식", "구이/고기류"],
            "reason": "6명 중 5명의 개인 선호를 반영한 평균 만족도",
        },
        {
            "name": "마루토모",
            "food": "면류",
            "category": "일식",
            "score": 0.68,
            "distance_m": 520,
            "walking_minutes": 9,
            "review_rank": 1,
            "matched_terms": ["일식", "면류"],
            "reason": "4명 중 4명의 개인 선호를 반영한 평균 만족도",
        },
    ]
    groups = []
    for group_id, indexes in enumerate(members, start=1):
        group_members = [participants[index] for index in indexes]
        groups.append(
            {
                "group_id": group_id,
                "members": [member["user_id"] for member in group_members],
                "member_names": [member["user_id"] for member in group_members],
                "recommendations": [restaurants[group_id - 1]],
            }
        )
    folders = "".join(
        (
            '<div class="user-folder selected">'
            '<span class="folder-icon">📁</span>'
            f'<span class="folder-id">U{index:04d}</span></div>'
        )
        for index in range(1, 11)
    )
    injection = f"""
      currentSessionId = 'demo-docs';
      participants = {json.dumps(participants, ensure_ascii=False)};
      document.getElementById('noData').style.display = 'none';
      document.getElementById('participantsContainer').style.display = 'block';
      document.getElementById('resultsContainer').style.display = 'flex';
      document.getElementById('sessionStatus').style.display = 'block';
      document.getElementById('sessionStatus').className = 'status success';
      document.getElementById('sessionStatus').textContent = '✅ 세션 생성됨 · 2개 그룹 · 전체 10명';
      document.getElementById('sessionId').style.display = 'block';
      document.getElementById('sessionId').textContent = '세션 ID: demo-docs';
      renderQrPanel('https://example.trycloudflare.com/join/demo-docs');
      document.getElementById('qrCode').innerHTML = {json.dumps(qr_preview_svg(), ensure_ascii=False)};
      document.getElementById('userFolders').innerHTML = {json.dumps(folders, ensure_ascii=False)};
      updateParticipantsList();
      renderRecommendationGroups({json.dumps(groups, ensure_ascii=False)});
      const screen = document.querySelector('.terminal-screen');
      screen.innerHTML = '<div class="terminal-line terminal-command"><span class="terminal-prompt">$ </span>jq 그룹 프로필 생성 | provider 검색 | 점수 계산</div><div class="terminal-line terminal-output">완료: 추천 결과 JSON을 웹 화면으로 전달했습니다.</div>';
    """
    return replace_dom_ready(html, injection)


def mobile_mock_script(menu: dict[str, list[str]]) -> str:
    categories = list(menu)
    profile_response = {
        "profile": None,
        "previous_session_id": None,
        "last_recommendation": None,
        "navigation": {
            "global_enabled": True,
            "enabled": True,
            "consent_status": "unknown",
        },
    }
    return f"""
  <script>
    const docsMenu = {json.dumps(menu, ensure_ascii=False)};
    const docsProfile = {json.dumps(profile_response, ensure_ascii=False)};
    window.fetch = async function(url, options = {{}}) {{
      const path = String(url);
      let payload = {{}};
      if (path.startsWith('/api/session/') && path.includes('/participant-recommendation/')) {{
        payload = {{status: 'collecting', participant_id: null, recommendation: null}};
      }} else if (path.startsWith('/api/session/')) {{
        payload = {{id: 'demo-docs', status: 'collecting', mobile_enabled: true}};
      }} else if (path === '/api/categories') {{
        payload = {json.dumps(categories, ensure_ascii=False)};
      }} else if (path.startsWith('/api/foods')) {{
        const category = decodeURIComponent((path.split('category=')[1] || '').replace(/\\+/g, ' '));
        payload = docsMenu[category] || [];
      }} else if (path.startsWith('/api/participant/')) {{
        payload = docsProfile;
      }}
      return new Response(JSON.stringify(payload), {{
        status: 200,
        headers: {{'Content-Type': 'application/json'}}
      }});
    }};
  </script>
"""


def mobile_stage_script(stage: str) -> str:
    shared = """
      categories = Object.keys(docsMenu);
      document.getElementById('userId').value = '반짝이는 수달';
      selectMealType('lunch');
    """
    states = {
        "01-entry": """
          currentStep = 0;
          render();
        """,
        "02-recent-food": """
          state.recent = {high: '한식', food: ''};
          currentStep = 1;
          render();
        """,
        "03-preference-1-category": """
          state.recent = {high: '한식', food: '밥/정식류'};
          currentStep = 2;
          render();
        """,
        "04-preference-1-foods": """
          state.recent = {high: '한식', food: '밥/정식류'};
          state.likeHigh = ['일식'];
          state.likeFoods = {'일식': []};
          currentStep = 3;
          render();
        """,
        "05-preference-2-category": """
          state.recent = {high: '한식', food: '밥/정식류'};
          state.likeHigh = ['일식'];
          state.likeFoods = {'일식': ['초밥/회류', '면류']};
          currentStep = 4;
          render();
        """,
        "06-preference-2-foods": """
          state.recent = {high: '한식', food: '밥/정식류'};
          state.likeHigh = ['일식', '중식'];
          state.likeFoods = {
            '일식': ['초밥/회류', '면류'],
            '중식': []
          };
          currentStep = 5;
          render();
        """,
        "07-ready": """
          state.recent = {high: '한식', food: '밥/정식류'};
          state.likeHigh = ['일식', '중식'];
          state.likeFoods = {
            '일식': ['초밥/회류', '면류'],
            '중식': ['면/밥류', '볶음류']
          };
          currentStep = 5;
          render();
        """,
        "08-submitted": """
          state.recent = {high: '한식', food: '밥/정식류'};
          state.likeHigh = ['일식', '중식'];
          state.likeFoods = {
            '일식': ['초밥/회류', '면류'],
            '중식': ['면/밥류', '볶음류']
          };
          currentStep = 5;
          render();
          showStatus('접수되었습니다. 현재 11명이 참여했습니다.', 'success');
          document.getElementById('submitButton').textContent = '제출 완료';
          document.getElementById('submitButton').disabled = true;
        """,
        "09-previous-feedback": """
          currentStep = 0;
          render();
          lastRecommendation = {
            recommendation_id: 'previous-demo',
            recommendations: [{
              name: '마루토모',
              food: '면류',
              category: '일식',
              address: '서울 광진구 군자로'
            }]
          };
          showPreviousRecommendation();
        """,
        "10-result": """
          state.recent = {high: '한식', food: '밥/정식류'};
          state.likeHigh = ['일식', '중식'];
          state.likeFoods = {
            '일식': ['초밥/회류', '면류'],
            '중식': ['면/밥류', '볶음류']
          };
          currentStep = 5;
          render();
          currentSessionRecommendation = {
            recommendation_id: 'current-demo',
            recommendations: [{
              name: '숙성부심 군자본점',
              food: '구이/고기류',
              category: '한식',
              address: '서울 광진구 능동로 267',
              mapx: '1270774430',
              mapy: '375539087'
            }]
          };
          navigationSettings = {
            global_enabled: true,
            enabled: true,
            consent_status: 'unknown'
          };
          showCurrentRecommendation();
        """,
    }
    return f"""
  <script>
    document.addEventListener('DOMContentLoaded', () => {{
      {shared}
      {states[stage]}
    }});
  </script>
"""


def build_mobile_preview(stage: str) -> str:
    html = (ROOT / "templates" / "mobile.html").read_text(encoding="utf-8")
    html = html.replace("{{ session_id }}", "demo-docs")
    html = html.replace(
        "    document.addEventListener('DOMContentLoaded', loadSurvey);",
        "",
    )
    menu = json.loads((ROOT / "dataset" / "menu_categories.json").read_text(encoding="utf-8"))
    html = html.replace("</head>", f"{mobile_mock_script(menu)}</head>")
    html = html.replace("</body>", f"{mobile_stage_script(stage)}</body>")
    return html


def build_architecture_preview() -> str:
    return """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0;
    width: 1600px;
    height: 1000px;
    padding: 42px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: #294866;
    background: linear-gradient(135deg, #e5f4ff, #f0ebff 55%, #fff0e4);
  }
  h1 { margin: 0; text-align: center; font-size: 46px; color: #244d78; }
  .subtitle { margin: 8px 0 28px; text-align: center; color: #6685a3; font-size: 20px; }
  .flow { display: grid; grid-template-columns: 1fr 56px 1.2fr 56px 1.35fr 56px 1fr; align-items: stretch; }
  .arrow { display: grid; place-items: center; color: #7494bc; font-size: 38px; font-weight: 900; }
  .panel {
    min-height: 520px;
    padding: 22px;
    border: 2px solid #b8d3eb;
    border-radius: 22px;
    background: rgba(255,255,255,.9);
    box-shadow: 0 16px 36px rgba(53,93,137,.13);
  }
  .panel h2 { margin: 0 0 18px; font-size: 25px; color: #355d89; }
  .item {
    margin-top: 14px;
    padding: 16px;
    border: 1px solid #bdd4ea;
    border-radius: 14px;
    background: #f8fbff;
  }
  .item strong { display: block; margin-bottom: 6px; font-size: 18px; }
  .item span { color: #6685a3; font-size: 15px; line-height: 1.45; }
  .core { background: linear-gradient(160deg, #f8fbff, #f7f2ff); }
  .core .item { background: white; }
  .bottom {
    display: grid;
    grid-template-columns: 1.15fr 1fr 1fr;
    gap: 18px;
    margin-top: 24px;
  }
  .mini {
    padding: 18px 20px;
    border: 1px solid #bdd4ea;
    border-radius: 18px;
    background: rgba(255,255,255,.88);
  }
  .mini h3 { margin: 0 0 9px; color: #355d89; }
  .mini p { margin: 0; color: #6685a3; line-height: 1.55; font-size: 15px; }
  code { color: #355d89; font-weight: 700; }
</style>
</head>
<body>
  <h1>식당 추천 시스템 구조</h1>
  <div class="subtitle">모바일 선호 수집부터 CLI 그룹 추천, 결과 피드백까지의 현재 데이터 흐름</div>
  <div class="flow">
    <section class="panel">
      <h2>1. 데이터와 저장소</h2>
      <div class="item"><strong>기본 참가자 10명</strong><span><code>dataset/demo_session.json</code><br>서버 시작 시 U0001~U0010 구조로 동기화</span></div>
      <div class="item"><strong>영구 참가자 폴더</strong><span>프로필, 기기 UUID, 세션 접속, 끼니, 추천, 제외 식당</span></div>
      <div class="item"><strong>식당·카테고리</strong><span>메뉴 트리, mock 식당, 분류 규칙, 자동 별칭 사전</span></div>
    </section>
    <div class="arrow">→</div>
    <section class="panel">
      <h2>2. 사용자 인터페이스</h2>
      <div class="item"><strong>PC 관리자 대시보드</strong><span>세션 설정, 저장 사용자 선택, QR, 참가자, 결과, CLI 로그, 취향 지도</span></div>
      <div class="item"><strong>모바일 QR 설문</strong><span>끼니 → 최근 음식 1개 → 선호 대분류 2개 → 대분류별 음식 2개</span></div>
      <div class="item"><strong>이전 추천 평가</strong><span>‘안 갈래요’ 선택 시 사용자별 제외 목록에 누적</span></div>
    </section>
    <div class="arrow">→</div>
    <section class="panel core">
      <h2>3. CLI 추천 엔진</h2>
      <div class="item"><strong>jq 그룹화</strong><span>참가자 term의 Jaccard 유사도 → 계층 병합 → 1인 그룹 재배치</span></div>
      <div class="item"><strong>식당 검색</strong><span>mock 또는 Naver 지역 검색 provider<br>도보·리뷰·최근 음식·제외 식당 필터</span></div>
      <div class="item"><strong>점수와 Top 1</strong><span>대분류 일치 +0.5, 음식 일치 +0.3<br>그룹 간 동일 식당 중복 방지</span></div>
      <div class="item"><strong>실시간 CLI 스트림</strong><span>핵심 명령만 관리자 화면에 위생 처리해 표시</span></div>
    </section>
    <div class="arrow">→</div>
    <section class="panel">
      <h2>4. 결과와 후속 동작</h2>
      <div class="item"><strong>그룹별 식당 한 곳</strong><span>PC 결과 카드와 취향·추천 근거 지도에 즉시 표시</span></div>
      <div class="item"><strong>모바일 결과 팝업</strong><span>참가자 자신의 그룹 추천을 폴링해 자동 표시</span></div>
      <div class="item"><strong>네이버 길찾기</strong><span>현재 위치는 브라우저에서만 사용하며 서버에 좌표를 저장하지 않음</span></div>
    </section>
  </div>
  <div class="bottom">
    <section class="mini"><h3>외부 접속</h3><p><code>scripts/mobile_web.sh</code>가 cloudflared → ngrok → npx cloudflared 순으로 HTTPS 터널을 준비합니다.</p></section>
    <section class="mini"><h3>Flask API</h3><p>세션 생성·참가자 선택·모바일 제출·마감·추천 job·피드백·위치 설정을 담당합니다.</p></section>
    <section class="mini"><h3>리포트</h3><p>CLI 실행은 <code>output/report.html</code>을 만들고, 웹 실행은 참가자별 추천 이력을 JSON으로 저장합니다.</p></section>
  </div>
</body>
</html>"""


def build_naver_route_preview() -> str:
    """Render a documentation-only approximation of the opened Naver route screen."""
    return """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0;
    width: 480px;
    height: 1000px;
    overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: #222;
    background: #eef1f4;
  }
  header {
    height: 64px;
    display: flex;
    align-items: center;
    gap: 13px;
    padding: 0 18px;
    background: #fff;
    border-bottom: 1px solid #dce1e6;
  }
  .back { color: #555; font-size: 27px; }
  .naver { color: #03c75a; font-weight: 900; font-size: 21px; }
  .title { font-weight: 800; font-size: 18px; }
  .search {
    position: relative;
    z-index: 2;
    margin: 12px;
    padding: 14px 15px;
    border-radius: 13px;
    background: white;
    box-shadow: 0 5px 18px rgba(40,55,70,.16);
  }
  .place {
    display: grid;
    grid-template-columns: 25px 1fr;
    gap: 8px;
    align-items: center;
    min-height: 44px;
  }
  .place + .place { border-top: 1px solid #edf0f2; }
  .dot {
    width: 11px;
    height: 11px;
    margin: auto;
    border: 3px solid #03c75a;
    border-radius: 50%;
  }
  .dot.end { border-color: #ef4c4c; }
  .place strong { display: block; font-size: 15px; }
  .place span { color: #77818a; font-size: 12px; }
  .map {
    position: absolute;
    inset: 64px 0 212px;
    overflow: hidden;
    background:
      linear-gradient(30deg, transparent 48%, rgba(255,255,255,.72) 49%, rgba(255,255,255,.72) 52%, transparent 53%) 0 0/120px 95px,
      linear-gradient(120deg, transparent 47%, rgba(255,255,255,.76) 48%, rgba(255,255,255,.76) 52%, transparent 53%) 0 0/145px 120px,
      #e8eee5;
  }
  .water {
    position: absolute;
    width: 580px;
    height: 145px;
    left: -55px;
    top: 370px;
    transform: rotate(-7deg);
    background: #cfe9f4;
  }
  .route {
    position: absolute;
    left: 145px;
    top: 245px;
    width: 190px;
    height: 235px;
    border: 11px solid #03c75a;
    border-left-color: transparent;
    border-bottom-color: transparent;
    border-radius: 42% 58% 40% 60%;
    transform: rotate(22deg);
  }
  .route::after {
    content: "";
    position: absolute;
    width: 120px;
    height: 110px;
    right: 30px;
    bottom: -61px;
    border: 11px solid #03c75a;
    border-top-color: transparent;
    border-right-color: transparent;
    border-radius: 50%;
  }
  .pin {
    position: absolute;
    z-index: 1;
    width: 33px;
    height: 33px;
    display: grid;
    place-items: center;
    border-radius: 50% 50% 50% 8px;
    transform: rotate(-45deg);
    color: #fff;
    font-weight: 900;
    box-shadow: 0 3px 8px rgba(0,0,0,.22);
  }
  .pin span { transform: rotate(45deg); }
  .start { left: 112px; top: 235px; background: #03c75a; }
  .end { right: 90px; top: 470px; background: #ef4c4c; }
  .label {
    position: absolute;
    z-index: 1;
    padding: 6px 9px;
    border-radius: 7px;
    background: rgba(255,255,255,.94);
    font-size: 12px;
    font-weight: 750;
    box-shadow: 0 2px 7px rgba(0,0,0,.14);
  }
  .start-label { left: 45px; top: 285px; }
  .end-label { right: 28px; top: 518px; }
  .summary {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    height: 224px;
    padding: 18px;
    border-radius: 21px 21px 0 0;
    background: white;
    box-shadow: 0 -5px 20px rgba(33,47,61,.15);
  }
  .mode { color: #03a950; font-weight: 850; font-size: 14px; }
  .time { margin-top: 5px; font-size: 30px; font-weight: 900; }
  .meta { margin-left: 8px; color: #69747e; font-size: 14px; font-weight: 500; }
  .route-info {
    display: flex;
    gap: 10px;
    margin-top: 14px;
    padding: 12px;
    border-radius: 10px;
    background: #f4f7f8;
    color: #4e5963;
    font-size: 13px;
  }
  .start-button {
    margin-top: 14px;
    width: 100%;
    height: 48px;
    border: 0;
    border-radius: 9px;
    background: #03c75a;
    color: #fff;
    font-size: 17px;
    font-weight: 850;
  }
  .docs {
    position: absolute;
    right: 12px;
    top: 72px;
    z-index: 3;
    padding: 5px 8px;
    border-radius: 999px;
    background: rgba(36,77,120,.9);
    color: white;
    font-size: 10px;
  }
</style>
</head>
<body>
  <header><span class="back">‹</span><span class="naver">NAVER</span><span class="title">길찾기</span></header>
  <div class="docs">문서용 미리보기</div>
  <div class="map">
    <div class="water"></div>
    <div class="route"></div>
    <div class="pin start"><span>A</span></div>
    <div class="pin end"><span>B</span></div>
    <div class="label start-label">세종대학교</div>
    <div class="label end-label">마루토모</div>
  </div>
  <section class="search">
    <div class="place"><span class="dot"></span><div><strong>세종대학교</strong><span>서울 광진구 능동로 209</span></div></div>
    <div class="place"><span class="dot end"></span><div><strong>마루토모</strong><span>서울 광진구 군자로</span></div></div>
  </section>
  <section class="summary">
    <div class="mode">자동차 추천 경로</div>
    <div class="time">약 4분 <span class="meta">1.2km</span></div>
    <div class="route-info"><strong>출발</strong> 세종대학교 임시 좌표 37.550260, 127.073139</div>
    <button class="start-button">안내 시작</button>
  </section>
</body>
</html>"""


def main() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mm-doc-capture.") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        admin_html = temp_dir / "admin.html"
        admin_html.write_text(build_admin_preview(), encoding="utf-8")
        chrome_screenshot(admin_html, SCREENSHOT_DIR / "pc-dashboard.png", 1600, 1000)

        architecture_html = temp_dir / "architecture.html"
        architecture_html.write_text(build_architecture_preview(), encoding="utf-8")
        chrome_screenshot(architecture_html, ROOT / "docs" / "SystemDiagram.png", 1600, 1000)

        naver_route_html = temp_dir / "naver-route.html"
        naver_route_html.write_text(build_naver_route_preview(), encoding="utf-8")
        chrome_screenshot(
            naver_route_html,
            SCREENSHOT_DIR / "mobile-11-naver-route.png",
            480,
            1000,
        )

        stages = [
            "01-entry",
            "02-recent-food",
            "03-preference-1-category",
            "04-preference-1-foods",
            "05-preference-2-category",
            "06-preference-2-foods",
            "07-ready",
            "08-submitted",
            "09-previous-feedback",
            "10-result",
        ]
        for stage in stages:
            mobile_html = temp_dir / f"{stage}.html"
            mobile_html.write_text(build_mobile_preview(stage), encoding="utf-8")
            chrome_screenshot(
                mobile_html,
                SCREENSHOT_DIR / f"mobile-{stage}.png",
                480,
                1000,
            )

    create_feature_crops()
    print(f"Captured documentation screenshots in {SCREENSHOT_DIR}")
    print(f"Captured feature crops in {CROPPED_SCREENSHOT_DIR}")


if __name__ == "__main__":
    main()
