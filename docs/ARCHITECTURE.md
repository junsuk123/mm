# 시스템 구조

![식당 추천 시스템 구조](SystemDiagram.png)

## 실행 경로

시스템에는 두 개의 진입점이 있습니다.

- `scripts/recommend.sh`: 터미널에서 직접 실행하는 CLI 추천
- `src/app.py`: PC 관리자 화면과 모바일 QR 설문을 제공하는 Flask 서버

웹 추천도 별도 알고리즘을 사용하지 않습니다. Flask가 현재 세션을 임시 JSON으로 저장하고 `scripts/recommend.sh --session-file ... --json-output`을 실행합니다.

## 구성요소

### PC 관리자 화면

`templates/index.html`은 3열 무스크롤 대시보드입니다.

- 왼쪽: 세션 설정, 접수 시작·마감, QR
- 가운데: 저장 사용자 선택, 현재 참가자, 그룹별 추천
- 오른쪽: CLI 핵심 로그, 그룹 취향 분포, 추천 점수 근거

CLI 로그는 서버 시작 이후 발생한 이벤트를 `/api/cli-events`에서 250ms 간격으로 읽습니다.

### 모바일 설문

`templates/mobile.html`은 한 화면 고정형 설문입니다. 음식 타일이 많을 때 타일 영역만 내부 스크롤됩니다.

- 기기 UUID 생성과 재사용
- 저장 프로필 조회
- 직전 추천 평가
- 끼니 및 6단계 음식 입력
- 현재 세션 추천 폴링
- 위치 동의와 네이버 길찾기

### Flask 서버

`src/app.py`는 다음 상태를 연결합니다.

- 메모리의 현재 세션과 추천 job
- `dataset/mobile_sessions.json`의 영속 세션
- `dataset/participants/Uxxxx/`의 사용자별 기록
- CLI stderr의 `[cmd]`, `[out]` 이벤트

### CLI 추천 엔진

`scripts/recommend.sh`가 임시 파일과 provider를 조합합니다.

1. 세션 읽기
2. `scripts/grouping_cli.sh` 실행
3. 그룹별 선호 프로필 생성
4. provider 검색
5. 제외·최근 음식·도보·리뷰 필터
6. 점수 계산과 그룹별 Top 1 선택
7. JSON 통합과 HTML 리포트 생성
8. 익명화 기업 분석 JSON·CSV 패키지 생성

기업 분석 생성은 `scripts/recommend.sh`가
`sh scripts/enterprise_data.sh export ...`를 호출하는 Linux CLI 경로로
통일되어 있습니다. 같은 CLI에서 목록, 검증, 요약 조회, 외부 전달용 압축,
SHA-256 생성과 삭제를 수행합니다.

### 그룹화

`scripts/grouping_cli.sh`는 Python이 아니라 하나의 `jq` 프로그램입니다.

- term: 선호 대분류와 `대분류|음식`
- 참가자 유사도: Jaccard
- 클러스터 유사도: 두 클러스터 참가자 쌍의 평균
- 병합: 유사도가 가장 높은 쌍 우선
- 균형: 1인 그룹을 3명 이상 그룹의 마지막 참가자로 보완

## 검색 provider

`scripts/providers/restaurant_provider.sh`가 provider를 선택합니다.

- `mock`: `dataset/mock_restaurants.json`
- `naver`: `src/naver_restaurant_api.py`

Naver 결과는 `dataset/restaurant_classifications.json` 규칙으로 추천 카테고리에 맞춥니다.

## 결과 저장

- CLI 리포트: `output/report.html`
- 웹 실행 임시 결과: `/tmp/session_<세션ID>_result.json`
- 사용자 추천 이력: `dataset/participants/Uxxxx/recommendations/`
- 사용자 피드백: 추천 이력의 `feedback` 및 `exclusions.json`
- 기업 분석 패키지: `enterprise_analytics/sessions/<세션ID>/`

## 보안과 개인정보 경계

- 브라우저 UUID는 MAC 주소가 아닙니다.
- CLI 표시 전에 홈·프로젝트 절대 경로와 임시 파일명이 정리됩니다.
- 현재 위도·경도는 모바일 브라우저에서만 네이버 URL 생성에 사용됩니다.
- 위치 설정 파일에는 동의 상태와 ON/OFF만 저장됩니다.
- 기업 분석 패키지는 운영 ID와의 매핑 파일을 만들지 않고 `P001` 순번만 사용합니다.
