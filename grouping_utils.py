#!/usr/bin/env python3
"""Group assignment helpers for recommendation sessions."""

from __future__ import annotations

import argparse
import json
from collections import Counter
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


def build_similarity_groups(participants: list[dict[str, Any]], group_count: int) -> list[dict[str, Any]] | None:
    if group_count <= 0:
        return None

    participant_terms_map = {
        participant["user_id"]: participant_terms(participant)
        for participant in participants
    }
    term_frequency = Counter(term for terms in participant_terms_map.values() for term in terms)
    seed_terms = [term for term, _ in term_frequency.most_common(group_count)]

    if len(seed_terms) < group_count:
        return None

    groups = {index: [] for index in range(1, group_count + 1)}
    ordered_participants = sorted(
        participants,
        key=lambda item: (-len(participant_terms_map[item["user_id"]]), item["user_id"]),
    )

    for participant in ordered_participants:
        user_id = participant["user_id"]
        terms = set(participant_terms_map[user_id])
        best_group = None
        best_score = -1

        for group_index, seed_term in enumerate(seed_terms, start=1):
            score = 1 if seed_term in terms else 0
            if score > best_score:
                best_group = group_index
                best_score = score
            elif score == best_score and best_group is not None and len(groups[group_index]) < len(groups[best_group]):
                best_group = group_index

        if best_group is None or best_score <= 0:
            return None

        groups[best_group].append(user_id)

    if any(not members for members in groups.values()):
        return None

    return [{"group_id": index, "members": members} for index, members in groups.items()]


def build_common_term_groups(participants: list[dict[str, Any]], group_count: int) -> list[dict[str, Any]]:
    if group_count <= 0:
        return []

    participant_entries = []
    term_frequency = Counter()
    for participant in participants:
        terms = participant_terms(participant)
        term_frequency.update(terms)
        participant_entries.append((participant["user_id"], terms))

    dominant_term = term_frequency.most_common(1)[0][0] if term_frequency else None

    def sort_key(item: tuple[str, list[str]]) -> tuple[int, int, str]:
        user_id, terms = item
        return (
            0 if dominant_term and dominant_term in terms else 1,
            -len(terms),
            user_id,
        )

    ordered_participants = sorted(participant_entries, key=sort_key)
    groups = {index: [] for index in range(1, group_count + 1)}

    for index, (user_id, _) in enumerate(ordered_participants):
        group_index = (index % group_count) + 1
        groups[group_index].append(user_id)

    return [{"group_id": index, "members": members} for index, members in groups.items()]


def build_groups(participants: list[dict[str, Any]], group_count: int) -> list[dict[str, Any]]:
    groups = build_similarity_groups(participants, group_count)
    if groups is not None:
        return groups
    return build_common_term_groups(participants, group_count)


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
