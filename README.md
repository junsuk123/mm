# Restaurant Recommendation System

이 워크스페이스는 셸 스크립트와 CLI 명령만으로 동작합니다.

## 구조

- `recommend.sh`: 메인 CLI 진입점
- `restaurant_provider.sh`: provider 디스패치 인터페이스 (`naver`, `mock`)
- `naver_restaurant_provider.sh`: 네이버 지역 검색 API provider
- `naver_restaurant_api.py`: 네이버 API 응답 정규화 헬퍼
- `dataset/menu_categories.json`: 한국어 카테고리 트리
- `dataset/demo_session.json`: 10명, 3그룹 예시 시뮬레이션 세션 데이터
- `dataset/users.json`: 루트 하위 모듈 폴더에 저장한 사용자 예시 데이터

## 리눅스 CLI 사용 방식

핵심 구현은 아래 명령들을 조합해서 처리합니다. 이 프로젝트는 셸 스크립트가 전체 흐름을 조립하고, `jq`와 `python3`가 중간 계산을 담당하는 구조입니다.

- `sh`: 메인 진입점인 `recommend.sh`를 실행하고, `restaurant_provider.sh`와 `naver_restaurant_provider.sh`를 이어 붙입니다.
- `jq`: 입력한 선호를 JSON으로 바꾸고, 그룹별 프로필을 합치고, 후보 식당을 필터링하고, 점수를 계산하고, 최종 Top 3를 남깁니다.
- `mktemp`: 세션, 그룹 프로필, 후보 목록, 최종 결과를 임시 파일로 분리해서 안전하게 다룹니다.
- `awk`: 번호가 붙은 메뉴 목록을 보기 좋게 출력하고, 데모 모드에서는 입력이 천천히 찍히는 것처럼 보여 줍니다.
- `sed`: 사용자가 입력한 번호 문자열의 앞뒤 공백을 정리하고, 선택한 줄을 정확히 찾아옵니다.
- `python3`: 그룹 배정 fallback 로직, 네이버 API 응답 정규화, HTML 시각화 리포트를 생성합니다.

이 프로젝트는 단순히 명령을 실행하는 것이 아니라, 셸과 JSON 도구를 연결해 작은 데이터 파이프라인처럼 동작합니다. 예를 들어 `jq`로 선호 항목을 모으고, `mktemp`로 후보를 저장한 뒤, 다시 `jq`로 점수를 계산합니다.
최종 표준 출력은 JSON이 아니라 그룹별 Top 3 식당 요약입니다.

CLI에서 실제로 일어나는 흐름은 다음과 같습니다.

1. `recommend.sh`가 사용자 입력을 받아 like, dislike, recent를 대분류, 소분류로 수집합니다.
2. `grouping_utils.py`가 참가자들을 먼저 유사도 기준으로 묶고, 실패하면 가장 많이 겹치는 항목 기준으로 다시 묶습니다.
3. 각 그룹의 선호를 합쳐 그룹 프로필을 만들고, `naver_restaurant_provider.sh`가 네이버 지역 검색 결과를 가져옵니다.
4. `jq`가 후보 식당을 정리하고, 선호도 기반 점수를 계산한 뒤, 그룹당 가장 높은 3곳을 남깁니다.

## 실행 예시

단일 사용자 추천:

```bash
sh recommend.sh --user-id U01 --provider naver
```

전체 세션 추천:

```bash
sh recommend.sh --collect-session --provider naver
```

예시 데이터 시뮬레이션:

```bash
sh recommend.sh --demo --provider mock
```

시각화 리포트 생성:

Flask API의 세션 결과는 JSON으로 반환되므로, 필요하면 그 응답을 파일로 저장한 뒤 `visualization/recommendation_visualizer.py`에 넘겨 HTML 리포트를 만들 수 있습니다. 이 저장된 JSON을 시각화 입력으로 쓰면, 그룹별 후보와 최종 선정 결과를 HTML로 볼 수 있습니다.

## 핵심 알고리즘

1. 참가자의 like, dislike, recent 입력을 대분류와 소분류로 모읍니다.
2. 그룹은 먼저 유사도 기준으로 묶고, 실패하면 가장 많이 공통된 항목을 기준으로 다시 묶습니다.
3. 각 그룹의 선호 항목으로 후보 식당을 찾고, 위치가 맞지 않는 식당은 제외합니다.
4. 점수는 다음처럼 계산합니다.

```text
score = 0.5 * 선호 대분류 + 0.3 * 선호 소분류 - 0.5 * 최근 음식 - 0.8 * 싫어하는 대분류 - 1.0 * 싫어하는 소분류
```

5. 점수가 가장 높은 식당 3곳을 최종 추천으로 남깁니다.

좀 더 풀어 쓰면, `like`는 가산점, `recent`와 `dislike`는 감점으로 작동합니다. 대분류는 넓은 취향을, 소분류는 더 구체적인 메뉴 취향을 반영하고, 최근 먹은 음식은 반복 추천을 줄이기 위해 빼 줍니다. 추천 결과에는 점수와 함께 어떤 선호가 맞았고 어떤 항목이 감점되었는지 짧은 이유가 표시됩니다.

그룹 생성은 `grouping_utils.py`에서 두 단계로 처리합니다.

1. 참가자끼리 공유하는 선호 항목이 충분하면 유사도 기준으로 묶습니다.
2. 유사도 기준으로 유효한 그룹을 만들 수 없으면, 가장 많이 공통된 항목을 기준으로 그룹을 다시 만듭니다.

이 방식은 데이터가 고르게 분포하지 않아도 항상 그룹을 만들 수 있게 해 줍니다.

CLI 실행 결과는 다음처럼 사람이 읽는 한 줄 요약으로 출력됩니다.

```text
Group 1 members=U01, U04 -> Top 1: 진미식당 | food=김치찌개 | category=한식 | score=0.8 | reason=matched preferred category 한식; matched preferred food 김치찌개
```

생성된 HTML 리포트에는 다음이 포함됩니다.

- 사용자 입력 과정의 대분류 / 소분류 시각화
- 좋아하는 음식과 최근 먹은 음식의 중복 항목
- 그룹별 후보 식당 리스트
- 최종 선정된 식당 Top 3와 추천 이유
- Business Insight Report: 추천/선호/최근/회피 카테고리 집계와 추정 참가자 수

`--demo` 모드에서는 `dataset/demo_session.json`의 예시 데이터를 자동으로 불러와, 실제 입력하는 것처럼 참가자 수, 그룹 수, 카테고리 선택 과정을 터미널에 보여 줍니다.

기본 검색 위치는 세종대학교입니다. CLI와 웹 화면 모두 별도 `--location` 입력이 없으면 세종대학교 기준으로 네이버 지역 검색을 수행합니다.

## 전체 세션 흐름

프로그램은 다음 순서로 입력을 받습니다.

1. 참가자 수
2. 그룹 수
3. 각 참가자 ID
4. 각 참가자의 like, dislike, recent 메뉴를 high, low 단계별로 입력

각 단계마다 터미널이 한국어 카테고리 목록을 번호로 보여 주고, 사용자는 번호만 입력합니다.
high는 대분류, low는 개별 메뉴를 의미합니다. 기존 중분류 입력은 이제 소분류 입력으로 재정의됩니다.

메뉴는 번호를 쉼표로 여러 개 입력할 수 있으며, 비워 두면 해당 항목은 없는 것으로 처리합니다. 오프라인 발표나 API 키 없는 테스트는 `sh recommend.sh --demo --provider mock`을 사용하면 `dataset/mock_restaurants.json`만으로 실행됩니다.

입력이 끝나면 즉시 그룹별 추천을 시작하고, 최종 결과는 그룹별 식당 Top 3를 사람이 읽을 수 있는 텍스트로 출력합니다.

## 메모

- Naver 지역 검색 API는 `title`, `category`, `address`, `roadAddress`, `mapx`, `mapy`를 반환하며, `음식점>한식` 같은 값은 추천 점수 계산을 위해 한식처럼 정규화합니다.
- 식당 후보는 선택한 음식/분류를 쿼리로 검색해 모으고, 중복은 `restaurant_id` 기준으로 제거합니다.
