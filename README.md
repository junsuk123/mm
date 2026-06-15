# Restaurant Recommendation System

식당 추천 시스템입니다. 기본 참가자 데이터, CLI 데모, 웹 관리자 화면, QR 기반 모바일 설문을 함께 사용할 수 있습니다.

## 구성

- `recommend.sh`: CLI 추천 실행 진입점
- `app.py`: Flask 기반 웹 관리자 화면과 모바일 QR API
- `mobile_web.sh`: 다른 네트워크와 Safari에서도 접속 가능한 공개 HTTPS 터널 실행 스크립트
- `templates/index.html`: 관리자 화면
- `templates/mobile.html`: QR로 접속하는 모바일 설문 화면
- `dataset/demo_session.json`: 기본 내장 참가자 데이터
- `dataset/mobile_sessions.json`: QR 설문으로 수집된 참가자 데이터
- `dataset/menu_categories.json`: 대분류, 중분류, 소분류 음식 카테고리
- `dataset/mock_restaurants.json`: API 키 없이 테스트하는 mock 식당 데이터
- `visualization/recommendation_visualizer.py`: 추천 결과 HTML 리포트 생성

## 빠른 실행

최초 1회 Python 의존성 설치:

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
3. `기본 참가자 데이터 포함`은 기본으로 켜져 있습니다.
4. `식당 검색 provider`를 고릅니다. API 키 없이 확인하려면 `mock`, 실제 인근 검색은 `naver`를 사용합니다.
5. `모바일 QR 수집 사용`을 체크합니다.
6. `새 세션 시작`을 누르면 QR 코드와 모바일 접속 링크가 표시됩니다.
7. 참가자는 QR을 스캔하고 모바일 설문에 응답합니다.
8. 참가자 목록에는 `dataset/demo_session.json`의 기본 참가자 뒤에 QR 참가자가 계속 추가됩니다.
9. 접수를 끝낼 때 `마감 및 실행`을 누르면 현재 참가자 전체로 그룹을 만들고, 각 그룹별 인근 식당 Top 3까지 추천합니다.

사용자는 끝까지 웹 GUI만 사용하면 됩니다. 다만 수업 시연을 위해, 관리자 화면의 `리눅스 명령어 처리 과정` 영역에 내부에서 실행된 CLI 파이프라인을 시각화해서 보여 줍니다.

내부적으로는 서버가 현재 세션을 임시 JSON 파일로 저장한 뒤 아래 형태의 CLI 명령을 실행합니다.

```bash
sh recommend.sh --session-file /tmp/mm-web-session.xxxxx.json --provider mock --location 세종대학교 --json-output
```

웹 화면에는 이 명령을 사용자가 직접 입력하라고 보여주는 것이 아니라, PC 화면 기준 세 번째 열의 터미널 패널에서 `mktemp`, `sh recommend.sh`, `jq`, `python3 grouping_utils.py`, `restaurant_provider.sh` 같은 내부 리눅스 명령 처리 단계를 실시간으로 보여 줍니다. 백엔드 처리 과정 자체에 짧은 딜레이를 두고, 웹은 job 상태를 polling하면서 새 명령어와 피드백이 생기는 즉시 터미널 패널에 추가합니다.

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

모바일 페이지는 번호 입력이 아니라 정사각형 타일 선택 방식입니다.

1. 좋아하는 음식
2. 싫어하는 음식
3. 최근 먹은 음식

각 항목은 다음 순서로 하나씩 선택합니다.

```text
대분류 -> 중분류 -> 소분류 음식
```

예를 들어 `한식 -> 국물류 -> 김치찌개`처럼 선택하면 내부 데이터에는 경로가 저장되고, 추천 계산에서는 마지막 음식명인 `김치찌개`가 점수와 검색어에 사용됩니다.

## 데이터 동작

웹 세션을 만들면 기본적으로 `dataset/demo_session.json`의 참가자가 먼저 들어갑니다. QR 응답은 같은 세션의 참가자 목록 뒤에 추가됩니다.

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

참가자의 입력은 `like`, `dislike`, `recent`로 모입니다. 각 항목은 대분류와 소분류 음식명을 사용합니다.

점수 계산:

```text
score = 0.5 * 선호 대분류 + 0.3 * 선호 소분류 - 0.5 * 최근 음식 - 0.8 * 싫어하는 대분류 - 1.0 * 싫어하는 소분류
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
