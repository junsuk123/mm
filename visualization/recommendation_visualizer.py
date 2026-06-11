#!/usr/bin/env python3
"""Render a recommendation session report as a standalone HTML visualization.

This script is intentionally isolated from the shell-based recommendation flow so it can be
removed later without affecting the main CLI.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
DATASET_DIR = BASE_DIR / "dataset"

# naver_restaurant_api.py가 프로젝트 루트 또는 visualization 폴더 기준으로 import 되도록 보완
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from naver_restaurant_api import search_restaurants
except Exception:  # 데모/시각화만 볼 때 API 모듈이 없어도 HTML 생성이 가능하도록 처리
    search_restaurants = None

LEVELS = ("high", "low")
PREFERENCE_GROUPS = ("like", "dislike", "recent")


@dataclass(frozen=True)
class CandidateView:
    restaurant_id: str
    name: str
    food: str
    category: str
    location: str
    address: str
    link: str
    score: float
    matched_terms: list[str]


def load_json(path: Path) -> Any:
    """Load the first JSON object from a file.

    데모 실행 중 실수로 JSON이 두 번 붙거나 뒤쪽에 로그가 섞인 경우에도
    첫 번째 JSON 객체만 읽어 시각화가 중단되지 않도록 한다.
    """
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"입력 JSON 파일이 비어 있습니다: {path}")

    decoder = json.JSONDecoder()
    obj, end = decoder.raw_decode(text.lstrip())
    extra = text.lstrip()[end:].strip()
    if extra:
        print(
            f"[warning] 입력 파일 뒤에 추가 데이터가 있어 첫 번째 JSON 객체만 사용합니다: {path}",
            file=sys.stderr,
        )
    return obj


def unique_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def split_menu_path(value: str) -> list[str]:
    return [part.strip() for part in str(value).split("|") if part.strip()]


def menu_leaf(value: str) -> str:
    parts = split_menu_path(value)
    return parts[-1] if parts else str(value)


def menu_path_label(value: str, level: str) -> str:
    parts = split_menu_path(value)
    if not parts:
        return str(value)
    if level == "high":
        return parts[0]
    if level == "low":
        return " > ".join(parts[:2]) if len(parts) >= 2 else parts[0]
    return " > ".join(parts)


def normalize_preference_levels(preferences: dict[str, list[str]]) -> dict[str, list[str]]:
    high = list(preferences.get("high", []))
    low = list(preferences.get("low", []))
    if not low:
        low = list(preferences.get("mid", []))
    return {"high": high, "low": low}


def flatten_preferences(preferences: dict[str, dict[str, list[str]]]) -> dict[str, list[str]]:
    normalized = {
        group: normalize_preference_levels(preferences.get(group, {}))
        for group in PREFERENCE_GROUPS
    }
    return {
        group: [
            menu_leaf(item)
            for level in LEVELS
            for item in normalized[group].get(level, [])
        ]
        for group in PREFERENCE_GROUPS
    }


def preference_overlap_report(preferences: dict[str, dict[str, list[str]]]) -> list[dict[str, Any]]:
    term_locations: dict[str, set[str]] = defaultdict(set)
    normalized = {
        group: normalize_preference_levels(preferences.get(group, {}))
        for group in PREFERENCE_GROUPS
    }

    for group in PREFERENCE_GROUPS:
        for level in LEVELS:
            for value in normalized[group].get(level, []):
                path_parts = split_menu_path(value)
                for index, part in enumerate(path_parts):
                    path_level = "high" if index == 0 else "low"
                    term_locations[part].add(f"{group}.{level}.{path_level}")

    overlaps: list[dict[str, Any]] = []
    for term, locations in sorted(term_locations.items()):
        if len(locations) > 1:
            overlaps.append({"term": term, "locations": sorted(locations)})
    return overlaps


def build_group_members(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        participant["user_id"]: participant
        for participant in report.get("participants", [])
        if "user_id" in participant
    }


def build_group_profile(members: list[dict[str, Any]]) -> dict[str, list[str]]:
    combined = {"positive": [], "dislike": [], "recent": []}
    for member in members:
        preferences = flatten_preferences(member.get("preferences", {}))
        combined["positive"].extend(preferences["like"])
        combined["dislike"].extend(preferences["dislike"])
        combined["recent"].extend(preferences["recent"])
    return {key: unique_preserve(values) for key, values in combined.items()}


def score_restaurant(restaurant: dict[str, Any], profile: dict[str, list[str]]) -> float:
    positive = profile["positive"]
    recent = profile["recent"]

    pref_match = 0.0
    if restaurant.get("category") in positive:
        pref_match += 0.5
    if restaurant.get("food") in positive:
        pref_match += 0.3
    if restaurant.get("category") in recent or restaurant.get("food") in recent:
        pref_match -= 0.5
    if restaurant.get("category") in profile.get("dislike", []):
        pref_match -= 0.8
    if restaurant.get("food") in profile.get("dislike", []):
        pref_match -= 1.0

    return pref_match


def candidate_restaurants(profile: dict[str, list[str]], location: str) -> list[CandidateView]:
    if os.environ.get("MM_VISUALIZER_SKIP_LIVE") == "1" or search_restaurants is None:
        return []

    search_terms = unique_preserve(profile["positive"] + profile["recent"])
    restaurants = search_restaurants(search_terms, location)
    candidates: list[CandidateView] = []

    for restaurant in restaurants:
        matched_terms = [
            term
            for term in search_terms
            if term in restaurant.get("matched_terms", [])
            or term == restaurant.get("food")
            or term == restaurant.get("category")
        ]
        if not matched_terms:
            continue

        candidates.append(
            CandidateView(
                restaurant_id=str(restaurant.get("restaurant_id", "")),
                name=str(restaurant.get("name", "")),
                food=str(restaurant.get("food", "")),
                category=str(restaurant.get("category", "")),
                location=str(restaurant.get("location", location)),
                address=str(restaurant.get("roadAddress") or restaurant.get("address", "")),
                link=str(restaurant.get("link", "")),
                score=score_restaurant(restaurant, profile),
                matched_terms=matched_terms,
            )
        )

    return sorted(candidates, key=lambda item: item.score, reverse=True)


def group_shared_terms(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    term_members: dict[str, set[str]] = defaultdict(set)
    for member in members:
        user_id = member.get("user_id", "")
        preferences = flatten_preferences(member.get("preferences", {}))
        for group in PREFERENCE_GROUPS:
            for value in preferences[group]:
                term_members[value].add(user_id)

    shared_terms: list[dict[str, Any]] = []
    for term, user_ids in sorted(term_members.items()):
        if len(user_ids) > 1:
            shared_terms.append({"term": term, "members": sorted(user_ids)})
    return shared_terms


def score_bar_width(score: float, max_score: float) -> float:
    if max_score <= 0:
        return 8.0
    return max(8.0, min(100.0, (score / max_score) * 100.0))


def render_tag_list(items: list[str]) -> str:
    if not items:
        return '<span class="muted">없음</span>'
    return "".join(f'<span class="tag">{html.escape(str(item))}</span>' for item in items)


def render_path_tag_list(items: list[str], level: str) -> str:
    if not items:
        return '<span class="muted">없음</span>'
    return "".join(
        f'<span class="tag">{html.escape(menu_path_label(str(item), level))}</span>'
        for item in items
    )


def render_level_card(title: str, items: list[str]) -> str:
    level = {"대분류": "high", "소분류": "low"}.get(title, "low")
    return f"""
    <div class="level-card">
      <div class="level-title">{html.escape(title)}</div>
      <div class="tags">{render_path_tag_list(items, level)}</div>
    </div>
    """


def render_participant_section(participant: dict[str, Any]) -> str:
    preferences = participant.get("preferences", {})
    overlaps = preference_overlap_report(preferences)

    if overlaps:
        overlap_rows = "".join(
            f"<li><strong>{html.escape(item['term'])}</strong> "
            f"<span class='muted'>({html.escape(', '.join(item['locations']))})</span></li>"
            for item in overlaps
        )
        overlap_html = f"""
        <div class="callout">
            <div class="callout-title">겹치는 분류명</div>
            <ul class="tight-list">{overlap_rows}</ul>
        </div>
        """
    else:
        overlap_html = "<div class='callout muted'>겹치는 항목 없음</div>"

    sections = []
    for group in PREFERENCE_GROUPS:
        levels = normalize_preference_levels(preferences.get(group, {}))
        sections.append(
            f"""
            <section class="group-block">
                <h4>{html.escape(group.upper())}</h4>
                {render_level_card('대분류', levels.get('high', []))}
                {render_level_card('소분류', levels.get('low', []))}
            </section>
            """
        )

    return f"""
    <article class="panel">
        <div class="panel-head">
            <h3>{html.escape(str(participant.get('user_id', 'UNKNOWN')))}</h3>
            <div class="muted">사용자 입력 단계 시각화</div>
        </div>
        <div class="participant-grid">
            {''.join(sections)}
        </div>
        {overlap_html}
    </article>
    """


def render_candidate_table(candidates: list[CandidateView]) -> str:
    if not candidates:
        return '<div class="callout muted">후보 식당이 없습니다.</div>'

    rows = []
    for index, candidate in enumerate(candidates, start=1):
        rows.append(
            f"""
            <tr>
              <td>{index}</td>
              <td>{html.escape(candidate.restaurant_id)}</td>
              <td>{html.escape(candidate.name)}</td>
              <td>{html.escape(candidate.food)}</td>
              <td>{html.escape(candidate.category)}</td>
              <td>{candidate.score:.3f}</td>
              <td>{html.escape(candidate.address)}</td>
              <td>{render_tag_list(candidate.matched_terms)}</td>
            </tr>
            """
        )

    return f"""
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>ID</th>
            <th>이름</th>
            <th>메뉴</th>
            <th>카테고리</th>
            <th>점수</th>
            <th>주소</th>
            <th>매칭 항목</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows)}
        </tbody>
      </table>
    </div>
    """


def get_item_address(item: dict[str, Any]) -> str:
    return str(item.get("roadAddress") or item.get("address") or item.get("location") or "")


def render_final_cards(finals: list[dict[str, Any]]) -> str:
    if not finals:
        return '<div class="callout muted">최종 식당이 없습니다.</div>'

    max_score = max(float(item.get("score", 0)) for item in finals)
    cards = []
    for index, item in enumerate(finals, start=1):
        score = float(item.get("score", 0))
        width = score_bar_width(score, max_score)
        cards.append(
            f"""
            <div class="final-card">
              <div class="final-rank">TOP {index}</div>
              <div class="final-name">{html.escape(str(item.get('name', '')))}</div>
              <div class="final-meta">{html.escape(str(item.get('food', '')))} · {html.escape(str(item.get('category', '')))}</div>
              <div class="score-bar"><span style="width: {width:.1f}%"></span></div>
              <div class="final-footer">
                <span>점수 {score:.3f}</span>
                <span>{html.escape(get_item_address(item))}</span>
              </div>
              <div class="reason">{html.escape(str(item.get('reason', '')))}</div>
            </div>
            """
        )

    return f'<div class="final-grid">{"".join(cards)}</div>'


def render_network_label(text: str, max_chars: int = 16) -> str:
    clean = str(text)
    if len(clean) > max_chars:
        clean = clean[: max_chars - 1] + "…"
    return html.escape(clean)


def render_recommendation_network(report: dict[str, Any]) -> str:
    groups = report.get("groups", [])
    if not groups:
        return '<div class="callout muted">시각화할 그룹 데이터가 없습니다.</div>'

    row_height = 210
    top_pad = 56
    bottom_pad = 44
    width = 1120
    height = max(320, top_pad + bottom_pad + row_height * len(groups))
    participant_x = 170
    group_x = 555
    restaurant_x = 930

    svg_parts = [
        f'<svg class="network-svg" viewBox="0 0 {width} {height}" role="img" aria-label="Group recommendation network diagram">',
        """
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" class="arrow-head"></path>
          </marker>
        </defs>
        """,
        '<text x="170" y="30" class="network-axis">Participants</text>',
        '<text x="555" y="30" class="network-axis">Groups</text>',
        '<text x="930" y="30" class="network-axis">Top 3 Restaurants</text>',
    ]

    for group_index, group in enumerate(groups):
        row_y = top_pad + group_index * row_height
        center_y = row_y + 92
        members = list(group.get("members", []))
        recommendations = list(group.get("recommendations", []))[:3]
        participant_gap = 42
        restaurant_gap = 54
        participant_start = center_y - ((len(members) - 1) * participant_gap / 2)
        restaurant_start = center_y - ((len(recommendations) - 1) * restaurant_gap / 2)

        svg_parts.append(f'<line x1="70" y1="{row_y + row_height - 8}" x2="1050" y2="{row_y + row_height - 8}" class="network-row-line"></line>')
        svg_parts.append(f'<circle cx="{group_x}" cy="{center_y}" r="38" class="network-node group-node"></circle>')
        svg_parts.append(f'<text x="{group_x}" y="{center_y - 4}" class="network-group-title">G{html.escape(str(group.get("group_id", "")))}</text>')
        svg_parts.append(f'<text x="{group_x}" y="{center_y + 16}" class="network-group-sub">{len(members)}명</text>')

        for member_index, member in enumerate(members):
            member_y = participant_start + member_index * participant_gap
            svg_parts.append(f'<line x1="{participant_x + 58}" y1="{member_y}" x2="{group_x - 42}" y2="{center_y}" class="network-edge member-edge"></line>')
            svg_parts.append(f'<circle cx="{participant_x}" cy="{member_y}" r="21" class="network-node member-node"></circle>')
            svg_parts.append(f'<text x="{participant_x}" y="{member_y + 5}" class="network-member-label">{render_network_label(member, 8)}</text>')

        for rec_index, recommendation in enumerate(recommendations):
            rec_y = restaurant_start + rec_index * restaurant_gap
            score = float(recommendation.get("score", 0) or 0)
            edge_class = "top-edge" if rec_index == 0 else "restaurant-edge"
            rank = rec_index + 1
            svg_parts.append(f'<line x1="{group_x + 42}" y1="{center_y}" x2="{restaurant_x - 86}" y2="{rec_y}" class="network-edge {edge_class}" marker-end="url(#arrow)"></line>')
            svg_parts.append(f'<rect x="{restaurant_x - 78}" y="{rec_y - 23}" width="172" height="46" rx="10" class="network-node restaurant-node rank-{rank}"></rect>')
            svg_parts.append(f'<text x="{restaurant_x - 66}" y="{rec_y - 5}" class="network-restaurant-name">#{rank} {render_network_label(recommendation.get("name", ""), 14)}</text>')
            svg_parts.append(f'<text x="{restaurant_x - 66}" y="{rec_y + 14}" class="network-restaurant-meta">{render_network_label(recommendation.get("category", ""), 8)} · {score:.1f}</text>')

    svg_parts.append("</svg>")
    return f"""
    <section class="section">
      <h2>Recommendation Network</h2>
      <div class="network-panel">
        {''.join(svg_parts)}
      </div>
    </section>
    """


def render_group_section(group: dict[str, Any], report: dict[str, Any], members_by_id: dict[str, dict[str, Any]]) -> str:
    members = [
        members_by_id[user_id]
        for user_id in group.get("members", [])
        if user_id in members_by_id
    ]
    profile = build_group_profile(members)
    finals = group.get("recommendations", [])
    preferred_tags = render_tag_list(profile["positive"][:6])
    recent_tags = render_tag_list(profile["recent"][:4])
    dislike_tags = render_tag_list(profile["dislike"][:4])
    members_text = html.escape(", ".join(group.get("members", [])))

    profile_html = f"""
    <div class="profile-summary">
      <div><strong>멤버</strong>: {members_text}</div>
      <div><strong>선호 핵심</strong>: {preferred_tags}</div>
      <div><strong>피하고 싶은 메뉴</strong>: {dislike_tags}</div>
      <div><strong>최근 먹은 메뉴</strong>: {recent_tags}</div>
    </div>
    """

    return f"""
    <article class="panel">
      <div class="panel-head">
        <h3>그룹 {html.escape(str(group.get('group_id', '')))}</h3>
        <div class="muted">인원 {len(group.get('members', []))}명</div>
      </div>
      {profile_html}
      <h4 class="mini-heading">Recommendation Reasons</h4>
      {render_final_cards(finals[:3])}
    </article>
    """


def top_counts(items: list[str], limit: int = 5) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        if item:
            counts[item] += 1
    return [f"{name} {count}회" for name, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]]


def business_insight(report: dict[str, Any]) -> dict[str, list[str] | int]:
    recommended_categories: list[str] = []
    preferred_categories: list[str] = []
    recent_categories: list[str] = []
    avoided_categories: list[str] = []

    for group in report.get("groups", []):
        for item in group.get("recommendations", []):
            recommended_categories.append(str(item.get("category", "")))

    for participant in report.get("participants", []):
        preferences = participant.get("preferences", {})
        for value in normalize_preference_levels(preferences.get("like", {})).get("high", []):
            preferred_categories.append(menu_leaf(str(value)))
        for value in normalize_preference_levels(preferences.get("recent", {})).get("high", []):
            recent_categories.append(menu_leaf(str(value)))
        for value in normalize_preference_levels(preferences.get("dislike", {})).get("high", []):
            avoided_categories.append(menu_leaf(str(value)))

    return {
        "recommended": top_counts(recommended_categories),
        "preferred": top_counts(preferred_categories),
        "recent": top_counts(recent_categories),
        "avoided": top_counts(avoided_categories),
        "participants": int(report.get("session", {}).get("participant_count") or len(report.get("participants", []))),
    }


def render_business_insight_report(report: dict[str, Any]) -> str:
    insight = business_insight(report)
    return f"""
    <section class="section">
      <h2>Business Insight Report</h2>
      <div class="insight-grid">
        <div class="insight-item"><strong>Most recommended categories</strong><div class="tags">{render_tag_list(insight['recommended'])}</div></div>
        <div class="insight-item"><strong>Most preferred categories</strong><div class="tags">{render_tag_list(insight['preferred'])}</div></div>
        <div class="insight-item"><strong>Recently eaten categories</strong><div class="tags">{render_tag_list(insight['recent'])}</div></div>
        <div class="insight-item"><strong>Avoided categories</strong><div class="tags">{render_tag_list(insight['avoided'])}</div></div>
        <div class="insight-item"><strong>Estimated total participants</strong><div class="big-number">{html.escape(str(insight['participants']))}</div></div>
      </div>
    </section>
    """


def render_flow(report: dict[str, Any]) -> str:
    session = report.get("session", {})
    return f"""
    <section class="flow">
      <div class="flow-step"><div class="flow-number">1</div><div class="flow-title">사용자 입력 수집</div><div class="muted">참가자 {session.get('participant_count', 0)}명</div></div>
      <div class="flow-arrow">→</div>
      <div class="flow-step"><div class="flow-number">2</div><div class="flow-title">그룹 구성</div><div class="muted">그룹 {session.get('group_count', 0)}개</div></div>
      <div class="flow-arrow">→</div>
      <div class="flow-step"><div class="flow-number">3</div><div class="flow-title">후보 식당 생성</div><div class="muted">선호/최근 메뉴 기준</div></div>
      <div class="flow-arrow">→</div>
      <div class="flow-step"><div class="flow-number">4</div><div class="flow-title">Top 3 선정</div><div class="muted">점수 상위 3곳</div></div>
    </section>
    """


def render_html(report: dict[str, Any]) -> str:
    members_by_id = build_group_members(report)
    title = "식당 추천 결과 요약"
    provider = html.escape(str(report.get("provider", "naver")))
    session = report.get("session", {})
    session_meta = (
        f"참가자 {session.get('participant_count', 0)}명 · "
        f"그룹 {session.get('group_count', 0)}개 · "
        f"위치 {html.escape(str(session.get('location', '서울')))}"
    )

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6efe7;
      --panel: #fffaf2;
      --ink: #1e1a17;
      --muted: #6d6257;
      --line: #d9c8b7;
      --accent: #a95f2e;
      --accent-2: #6b8e23;
      --soft: #f1e3d5;
      --shadow: 0 18px 50px rgba(63, 41, 24, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Georgia, "Times New Roman", serif; background: radial-gradient(circle at top, #fff8f0 0%, var(--bg) 42%, #ead8c5 100%); color: var(--ink); }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 28px 18px 60px; }}
    header {{ padding: 24px; background: linear-gradient(135deg, rgba(255,255,255,0.88), rgba(255,250,242,0.72)); border: 1px solid var(--line); border-radius: 28px; box-shadow: var(--shadow); }}
    h1, h2, h3, h4 {{ margin: 0; }}
    h1 {{ font-size: clamp(2rem, 4vw, 3.4rem); letter-spacing: -0.03em; }}
    .subtitle {{ margin-top: 10px; color: var(--muted); font-size: 1rem; line-height: 1.6; }}
    .badge-row {{ margin-top: 16px; display: flex; gap: 10px; flex-wrap: wrap; }}
    .badge {{ background: #fff; border: 1px solid var(--line); border-radius: 999px; padding: 8px 14px; font-size: 0.92rem; color: var(--muted); }}
    .section {{ margin-top: 26px; }}
    .section h2 {{ margin-bottom: 14px; font-size: 1.45rem; }}
    .flow {{ display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 10px; align-items: center; }}
    .flow-step {{ background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 16px; box-shadow: var(--shadow); min-height: 120px; }}
    .flow-number {{ width: 30px; height: 30px; border-radius: 999px; display: grid; place-items: center; background: var(--accent); color: #fff; font-weight: 700; margin-bottom: 12px; }}
    .flow-title {{ font-weight: 700; font-size: 1.02rem; margin-bottom: 6px; }}
    .flow-arrow {{ text-align: center; color: var(--accent); font-size: 2rem; font-weight: 700; }}
    .panel {{ margin-top: 18px; background: rgba(255,255,255,0.88); border: 1px solid var(--line); border-radius: 24px; padding: 20px; box-shadow: var(--shadow); }}
    .panel-head {{ display: flex; justify-content: space-between; gap: 18px; flex-wrap: wrap; align-items: baseline; margin-bottom: 16px; }}
    .muted {{ color: var(--muted); }}
    .tags {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .tag {{ background: var(--soft); border: 1px solid #dfc2a8; border-radius: 999px; padding: 5px 10px; font-size: 0.88rem; }}
    .profile-summary {{ display: grid; gap: 8px; margin-bottom: 10px; }}
    .final-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px; margin-top: 10px; }}
    .final-card {{ background: linear-gradient(180deg, #fffaf3, #fff); border: 1px solid var(--line); border-radius: 20px; padding: 16px; }}
    .final-rank {{ color: var(--accent-2); font-weight: 700; font-size: 0.9rem; letter-spacing: 0.04em; }}
    .final-name {{ margin-top: 8px; font-size: 1.15rem; font-weight: 700; }}
    .final-meta {{ margin-top: 6px; color: var(--muted); }}
    .score-bar {{ margin-top: 14px; width: 100%; height: 12px; border-radius: 999px; background: #eadfcd; overflow: hidden; }}
    .score-bar span {{ display: block; height: 100%; background: linear-gradient(90deg, var(--accent), #d49b5b); border-radius: 999px; }}
    .final-footer {{ margin-top: 10px; display: flex; justify-content: space-between; gap: 8px; color: var(--muted); font-size: 0.92rem; }}
    .reason {{ margin-top: 10px; color: var(--muted); font-size: 0.9rem; line-height: 1.45; }}
    .mini-heading {{ margin-top: 16px; margin-bottom: 8px; font-size: 1rem; color: var(--accent); }}
    .insight-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }}
    .insight-item {{ background: rgba(255,255,255,0.88); border: 1px solid var(--line); border-radius: 18px; padding: 16px; box-shadow: var(--shadow); }}
    .insight-item strong {{ display: block; margin-bottom: 10px; }}
    .big-number {{ font-size: 2rem; font-weight: 700; color: var(--accent); }}
    .network-panel {{ background: rgba(255,255,255,0.88); border: 1px solid var(--line); border-radius: 24px; padding: 12px; box-shadow: var(--shadow); overflow-x: auto; }}
    .network-svg {{ display: block; width: 100%; min-width: 880px; height: auto; }}
    .network-axis {{ text-anchor: middle; fill: var(--muted); font-size: 14px; font-weight: 700; }}
    .network-row-line {{ stroke: rgba(217, 200, 183, 0.65); stroke-width: 1; }}
    .network-edge {{ fill: none; stroke-width: 2.4; opacity: 0.88; }}
    .member-edge {{ stroke: #6c8a92; }}
    .restaurant-edge {{ stroke: #b9824f; }}
    .top-edge {{ stroke: var(--accent-2); stroke-width: 3.4; }}
    .arrow-head {{ fill: #b9824f; }}
    .network-node {{ filter: drop-shadow(0 8px 12px rgba(63, 41, 24, 0.12)); }}
    .member-node {{ fill: #e8f4f2; stroke: #6c8a92; stroke-width: 2; }}
    .group-node {{ fill: #fff4dd; stroke: var(--accent); stroke-width: 3; }}
    .restaurant-node {{ fill: #fffaf3; stroke: #d9c8b7; stroke-width: 2; }}
    .restaurant-node.rank-1 {{ stroke: var(--accent-2); stroke-width: 3; }}
    .network-member-label, .network-group-title, .network-group-sub, .network-restaurant-name, .network-restaurant-meta {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .network-member-label {{ text-anchor: middle; fill: #25454d; font-size: 13px; font-weight: 700; }}
    .network-group-title {{ text-anchor: middle; fill: var(--accent); font-size: 18px; font-weight: 800; }}
    .network-group-sub {{ text-anchor: middle; fill: var(--muted); font-size: 12px; }}
    .network-restaurant-name {{ fill: var(--ink); font-size: 13px; font-weight: 800; }}
    .network-restaurant-meta {{ fill: var(--muted); font-size: 12px; }}
    @media (max-width: 1080px) {{
      .flow {{ grid-template-columns: 1fr; }}
      .flow-arrow {{ transform: rotate(90deg); }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{title}</h1>
      <div class="subtitle">그룹별 최종 추천 결과를 한눈에 볼 수 있는 요약 화면입니다. 세부 후보 분석은 자동 화면에서 제외해 가독성을 높였습니다.</div>
      <div class="badge-row">
        <span class="badge">Provider: {provider}</span>
        <span class="badge">{html.escape(session_meta)}</span>
      </div>
    </header>

    <section class="section">
      <h2>선정 흐름</h2>
      {render_flow(report)}
    </section>
    {render_recommendation_network(report)}

    <section class="section">
      <h2>Group Recommendation Results</h2>
      {''.join(render_group_section(group, report, members_by_id) for group in report.get('groups', []))}
    </section>
    {render_business_insight_report(report)}
  </main>
</body>
</html>
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a recommendation report as HTML")
    parser.add_argument("--input", required=True, help="Path to the JSON report produced by recommend.sh")
    parser.add_argument("--output", help="Path to the HTML file to write; defaults to stdout")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    report = load_json(Path(args.input))
    html_output = render_html(report)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(html_output, encoding="utf-8")
    else:
        print(html_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
