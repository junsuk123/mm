# 기업 분석 데이터 사전

## `analysis_summary.json`

| 필드 | 의미 |
|---|---|
| `schema_version` | 패키지 스키마 버전 |
| `generated_at` | UTC 생성 시각 |
| `session_id` | 추천 세션 ID |
| `privacy` | 제거한 식별자와 익명화 정책 |
| `session` | 참가자·그룹 수, provider, 검색 위치, 필터 |
| `aggregates` | 참가자 source, 선호·최근 음식 빈도 |
| `groups` | 그룹 규모, 공통 선호, 추천 요약 |

## `groups.csv`

| 열 | 의미 |
|---|---|
| `group_id` | 세션 안의 그룹 번호 |
| `member_count` | 그룹 참가자 수 |
| `anonymous_members` | 패키지 내부 익명 ID 목록 |
| `shared_preference_count` | 2명 이상이 선택한 term 수 |
| `shared_preferences` | term별 선택 인원 |
| `excluded_restaurant_count` | 추천 전 적용된 그룹 제외 식당 수 |
| `recommended_restaurant` | 그룹 추천 식당 |
| `recommended_category` | 추천 식당 대분류 |
| `recommended_food` | 추천 검색·매칭 음식 |
| `recommendation_score` | 현재 추천 규칙 점수 |

## `recommendations.csv`

| 열 | 의미 |
|---|---|
| `group_id`, `rank` | 그룹과 추천 순위 |
| `restaurant_name` | 추천 식당명 |
| `category`, `food` | 추천 분류와 매칭 음식 |
| `score` | 대분류 +0.5, 음식 +0.3 규칙 점수 |
| `distance_m` | 검색 기준 위치로부터 추정 거리 |
| `walking_minutes` | 직선거리와 보행 계수 기반 예상치 |
| `review_rank` | 검색어별 리뷰 정렬 순위 |
| `matched_terms` | provider 검색에서 일치한 term |
| `reason` | 점수 조건 설명 |

## `participants_anonymized.csv` — 제한 자료

| 열 | 의미 |
|---|---|
| `anonymous_participant_id` | 패키지 내부 `P001` 순번 |
| `group_id` | 소속 그룹 |
| `source_type` | demo 또는 mobile |
| `preferred_categories` | 선호 대분류 |
| `preferred_foods` | 선호 음식 |
| `recent_categories`, `recent_foods` | 최근 음식 |
| `exclusion_count` | 사용자 제외 식당 수 |

이 파일은 개인별 행을 포함하므로 소규모 집단에서 재식별 가능성이 있습니다. 기본 외부 압축에서 제외합니다.

## 해석 한계

- 참가자는 확률 표본이 아니므로 전체 시장 대표성이 보장되지 않습니다.
- 현재 샘플 10명은 데모 데이터이므로 상업 분석 모집단에 포함하면 안 됩니다.
- 선호는 설문 시점과 끼니 맥락에 따라 달라질 수 있습니다.
- 점수는 선호 인원 비율이 아니라 그룹 프로필 내 존재 여부를 사용합니다.
- 예상 도보 시간과 리뷰 순위는 실제 플랫폼의 경로·리뷰 수와 다를 수 있습니다.
