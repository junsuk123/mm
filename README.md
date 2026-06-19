# Restaurant Recommendation System

식당 추천 시스템입니다. 기본 참가자 데이터, CLI 데모, 웹 관리자 화면, QR 기반 모바일 설문을 함께 사용할 수 있습니다.

## 구성

- `recommend.sh`: CLI 추천 실행 진입점
- `app.py`: Flask 기반 웹 관리자 화면과 모바일 QR API
- `mobile_web.sh`: 다른 네트워크와 Safari에서도 접속 가능한 공개 HTTPS 터널 실행 스크립트
- `templates/index.html`: 관리자 화면
- `templates/mobile.html`: QR로 접속하는 모바일 설문 화면
- `dataset/demo_session.json`: CLI 데모 호환용 예시 세션
- `dataset/participants/U0001/profile.json`: 사용자별 최신 선호도
- `dataset/participants/U0001/device.json`: 사용자와 연결된 기기 식별자
- `dataset/participants/U0001/submissions/`: 사용자별 설문 제출 이력
- `dataset/mobile_sessions.json`: QR 설문으로 수집된 참가자 데이터
- `dataset/menu_categories.json`: 대분류, 중분류, 소분류 음식 카테고리
- `dataset/mock_restaurants.json`: API 키 없이 테스트하는 mock 식당 데이터
- `visualization/recommendation_visualizer.py`: 추천 결과 HTML 리포트 생성

## 빠른 실행

최초 1회 시스템 도구와 Python 의존성 설치:

```bash
sudo apt update && sudo apt install -y jq python3 python3-pip
```

```bash
python3 -m pip install -r requirements.txt
```

프로젝트 가상환경을 쓰는 경우:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

API 키 없이 데모 데이터와 mock 식당 데이터로 실행:

```bash
sh recommend.sh --demo --provider mock
```

웹 관리자 화면 실행:

```bash
python3 app.py
```

다른 네트워크의 모바일 기기, Safari, iPhone까지 QR 접속이 필요하면:

```bash
sh mobile_web.sh
```

## 웹 QR 운영 흐름

1. `sh mobile_web.sh`를 실행합니다.
2. 브라우저에서 관리자 화면이 자동으로 열립니다.
3. 식당 검색 provider는 기본적으로 네이버 지역 검색 API(`naver`)를 사용합니다. API 없이 테스트할 때만 `mock`을 선택합니다.
4. `이번 세션 참여자 선택`에서 함께 추천받을 사용자 폴더를 누릅니다.
5. 모바일 접속 주소를 확인하고 `모바일 접수 시작`을 누릅니다.
6. 선택된 저장 사용자가 해당 세션 참가자로 복사되고 QR 코드와 모바일 접속 링크가 표시됩니다.
7. QR로 새로 응답한 참가자는 현재 세션과 영구 사용자 폴더에 함께 추가됩니다.
8. 접수를 끝낼 때 `마감 및 실행`을 누르면 현재 세션에 포함된 참가자만 그룹으로 만들고 식당 Top 3를 추천합니다.

새 참가자 데이터 입력은 모두 모바일 설문에서 진행합니다. PC 관리자 화면에서는 저장된 사용자 폴더를 선택해 이번 추천에 함께할 사람을 구성합니다.

## 기기별 참가자 데이터

웹 브라우저는 보안상 MAC 주소를 읽을 수 없습니다. 따라서 모바일 기기가 처음 설문에 접속할 때 브라우저에서 UUID를 생성하고 `localStorage`에 저장하며, 이후 이 값을 기기 식별자로 사용합니다. 브라우저 저장 공간을 삭제하거나 다른 브라우저를 사용하면 새 기기로 인식됩니다.

각 사용자는 `U0001`, `U0002`처럼 짧은 ID를 자동으로 받습니다. 폴더 이름에는 기기 식별자를 사용하지 않고 이 사용자 ID만 사용합니다.

```text
dataset/participants/
  U0001/
    device.json
    profile.json
    meals/
      2026-06-20.json
    submissions/
      <제출시각>_<세션ID>.json
```

`device.json`에는 MAC 주소 대신 브라우저가 발급한 기기 UUID가 별도로 저장됩니다. `profile.json`에는 최신 이름·별명과 선호도가 저장되고, `submissions`에는 제출할 때마다 당시 설문 내용이 누적됩니다. 모바일 사용자는 음식명을 직접 입력하는 것이 아니라 이번 추천이 `점심`용인지 `저녁`용인지 버튼으로 선택합니다. `meals`에는 제출일을 파일명으로 하여 선택한 끼니의 설문 데이터를 저장합니다.

날짜는 사용자가 입력하지 않고 서버가 제출일 기준으로 자동 기록합니다. 저장 형식은 다음과 같습니다.

```json
{
  "participant_id": "U0011",
  "date": "2026-06-20",
  "meals": {
    "lunch": {
      "submitted_at": "2026-06-20T12:10:00",
      "session_id": "a1b2c3d4",
      "preferences": {
        "like": {},
        "recent": {}
      }
    }
  }
}
```

같은 날짜에 점심과 저녁을 각각 제출하면 하나의 날짜 파일 안에 두 끼가 따로 저장되며, 같은 끼니를 다시 제출하면 최신 설문 내용으로 갱신됩니다. 날짜별 기록은 `/api/participant/<device-id>/meals`에서 최신 날짜순으로 조회할 수 있어 추후 끼니별 추천 분석에 사용할 수 있습니다.

기본 예시 참가자 10명도 `dataset/participants/U0001`부터 `U0010`까지 같은 구조로 저장되어 있습니다. PC 관리자 화면의 `저장된 사용자 폴더` 영역에는 각 사용자가 폴더 아이콘과 ID로 표시됩니다.

## 영구 사용자와 추천 세션

`dataset/participants/Uxxxx` 폴더는 세션과 독립된 영구 사용자 데이터입니다. 새 세션 생성, 세션 마감, 추천 실행은 이 폴더를 삭제하지 않습니다.

새 세션은 저장된 사용자 중 이번에 함께 추천받을 사람을 선택하는 임시 묶음입니다. 세션을 시작할 때 선택한 사용자의 최신 프로필을 세션 참가자 목록으로 복사하며, 이후 폴더 선택을 바꾸더라도 이미 시작된 세션에는 영향을 주지 않습니다. 변경된 선택은 다음 새 세션에 적용됩니다. 아무 폴더도 선택하지 않고 세션을 시작하면 QR 신규 참가자만 받는 세션으로 사용할 수 있습니다.

내부적으로는 서버가 현재 세션을 임시 JSON 파일로 저장한 뒤 아래 형태의 CLI 명령을 실행합니다.

```bash
sh recommend.sh --session-file /tmp/mm-web-session.xxxxx.json --provider naver --location 세종대학교 --json-output
```

웹 화면에는 이 명령을 사용자가 직접 입력하라고 보여주는 것이 아니라, PC 화면 기준 세 번째 열의 터미널 패널에서 핵심 CLI 파이프라인을 실시간으로 보여 줍니다. 내부 변수 할당, 반복문, 주석 같은 세부 로그는 제외하고 `jq` 데이터 준비, `python3 grouping_utils.py` 그룹 생성, provider 검색과 점수 계산, 최종 결과 통합처럼 중요한 단계만 표시합니다. 함께 실행되는 작업은 `&&`와 파이프라인으로 한 줄에 묶으며, 각 단계는 일정한 간격으로 나타납니다. 새 명령이 시작되면 이전 명령 화면은 지워지므로 터미널이 아래로 길어지지 않습니다. 사용자 홈과 프로젝트의 절대 경로는 화면에 노출하지 않고 `./` 또는 `<임시파일>`로 표시합니다.

`python3 app.py`만 실행하면 같은 PC 또는 같은 네트워크에서 접속하는 용도에 적합합니다. 완전히 다른 네트워크에서는 `127.0.0.1`, `192.168.x.x`, `172.x.x.x` 같은 내부 주소가 열리지 않으므로 `sh mobile_web.sh`를 사용하세요.

이미 ngrok, Cloudflare Tunnel, 포트 포워딩 URL이 있다면 직접 고정할 수 있습니다.

```bash
MM_PUBLIC_BASE_URL=https://example-tunnel-url.ngrok-free.app python3 app.py
```

자동 브라우저 열기를 끄려면:

```bash
MM_AUTO_OPEN=0 python3 app.py
```

## 모바일 설문 방식

모바일 페이지는 번호 입력이 아니라 정사각형 타일 선택 방식입니다. 중분류와 싫어하는 음식 조사는 사용하지 않습니다.

1. 최근 먹은 음식: 대분류 1개 → 소분류 음식 1개
2. 선호 음식: 서로 다른 대분류 2개 → 각 대분류에서 소분류 음식 2개씩

예를 들어 선호 음식은 `한식 → 김치찌개, 불고기`, `일식 → 초밥, 라멘`처럼 총 2개 대분류와 음식 4개가 저장됩니다.

## 데이터 동작

웹 세션을 만들면 `dataset/participants/demo-*` 폴더의 예시 참가자가 먼저 들어갑니다. QR 응답은 기기별 참가자 폴더에 저장된 뒤 같은 세션의 참가자 목록에 추가됩니다.

QR 응답은 `dataset/mobile_sessions.json`에 저장됩니다. 이 파일은 최신 QR 세션과 각 세션의 참가자를 보관하므로, 서버를 다시 시작해도 저장된 QR 참가자를 CLI 데모에 붙일 수 있습니다.

CLI 데모는 기본적으로 다음 순서의 데이터를 사용합니다.

1. `dataset/demo_session.json` 기본 참가자
2. `dataset/mobile_sessions.json`의 최신 QR 세션 참가자

기본 참가자만 사용하려면:

```bash
sh recommend.sh --demo --without-mobile-responses --provider mock
```

특정 QR 세션의 참가자를 붙이려면:

```bash
sh recommend.sh --demo --mobile-session-id 세션ID --provider mock
```

## CLI 사용법

단일 사용자 추천:

```bash
sh recommend.sh --user-id U01 --provider naver
```

터미널에서 참가자 정보를 직접 입력:

```bash
sh recommend.sh --collect-session --provider naver
```

데모와 mock provider:

```bash
sh recommend.sh --demo --provider mock
```

네이버 API provider:

```bash
sh recommend.sh --demo --provider naver
```

기본 검색 위치는 세종대학교입니다. 위치를 바꾸려면:

```bash
sh recommend.sh --demo --provider mock --location 건국대학교
```

## 추천 알고리즘

참가자의 입력은 `like`, `recent`로 모입니다. `like`에는 선호 대분류 2개와 대분류별 음식 2개씩, `recent`에는 최근 대분류와 음식 1개가 저장됩니다.

점수 계산:

```text
score = 0.5 * 선호 대분류 + 0.3 * 선호 소분류 - 0.5 * 최근 대분류 또는 음식
```

그룹 생성은 `grouping_utils.py`에서 처리합니다. 참가자마다 선호 대분류와 소분류 음식명을 term으로 만들고, 참가자 간 term 겹침 비율로 유사도를 계산합니다.

1. 처음에는 참가자 1명을 하나의 작은 묶음으로 둡니다.
2. 평균 유사도가 가장 높은 두 묶음을 합칩니다.
3. 목표 그룹 수가 될 때까지 병합을 반복합니다.

따라서 선호 카테고리 종류가 그룹 수보다 많아도 fallback으로 떨어지지 않고, 목표 그룹 수 안에서 비슷한 취향끼리 최대한 보존합니다.

그룹이 만들어지면 각 그룹의 선호를 합쳐 그룹 프로필을 만들고, provider로 주변 식당 후보를 가져옵니다. `mock` provider는 `dataset/mock_restaurants.json`의 `distance_m` 값을 사용하고, `naver` provider는 네이버 지역 검색 API로 지정 위치 근처의 식당을 가져옵니다.

각 후보 식당은 그룹 프로필 기준으로 점수를 계산한 뒤, 점수가 높은 순서와 가까운 거리 순서로 정렬해 그룹별 Top 3를 반환합니다.

이 과정의 CLI 구현은 `sh`, `jq`, `mktemp`, `python3 grouping_utils.py`, provider shell dispatch를 조합합니다. 웹 GUI는 사용자의 편의를 위한 화면을 유지하고, 내부에서 같은 CLI 파이프라인을 호출한 뒤 그 명령 처리 과정을 시각화합니다.

## 출력과 리포트

CLI 결과는 사람이 읽는 요약으로 출력됩니다.

```text
Group 1 members=U01, U04 -> Top 1: 진미식당 | food=김치찌개 | category=한식 | score=0.8 | reason=matched preferred category 한식; matched preferred food 김치찌개
```

추천 실행 후 `report.html`이 생성됩니다. 리포트에는 참가자 입력, 그룹별 후보, 최종 Top 3, 추천 이유, 참가자 수 요약이 포함됩니다.

## 참고

- `mock` provider는 `dataset/mock_restaurants.json`만 사용하므로 API 키가 없어도 동작합니다.
- `naver` provider는 네이버 지역 검색 API를 사용합니다.
- `mobile_web.sh`가 만든 Cloudflare 임시 URL은 터미널이 켜져 있는 동안만 유지됩니다. 다시 실행하면 새 URL이 만들어집니다.
