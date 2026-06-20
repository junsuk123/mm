#!/usr/bin/env python3
"""Naver local search helper for restaurant recommendations."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

NAVER_LOCAL_API_URL = "https://openapi.naver.com/v1/search/local.json"
DEFAULT_DISPLAY = 5
DEFAULT_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "lGUa_EkwRbpimNJxGp5i")
DEFAULT_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "i_JWpEJez1")
WALKING_ROUTE_FACTOR = 1.25
WALKING_METERS_PER_MINUTE = 80

RESTAURANT_TOP_CATEGORIES = {
    "음식점",
    "한식",
    "중식",
    "양식",
    "일식",
    "세계음식",
    "분식",
    "치킨",
    "패스트푸드",
    "족발,보쌈",
    "찜닭",
    "곱창,막창",
    "고기요리",
    "해물,생선",
    "돈까스,우동",
    "샌드위치",
    "도시락",
    "죽",
    "술집",
}

NON_RESTAURANT_LEAF_CATEGORIES = {
    "가공식품",
    "식자재",
    "식품",
    "유통",
    "판매",
    "도매",
    "마트",
    "슈퍼",
    "편의점",
    "온라인쇼핑",
    "가전제품",
}


TAG_RE = re.compile(r"<[^>]+>")


def strip_html(value: str) -> str:
    return TAG_RE.sub("", html.unescape(str(value))).strip()


def top_category(raw_category: str) -> str:
    text = str(raw_category or "").strip()
    if not text:
        return ""
    return text.split(">", 1)[0].strip()


def leaf_category(raw_category: str) -> str:
    text = str(raw_category or "").strip()
    if not text:
        return ""
    return text.split(">")[-1].strip()


def canonical_category(raw_category: str) -> str:
    parts = [part.strip() for part in str(raw_category or "").split(">") if part.strip()]
    if not parts:
        return ""
    if parts[0] == "음식점" and len(parts) > 1:
        return parts[-1]
    return parts[0]


def is_restaurant_category(raw_category: str) -> bool:
    parts = [part.strip() for part in str(raw_category or "").split(">") if part.strip()]
    if not parts:
        return False

    top = parts[0]
    leaf = parts[-1]

    if leaf in NON_RESTAURANT_LEAF_CATEGORIES:
        return False
    if top in {"쇼핑,유통", "가정,생활", "생활편의", "부동산", "공공,행정", "병원,의료", "금융", "교육", "문화,예술", "전문,기술", "제조업", "자동차", "숙박", "여행", "스포츠,오락", "기업"}:
        return False

    return top in RESTAURANT_TOP_CATEGORIES


def restaurant_id(item: dict[str, Any]) -> str:
    seed = "|".join(
        [
            strip_html(item.get("title", "")),
            str(item.get("address", "")),
            str(item.get("roadAddress", "")),
            str(item.get("link", "")),
        ]
    )
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def fetch_local_results(
    query: str,
    display: int = DEFAULT_DISPLAY,
    client_id: str | None = None,
    client_secret: str | None = None,
    sort: str = "random",
) -> list[dict[str, Any]]:
    if not query.strip():
        return []

    client_id = client_id or DEFAULT_CLIENT_ID
    client_secret = client_secret or DEFAULT_CLIENT_SECRET
    request_url = f"{NAVER_LOCAL_API_URL}?{urlencode({'query': query, 'display': display, 'start': 1, 'sort': sort})}"
    request = Request(request_url)
    request.add_header("X-Naver-Client-Id", client_id)
    request.add_header("X-Naver-Client-Secret", client_secret)

    with urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))

    return payload.get("items", [])


def coordinate(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if abs(number) > 1000:
        number /= 10_000_000
    return number


def haversine_distance_m(
    first: tuple[float, float] | None,
    second: tuple[float, float] | None,
) -> int | None:
    if first is None or second is None:
        return None
    first_lng, first_lat = first
    second_lng, second_lat = second
    radius_m = 6_371_000
    lat_delta = math.radians(second_lat - first_lat)
    lng_delta = math.radians(second_lng - first_lng)
    value = (
        math.sin(lat_delta / 2) ** 2
        + math.cos(math.radians(first_lat))
        * math.cos(math.radians(second_lat))
        * math.sin(lng_delta / 2) ** 2
    )
    value = min(1.0, max(0.0, value))
    return round(radius_m * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value)))


def item_coordinate(item: dict[str, Any]) -> tuple[float, float] | None:
    lng = coordinate(item.get("mapx"))
    lat = coordinate(item.get("mapy"))
    if lng is None or lat is None:
        return None
    return lng, lat


def estimated_walking_minutes(distance_m: int | None) -> int | None:
    if distance_m is None:
        return None
    route_distance = distance_m * WALKING_ROUTE_FACTOR
    return max(1, math.ceil(route_distance / WALKING_METERS_PER_MINUTE))


def resolve_location_coordinate(
    location: str,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> tuple[float, float] | None:
    results = fetch_local_results(
        location,
        display=1,
        client_id=client_id,
        client_secret=client_secret,
    )
    return item_coordinate(results[0]) if results else None


def normalize_item(
    item: dict[str, Any],
    matched_term: str,
    location: str,
    origin: tuple[float, float] | None = None,
    review_rank: int | None = None,
) -> dict[str, Any]:
    title = strip_html(item.get("title", ""))
    raw_category = str(item.get("category", "")).strip()
    distance_m = haversine_distance_m(origin, item_coordinate(item))
    normalized = {
        "restaurant_id": restaurant_id(item),
        "name": title,
        "food": matched_term,
        "matched_terms": [matched_term],
        "category": canonical_category(raw_category),
        "category_group": top_category(raw_category),
        "sub_category": leaf_category(raw_category),
        "raw_category": raw_category,
        "location": location,
        "address": item.get("address", ""),
        "roadAddress": item.get("roadAddress", ""),
        "link": item.get("link", ""),
        "mapx": item.get("mapx"),
        "mapy": item.get("mapy"),
        "distance_m": distance_m,
        "walking_minutes": estimated_walking_minutes(distance_m),
        "review_rank": review_rank,
    }
    return normalized


def search_restaurants(
    terms: list[str],
    location: str,
    display: int = DEFAULT_DISPLAY,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    origin = resolve_location_coordinate(location, client_id, client_secret)

    for term in terms:
        clean_term = str(term).strip()
        if not clean_term:
            continue

        query = f"{clean_term} {location}".strip()
        results = fetch_local_results(
            query,
            display=display,
            client_id=client_id,
            client_secret=client_secret,
            sort="comment",
        )
        for index, item in enumerate(results):
            raw_category = str(item.get("category", "")).strip()
            if not is_restaurant_category(raw_category):
                continue

            normalized = normalize_item(
                item,
                clean_term,
                location,
                origin=origin,
                review_rank=index + 1,
            )
            restaurant_key = normalized["restaurant_id"]
            if restaurant_key in seen:
                matched_terms = seen[restaurant_key].setdefault("matched_terms", [])
                if clean_term not in matched_terms:
                    matched_terms.append(clean_term)
                previous_rank = seen[restaurant_key].get("review_rank")
                if previous_rank is None or index + 1 < previous_rank:
                    seen[restaurant_key]["review_rank"] = index + 1
                continue
            seen[restaurant_key] = normalized

    return list(seen.values())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch Naver local restaurant results")
    parser.add_argument("--query", required=True, help="Search term or food category")
    parser.add_argument("--location", required=True, help="Location keyword")
    parser.add_argument("--display", type=int, default=DEFAULT_DISPLAY, help="Number of results to fetch per query")
    parser.add_argument("--client-id", default=DEFAULT_CLIENT_ID, help="Naver client ID")
    parser.add_argument("--client-secret", default=DEFAULT_CLIENT_SECRET, help="Naver client secret")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    results = search_restaurants([args.query], args.location, display=args.display, client_id=args.client_id, client_secret=args.client_secret)
    json.dump(results, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
