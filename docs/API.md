# Flask API

기준 구현: `src/app.py`

## 화면

| Method | Path | 설명 |
|---|---|---|
| GET | `/` | PC 관리자 대시보드 |
| GET | `/join/<session_id>` | 모바일 설문 |

## 메뉴

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/categories` | 대분류 목록 |
| GET | `/api/subcategories/<category>` | 중분류 호환 API |
| GET | `/api/foods/<category>/<subcategory>` | 중분류 아래 음식 |
| GET | `/api/foods/<category>` | 대분류의 음식 |
| GET | `/api/foods?category=...` | 슬래시 포함 카테고리용 권장 API |

모바일 현재 구현은 query parameter 형태의 `/api/foods`를 사용합니다.

## 네트워크와 CLI

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/network-info` | QR에 사용할 접속 URL 후보 |
| GET | `/api/cli-events?after=<id>` | 지정 ID 이후 CLI 이벤트 |

## 참가자

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/participants` | 관리자용 영구 참가자 폴더 |
| GET | `/api/participant/<device_id>?session_id=...` | 기기 프로필과 직전 추천 |
| GET | `/api/participant/<device_id>/meals` | 날짜별 점심·저녁 기록 |
| GET/POST | `/api/participant/<device_id>/location-settings` | 길찾기 동의와 ON/OFF |
| POST | `/api/participant/<device_id>/recommendation-feedback` | 이전 추천 닫기 또는 제외 |

피드백 요청:

```json
{
  "recommendation_id": "20260621T120000000000_abcd1234",
  "action": "exclude",
  "restaurant": {
    "restaurant_id": "restaurant-id",
    "name": "식당명",
    "address": "주소"
  }
}
```

`action`은 `exclude` 또는 `dismiss`입니다. `dismiss`일 때는 `restaurant`를 생략할 수 있습니다.

## 세션

| Method | Path | 설명 |
|---|---|---|
| POST | `/api/session/create` | 세션과 QR 생성 |
| GET | `/api/session/<session_id>` | 세션 조회 |
| PUT | `/api/session/<session_id>/participants` | 접수 중 저장 사용자 선택 변경 |
| POST | `/api/session/<session_id>/add-participant` | 모바일 설문 제출 |
| POST | `/api/session/<session_id>/close` | 접수 마감 |
| POST | `/api/session/<session_id>/generate-recommendations` | 비동기 CLI job 시작 |
| GET | `/api/session/<session_id>/participant-recommendation/<device_id>` | 모바일 추천 폴링 |
| GET | `/api/job/<job_id>` | CLI job 상태와 결과 |

세션 생성 예:

```json
{
  "group_count": 2,
  "location": "세종대학교",
  "provider": "naver",
  "walking_minutes": 15,
  "review_top_n": 3,
  "use_exclusions": true,
  "participant_ids": ["U0011"],
  "public_base_url": "https://example.com"
}
```

제약:

- `group_count`: 모든 그룹에 최소 2명이 들어가는 범위
- `walking_minutes`: `0`, `5`, `10`, `15`, `20`, `25`, `30`
- `review_top_n`: `0`, `1`, `3`, `5`
- 모바일 제출의 `source`: 반드시 `mobile`

모바일 제출 예:

```json
{
  "source": "mobile",
  "device_id": "browser-generated-uuid",
  "user_id": "반짝이는 수달",
  "meal_type": "lunch",
  "like_high": ["일식", "중식"],
  "like_low": [
    "일식|초밥/회류",
    "일식|면류",
    "중식|면류",
    "중식|밥류"
  ],
  "recent_high": ["한식"],
  "recent_low": ["한식|밥/정식류"]
}
```

## 세션 상태

- `collecting`: 모바일 제출과 저장 사용자 변경 가능
- `closed`: 접수 마감, 결과 계산 전후
- `completed`: 결과 저장 완료
- `failed`: CLI 실행 실패

추천 job은 별도 daemon thread에서 실행됩니다. `/api/job/<job_id>`를 폴링해 `running`, `completed`, `failed`를 확인합니다.
