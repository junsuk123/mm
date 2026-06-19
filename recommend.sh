#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DATASET_DIR="$SCRIPT_DIR/dataset"
MENU_TREE_FILE="$DATASET_DIR/menu_categories.json"
MOBILE_SESSIONS_FILE="$DATASET_DIR/mobile_sessions.json"
USERS_FILE="$DATASET_DIR/users.json"
TMP_FILES=""

. "$SCRIPT_DIR/restaurant_provider.sh"
. "$SCRIPT_DIR/naver_restaurant_provider.sh"

cleanup() {
  for file in $TMP_FILES; do
    [ -n "$file" ] && rm -f "$file"
  done
}
trap cleanup EXIT INT TERM HUP

add_tmp_file() {
  TMP_FILES="$TMP_FILES $1"
}

new_tmp() {
  file=$(mktemp "${TMPDIR:-/tmp}/recommend-$1.XXXXXX")
  add_tmp_file "$file"
  printf '%s' "$file"
}

web_step() {
  if [ -n "${MM_STEP_DELAY_SEC:-}" ]; then
    printf '[cmd] %s\n' "$1" >&2
    sleep "$MM_STEP_DELAY_SEC"
    printf '[out] %s\n' "$2" >&2
    sleep "$MM_STEP_DELAY_SEC"
  fi
}

usage() {
  cat <<'EOF'
Usage:
  sh recommend.sh --collect-session [--provider mock] [--location 세종대학교]
  sh recommend.sh --demo [--without-mobile-responses] [--mobile-session-id ID] [--provider mock]
  sh recommend.sh --session-file session.json [--json-output] [--provider mock]
  sh recommend.sh --user-id U01 [--provider mock]

Each participant selects:
  1 recently eaten main category and subcategory
  2 preferred main categories
  2 preferred subcategories for each preferred main category
EOF
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Missing required command: %s\n' "$1" >&2
    exit 127
  }
}

prompt_text() {
  printf '%s' "$1" >&2
  IFS= read -r value || value=
  printf '%s' "$value"
}

prompt_positive_int() {
  while :; do
    value=$(prompt_text "$1")
    case $value in
      ''|*[!0-9]*|0) printf '%s\n' "Please enter a positive integer." >&2 ;;
      *) printf '%s' "$value"; return ;;
    esac
  done
}

build_main_options() {
  jq -r 'to_entries[] | "\(.key)\t\(.key)"' "$MENU_TREE_FILE" > "$1"
}

build_subcategory_options() {
  main=$1
  output=$2
  jq -r --arg main "$main" '
    .[$main][] | "\($main)|\(.)\t\(.)"
  ' "$MENU_TREE_FILE" > "$output"
}

show_options() {
  awk -F '	' '{printf "%d) %s\n", NR, $2}' "$1" >&2
}

select_exact() {
  prompt=$1
  options=$2
  count=$3
  while :; do
    printf '%s\n' "Select $count option(s):" >&2
    show_options "$options"
    raw=$(prompt_text "$prompt")
    selected=$(jq -Rn --arg raw "$raw" --slurpfile options "$options.json" '
      $raw
      | split(",")
      | map(gsub("^\\s+|\\s+$"; ""))
      | map(select(test("^[0-9]+$")))
      | map(tonumber - 1)
      | map(select(. >= 0 and . < ($options[0] | length)))
      | map($options[0][.])
      | unique
    ')
    if [ "$(printf '%s' "$selected" | jq 'length')" -eq "$count" ]; then
      printf '%s' "$selected"
      return
    fi
    printf 'Please select exactly %s different option(s).\n' "$count" >&2
  done
}

prepare_options_json() {
  options=$1
  cut -f1 "$options" | jq -Rn '[inputs]' > "$options.json"
  add_tmp_file "$options.json"
}

collect_participant() {
  user_id=$1
  main_options=$(new_tmp main-options)
  sub_options=$(new_tmp sub-options)
  build_main_options "$main_options"
  prepare_options_json "$main_options"

  printf 'Collecting food choices for %s\n' "$user_id" >&2
  recent_main_json=$(select_exact "Recently eaten main category: " "$main_options" 1)
  recent_main=$(printf '%s' "$recent_main_json" | jq -r '.[0]')
  build_subcategory_options "$recent_main" "$sub_options"
  prepare_options_json "$sub_options"
  recent_sub_path=$(select_exact "Recently eaten subcategory: " "$sub_options" 1)
  recent_subcategory=$(printf '%s' "$recent_sub_path" | jq -r '.[0] | split("|")[1]')

  preferred_mains=$(select_exact "Two preferred main categories: " "$main_options" 2)
  preferred='[]'
  for main in $(printf '%s' "$preferred_mains" | jq -r '.[]'); do
    build_subcategory_options "$main" "$sub_options"
    prepare_options_json "$sub_options"
    selected_paths=$(select_exact "Two preferred subcategories for $main: " "$sub_options" 2)
    subcategories=$(printf '%s' "$selected_paths" | jq 'map(split("|")[1])')
    preferred=$(printf '%s' "$preferred" | jq \
      --arg main "$main" --argjson subcategories "$subcategories" \
      '. + [{main: $main, subcategories: $subcategories}]')
  done

  jq -n \
    --arg user_id "$user_id" \
    --arg recent_main "$recent_main" \
    --arg recent_subcategory "$recent_subcategory" \
    --argjson preferred "$preferred" '
    {
      user_id: $user_id,
      preferences: {
        recent: {main: $recent_main, subcategory: $recent_subcategory},
        preferred: $preferred
      }
    }
  '
}

collect_session() {
  participant_count=$(prompt_positive_int "Number of participants: ")
  group_count=$(prompt_positive_int "Number of groups: ")
  records=$(new_tmp participants)
  : > "$records"
  index=1
  while [ "$index" -le "$participant_count" ]; do
    user_id=$(prompt_text "User ID (blank for auto-generated): ")
    [ -n "$user_id" ] || user_id=$(printf 'U%02d' "$index")
    collect_participant "$user_id" >> "$records"
    index=$((index + 1))
  done
  SESSION_JSON_FILE=$(new_tmp session)
  jq -s --argjson participant_count "$participant_count" --argjson group_count "$group_count" '
    {participant_count: $participant_count, group_count: $group_count, participants: .}
  ' "$records" > "$SESSION_JSON_FILE"
  PARTICIPANT_COUNT=$participant_count
  GROUP_COUNT=$group_count
}

normalize_session() {
  python3 "$SCRIPT_DIR/preference_utils.py" --session-file "$1" > "$2"
}

load_demo_session() {
  merged=$(new_tmp demo-merged)
  if [ "$WITH_MOBILE" = true ] && [ -f "$MOBILE_SESSIONS_FILE" ]; then
    jq --slurpfile mobile "$MOBILE_SESSIONS_FILE" --arg session_id "$MOBILE_SESSION_ID" '
      ($mobile[0] // {latest_session_id: null, sessions: {}}) as $store
      | (if $session_id != "" then $session_id else ($store.latest_session_id // "") end) as $id
      | .participants += (($store.sessions[$id].participants // []) | map(select(.source == "mobile")))
      | .participant_count = (.participants | length)
    ' "$DATASET_DIR/demo_session.json" > "$merged"
  else
    cp "$DATASET_DIR/demo_session.json" "$merged"
  fi
  SESSION_JSON_FILE=$(new_tmp demo-session)
  normalize_session "$merged" "$SESSION_JSON_FILE"
  PARTICIPANT_COUNT=$(jq -r '.participant_count' "$SESSION_JSON_FILE")
  GROUP_COUNT=$(jq -r '.group_count' "$SESSION_JSON_FILE")
  printf 'Demo: %s participants, %s groups\n' "$PARTICIPANT_COUNT" "$GROUP_COUNT" >&2
  jq -r '.participants[] |
    "\(.user_id): recent=\(.preferences.recent.main) > \(.preferences.recent.subcategory)",
    (.preferences.preferred[] | "  preferred=\(.main) > \(.subcategories | join(", "))")
  ' "$SESSION_JSON_FILE" >&2
}

build_group_profile() {
  session_file=$1
  members=$2
  output=$3
  web_step \
    "jq --argjson members '<members>' 'reduce preferred and recent choices' $session_file > $output" \
    "그룹의 선호 대분류 2개씩과 소분류 4개씩을 합치고 최근 음식도 집계합니다."
  jq -c --argjson members "$members" '
    .participants
    | map(select(.user_id as $id | ($members | index($id))))
    | map(.preferences)
    | reduce .[] as $p (
        {preferred_main: [], preferred_subcategory: [], recent_main: [], recent_subcategory: []};
        .preferred_main += [$p.preferred[].main]
        | .preferred_subcategory += [$p.preferred[].subcategories[]]
        | .recent_main += [$p.recent.main]
        | .recent_subcategory += [$p.recent.subcategory]
      )
    | .preferred_main |= unique
    | .preferred_subcategory |= unique
    | .recent_main |= unique
    | .recent_subcategory |= unique
    | .positive = ((.preferred_main + .preferred_subcategory) | unique)
    | .recent = ((.recent_main + .recent_subcategory) | unique)
  ' "$session_file" > "$output"
}

recommend_profile() {
  profile=$1
  location=$2
  provider=$3
  output=$4
  candidates=$(new_tmp candidates)
  terms=$(new_tmp terms)
  : > "$candidates"

  web_step \
    "jq -r '[.positive[], .recent[]] | unique | .[]' $profile > $terms" \
    "선호 및 최근 대분류·소분류를 검색어로 준비합니다."
  jq -r '[.positive[], .recent[]] | unique | .[]' "$profile" > "$terms"
  seen='|'
  while IFS= read -r term; do
    [ -n "$term" ] || continue
    provider_result=$(new_tmp provider)
    web_step \
      "restaurant_provider.sh $provider '$term' '$location' > $provider_result" \
      "'$term' 기준으로 주변 식당 후보를 조회합니다."
    if provider_get_restaurants_by_food "$provider" "$term" "$location" > "$provider_result"; then
      while IFS= read -r restaurant; do
        id=$(printf '%s' "$restaurant" | jq -r '.restaurant_id')
        case $seen in
          *"|$id|"*) ;;
          *) seen="$seen$id|"; printf '%s\n' "$restaurant" >> "$candidates" ;;
        esac
      done <<EOF
$(jq -c '.[]' "$provider_result")
EOF
    fi
  done < "$terms"

  count=$(wc -l < "$candidates" | tr -d ' ')
  web_step "wc -l < $candidates | tr -d ' '" "중복 제거 후 후보는 ${count}개입니다."
  web_step \
    "jq -s 'score | sort_by([-.score, .distance_m]) | .[:3]' $candidates > $output" \
    "선호 일치 점수에서 최근 음식 반복 점수를 빼고 상위 3개를 선택합니다."
  jq -s --slurpfile profile "$profile" '
    def has($array; $value): ($array | index($value)) != null;
    def score($r; $p):
      (if has($p.preferred_main; $r.category) then 0.5 else 0 end)
      + (if has($p.preferred_subcategory; ($r.subcategory // "")) then 0.4 else 0 end)
      - (if has($p.recent_main; $r.category) then 0.2 else 0 end)
      - (if has($p.recent_subcategory; ($r.subcategory // "")) then 0.7 else 0 end);
    def reason($r; $p):
      [
        (if has($p.preferred_main; $r.category) then "preferred main category: \($r.category)" else empty end),
        (if has($p.preferred_subcategory; ($r.subcategory // "")) then "preferred subcategory: \($r.subcategory)" else empty end),
        (if has($p.recent_subcategory; ($r.subcategory // "")) then "recent subcategory reduced for variety"
         elif has($p.recent_main; $r.category) then "recent main category slightly reduced"
         else empty end)
      ] | if length > 0 then join("; ") else "best available nearby candidate" end;
    map(. + {
      score: ((score(.; $profile[0]) * 1000 | round) / 1000),
      reason: reason(.; $profile[0])
    })
    | sort_by([-.score, (.distance_m // 999999)])
    | .[:3]
  ' "$candidates" > "$output"
}

recommend_groups() {
  assignments=$(new_tmp assignments)
  groups=$(new_tmp groups)
  : > "$groups"
  web_step \
    "python3 grouping_utils.py --session-file $SESSION_JSON_FILE --group-count $GROUP_COUNT > $assignments" \
    "두 선호 대분류와 네 선호 소분류의 겹침으로 참가자를 그룹화합니다."
  python3 "$SCRIPT_DIR/grouping_utils.py" \
    --session-file "$SESSION_JSON_FILE" --group-count "$GROUP_COUNT" > "$assignments"

  while IFS= read -r group; do
    group_id=$(printf '%s' "$group" | jq -r '.group_id')
    members=$(printf '%s' "$group" | jq -c '.members')
    profile=$(new_tmp profile)
    recommendations=$(new_tmp recommendations)
    build_group_profile "$SESSION_JSON_FILE" "$members" "$profile"
    recommend_profile "$profile" "$LOCATION" "$PROVIDER" "$recommendations"
    jq -n --argjson group_id "$group_id" --argjson members "$members" \
      --slurpfile recommendations "$recommendations" '
      {group_id: $group_id, members: $members, recommendations: $recommendations[0]}
    ' >> "$groups"
  done <<EOF
$(jq -c '.groups[]' "$assignments")
EOF

  jq -s --slurpfile session "$SESSION_JSON_FILE" \
    --arg provider "$PROVIDER" --arg location "$LOCATION" \
    --argjson participant_count "$PARTICIPANT_COUNT" --argjson group_count "$GROUP_COUNT" '
    {
      session: {
        participant_count: $participant_count,
        group_count: $group_count,
        location: $location
      },
      provider: $provider,
      participants: $session[0].participants,
      groups: .
    }
  ' "$groups"
}

print_summary() {
  jq -r '.groups[] as $g | $g.recommendations | to_entries[] |
    "Group \($g.group_id) members=\($g.members | join(", ")) -> Top \(.key + 1): \(.value.name) | category=\(.value.category) > \(.value.subcategory // "-") | score=\(.value.score) | reason=\(.value.reason)"
  ' "$1"
}

visualize() {
  MM_VISUALIZER_SKIP_LIVE=1 PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    python3 "$SCRIPT_DIR/visualization/recommendation_visualizer.py" \
    --input "$1" --output "$SCRIPT_DIR/report.html" || true
}

PROVIDER=naver
LOCATION=세종대학교
MODE=
USER_ID=
WITH_MOBILE=true
MOBILE_SESSION_ID=
SESSION_INPUT=
JSON_OUTPUT=false

while [ "$#" -gt 0 ]; do
  case $1 in
    --collect-session) MODE=collect ;;
    --demo) MODE=demo ;;
    --without-mobile-responses) WITH_MOBILE=false ;;
    --with-mobile-responses) WITH_MOBILE=true ;;
    --mobile-session-id) shift; MOBILE_SESSION_ID=${1:-} ;;
    --session-file) shift; SESSION_INPUT=${1:-}; MODE=session ;;
    --user-id) shift; USER_ID=${1:-}; MODE=user ;;
    --provider) shift; PROVIDER=${1:-} ;;
    --location) shift; LOCATION=${1:-} ;;
    --json-output) JSON_OUTPUT=true ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 1 ;;
  esac
  shift
done

require_command jq
require_command python3

case $MODE in
  collect)
    collect_session
    ;;
  demo)
    load_demo_session
    ;;
  session)
    [ -f "$SESSION_INPUT" ] || { printf 'Session file not found: %s\n' "$SESSION_INPUT" >&2; exit 1; }
    SESSION_JSON_FILE=$(new_tmp normalized-session)
    normalize_session "$SESSION_INPUT" "$SESSION_JSON_FILE"
    PARTICIPANT_COUNT=$(jq -r '.participant_count' "$SESSION_JSON_FILE")
    GROUP_COUNT=$(jq -r '.group_count' "$SESSION_JSON_FILE")
    ;;
  user)
    user_session=$(new_tmp user-session)
    jq --arg user_id "$USER_ID" '
      [.users[] | select(.user_id == $user_id)] as $participants
      | {participant_count: ($participants | length), group_count: 1, participants: $participants}
    ' "$USERS_FILE" > "$user_session"
    SESSION_JSON_FILE=$(new_tmp normalized-user)
    normalize_session "$user_session" "$SESSION_JSON_FILE"
    PARTICIPANT_COUNT=$(jq -r '.participant_count' "$SESSION_JSON_FILE")
    [ "$PARTICIPANT_COUNT" -gt 0 ] || { printf 'User not found: %s\n' "$USER_ID" >&2; exit 1; }
    GROUP_COUNT=1
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac

FINAL_RESULT=$(new_tmp final)
recommend_groups > "$FINAL_RESULT"
if [ "$JSON_OUTPUT" = true ]; then
  cat "$FINAL_RESULT"
else
  print_summary "$FINAL_RESULT"
  visualize "$FINAL_RESULT"
fi
