# 데이터 모델

## 최상위 데이터

```text
dataset/
  alias_words.json
  demo_session.json
  device_index.json
  menu_categories.json
  mobile_sessions.json
  mock_restaurants.json
  restaurant_classifications.json
  users.json
  participants/
```

## 참가자 폴더

```text
dataset/participants/U0011/
  device.json
  profile.json
  exclusions.json
  location_settings.json
  session_access.json
  meals/
    2026-06-21.json
  submissions/
    <제출시각>_<세션ID>.json
  recommendations/
    <추천시각>_<세션ID>.json
```

### `device.json`

브라우저 `localStorage`가 만든 UUID와 참가자 ID를 연결합니다. 웹 브라우저는 MAC 주소를 읽지 않습니다.

### `profile.json`

최신 이름·별명, source, 생성·갱신 시각과 최신 선호도를 저장합니다.

### `exclusions.json`

사용자가 이전 추천에서 `안 갈래요`를 누른 식당을 누적합니다. 추천 시 식당 ID 또는 식당명·주소로 제외합니다.

### `location_settings.json`

```json
{
  "enabled": true,
  "consent_status": "granted"
}
```

실제 위도·경도는 저장하지 않습니다.

### `session_access.json`

기기가 접속한 QR 세션의 최초·최근 시각을 저장합니다. 현재 세션과 다른 직전 세션을 찾아 이전 추천 평가를 표시할 때 사용합니다.

### `meals/YYYY-MM-DD.json`

```json
{
  "participant_id": "U0011",
  "date": "2026-06-21",
  "meals": {
    "lunch": {
      "submitted_at": "2026-06-21T12:10:00",
      "session_id": "abcd1234",
      "preferences": {
        "like": {
          "high": ["일식", "중식"],
          "low": ["일식|면류", "중식|밥류"]
        },
        "recent": {
          "high": ["한식"],
          "low": ["한식|밥/정식류"]
        }
      }
    }
  }
}
```

같은 날짜의 점심과 저녁은 한 파일에 따로 저장됩니다. 같은 끼니를 다시 제출하면 `submitted_at`이 더 최신인 값만 유지합니다.

### `submissions/`

제출 당시 요청과 세션 맥락을 누적 보존합니다. `profile.json`과 달리 과거 이력입니다.

### `recommendations/`

참가자가 속한 그룹의 추천과 피드백 상태를 저장합니다.

```json
{
  "recommendation_id": "20260621T120000000000_abcd1234",
  "participant_id": "U0011",
  "session_id": "abcd1234",
  "group_id": 1,
  "recommended_at": "2026-06-21T12:00:00",
  "recommendations": [],
  "feedback": {
    "status": "pending"
  }
}
```

## `device_index.json`

기기 UUID → 참가자 ID 인덱스입니다. 파일 락과 함께 사용해 동시 제출 시 동일 기기의 중복 폴더 생성을 막습니다.

기존 중복이 발견되면 가장 오래된 참가자 ID를 유지하고 프로필, 제출, 추천, 제외, 접속, 끼니 기록을 병합합니다.

## `mobile_sessions.json`

최신 세션 ID와 모든 QR 세션을 저장합니다.

세션 주요 필드:

- `id`, `created`, `updated`
- `groups`, `location`, `provider`
- `recommendation_filters`
- `use_exclusions`
- `status`, `mobile_enabled`, `join_url`
- `selected_participant_ids`
- `sample_participant_ids`
- `participants`
- 완료 후 `result_file`

## 샘플 참가자

`dataset/demo_session.json`의 10명은 `U0001`~`U0010` 폴더로 동기화됩니다. 관리자 화면에서 항상 포함되며 삭제 선택할 수 없습니다.

## 자동 별칭

`dataset/alias_words.json`의 형용사 100개와 동물 이름 100개를 조합합니다. 동일 기기는 같은 별칭을 유지하고 이미 사용 중인 조합은 건너뜁니다.

## 기업 분석 패키지

추천 완료 시 `enterprise_analytics/sessions/<세션ID>/`에 생성됩니다.

| 파일 | 내용 |
|---|---|
| `analysis_summary.json` | 세션 설정, 선호 빈도, 그룹별 집계 |
| `participants_anonymized.csv` | `P001` 형식 참가자별 그룹·선호·최근 음식 |
| `groups.csv` | 그룹 규모, 공통 선호, 추천 요약 |
| `recommendations.csv` | 추천 식당의 카테고리, 음식, 점수, 거리·필터 필드 |
| `release_manifest.json` | 기본 외부 제공 후보와 제한 자료 분류 |
| `SUBMISSION_README.md` | 제출 패키지 설명과 개인정보 제거 범위 |

제외되는 필드:

- 이름과 자동 별명
- `U0001` 형식 운영 참가자 ID
- 기기 UUID
- QR 접속 URL
- 제출·접속 시각
- 참가자 위치 좌표

익명 ID와 운영 ID의 매핑 파일은 생성하지 않습니다.

`participants_anonymized.csv`는 기본 외부 전달 압축에서 제외됩니다.
`sh scripts/enterprise_data.sh archive SESSION_ID`는 집계·추천 파일만
압축하며, 제한 자료는 법률 검토 확인 옵션 없이는 압축할 수 없습니다.
