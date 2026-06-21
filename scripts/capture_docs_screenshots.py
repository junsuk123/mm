#!/usr/bin/env python3
"""Render documentation screenshots without changing participant/session data."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT_DIR = ROOT / "docs" / "screenshots"
CHROME = shutil.which("google-chrome") or shutil.which("chromium")


def chrome_screenshot(html_path: Path, output_path: Path, width: int, height: int) -> None:
    if not CHROME:
        raise RuntimeError("Google Chrome or Chromium is required")
    with tempfile.TemporaryDirectory(prefix="mm-chrome-profile.") as profile_dir:
        subprocess.run(
            [
                CHROME,
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--no-first-run",
                f"--user-data-dir={profile_dir}",
                "--hide-scrollbars",
                f"--window-size={width},{height}",
                f"--screenshot={output_path}",
                html_path.as_uri(),
            ],
            check=True,
            timeout=30,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def replace_dom_ready(html: str, injection: str) -> str:
    needle = "      loadUserFolders();\n    });"
    if needle not in html:
        raise RuntimeError("Admin DOM-ready block was not found")
    return html.replace(
        needle,
        "      loadUserFolders();\n" + injection + "\n    });",
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
            "name": "후문 카페",
            "food": "김치볶음밥",
            "category": "양식",
            "score": 0.8,
            "distance_m": 1301,
            "walking_minutes": 21,
            "review_rank": 1,
            "matched_terms": ["김치볶음밥"],
            "reason": "matched preferred category 양식; matched preferred food 김치볶음밥",
        },
        {
            "name": "위아더퓨쳐",
            "food": "크림파스타",
            "category": "양식",
            "score": 0.8,
            "distance_m": 725,
            "walking_minutes": 12,
            "review_rank": 2,
            "matched_terms": ["크림파스타"],
            "reason": "matched preferred category 양식; matched preferred food 크림파스타",
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
      document.getElementById('qrPanel').style.display = 'block';
      document.getElementById('qrCode').innerHTML = '<div style="font-size:2rem">▦</div>';
      document.getElementById('joinLink').textContent = 'https://example.trycloudflare.com/join/demo-docs';
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
            '중식': ['면류', '밥류']
          };
          currentStep = 5;
          render();
        """,
        "08-submitted": """
          state.recent = {high: '한식', food: '밥/정식류'};
          state.likeHigh = ['일식', '중식'];
          state.likeFoods = {
            '일식': ['초밥/회류', '면류'],
            '중식': ['면류', '밥류']
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
              name: '세종 한상',
              food: '김치찌개',
              category: '한식',
              address: '서울 광진구 능동로'
            }]
          };
          showPreviousRecommendation();
        """,
        "10-result": """
          state.recent = {high: '한식', food: '밥/정식류'};
          state.likeHigh = ['일식', '중식'];
          state.likeFoods = {
            '일식': ['초밥/회류', '면류'],
            '중식': ['면류', '밥류']
          };
          currentStep = 5;
          render();
          currentSessionRecommendation = {
            recommendation_id: 'current-demo',
            recommendations: [{
              name: '마루토모',
              food: '우동',
              category: '일식',
              address: '서울 광진구 군자로',
              mapx: '1270720000',
              mapy: '375470000'
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


def main() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for old_mobile_screenshot in SCREENSHOT_DIR.glob("mobile-*.png"):
        old_mobile_screenshot.unlink()
    with tempfile.TemporaryDirectory(prefix="mm-doc-capture.") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        admin_html = temp_dir / "admin.html"
        admin_html.write_text(build_admin_preview(), encoding="utf-8")
        chrome_screenshot(admin_html, SCREENSHOT_DIR / "pc-dashboard.png", 1600, 1000)

        architecture_html = temp_dir / "architecture.html"
        architecture_html.write_text(build_architecture_preview(), encoding="utf-8")
        chrome_screenshot(architecture_html, ROOT / "docs" / "SystemDiagram.png", 1600, 1000)

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

    print(f"Captured documentation screenshots in {SCREENSHOT_DIR}")


if __name__ == "__main__":
    main()
