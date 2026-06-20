# Restaurant Recommendation System

식당 추천 시스템입니다. 기본 참가자 데이터, CLI 데모, 웹 관리자 화면, QR 기반 모바일 설문을 함께 사용할 수 있습니다.

## 구성

- `scripts/recommend.sh`: CLI 추천 실행 진입점
- `scripts/grouping_cli.sh`: `jq` 기반 참가자 유사도 계산 및 그룹 생성
- `scripts/mobile_web.sh`: 다른 네트워크와 Safari에서도 접속 가능한 공개 HTTPS 터널 실행 스크립트
- `scripts/providers/`: mock·네이버 식당 검색 provider
- `src/app.py`: Flask 기반 웹 관리자 화면과 모바일 QR API
- `src/`: 네이버 API, 선호도 정규화, 추천 리포트 생성 Python 코드
- `templates/index.html`: 관리자 화면
- `templates/mobile.html`: QR로 접속하는 모바일 설문 화면
- `dataset/demo_session.json`: CLI 데모 호환용 예시 세션
- `dataset/participants/U0001/profile.json`: 사용자별 최신 선호도
- `dataset/participants/U0001/device.json`: 사용자와 연결된 기기 식별자
- `dataset/participants/U0001/submissions/`: 사용자별 설문 제출 이력
- `dataset/mobile_sessions.json`: QR 설문으로 수집된 참가자 데이터
- `dataset/menu_categories.json`: 대분류, 중분류, 소분류 음식 카테고리
- `dataset/alias_words.json`: 자동 별칭용 형용사 100개와 귀여운 동물 이름 100개
- `dataset/restaurant_classifications.json`: mock 식당의 원본 카테고리와 음식명을 추천 카테고리로 변환하는 순서 기반 분류 규칙
- `dataset/mock_restaurants.json`: API 키 없이 테스트하는 mock 식당 데이터
- `output/`: 실행 중 생성되는 HTML 리포트 디렉터리(Git 제외)

## 빠른 실행

최초 1회 시스템 도구와 Python 의존성 설치:

```bash
sudo apt update && sudo apt install -y jq python3 python3-pip python3-venv
```

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

API 키 없이 데모 데이터와 mock 식당 데이터로 실행:

```bash
sh scripts/recommend.sh --demo --provider mock
```

웹 관리자 화면 실행:

```bash
.venv/bin/python src/app.py
```

다른 네트워크의 모바일 기기, Safari, iPhone까지 QR 접속이 필요하면:

```bash
sh scripts/mobile_web.sh
```

## 웹 QR 운영 흐름

1. `sh scripts/mobile_web.sh`를 실행합니다.
2. 브라우저에서 관리자 화면이 자동으로 열립니다.
3. 식당 검색 provider는 기본적으로 네이버 지역 검색 API(`naver`)를 사용합니다. API 없이 테스트할 때만 `mock`을 선택합니다.
4. 샘플 참가자 10명은 항상 포함됩니다. `이번 세션 참여자 선택`에서 추가할 실제 사용자 폴더를 누릅니다.
5. 모바일 접속 주소를 확인하고 `모바일 접수 시작`을 누릅니다.
6. 샘플 참가자 10명과 선택된 실제 사용자가 해당 세션 참가자로 복사되고 QR 코드와 모바일 접속 링크가 표시됩니다.
7. QR로 새로 응답한 참가자는 현재 세션과 영구 사용자 폴더에 함께 추가됩니다.
8. 접수를 끝낼 때 `마감 및 실행`을 누르면 현재 세션에 포함된 참가자만 그룹으로 만들고 그룹별 식당 한 곳을 추천합니다.

세션 시작 전 관리자는 예상 도보 시간(`전체`, `5분`부터 `30분`까지 5분 단위), 리뷰 인기순(`전체`, 검색어별 상위 `1/3/5개`), 기존 `안갈래요` 목록의 사용 여부를 선택할 수 있습니다. 도보 시간은 Naver 지역검색 좌표의 직선거리에 보행 우회계수를 적용한 예상치입니다. Naver 공식 지역검색 API는 실제 도보 경로 시간, Place ID, 리뷰 개수를 반환하지 않으므로 리뷰 필터는 API의 리뷰 수 내림차순 정렬 결과를 사용합니다.

새 참가자 데이터 입력은 모두 모바일 설문에서 진행합니다. PC 관리자 화면에서는 저장된 사용자 폴더를 선택해 이번 추천에 함께할 사람을 구성합니다.

## 기기별 참가자 데이터

웹 브라우저는 보안상 MAC 주소를 읽을 수 없습니다. 따라서 모바일 기기가 처음 설문에 접속할 때 브라우저에서 UUID를 생성하고 `localStorage`에 저장하며, 이후 이 값을 기기 식별자로 사용합니다. 브라우저 저장 공간을 삭제하거나 다른 브라우저를 사용하면 새 기기로 인식됩니다.

각 사용자는 `U0001`, `U0002`처럼 짧은 ID를 자동으로 받습니다. 폴더 이름에는 기기 식별자를 사용하지 않고 이 사용자 ID만 사용합니다.

```text
dataset/participants/
  U0001/
    device.json
    profile.json
    exclusions.json
    location_settings.json
    session_access.json
    meals/
      2026-06-20.json
    recommendations/
      <추천시각>_<세션ID>.json
    submissions/
      <제출시각>_<세션ID>.json
```

`device.json`에는 MAC 주소 대신 브라우저가 발급한 기기 UUID가 별도로 저장됩니다. `session_access.json`에는 이 기기로 접속한 QR 세션 ID와 최초·최근 접속 시각이 순서대로 누적됩니다. `location_settings.json`에는 위치 기반 네이버 길찾기의 동의 상태와 사용자별 ON/OFF 설정만 저장합니다. 실제 위도·경도는 모바일 브라우저에서 길찾기 URL을 만드는 데만 사용하고 서버에는 저장하지 않습니다. `profile.json`에는 최신 이름·별명과 선호도가 저장되고, `submissions`에는 제출할 때마다 당시 설문 내용이 누적됩니다. `recommendations`에는 해당 사용자가 속한 그룹의 추천 결과가 저장되며, `exclusions.json`에는 사용자가 다시 가고 싶지 않다고 선택한 식당이 누적됩니다.

이름이나 별명을 비워 두면 `dataset/alias_words.json`에 저장된 형용사 100개와 귀여운 동물 이름 100개를 조합해 `반짝이는 수달` 같은 별칭을 자동 생성합니다. 총 10,000개 조합을 사용할 수 있으며, 같은 기기는 계속 같은 별칭을 사용합니다. 이미 사용 중인 조합은 다음 조합으로 이동해 중복을 피하고, 사용자가 직접 이름을 입력하면 자동 별칭 대신 입력한 이름을 저장합니다.

브라우저 UUID 하나는 반드시 사용자 폴더 하나에만 연결됩니다. 서버는 파일 락과 `dataset/device_index.json`을 사용해 여러 프로세스에서 동시에 제출되어도 같은 기기의 새 폴더가 중복 생성되지 않게 합니다. 기존 중복 폴더가 발견되면 가장 오래된 사용자 ID 폴더를 유지하고, 프로필·제출·추천·제외 식당·세션 접속·식사 기록을 병합한 뒤 중복 폴더를 제거합니다.

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

같은 날짜에 점심과 저녁을 각각 제출하면 하나의 날짜 파일 안에 두 끼가 따로 저장됩니다. 같은 날짜의 같은 끼니를 여러 번 제출하면 `submitted_at`이 가장 최신인 조사 결과만 남고 이전 결과를 덮어씁니다. 늦게 도착한 오래된 요청은 최신 기록을 되돌리지 않습니다. 날짜별 기록은 `/api/participant/<device-id>/meals`에서 최신 날짜순으로 조회할 수 있어 추후 끼니별 추천 분석에 사용할 수 있습니다.

기본 예시 참가자 10명도 `dataset/participants/U0001`부터 `U0010`까지 같은 구조로 저장되어 있습니다. 서버는 `dataset/demo_session.json`을 원본으로 사용해 `device.json`, `profile.json`, `exclusions.json`, `session_access.json`, `meals/`, `submissions/`, `recommendations/` 구조를 자동 동기화합니다. PC 관리자 화면에서는 샘플 폴더가 `항상 포함`으로 표시됩니다.

## 영구 사용자와 추천 세션

`dataset/participants/Uxxxx` 폴더는 세션과 독립된 영구 사용자 데이터입니다. 새 세션 생성, 세션 마감, 추천 실행은 이 폴더를 삭제하지 않습니다.

새 세션은 샘플 참가자 10명을 기본으로 포함하고, 저장된 실제 사용자 중 이번에 함께 추천받을 사람을 추가하는 임시 묶음입니다. 세션을 시작할 때 샘플과 선택한 사용자의 최신 프로필을 세션 참가자 목록으로 복사하며, 이후 폴더 선택을 바꾸더라도 이미 시작된 세션에는 영향을 주지 않습니다. 변경된 선택은 다음 새 세션에 적용됩니다. 아무 폴더도 선택하지 않아도 샘플 10명은 포함되며 QR 신규 참가자가 여기에 추가됩니다.

내부적으로는 서버가 현재 세션을 임시 JSON 파일로 저장한 뒤 아래 형태의 CLI 명령을 실행합니다.

```bash
sh scripts/recommend.sh --session-file /tmp/mm-web-session.xxxxx.json --provider naver --location 세종대학교 --json-output
```

웹 화면에는 이 명령을 사용자가 직접 입력하라고 보여주는 것이 아니라, PC 화면 기준 세 번째 열의 터미널 패널에서 핵심 CLI 파이프라인을 실시간으로 보여 줍니다. 내부 변수 할당, 반복문, 주석 같은 세부 로그는 제외하고 `jq` 데이터 준비, `sh scripts/grouping_cli.sh` 그룹 생성, provider 검색과 점수 계산, 최종 결과 통합처럼 중요한 단계만 표시합니다. 함께 실행되는 작업은 `&&`와 파이프라인으로 한 줄에 묶으며, 각 단계는 일정한 간격으로 나타납니다. 새 명령이 시작되면 이전 명령 화면은 지워지므로 터미널이 아래로 길어지지 않습니다. 사용자 홈과 프로젝트의 절대 경로는 화면에 노출하지 않고 `./` 또는 `<임시파일>`로 표시합니다.

`.venv/bin/python src/app.py`만 실행하면 같은 PC 또는 같은 네트워크에서 접속하는 용도에 적합합니다. 완전히 다른 네트워크에서는 `127.0.0.1`, `192.168.x.x`, `172.x.x.x` 같은 내부 주소가 열리지 않으므로 `sh scripts/mobile_web.sh`를 사용하세요.

이미 ngrok, Cloudflare Tunnel, 포트 포워딩 URL이 있다면 직접 고정할 수 있습니다.

```bash
MM_PUBLIC_BASE_URL=https://example-tunnel-url.ngrok-free.app .venv/bin/python src/app.py
```

자동 브라우저 열기를 끄려면:

```bash
MM_AUTO_OPEN=0 .venv/bin/python src/app.py
```

## 모바일 설문 방식

모바일 페이지는 번호 입력이 아니라 정사각형 타일 선택 방식입니다. 중분류와 싫어하는 음식 조사는 사용하지 않습니다.
화면 전체는 모바일 뷰포트 한 화면에 고정되며, 항목이 많을 때 음식 타일 영역만 내부 스크롤됩니다. 상단 `다시하기` 버튼을 누르면 저장된 프로필을 자동 입력하지 않은 빈 설문으로 새로고침됩니다.

기존 사용자가 새 QR 세션에 다시 접속하면 `session_access.json`에서 현재 세션과 다른 직전 접속 세션을 찾고, 그 세션의 그룹 추천만 평가 팝업에 표시합니다. 각 식당의 `안 갈래요` 버튼을 누르면 사용자 폴더의 `exclusions.json`에 저장되고, 우측 상단 X를 누르면 평가 없이 닫을 수 있습니다. 두 경우 모두 이후 설문은 빈 상태에서 다시 시작합니다. 접속 이력이 없던 기존 사용자는 과거 `submissions`와 추천 이력에서 세션 기록을 한 번 자동 복원합니다.

설문을 제출한 모바일 페이지는 현재 세션의 CLI 추천 완료 여부를 주기적으로 확인합니다. 관리자가 `마감 및 실행`을 누르고 추천 생성이 끝나면 새로고침하지 않아도 해당 사용자가 속한 그룹의 추천 식당 한 곳이 `추천이 완료됐어요!` 팝업으로 표시됩니다. 접수가 마감된 뒤 결과 계산 중인 동안에도 모바일 페이지는 결과 확인을 계속합니다.

## 네이버 위치 기반 길찾기

추천 완료 팝업은 네이버 지역검색 API가 반환한 식당 좌표와 모바일 브라우저의 현재 위치를 결합해 네이버 지도 자동차 길찾기 URL Scheme을 실행합니다.

```text
nmap://route/car?slat=<현재 위도>&slng=<현재 경도>&dlat=<식당 위도>&dlng=<식당 경도>
```

처음 사용할 때만 팝업에서 위치 사용 동의를 받으며, 이후에는 사용자 폴더의 `location_settings.json`을 사용합니다. 브라우저 자체 위치 권한은 Safari·Chrome 설정에서 별도로 관리됩니다. 네이버 지도 앱 실행이나 식당 좌표 확인에 실패하면 식당명·주소를 사용한 네이버 지도 검색으로 대체합니다.

사용자는 추천 팝업에서 `길찾기 끄기`를 눌러 개인별로 비활성화할 수 있습니다. 관리자는 서버 실행 전에 아래 환경변수로 전체 기능을 켜거나 끌 수 있습니다.

```bash
# 기본값: 1
MM_NAVER_DIRECTIONS_ENABLED=1 sh scripts/mobile_web.sh

# 전체 비활성화
MM_NAVER_DIRECTIONS_ENABLED=0 sh scripts/mobile_web.sh
```

현재 위치 기능은 HTTPS 또는 localhost에서만 정상 동작하므로 외부 모바일 접속은 `scripts/mobile_web.sh`의 HTTPS 주소를 사용해야 합니다.

- 네이버 공식 지도 앱 URL Scheme: https://guide.ncloud-docs.com/docs/maps-url-scheme
- 네이버 지역검색 API 좌표 설명: https://developers.naver.com/docs/serviceapi/search/local/local.md

1. 최근 먹은 음식: 대분류 1개 → 소분류 음식 1개
2. 선호 음식 1: 대분류 1개 → 해당 대분류에서 소분류 2개
3. 선호 음식 2: 첫 번째와 다른 대분류 1개 → 해당 대분류에서 소분류 2개

예를 들어 `한식 → 밥/정식류, 국물/탕류`를 고른 뒤 `일식 → 초밥/회류, 면류`를 고르는 순서로 진행되며, 총 2개 대분류와 소분류 4개가 저장됩니다.

## 데이터 동작

웹 세션을 만들면 `dataset/participants/U0001`부터 `U0010`까지의 샘플 참가자 10명이 항상 먼저 들어갑니다. QR 응답은 기기별 참가자 폴더에 저장된 뒤 같은 세션의 참가자 목록에 추가됩니다.

QR 응답은 `dataset/mobile_sessions.json`에 저장됩니다. 이 파일은 최신 QR 세션과 각 세션의 참가자를 보관하므로, 서버를 다시 시작해도 저장된 QR 참가자를 CLI 데모에 붙일 수 있습니다.

CLI 데모는 기본적으로 다음 순서의 데이터를 사용합니다.

1. `dataset/demo_session.json` 기본 참가자
2. `dataset/mobile_sessions.json`의 최신 QR 세션 참가자

기본 참가자만 사용하려면:

```bash
sh scripts/recommend.sh --demo --without-mobile-responses --provider mock
```

특정 QR 세션의 참가자를 붙이려면:

```bash
sh scripts/recommend.sh --demo --mobile-session-id 세션ID --provider mock
```

## CLI 사용법

단일 사용자 추천:

```bash
sh scripts/recommend.sh --user-id U01 --provider naver
```

터미널에서 참가자 정보를 직접 입력:

```bash
sh scripts/recommend.sh --collect-session --provider naver
```

데모와 mock provider:

```bash
sh scripts/recommend.sh --demo --provider mock
```

네이버 API provider:

```bash
sh scripts/recommend.sh --demo --provider naver
```

기본 검색 위치는 세종대학교입니다. 위치를 바꾸려면:

```bash
sh scripts/recommend.sh --demo --provider mock --location 건국대학교
```

## 추천 알고리즘

참가자의 입력은 `like`, `recent`로 모입니다. `like`에는 선호 대분류 2개와 대분류별 음식 2개씩, `recent`에는 최근 대분류와 음식 1개가 저장됩니다.

점수 계산:

```text
score = 0.5 * 선호 대분류 + 0.3 * 선호 소분류 - 0.5 * 최근 대분류 또는 음식
```

그룹 생성은 `scripts/grouping_cli.sh` 안의 `jq` 프로그램이 처리합니다. 참가자마다 선호 대분류와 소분류 음식명을 term으로 만들고, 참가자 간 term 겹침 비율로 유사도를 계산합니다.

1. 처음에는 참가자 1명을 하나의 작은 묶음으로 둡니다.
2. 평균 유사도가 가장 높은 두 묶음을 합칩니다.
3. 목표 그룹 수가 될 때까지 병합을 반복합니다.

따라서 선호 카테고리 종류가 그룹 수보다 많아도 fallback으로 떨어지지 않고, 목표 그룹 수 안에서 비슷한 취향끼리 최대한 보존합니다.

그룹이 만들어지면 각 그룹의 선호를 합쳐 그룹 프로필을 만들고, provider로 주변 식당 후보를 가져옵니다. `mock` provider는 `dataset/mock_restaurants.json`의 `distance_m` 값과 `dataset/restaurant_classifications.json`의 분류 규칙을 사용하고, `naver` provider는 네이버 지역 검색 API로 지정 위치 근처의 식당을 가져옵니다. 분류 규칙은 위에서부터 처음 일치한 항목을 적용하며, `food_pattern`이 없는 항목은 해당 원본 카테고리의 기본값 또는 전체 기본값입니다.

각 그룹원의 `excluded_restaurants`를 CLI에서 하나로 합친 뒤, `scripts/recommend.sh`의 `jq` 후보 필터가 식당 ID 또는 식당명·주소가 일치하는 후보를 제거합니다. 남은 후보는 그룹 프로필 기준으로 점수를 계산한 뒤, 점수가 가장 높고 가까운 식당 한 곳을 반환합니다.

이 과정의 CLI 구현은 `sh`, `jq`, `mktemp`, `scripts/grouping_cli.sh`, provider shell dispatch를 조합합니다. 그룹화의 유사도 계산과 반복 병합도 Python이 아니라 `jq` 기반 CLI가 담당합니다. 웹 GUI는 사용자의 편의를 위한 화면을 유지하고, 내부에서 같은 CLI 파이프라인을 호출한 뒤 그 명령 처리 과정을 시각화합니다.

## 출력과 리포트

CLI 결과는 사람이 읽는 요약으로 출력됩니다.

```text
Group 1 members=U01, U04 -> Top 1: 진미식당 | food=김치찌개 | category=한식 | score=0.8 | reason=matched preferred category 한식; matched preferred food 김치찌개
```

추천 실행 후 `output/report.html`이 생성됩니다. 리포트에는 참가자 입력, 그룹별 최종 추천 식당, 추천 이유, 참가자 수 요약이 포함됩니다.

## 참고

- `mock` provider는 `dataset/mock_restaurants.json`만 사용하므로 API 키가 없어도 동작합니다.
- `naver` provider는 네이버 지역 검색 API를 사용합니다.
- `scripts/mobile_web.sh`가 만든 Cloudflare 임시 URL은 터미널이 켜져 있는 동안만 유지됩니다. 다시 실행하면 새 URL이 만들어집니다.
