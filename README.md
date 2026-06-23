# Restaurant Recommendation System

참가자의 음식 선호를 모바일 QR 설문으로 수집하고, 비슷한 취향끼리 그룹화한 뒤 그룹별 식당 한 곳을 추천하는 시스템입니다. 추천 엔진은 `sh`와 `jq` 중심의 CLI 파이프라인이며 Flask 웹 화면은 세션 운영, 모바일 입력, 실시간 CLI 표시와 결과 시각화를 담당합니다.

![현재 시스템 구조](docs/SystemDiagram.png)

## 화면

PC 관리자 화면은 스크롤 없이 한 화면에서 세션 설정, QR, 참가자, 추천 결과, CLI 처리 상태와 그룹 취향·추천 근거를 함께 보여줍니다.

![PC 관리자 대시보드](docs/screenshots/pc-dashboard.png)

모바일 설문은 끼니 선택부터 최근 음식과 두 개의 선호 음식군 입력, 제출, 추천 확인까지 한 화면형 단계 UI로 진행됩니다.

| 첫 접속 | 최근 음식 선택 | 선호 음식 선택 |
|---|---|---|
| ![모바일 첫 접속](docs/screenshots/mobile-01-entry.png) | ![최근 음식](docs/screenshots/mobile-02-recent-food.png) | ![선호 음식](docs/screenshots/mobile-04-preference-1-foods.png) |

전체 모바일 동작 과정은 [모바일 설문 흐름](docs/MOBILE_FLOW.md)에서 단계별 이미지로 확인할 수 있습니다.

PC와 모바일의 기능별 레이아웃만 분리한 이미지는 [기능별 화면 스크린샷](docs/FEATURE_SCREENSHOTS.md)에서 확인할 수 있습니다.

<details>
<summary><strong>모바일 전체 동작 과정 펼치기</strong></summary>

| 1. 첫 접속 | 2. 최근 음식 |
|---|---|
| ![첫 접속](docs/screenshots/mobile-01-entry.png) | ![최근 음식 선택](docs/screenshots/mobile-02-recent-food.png) |

| 3. 선호 1 대분류 | 4. 선호 1 음식 |
|---|---|
| ![첫 번째 선호 대분류](docs/screenshots/mobile-03-preference-1-category.png) | ![첫 번째 선호 음식](docs/screenshots/mobile-04-preference-1-foods.png) |

| 5. 선호 2 대분류 | 6. 선호 2 음식 |
|---|---|
| ![두 번째 선호 대분류](docs/screenshots/mobile-05-preference-2-category.png) | ![두 번째 선호 음식](docs/screenshots/mobile-06-preference-2-foods.png) |

| 7. 제출 준비 | 8. 제출 완료 |
|---|---|
| ![제출 준비](docs/screenshots/mobile-07-ready.png) | ![제출 완료](docs/screenshots/mobile-08-submitted.png) |

| 9. 이전 추천 평가 | 10. 최종 추천·길찾기 |
|---|---|
| ![이전 추천 평가](docs/screenshots/mobile-09-previous-feedback.png) | ![최종 추천과 길찾기](docs/screenshots/mobile-10-result.png) |

| 11. 네이버 길찾기 실행 |
|---|
| ![네이버 길찾기 문서용 미리보기](docs/screenshots/mobile-11-naver-route.png) |

</details>

## 주요 기능

- 샘플 참가자 10명과 저장된 실제 사용자를 조합한 임시 추천 세션
- 브라우저 UUID 기반 사용자 식별과 `U0001` 형식의 영구 참가자 폴더
- 이름 미입력 시 형용사·동물 조합 자동 별칭
- 점심·저녁별 최신 설문 기록
- Jaccard 유사도와 계층 병합을 이용한 `jq` 기반 그룹화
- mock 또는 Naver 지역 검색 provider
- 예상 도보 시간, 리뷰 인기순, 최근 음식, 사용자별 제외 식당 필터
- 그룹별 추천 식당 중복 방지
- PC 무스크롤 대시보드와 실시간 CLI 핵심 단계 표시
- 참가자 → 그룹 취향 → 추천 식당 관계 시각화
- 모바일 이전 추천 평가와 `안 갈래요` 제외 목록
- 모바일 추천 완료 자동 확인과 네이버 지도 길찾기
- 독립 실행 가능한 HTML 결과 리포트
- 기업 제출용 익명화 JSON·CSV 분석 패키지 자동 생성

## 빠른 실행

### 1. 의존성

```bash
sudo apt update
sudo apt install -y jq python3 python3-pip python3-venv

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Python 패키지는 Flask만 필요합니다. 추천 파이프라인은 시스템의 `sh`, `jq`, `mktemp`를 사용합니다.

### 2. 웹 관리자 화면

```bash
.venv/bin/python src/app.py
```

기본 주소:

```text
http://127.0.0.1:5000
```

브라우저 자동 실행을 끄려면:

```bash
MM_AUTO_OPEN=0 .venv/bin/python src/app.py
```

포트를 변경하려면:

```bash
PORT=8000 .venv/bin/python src/app.py
```

### 3. 외부 모바일 QR 접속

```bash
sh scripts/mobile_web.sh
```

스크립트는 다음 순서로 사용 가능한 HTTPS 터널을 찾습니다.

1. `cloudflared`
2. `ngrok`
3. `npx --yes cloudflared`

이미 공개 URL이 있으면 터널 생성을 생략할 수 있습니다.

```bash
MM_PUBLIC_BASE_URL=https://example.com sh scripts/mobile_web.sh
```

### 4. API 없이 CLI 데모

```bash
sh scripts/recommend.sh --demo --without-mobile-responses --provider mock
```

실행 후 `output/report.html`이 생성됩니다.

## 웹 운영 순서

1. 관리자 화면에서 그룹 수, 위치, provider, 도보·리뷰 필터와 `안갈래요` 사용 여부를 정합니다.
2. 저장 사용자 폴더를 선택합니다. 샘플 참가자 10명은 항상 포함됩니다.
3. `접수 시작`을 누르면 세션과 QR 링크가 생성됩니다.
4. 참가자는 QR로 접속해 이름 또는 별명, 끼니와 음식 선호를 제출합니다.
5. 접수 중 저장 사용자 선택을 바꾸면 현재 세션에도 즉시 반영됩니다.
6. `마감 및 실행`을 누르면 모바일 접수가 닫히고 CLI 추천 job이 실행됩니다.
7. PC 화면에는 그룹 결과와 취향·추천 근거 지도가 표시됩니다.
8. 모바일 참가자는 자신의 그룹 추천을 자동으로 확인합니다.
9. `enterprise_analytics/sessions/<세션ID>/`에 익명화 분석 패키지가 저장됩니다.

세션은 참가자가 최소 2명씩 배정될 수 있는 그룹 수만 허용합니다. 기본 참가자 10명만 사용하는 경우 1~5개 그룹을 선택할 수 있습니다.

## 모바일 설문 입력

모바일 입력은 실제로 여섯 단계입니다.

1. 최근 음식 대분류 1개
2. 최근 음식 소분류 1개
3. 첫 번째 선호 대분류 1개
4. 첫 번째 대분류의 소분류 2개
5. 두 번째 선호 대분류 1개
6. 두 번째 대분류의 소분류 2개

두 번째 선호 대분류는 첫 번째와 달라야 합니다. 제출하려면 점심 또는 저녁도 선택해야 합니다. `다시하기`는 저장 프로필 자동 입력 없이 빈 설문으로 다시 시작합니다.

기존 사용자가 새 세션에 접속하면 직전 다른 세션의 추천을 평가할 수 있습니다. `안 갈래요`를 누른 식당은 해당 사용자의 `exclusions.json`에 저장됩니다.

## 추천 알고리즘

### 그룹화

`scripts/grouping_cli.sh`가 참가자의 선호 대분류와 `대분류|음식` term을 만듭니다.

1. 참가자 간 Jaccard 유사도를 계산합니다.
2. 평균 유사도가 가장 높은 두 클러스터를 합칩니다.
3. 요청한 그룹 수까지 반복합니다.
4. 1인 그룹이 생기면 3명 이상인 가장 큰 그룹에서 한 명을 재배치합니다.

### 후보 검색과 필터

그룹별 선호 term으로 식당을 검색한 뒤 다음 후보를 제거합니다.

- 그룹원이 최근 먹은 음식
- 그룹원의 `안 갈래요` 식당
- 앞 그룹이 이미 추천받은 식당
- 설정한 예상 도보 시간 또는 리뷰 인기순 범위를 벗어난 식당

거리·리뷰 조건 때문에 후보가 모두 사라지면 두 조건만 완화합니다. 그래도 후보가 없으면 Naver provider는 `음식점`, `맛집` 검색으로 범위를 넓힙니다. 최근 음식과 제외 식당 조건은 유지됩니다.

### 점수

```text
대분류가 그룹 프로필에 존재하면 +0.5
음식이 그룹 프로필에 존재하면 +0.3
```

현재 점수는 선호 인원수를 가중치로 사용하지 않습니다. PC 취향 지도에서 파란 선은 그룹 내 선호 분포, 초록 선은 실제 추천 점수 조건과 일치한 항목을 뜻합니다.

## CLI 사용법

```bash
# 대화형 참가자 입력
sh scripts/recommend.sh --collect-session --provider naver

# 기본 데모 + 최신 모바일 세션
sh scripts/recommend.sh --demo --provider mock

# 기본 데모만
sh scripts/recommend.sh --demo --without-mobile-responses --provider mock

# 특정 모바일 세션 결합
sh scripts/recommend.sh --demo --mobile-session-id SESSION_ID --provider mock

# 저장된 dataset/users.json 사용자
sh scripts/recommend.sh --user-id U01 --provider naver

# 웹 서버와 같은 세션 JSON 실행
sh scripts/recommend.sh \
  --session-file /tmp/session.json \
  --provider mock \
  --location 세종대학교 \
  --json-output
```

지원 옵션은 다음 명령으로 확인할 수 있습니다.

```bash
sh scripts/recommend.sh --help
```

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---:|---|
| `PORT` | `5000` | Flask와 터널이 사용할 포트 |
| `PYTHON` | `.venv/bin/python` 또는 `python3` | `mobile_web.sh`가 사용할 Python |
| `MM_PUBLIC_BASE_URL` | 없음 | QR에 넣을 공개 기준 URL |
| `MM_AUTO_OPEN` | `1` | 관리자 화면 자동 열기 |
| `MM_NAVER_DIRECTIONS_ENABLED` | `1` | 모바일 네이버 길찾기 전체 활성화 |
| `MM_NAVER_MAX_WORKERS` | `5` | Naver 음식 검색 동시 요청 수 |
| `MM_STEP_TRACE` | 실행별 설정 | 웹 화면에 CLI 실행 단계를 표시할지 여부 |
| `MM_VISUALIZER_SKIP_LIVE` | 없음 | HTML 리포트에서 추가 실시간 검색 생략 |
| `NAVER_CLIENT_ID` | 코드 기본값 | Naver 지역 검색 Client ID 재정의 |
| `NAVER_CLIENT_SECRET` | 코드 기본값 | Naver 지역 검색 Client Secret 재정의 |

Naver API 인증은 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` 환경변수 또는 `src/naver_restaurant_api.py`의 CLI 인자를 사용합니다. API 키 없이 개발·검증할 때는 `mock` provider를 사용하세요.

## 기업 제출용 데이터 분석

그룹 추천이 완료되면 운영 원본과 분리된 다음 폴더가 자동 생성됩니다.

```text
enterprise_analytics/
  sessions/
    <세션ID>/
      analysis_summary.json
      participants_anonymized.csv
      groups.csv
      recommendations.csv
      release_manifest.json
      SUBMISSION_README.md
```

생성·조회·검증·압축·삭제는 모두 Linux CLI 진입점을 사용합니다.

```bash
# 기존 추천 결과로 생성
sh scripts/enterprise_data.sh export \
  --input /tmp/session_SESSION_ID_result.json \
  --session-id SESSION_ID

# 저장된 세션 목록과 요약
sh scripts/enterprise_data.sh list
sh scripts/enterprise_data.sh inspect SESSION_ID

# 필수 파일·식별자 필드 검사
sh scripts/enterprise_data.sh verify SESSION_ID

# 기본 외부 전달 후보만 tar.gz + SHA-256으로 압축
sh scripts/enterprise_data.sh archive SESSION_ID

# 삭제
sh scripts/enterprise_data.sh delete SESSION_ID --yes
```

- 참가자는 `P001` 형식으로 다시 번호를 부여합니다.
- 이름·별명, 원본 사용자 ID, 기기 UUID, QR URL, 제출 시각과 참가자 위치 좌표는 제외합니다.
- `participants_anonymized.csv`는 참가자별 선호와 그룹을 담습니다.
- `groups.csv`는 그룹 규모, 공통 선호와 추천 결과를 담습니다.
- `recommendations.csv`는 점수·거리·도보·리뷰 관련 분석 필드를 담습니다.
- `analysis_summary.json`은 전체 선호 빈도와 그룹별 요약을 담습니다.
- `release_manifest.json`은 기본 외부 제공 후보와 제한 자료를 구분합니다.

`participants_anonymized.csv`는 참가자 단위 행이 있어 기본 외부 압축에서 제외됩니다. 법률·보안 검토가 끝난 경우에만 아래처럼 명시적으로 포함합니다.

```bash
sh scripts/enterprise_data.sh archive SESSION_ID \
  --include-restricted \
  --confirm-legal-review
```

생성된 세션 패키지는 운영 데이터일 수 있으므로 Git에서 제외되며, 폴더 설명 파일만 저장소에서 관리합니다.

상세 가이드:

- [활용성과 사용 방법](enterprise_analytics/USAGE_GUIDE.md)
- [Linux CLI 운영](enterprise_analytics/CLI_GUIDE.md)
- [데이터 사전](enterprise_analytics/DATA_DICTIONARY.md)
- [상업적 제공 준수사항](enterprise_analytics/COMPLIANCE_GUIDE.md)
- [상업화·수익 모델](enterprise_analytics/COMMERCIALIZATION_GUIDE.md)

## 상업적 활용과 수익 모델

배달·지도·커머스 요식업 기업에 제안할 수 있는 핵심 자산은 개인 식별 데이터가 아니라, 적법하게 수집한 집계 선호와 추천·피드백 분석입니다.

가능한 사업 모델:

- 지역·끼니별 음식 선호를 제공하는 정기 상권 인사이트 구독
- 플랫폼·프랜차이즈별 맞춤 설문과 분석 프로젝트
- 그룹 주문과 최근 음식 회피 기능을 포함한 추천 API 라이선스
- 대학·기업·행사용 QR 설문 및 그룹 주문 SaaS
- 기업 내부 데이터의 음식 분류·익명화·리포트 가공 서비스

활용 예:

- 배달 플랫폼: 그룹 주문 메뉴, 끼니별 카테고리 수요, 교차 주문 조합
- 지도·검색 플랫폼: 그룹 외식 장소, 이동 허용 범위, 추천 제외 피드백
- 커머스 플랫폼: 간편식·밀키트 수요, 지역·시간대별 상품 구성

수익화 방식은 정액 구독, 응답 수·상권 수 기반 과금, 프로젝트 비용, API 호출량 과금, 설치형 라이선스와 유지보수 계약을 조합할 수 있습니다. 다만 실제 매출이나 특정 기업의 구매·제휴를 보장하는 것은 아닙니다. 초기에는 원시 데이터 판매보다 PoC 분석, 리포트, 수집 SaaS와 추천 API가 현실적인 수익 경로입니다.

### 제공 전 필수 조건

현재 모바일 설문에는 특정 기업에 대한 상업적 제3자 제공을 별도로 고지하고 동의받는 절차가 없습니다. 따라서 기존 참가자 단위 데이터를 바로 판매하거나 제공하면 안 됩니다.

신규 상업 수집 전에는 최소한 다음을 준비해야 합니다.

- 제공받는 자, 목적, 항목, 보유기간과 거부권을 명확히 알리는 절차
- 별도 동의 또는 적용 가능한 다른 적법 근거에 대한 검토
- 재식별 위험과 소수 집단·희귀 취향 노출 검토
- 재판매·재제공·재결합·재식별 금지 계약
- 전달 파일 SHA-256, 수신자, 계약 번호, 보유·파기 일자의 관리대장
- 데모 참가자를 제외한 실제 표본과 표본 편향·추천 점수 한계의 고지

공식 참고:

- [개인정보 보호법](https://www.law.go.kr/LSW/lsInfoP.do?lsId=011357)
- [개인정보 보호법 시행령](https://www.law.go.kr/LSW/lsInfoP.do?lsId=011468)
- [개인정보보호위원회](https://www.pipc.go.kr/)
- [한국데이터산업진흥원](https://www.kdata.or.kr/)
- [산업데이터 계약 가이드라인](https://www.data.go.kr/data/15113186/fileData.do)

## 문서

- [시스템 구조](docs/ARCHITECTURE.md)
- [모바일 설문 흐름과 전체 캡처](docs/MOBILE_FLOW.md)
- [Flask API](docs/API.md)
- [데이터 모델](docs/DATA_MODEL.md)

문서 이미지를 현재 템플릿으로 다시 생성하려면:

```bash
python3 scripts/capture_docs_screenshots.py
```

Google Chrome 또는 Chromium이 필요하며, 캡처는 미리보기 데이터만 사용하므로 참가자와 세션 파일을 변경하지 않습니다.

## 디렉터리

```text
dataset/                  세션·참가자·메뉴·식당 데이터
docs/                     구조 문서와 화면 캡처
output/                   생성된 HTML 리포트
enterprise_analytics/     기업 제출용 익명화 분석 패키지
scripts/recommend.sh      CLI 추천 진입점
scripts/grouping_cli.sh   jq 그룹화
scripts/mobile_web.sh     공개 HTTPS 모바일 실행
scripts/providers/        식당 provider dispatch
src/app.py                Flask 서버와 API
src/naver_restaurant_api.py
src/preference_utils.py
src/recommendation_visualizer.py
templates/index.html      PC 관리자 화면
templates/mobile.html     모바일 설문
```

## 참고

- 브라우저에서는 MAC 주소를 읽지 않습니다. `localStorage`의 UUID를 기기 식별자로 사용합니다.
- 위치 좌표는 네이버 길찾기 URL을 만드는 모바일 브라우저에서만 사용하며 서버에 저장하지 않습니다.
- Cloudflare 임시 URL은 터널 프로세스가 종료되면 사라지고 재실행 시 바뀔 수 있습니다.
- `dataset/participants/`와 `dataset/mobile_sessions.json`은 실제 운영 데이터이므로 백업 후 관리하세요.
