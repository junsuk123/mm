#!/usr/bin/env python3
"""Create anonymized, company-submission-ready analytics files."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "enterprise_analytics" / "sessions"
SAFE_ID_PATTERN = re.compile(r"[^A-Za-z0-9_-]+")


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return data


def leaf(value: Any) -> str:
    parts = [part.strip() for part in str(value or "").split("|") if part.strip()]
    return parts[-1] if parts else ""


def values(preferences: dict[str, Any], group: str, level: str) -> list[str]:
    raw = preferences.get(group, {}).get(level, [])
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(filter(None, (leaf(item) for item in raw))))


def safe_session_id(value: Any) -> str:
    cleaned = SAFE_ID_PATTERN.sub("-", str(value or "").strip()).strip("-_")
    if cleaned:
        return cleaned[:80]
    return datetime.now(timezone.utc).strftime("cli-%Y%m%dT%H%M%SZ")


def anonymous_mapping(participants: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for index, participant in enumerate(participants, start=1):
        anonymous_id = f"P{index:03d}"
        for key in ("user_id", "participant_id", "original_user_id"):
            value = str(participant.get(key) or "").strip()
            if value:
                mapping[value] = anonymous_id
    return mapping


def group_lookup(groups: list[dict[str, Any]], mapping: dict[str, str]) -> dict[str, Any]:
    lookup: dict[str, Any] = {}
    for group in groups:
        group_id = group.get("group_id")
        for member in group.get("members", []):
            anonymous_id = mapping.get(str(member))
            if anonymous_id:
                lookup[anonymous_id] = group_id
    return lookup


def shared_terms(member_rows: list[dict[str, Any]]) -> list[tuple[str, int]]:
    support: Counter[str] = Counter()
    for row in member_rows:
        terms = set(row["preferred_categories"] + row["preferred_foods"])
        support.update(terms)
    return sorted(
        ((term, count) for term, count in support.items() if count > 1),
        key=lambda item: (-item[1], item[0]),
    )


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def export_analytics(
    report: dict[str, Any],
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    session_id: str = "",
) -> Path:
    participants = [
        participant
        for participant in report.get("participants", [])
        if isinstance(participant, dict)
    ]
    groups = [group for group in report.get("groups", []) if isinstance(group, dict)]
    session = report.get("session", {}) if isinstance(report.get("session"), dict) else {}
    resolved_session_id = safe_session_id(
        session_id or session.get("session_id") or report.get("session_id")
    )
    output_dir = output_root / resolved_session_id
    output_dir.mkdir(parents=True, exist_ok=True)

    mapping = anonymous_mapping(participants)
    participant_groups = group_lookup(groups, mapping)
    participant_rows: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    food_counts: Counter[str] = Counter()
    recent_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()

    for index, participant in enumerate(participants, start=1):
        anonymous_id = mapping.get(
            str(participant.get("user_id") or participant.get("participant_id") or ""),
            f"P{index:03d}",
        )
        preferences = (
            participant.get("preferences", {})
            if isinstance(participant.get("preferences"), dict)
            else {}
        )
        preferred_categories = values(preferences, "like", "high")
        preferred_foods = values(preferences, "like", "low")
        recent_categories = values(preferences, "recent", "high")
        recent_foods = values(preferences, "recent", "low")
        source = str(participant.get("source") or "unknown")
        exclusions = participant.get("excluded_restaurants", [])
        exclusion_count = len(exclusions) if isinstance(exclusions, list) else 0

        category_counts.update(preferred_categories)
        food_counts.update(preferred_foods)
        recent_counts.update(recent_foods)
        source_counts.update([source])
        participant_rows.append(
            {
                "anonymous_participant_id": anonymous_id,
                "group_id": participant_groups.get(anonymous_id, ""),
                "source_type": source,
                "preferred_categories": preferred_categories,
                "preferred_foods": preferred_foods,
                "recent_categories": recent_categories,
                "recent_foods": recent_foods,
                "exclusion_count": exclusion_count,
            }
        )

    participant_csv_rows = [
        {
            **row,
            "preferred_categories": " | ".join(row["preferred_categories"]),
            "preferred_foods": " | ".join(row["preferred_foods"]),
            "recent_categories": " | ".join(row["recent_categories"]),
            "recent_foods": " | ".join(row["recent_foods"]),
        }
        for row in participant_rows
    ]
    write_csv(
        output_dir / "participants_anonymized.csv",
        [
            "anonymous_participant_id",
            "group_id",
            "source_type",
            "preferred_categories",
            "preferred_foods",
            "recent_categories",
            "recent_foods",
            "exclusion_count",
        ],
        participant_csv_rows,
    )

    participant_by_anonymous_id = {
        row["anonymous_participant_id"]: row for row in participant_rows
    }
    group_rows: list[dict[str, Any]] = []
    recommendation_rows: list[dict[str, Any]] = []
    group_summaries: list[dict[str, Any]] = []
    for group in groups:
        anonymous_members = [
            mapping.get(str(member), "")
            for member in group.get("members", [])
            if mapping.get(str(member))
        ]
        member_rows = [
            participant_by_anonymous_id[member]
            for member in anonymous_members
            if member in participant_by_anonymous_id
        ]
        shared = shared_terms(member_rows)
        recommendations = [
            recommendation
            for recommendation in group.get("recommendations", [])
            if isinstance(recommendation, dict)
        ]
        top = recommendations[0] if recommendations else {}
        group_id = group.get("group_id")
        group_row = {
            "group_id": group_id,
            "member_count": len(anonymous_members),
            "anonymous_members": " | ".join(anonymous_members),
            "shared_preference_count": len(shared),
            "shared_preferences": " | ".join(
                f"{term}({count})" for term, count in shared
            ),
            "excluded_restaurant_count": group.get(
                "excluded_restaurant_count", 0
            ),
            "recommended_restaurant": top.get("name", ""),
            "recommended_category": top.get("category", ""),
            "recommended_food": top.get("food", ""),
            "recommendation_score": top.get("score", ""),
        }
        group_rows.append(group_row)
        group_summaries.append(
            {
                **group_row,
                "anonymous_members": anonymous_members,
                "shared_preferences": [
                    {"term": term, "participant_count": count}
                    for term, count in shared
                ],
            }
        )
        for rank, recommendation in enumerate(recommendations, start=1):
            recommendation_rows.append(
                {
                    "group_id": group_id,
                    "rank": rank,
                    "restaurant_name": recommendation.get("name", ""),
                    "category": recommendation.get("category", ""),
                    "food": recommendation.get("food", ""),
                    "score": recommendation.get("score", ""),
                    "distance_m": recommendation.get("distance_m", ""),
                    "walking_minutes": recommendation.get(
                        "walking_minutes", ""
                    ),
                    "review_rank": recommendation.get("review_rank", ""),
                    "matched_terms": " | ".join(
                        str(item)
                        for item in recommendation.get("matched_terms", [])
                    ),
                    "reason": recommendation.get("reason", ""),
                }
            )

    write_csv(
        output_dir / "groups.csv",
        [
            "group_id",
            "member_count",
            "anonymous_members",
            "shared_preference_count",
            "shared_preferences",
            "excluded_restaurant_count",
            "recommended_restaurant",
            "recommended_category",
            "recommended_food",
            "recommendation_score",
        ],
        group_rows,
    )
    write_csv(
        output_dir / "recommendations.csv",
        [
            "group_id",
            "rank",
            "restaurant_name",
            "category",
            "food",
            "score",
            "distance_m",
            "walking_minutes",
            "review_rank",
            "matched_terms",
            "reason",
        ],
        recommendation_rows,
    )

    generated_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "session_id": resolved_session_id,
        "privacy": {
            "participant_names_removed": True,
            "device_ids_removed": True,
            "join_url_removed": True,
            "participant_location_coordinates_removed": True,
            "anonymous_id_format": "P001",
        },
        "session": {
            "participant_count": len(participants),
            "group_count": len(groups),
            "provider": report.get("provider", ""),
            "search_location": session.get("location", ""),
            "recommendation_filters": session.get(
                "recommendation_filters", {}
            ),
            "use_exclusions": bool(session.get("use_exclusions", True)),
        },
        "aggregates": {
            "participant_source_counts": dict(source_counts),
            "preferred_category_counts": dict(category_counts.most_common()),
            "preferred_food_counts": dict(food_counts.most_common()),
            "recent_food_counts": dict(recent_counts.most_common()),
        },
        "groups": group_summaries,
    }
    (output_dir / "analysis_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "release_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "session_id": resolved_session_id,
                "default_external_files": [
                    "analysis_summary.json",
                    "groups.csv",
                    "recommendations.csv",
                    "SUBMISSION_README.md",
                ],
                "restricted_files": [
                    "participants_anonymized.csv",
                ],
                "restricted_release_conditions": [
                    "commercial third-party provision purpose was disclosed before collection",
                    "a valid legal basis or separate informed consent was confirmed",
                    "re-identification risk and small-cell disclosure were reviewed",
                    "recipient, purpose, fields, retention period, deletion, and breach response were contracted",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "SUBMISSION_README.md").write_text(
        f"""# 기업 제출용 데이터 분석 패키지

- 세션 ID: `{resolved_session_id}`
- 생성 시각(UTC): `{generated_at}`
- 참가자 수: {len(participants)}
- 그룹 수: {len(groups)}

## 파일

- `analysis_summary.json`: 세션 설정, 집계 지표, 그룹 요약
- `participants_anonymized.csv`: 익명 참가자별 선호·최근 음식·그룹
- `groups.csv`: 그룹 구성과 공통 선호 및 추천 요약
- `recommendations.csv`: 추천 식당과 점수·필터 관련 분석 필드
- `release_manifest.json`: 외부 제공 후보와 제한 자료 분류

## 개인정보 처리

이 패키지는 참가자 이름·별명, 원본 참가자 ID, 기기 UUID, 접속 URL,
제출 시각과 참가자 위치 좌표를 포함하지 않습니다. `P001` 형식의 ID는
이 패키지 내부 분석을 위한 일회성 순번이며 운영 데이터와 직접 연결할 수
있는 매핑 파일은 생성하지 않습니다.

`participants_anonymized.csv`는 참가자 단위 기록이므로 기본 외부 제공
대상이 아닙니다. 상업적 제3자 제공 목적 고지·동의 또는 다른 적법 근거,
재식별 위험 검토와 계약 검토가 끝난 경우에만 별도로 검토하세요.
""",
        encoding="utf-8",
    )
    return output_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export anonymized enterprise analytics files"
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--session-id", default="")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output_dir = export_analytics(
        load_json(args.input),
        output_root=args.output_root,
        session_id=args.session_id,
    )
    print(output_dir)


if __name__ == "__main__":
    main()
