#!/usr/bin/env python3
"""Group assignment helpers for recommendation sessions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def normalize_levels(preferences: dict[str, list[str]]) -> dict[str, list[str]]:
    high = list(preferences.get("high", []))
    low = list(preferences.get("low", []))
    if not low:
        low = list(preferences.get("mid", []))
    return {"high": [leaf_value(item) for item in high], "low": [leaf_value(item) for item in low]}


def leaf_value(value: str) -> str:
    return value.split("|")[-1] if isinstance(value, str) else value


def participant_terms(participant: dict[str, Any]) -> list[str]:
    preferences = participant.get("preferences", {})
    positive = normalize_levels(preferences.get("like", {}))
    terms = positive["high"] + positive["low"]
    return list(dict.fromkeys(terms))


def participant_similarity(first_terms: list[str], second_terms: list[str]) -> float:
    first = set(first_terms)
    second = set(second_terms)
    if not first and not second:
        return 0.0
    union = first | second
    if not union:
        return 0.0
    return len(first & second) / len(union)


def cluster_similarity(
    first_members: list[str],
    second_members: list[str],
    participant_terms_map: dict[str, list[str]],
) -> float:
    scores = [
        participant_similarity(participant_terms_map[first], participant_terms_map[second])
        for first in first_members
        for second in second_members
    ]
    return sum(scores) / len(scores) if scores else 0.0


def build_similarity_groups(participants: list[dict[str, Any]], group_count: int) -> list[dict[str, Any]]:
    if group_count <= 0:
        return []
    if not participants:
        return []

    participant_terms_map = {
        participant["user_id"]: participant_terms(participant)
        for participant in participants
    }
    clusters = [
        {"members": [participant["user_id"]], "first_index": index}
        for index, participant in enumerate(participants)
    ]
    target_count = min(group_count, len(clusters))

    while len(clusters) > target_count:
        best_pair: tuple[int, int] | None = None
        best_key: tuple[float, int, int, int, int] | None = None

        for first_index in range(len(clusters)):
            for second_index in range(first_index + 1, len(clusters)):
                first_cluster = clusters[first_index]
                second_cluster = clusters[second_index]
                similarity = cluster_similarity(
                    first_cluster["members"],
                    second_cluster["members"],
                    participant_terms_map,
                )
                combined_size = len(first_cluster["members"]) + len(second_cluster["members"])
                earliest_index = min(first_cluster["first_index"], second_cluster["first_index"])
                latest_index = max(first_cluster["first_index"], second_cluster["first_index"])
                key = (similarity, -combined_size, -earliest_index, -latest_index, -first_index)

                if best_key is None or key > best_key:
                    best_key = key
                    best_pair = (first_index, second_index)

        if best_pair is None:
            break

        first_index, second_index = best_pair
        merged = {
            "members": clusters[first_index]["members"] + clusters[second_index]["members"],
            "first_index": min(clusters[first_index]["first_index"], clusters[second_index]["first_index"]),
        }
        clusters = [
            cluster
            for index, cluster in enumerate(clusters)
            if index not in (first_index, second_index)
        ]
        clusters.append(merged)
        clusters.sort(key=lambda cluster: cluster["first_index"])

    clusters.sort(key=lambda cluster: cluster["first_index"])
    groups = [
        {"group_id": index + 1, "members": cluster["members"]}
        for index, cluster in enumerate(clusters[:group_count])
    ]
    for index in range(len(groups) + 1, group_count + 1):
        groups.append({"group_id": index, "members": []})
    return groups


def build_groups(participants: list[dict[str, Any]], group_count: int) -> list[dict[str, Any]]:
    return build_similarity_groups(participants, group_count)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build recommendation groups from session data")
    parser.add_argument("--session-file", required=True, help="Path to a session JSON file")
    parser.add_argument("--group-count", type=int, required=True, help="Number of groups to generate")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    session = load_json(Path(args.session_file))
    participants = session.get("participants", [])
    groups = build_groups(participants, args.group_count)
    print(json.dumps({"groups": groups}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
