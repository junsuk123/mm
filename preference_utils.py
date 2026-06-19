#!/usr/bin/env python3
"""Normalize and validate the food-only participant preference schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
MENU_TREE_FILE = BASE_DIR / "dataset" / "menu_categories.json"

MAIN_ALIASES = {
    "양식": "양식/이탈리안",
    "세계음식": "태국식",
}

SUBCATEGORY_ALIASES = {
    "한식": {
        "밥류": "밥/정식류",
        "국물류": "국물/탕류",
        "면류": "면/국수류",
        "구이·볶음": "구이/고기류",
        "길거리음식": "전/부침류",
    },
    "중식": {
        "면류": "면/밥류",
        "밥류": "면/밥류",
        "메인요리": "고기류",
    },
    "일식": {
        "밥류": "밥/덮밥류",
        "면류": "면류",
        "튀김류": "튀김/돈카츠류",
        "기타": "정식류",
    },
    "양식/이탈리안": {
        "파스타": "파스타/리조또류",
        "피자": "피자류",
        "고기요리": "스테이크/고기류",
        "패스트푸드": "브런치류",
    },
    "태국식": {
        "동남아": "면류",
    },
    "멕시칸": {"멕시코": "타코/부리또류"},
    "인도식": {"인도": "커리류"},
}


def load_menu_tree() -> dict[str, list[str]]:
    with MENU_TREE_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def split_path(value: Any) -> list[str]:
    return [part.strip() for part in str(value or "").split("|") if part.strip()]


def unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def migrate_main(main: str, subcategories: list[str] | None = None) -> str:
    if main == "세계음식":
        values = subcategories or []
        if "멕시코" in values:
            return "멕시칸"
        if "인도" in values:
            return "인도식"
        return "태국식"
    return MAIN_ALIASES.get(main, main)


def migrate_subcategory(main: str, subcategory: str) -> str:
    return SUBCATEGORY_ALIASES.get(main, {}).get(subcategory, subcategory)


def default_subcategories(menu_tree: dict[str, Any], main: str) -> list[str]:
    return list(menu_tree.get(main, []))[:2]


def choose_main_categories(menu_tree: dict[str, Any], requested: list[str]) -> list[str]:
    valid = unique([value for value in requested if value in menu_tree])
    menu_order = list(menu_tree)
    if valid:
        start = (menu_order.index(valid[0]) + 1) % len(menu_order)
        defaults = menu_order[start:] + menu_order[:start]
    else:
        defaults = menu_order
    for main in defaults:
        if main not in valid:
            valid.append(main)
        if len(valid) == 2:
            break
    return valid[:2]


def legacy_subcategories(preferences: dict[str, Any], main: str) -> list[str]:
    like = preferences.get("like", {})
    values = list(like.get("low", [])) + list(like.get("mid", []))
    result = []
    for value in values:
        parts = split_path(value)
        if len(parts) >= 2 and parts[0] == main:
            result.append(parts[1])
    return unique(result)


def normalize_preferences(
    preferences: dict[str, Any] | None,
    menu_tree: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the new schema, filling old/incomplete saved records with safe defaults."""
    menu_tree = menu_tree or load_menu_tree()
    preferences = preferences or {}

    preferred_input = preferences.get("preferred")
    if isinstance(preferred_input, list):
        migrated_preferred = []
        for item in preferred_input:
            if not isinstance(item, dict):
                continue
            raw_subcategories = [str(value) for value in item.get("subcategories", [])]
            main = migrate_main(str(item.get("main", "")), raw_subcategories)
            migrated_preferred.append(
                {
                    "main": main,
                    "subcategories": [
                        migrate_subcategory(main, value)
                        for value in raw_subcategories
                    ],
                }
            )
        preferred_input = migrated_preferred
        requested_mains = [item["main"] for item in preferred_input]
    else:
        requested_mains = [
            split_path(value)[0]
            for value in preferences.get("like", {}).get("high", [])
            if split_path(value)
        ]

    mains = choose_main_categories(menu_tree, requested_mains)
    preferred = []
    for main in mains:
        matching = next(
            (
                item
                for item in preferred_input or []
                if isinstance(item, dict) and item.get("main") == main
            ),
            {},
        )
        subcategories = unique(
            [
                str(value)
                for value in matching.get("subcategories", [])
                if str(value) in menu_tree.get(main, [])
            ]
        )
        if not subcategories:
            subcategories = legacy_subcategories(preferences, main)
        for default in default_subcategories(menu_tree, main):
            if default not in subcategories:
                subcategories.append(default)
            if len(subcategories) == 2:
                break
        preferred.append({"main": main, "subcategories": subcategories[:2]})

    recent_input = preferences.get("recent", {})
    recent_subcategory = str(recent_input.get("subcategory", ""))
    recent_main = migrate_main(str(recent_input.get("main", "")), [recent_subcategory])
    recent_subcategory = migrate_subcategory(recent_main, recent_subcategory)
    if recent_main not in menu_tree:
        legacy_high = recent_input.get("high", [])
        recent_main = split_path(legacy_high[0])[0] if legacy_high else mains[0]
    if recent_subcategory not in menu_tree.get(recent_main, []):
        legacy_values = list(recent_input.get("low", [])) + list(recent_input.get("mid", []))
        parts = split_path(legacy_values[0]) if legacy_values else []
        recent_subcategory = (
            parts[1]
            if len(parts) >= 2 and parts[0] == recent_main
            else default_subcategories(menu_tree, recent_main)[0]
        )

    return {
        "recent": {"main": recent_main, "subcategory": recent_subcategory},
        "preferred": preferred,
    }


def validate_preferences(
    preferences: dict[str, Any],
    menu_tree: dict[str, Any] | None = None,
) -> list[str]:
    menu_tree = menu_tree or load_menu_tree()
    errors: list[str] = []
    recent = preferences.get("recent", {})
    preferred = preferences.get("preferred", [])

    recent_main = recent.get("main")
    recent_subcategory = recent.get("subcategory")
    if recent_main not in menu_tree:
        errors.append("Select a valid recently eaten main category.")
    elif recent_subcategory not in menu_tree[recent_main]:
        errors.append("Select a valid recently eaten subcategory.")

    if not isinstance(preferred, list) or len(preferred) != 2:
        errors.append("Select exactly two preferred main categories.")
        return errors

    mains = [item.get("main") for item in preferred if isinstance(item, dict)]
    if len(mains) != 2 or len(set(mains)) != 2:
        errors.append("Preferred main categories must be two different categories.")

    for index, item in enumerate(preferred, start=1):
        main = item.get("main") if isinstance(item, dict) else None
        subcategories = item.get("subcategories", []) if isinstance(item, dict) else []
        if main not in menu_tree:
            errors.append(f"Preferred category {index} is invalid.")
            continue
        if len(subcategories) != 2 or len(set(subcategories)) != 2:
            errors.append(f"Select exactly two different subcategories for {main}.")
        elif any(value not in menu_tree[main] for value in subcategories):
            errors.append(f"One or more subcategories for {main} are invalid.")
    return errors


def normalize_participant(
    participant: dict[str, Any],
    menu_tree: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = dict(participant)
    normalized["preferences"] = normalize_preferences(
        participant.get("preferences", {}),
        menu_tree,
    )
    return normalized


def normalize_session(session: dict[str, Any]) -> dict[str, Any]:
    menu_tree = load_menu_tree()
    normalized = dict(session)
    normalized["participants"] = [
        normalize_participant(participant, menu_tree)
        for participant in session.get("participants", [])
    ]
    normalized["participant_count"] = len(normalized["participants"])
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize a recommendation session")
    parser.add_argument("--session-file", required=True)
    args = parser.parse_args()
    with Path(args.session_file).open("r", encoding="utf-8") as file:
        session = json.load(file)
    print(json.dumps(normalize_session(session), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
