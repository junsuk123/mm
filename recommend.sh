#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DATASET_DIR="$SCRIPT_DIR/dataset"
USERS_FILE="$DATASET_DIR/users.json"
MENU_TREE_FILE="$DATASET_DIR/menu_categories.json"
MOBILE_SESSIONS_FILE="$DATASET_DIR/mobile_sessions.json"

. "$SCRIPT_DIR/restaurant_provider.sh"
. "$SCRIPT_DIR/naver_restaurant_provider.sh"

TMP_FILES=""

cleanup() {
  for temp_file in $TMP_FILES; do
    [ -n "$temp_file" ] && rm -f "$temp_file"
  done
}

trap cleanup EXIT INT TERM HUP

add_tmp_file() {
  TMP_FILES="$TMP_FILES $1"
}

web_step() {
  command_text=$1
  output_text=$2
  if [ -n "${MM_STEP_DELAY_SEC:-}" ]; then
    printf '[cmd] %s\n' "$command_text" >&2
    sleep "$MM_STEP_DELAY_SEC"
    printf '[out] %s\n' "$output_text" >&2
    sleep "$MM_STEP_DELAY_SEC"
  fi
}

usage() {
  cat <<'EOF'
Usage:
  sh recommend.sh --collect-session [--provider naver] [--location 세종대학교]
  sh recommend.sh --demo [--without-mobile-responses] [--mobile-session-id ID] [--provider naver] [--location 세종대학교]
  sh recommend.sh --session-file session.json [--json-output] [--provider naver] [--location 세종대학교]
  sh recommend.sh --user-id U01 [--provider naver] [--location 세종대학교]

Options:
  --collect-session   Interactively collect participant count, group count, and personal preferences
  --demo              Replay example data from dataset/demo_session.json with visible input trace
  --with-mobile-responses
                      Append QR/mobile survey responses saved by the Flask web app to demo data (default for --demo)
  --without-mobile-responses
                      Use only dataset/demo_session.json in demo mode
  --mobile-session-id ID
                      Use a specific persisted mobile session instead of the latest one
  --session-file PATH
                      Recommend for an existing session JSON file using the shell pipeline
  --json-output       Print the full recommendation JSON to stdout
  --user-id ID        Recommend for a user in dataset/users.json
  --provider NAME     naver (default: naver)
  --location NAME     Search location (default: 세종대학교)
EOF
}

require_command() {
  command_name=$1
  install_hint=$2
  if command -v "$command_name" >/dev/null 2>&1; then
    return 0
  fi

  printf '%s\n' "Missing required command: $command_name" >&2
  printf '%s\n' "$install_hint" >&2
  exit 127
}

check_dependencies() {
  require_command jq "Install it with: sudo apt update && sudo apt install -y jq"
  require_command python3 "Install it with: sudo apt update && sudo apt install -y python3"
}

prompt_text() {
  prompt_message=$1
  printf '%s' "$prompt_message" >&2
  IFS= read -r value || value=
  printf '%s' "$value"
}

prompt_positive_int() {
  prompt_message=$1
  while :; do
    value=$(prompt_text "$prompt_message")
    case $value in
      ''|*[!0-9]*|0)
        printf '%s\n' "Please enter a positive integer." >&2
        ;;
      *)
        printf '%s' "$value"
          emit_demo_prompt_line() {
            prompt_message=$1
            value_text=$2
            if [ -n "$value_text" ]; then
              printf '%s %s\n' "$prompt_message" "$value_text" >&2
            else
              printf '%s\n' "$prompt_message" >&2
            fi
          }

        return 0
        ;;
    esac
  done
}

prompt_menu_array_json() {
  prompt_message=$1
  raw_value=$(prompt_text "$prompt_message")
  jq -Rn --arg value "$raw_value" '$value | split(",") | map(gsub("^\\s+|\\s+$"; "")) | map(select(length > 0))'
}

show_numbered_options_file() {
  options_file=$1
  awk -F '	' '{printf "%d) %s\n", NR, $2}' "$options_file" >&2
}

prompt_values_from_options_file() {
  prompt_message=$1
  options_file=$2

  if [ ! -s "$options_file" ]; then
    printf '%s' '[]'
    return 0
  fi

  printf '%s\n' "Select menu categories by number:" >&2
  show_numbered_options_file "$options_file"
  raw_value=$(prompt_text "$prompt_message")

  if [ -z "$raw_value" ]; then
    printf '%s' '[]'
    return 0
  fi

  selected_file=$(mktemp "${TMPDIR:-/tmp}/recommend-selected.XXXXXX")
  add_tmp_file "$selected_file"
  : > "$selected_file"

  old_ifs=$IFS
  IFS=,
  set -- $raw_value
  IFS=$old_ifs

  seen_values='|'
  for choice in "$@"; do
    choice=$(printf '%s' "$choice" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
    case $choice in
      ''|*[!0-9]*|0)
        continue
        ;;
    esac

    line=$(sed -n "${choice}p" "$options_file" || true)
    [ -n "$line" ] || continue
    value=$(printf '%s' "$line" | cut -f1)

    case $seen_values in
      *"|$value|"*)
        continue
        ;;
    esac

    seen_values="$seen_values$value|"
    printf '%s\n' "$value" >> "$selected_file"
  done

  if [ ! -s "$selected_file" ]; then
    printf '%s' '[]'
    return 0
  fi

  jq -Rn '[inputs]' < "$selected_file"
}

build_high_options_file() {
  options_file=$1
  jq -r 'to_entries[] | "\(.key)\t\(.key)"' "$MENU_TREE_FILE" > "$options_file"
}

build_mid_options_file() {
  selected_highs_json=$1
  options_file=$2

  jq -r --argjson highs "$selected_highs_json" '
    to_entries
    | map(.key as $high | select(($highs | length) == 0 or ($highs | index($high))))
    | .[]
    | .key as $high
    | .value
    | to_entries[]
    | "\($high)|\(.key)\t\(.key) (\($high))"
  ' "$MENU_TREE_FILE" > "$options_file"
}

build_low_options_file() {
  selected_highs_json=$1
  selected_mids_json=$2
  options_file=$3

  jq -r --argjson highs "$selected_highs_json" --argjson mids "$selected_mids_json" '
    to_entries
    | map(.key as $high | select(($highs | length) == 0 or ($highs | index($high))))
    | .[]
    | .key as $high
    | .value
    | to_entries
    | map(.key as $mid | select(($mids | length) == 0 or ($mids | index("\($high)|\($mid)"))))
    | .[]
    | .key as $mid
    | .value[]
    | "\($high)|\($mid)|\(.)\t\(.) (\($high) > \($mid))"
  ' "$MENU_TREE_FILE" > "$options_file"
}

collect_category_triplet_json() {
  preference_group=$1

  high_options_file=$(mktemp "${TMPDIR:-/tmp}/recommend-high-options.XXXXXX")
  low_options_file=$(mktemp "${TMPDIR:-/tmp}/recommend-low-options.XXXXXX")
  add_tmp_file "$high_options_file"
  add_tmp_file "$low_options_file"

  build_high_options_file "$high_options_file"
  high_json=$(prompt_values_from_options_file "$preference_group menus for high category (comma-separated numbers, blank for none): " "$high_options_file")

  build_mid_options_file "$high_json" "$low_options_file"
  low_json=$(prompt_values_from_options_file "$preference_group menus for low category (comma-separated numbers, blank for none): " "$low_options_file")

  jq -n \
    --argjson high "$high_json" \
    --argjson low "$low_json" '
      {high: $high, low: $low}
    '
}

collect_personal_preferences_json() {
  user_id=$1

  printf '%s\n' "Collecting preferences for $user_id" >&2
  like_json=$(collect_category_triplet_json "like")
  recent_json=$(collect_category_triplet_json "recent")

  jq -n \
    --arg user_id "$user_id" \
    --argjson like "$like_json" \
    --argjson recent "$recent_json" '
      {
        user_id: $user_id,
        preferences: {
          like: $like,
          recent: $recent
        }
      }
    '
}

collect_session_data() {
  participant_count=$(prompt_positive_int "Number of participants: ")
  group_count=$(prompt_positive_int "Number of groups: ")
  session_file=$(mktemp "${TMPDIR:-/tmp}/recommend-session.XXXXXX")
  add_tmp_file "$session_file"

  index=1
  while [ "$index" -le "$participant_count" ]; do
    printf '%s\n' "Participant $index of $participant_count" >&2
    user_id=$(prompt_text "User ID (blank for auto-generated): ")
    if [ -z "$user_id" ]; then
      user_id=$(printf 'U%02d' "$index")
    fi
    collect_personal_preferences_json "$user_id" >> "$session_file"
    index=$((index + 1))
  done

  SESSION_JSON_FILE=$(mktemp "${TMPDIR:-/tmp}/recommend-session-json.XXXXXX")
  add_tmp_file "$SESSION_JSON_FILE"
  jq -s \
    --argjson participant_count "$participant_count" \
    --argjson group_count "$group_count" \
    '{participant_count: $participant_count, group_count: $group_count, participants: .}' \
    "$session_file" > "$SESSION_JSON_FILE"

  PARTICIPANT_COUNT=$participant_count
  GROUP_COUNT=$group_count
}

load_demo_session_file() {
  printf '%s' "$DATASET_DIR/demo_session.json"
}

merge_mobile_responses_into_session() {
  base_session_file=$1
  output_session_file=$2
  mobile_session_id=$3

  if [ ! -f "$MOBILE_SESSIONS_FILE" ]; then
    cp "$base_session_file" "$output_session_file"
    printf '%s' 0
    return 0
  fi

  jq \
    --slurpfile mobile_store "$MOBILE_SESSIONS_FILE" \
    --arg mobile_session_id "$mobile_session_id" '
      def mobile_id($n): if $n < 10 then "M0\($n)" else "M\($n)" end;
      ($mobile_store[0] // {latest_session_id: null, sessions: {}}) as $store
      | (if ($mobile_session_id | length) > 0 then $mobile_session_id else ($store.latest_session_id // "") end) as $target_id
      | (($store.sessions[$target_id].participants // []) | map(select(.source == "mobile"))) as $mobile_participants
      | . as $base
      | reduce ($mobile_participants | to_entries[]) as $entry (
          $base;
          .participants += [
            ($entry.value
             | .original_user_id = (.user_id // "")
             | .user_id = mobile_id($entry.key + 1))
          ]
        )
      | .participant_count = (.participants | length)
      | .mobile_session_id = $target_id
      | .mobile_participant_count = ($mobile_participants | length)
    ' "$base_session_file" > "$output_session_file"

  jq -r '.mobile_participant_count // 0' "$output_session_file"
}

resolve_choice_numbers_from_options_file() {
  options_file=$1
  selected_json=$2

  if [ -z "$selected_json" ] || [ "$selected_json" = '[]' ]; then
    printf '%s' ""
    return 0
  fi

  resolved=""
  seen_numbers='|'
  old_ifs=$IFS
  IFS='
'
  set -f
  for value in $(printf '%s' "$selected_json" | jq -r '.[]'); do
    choice_number=$(awk -F '	' -v target="$value" '$1 == target {print NR; exit}' "$options_file")
    [ -n "$choice_number" ] || continue
    case $seen_numbers in
      *"|$choice_number|"*)
        continue
        ;;
    esac
    seen_numbers="$seen_numbers$choice_number|"
    if [ -n "$resolved" ]; then
      resolved="$resolved,$choice_number"
    else
      resolved="$choice_number"
    fi
  done
  set +f
  IFS=$old_ifs
  printf '%s' "$resolved"
}

build_profile_file_from_user() {
  user_id=$1
  profile_file=$2

  : > "$profile_file"
  jq -c --arg user_id "$user_id" '
    def leaf: if type == "string" then split("|")[-1] else . end;
    def normalize_levels:
      {
        high: (.high // []),
        low: (if has("mid") and (.mid | length) > 0 then .mid elif has("low") then .low else [] end)
      };
    .users[]
    | select(.user_id == $user_id)
    | .preferences
    | {like: (.like | normalize_levels), recent: (.recent | normalize_levels)}
    | {
        like_high: (.like.high | map(leaf)),
        like_low: (.like.low | map(leaf)),
        recent: ((.recent.high + .recent.low) | map(leaf))
      }
    | .positive = ((.like_high + .like_low) | unique)
  ' "$USERS_FILE" > "$profile_file"

  if [ ! -s "$profile_file" ]; then
    printf '%s\n' "User not found: $user_id" >&2
    return 1
  fi
}

emit_demo_prompt_line() {
  prompt_message=$1
  value_text=$2
  if [ -n "$value_text" ]; then
    printf '%s ' "$prompt_message" >&2
    # Simulate human typing for the value text if awk is available, else print with short pause
    if command -v awk >/dev/null 2>&1; then
      printf '%s' "$value_text" | awk '{ for(i=1;i<=length;i++){printf "%s",substr($0,i,1); fflush(); system("sleep 0.05") } print "" }' >&2
    else
      sleep 0.2
      printf '%s\n' "$value_text" >&2
    fi
  else
    printf '%s\n' "$prompt_message" >&2
  fi
}

emit_demo_selection_trace() {
  prompt_message=$1
  options_file=$2
  selected_json=$3

  printf '%s\n' "Select menu categories by number:" >&2
  show_numbered_options_file "$options_file"
  # small pause so the option list can be scanned
  sleep 0.35
  choice_numbers=$(resolve_choice_numbers_from_options_file "$options_file" "$selected_json")
  emit_demo_prompt_line "$prompt_message" "$choice_numbers"
}

emit_demo_category_group_trace() {
  preference_group=$1
  preference_json=$2

  high_options_file=$(mktemp "${TMPDIR:-/tmp}/recommend-demo-high.XXXXXX")
  low_options_file=$(mktemp "${TMPDIR:-/tmp}/recommend-demo-low.XXXXXX")
  add_tmp_file "$high_options_file"
  add_tmp_file "$low_options_file"

  high_json=$(printf '%s' "$preference_json" | jq -c ".preferences.${preference_group}.high")
  low_json=$(printf '%s' "$preference_json" | jq -c ".preferences.${preference_group}.low // .preferences.${preference_group}.mid // []")

  build_high_options_file "$high_options_file"
  emit_demo_selection_trace "$preference_group menus for high category (comma-separated numbers, blank for none):" "$high_options_file" "$high_json"

  build_mid_options_file "$high_json" "$low_options_file"
  emit_demo_selection_trace "$preference_group menus for low category (comma-separated numbers, blank for none):" "$low_options_file" "$low_json"
}

run_demo_session() {
  demo_session_file=$(load_demo_session_file)
  SESSION_JSON_FILE=$(mktemp "${TMPDIR:-/tmp}/recommend-demo-session.XXXXXX")
  add_tmp_file "$SESSION_JSON_FILE"

  if [ "$with_mobile_responses" = true ]; then
    mobile_count=$(merge_mobile_responses_into_session "$demo_session_file" "$SESSION_JSON_FILE" "$mobile_session_id")
  else
    cp "$demo_session_file" "$SESSION_JSON_FILE"
    mobile_count=0
  fi

  participant_count=$(jq -r '.participant_count' "$SESSION_JSON_FILE")
  group_count=$(jq -r '.group_count' "$SESSION_JSON_FILE")

  printf '%s\n' "Example data mode: loading $participant_count participants into $group_count groups" >&2
  if [ "$with_mobile_responses" = true ]; then
    printf '%s\n' "Mobile QR responses appended: $mobile_count" >&2
  fi
  printf '%s\n' "Number of participants: $participant_count" >&2
  printf '%s\n' "Number of groups: $group_count" >&2

  jq -c '.participants[]' "$SESSION_JSON_FILE" | while IFS= read -r participant_json; do
    user_id=$(printf '%s' "$participant_json" | jq -r '.user_id')
    emit_demo_prompt_line "User ID (blank for auto-generated):" "$user_id"
    printf '%s\n' "Collecting preferences for $user_id" >&2
    emit_demo_category_group_trace like "$participant_json"
    emit_demo_category_group_trace recent "$participant_json"
    # small pause between participants to mimic human pacing
    sleep 0.65
  done

  PARTICIPANT_COUNT=$participant_count
  GROUP_COUNT=$group_count

  report_file=$(mktemp "${TMPDIR:-/tmp}/recommend-demo-report.XXXXXX")
  add_tmp_file "$report_file"
  recommend_for_groups "$provider_name" "$location" "$SESSION_JSON_FILE" "$GROUP_COUNT" > "$report_file"

  print_group_summary "$report_file"
  open_visualization_report "$report_file"
}

build_group_profile_file() {
  session_file=$1
  group_index=$2
  group_count=$3
  profile_file=$4

  jq -c \
    --argjson group_index "$group_index" \
    --argjson group_count "$group_count" '
      def leaf: if type == "string" then split("|")[-1] else . end;
      def normalize_levels:
        {
          high: (.high // []),
          low: (if has("mid") and (.mid | length) > 0 then .mid elif has("low") then .low else [] end)
        };
      .participants
      | to_entries
      | map(select((.key % $group_count) + 1 == $group_index))
      | map(.value.preferences | {like: (.like | normalize_levels), recent: (.recent | normalize_levels)})
      | reduce .[] as $p (
          {like_high: [], like_low: [], recent: []};
          .like_high += ($p.like.high | map(leaf))
          | .like_low += ($p.like.low | map(leaf))
          | .recent += (($p.recent.high + $p.recent.low) | map(leaf))
        )
      | .positive = ((.like_high + .like_low) | unique)
      | .like_high |= unique
      | .like_low |= unique
      | .positive |= unique
      | .recent |= unique
    ' "$session_file" > "$profile_file"
}

build_group_assignments_file() {
  session_file=$1
  group_count=$2
  assignments_file=$3

  python3 "$SCRIPT_DIR/grouping_utils.py" --session-file "$session_file" --group-count "$group_count" > "$assignments_file"
}

build_group_profile_file_from_members() {
  session_file=$1
  members_json=$2
  profile_file=$3

  jq -c \
    --argjson members "$members_json" '
      def leaf: if type == "string" then split("|")[-1] else . end;
      def normalize_levels:
        {
          high: (.high // []),
          low: (if has("mid") and (.mid | length) > 0 then .mid elif has("low") then .low else [] end)
        };
      .participants
      | map(select(.user_id as $user_id | ($members | index($user_id))))
      | map(.preferences | {like: (.like | normalize_levels), recent: (.recent | normalize_levels)})
      | reduce .[] as $p (
          {like_high: [], like_low: [], recent: []};
          .like_high += ($p.like.high | map(leaf))
          | .like_low += ($p.like.low | map(leaf))
          | .recent += (($p.recent.high + $p.recent.low) | map(leaf))
        )
      | .positive = ((.like_high + .like_low) | unique)
      | .like_high |= unique
      | .like_low |= unique
      | .positive |= unique
      | .recent |= unique
    ' "$session_file" > "$profile_file"
}

recommend_from_profile_file() {
  profile_file=$1
  location=$2
  provider_name=$3
  result_file=$4

  candidate_file=$(mktemp "${TMPDIR:-/tmp}/recommend-candidates.XXXXXX")
  add_tmp_file "$candidate_file"
  terms_file=$(mktemp "${TMPDIR:-/tmp}/recommend-terms.XXXXXX")
  add_tmp_file "$terms_file"
  : > "$candidate_file"

  jq -r '[.positive[], .recent[]] | unique | .[]' "$profile_file" > "$terms_file"
  seen_ids='|'

  while IFS= read -r term; do
    [ -n "$term" ] || continue
    term_result_file=$(mktemp "${TMPDIR:-/tmp}/recommend-term.XXXXXX")
    restaurants_file=$(mktemp "${TMPDIR:-/tmp}/recommend-restaurants.XXXXXX")
    add_tmp_file "$term_result_file"
    add_tmp_file "$restaurants_file"
    if provider_get_restaurants_by_food "$provider_name" "$term" "$location" > "$term_result_file"; then
      jq -c '.[]' "$term_result_file" > "$restaurants_file"
      while IFS= read -r restaurant; do
        [ -n "$restaurant" ] || continue
        restaurant_id=$(printf '%s' "$restaurant" | jq -r '.restaurant_id')
        case $seen_ids in
          *"|$restaurant_id|"*)
            ;;
          *)
            seen_ids="$seen_ids$restaurant_id|"
            printf '%s\n' "$restaurant" >> "$candidate_file"
            ;;
        esac
      done < "$restaurants_file"
    fi
  done < "$terms_file"

  jq -s --slurpfile profile "$profile_file" '
    def has($arr; $value): ($arr | contains([$value]));
    def score($r; $p):
      (if has($p.like_high; $r.category) then 0.5 else 0 end)
      + (if has($p.like_low; $r.food) then 0.3 else 0 end)
      - (if has($p.recent; $r.category) or has($p.recent; $r.food) then 0.5 else 0 end);
    def reason($r; $p):
      [
        (if has($p.like_high; $r.category) then "matched preferred category \($r.category)" else empty end),
        (if has($p.like_low; $r.food) then "matched preferred food \($r.food)" else empty end),
        (if has($p.recent; $r.category) or has($p.recent; $r.food) then "recently eaten category or food was penalized" else empty end)
      ] as $parts
      | if ($parts | length) > 0 then ($parts | join("; ")) else "selected as the best available candidate from the search results" end;

    map(. + {
      score: ((score(.; $profile[0]) * 1000 | round) / 1000),
      reason: reason(.; $profile[0])
    })
    | sort_by(-.score)
    | .[:3]
  ' "$candidate_file" > "$result_file"
}

recommend_for_single_user() {
  user_id=$1
  location=$2
  provider_name=$3

  profile_file=$(mktemp "${TMPDIR:-/tmp}/recommend-profile.XXXXXX")
  add_tmp_file "$profile_file"
  build_profile_file_from_user "$user_id" "$profile_file"

  recommendations_file=$(mktemp "${TMPDIR:-/tmp}/recommend-result.XXXXXX")
  add_tmp_file "$recommendations_file"
  recommend_from_profile_file "$profile_file" "$location" "$provider_name" "$recommendations_file"

  jq -n \
    --arg user_id "$user_id" \
    --arg provider "$provider_name" \
    --slurpfile recommendations "$recommendations_file" \
    '{user_id: $user_id, provider: $provider, recommendations: $recommendations[0]}'
}

print_single_user_summary() {
  result_file=$1

  jq -r '
    .recommendations[0] as $r
    | if $r == null then
        "No recommendation found."
      else
        (.recommendations
        | to_entries[]
        | "Top \(.key + 1): \(.value.name) | food=\(.value.food) | category=\(.value.category) | score=\(.value.score) | reason=\(.value.reason)")
      end
  ' "$result_file"
}

recommend_for_groups() {
  provider_name=$1
  location=$2
  session_file=$3
  group_count=$4

  web_step \
    "python3 grouping_utils.py --session-file <세션파일> --group-count $group_count > <그룹파일>" \
    "참가자의 음식 선호 유사도를 계산해 그룹 구성을 완료했습니다."
  assignments_file=$(mktemp "${TMPDIR:-/tmp}/recommend-assignments.XXXXXX")
  add_tmp_file "$assignments_file"
  build_group_assignments_file "$session_file" "$group_count" "$assignments_file"

  web_step \
    "jq '<그룹별 선호 프로필 생성>' <세션파일> && restaurant_provider.sh $provider_name '<선호메뉴>' '$location' | jq '<점수 계산 및 Top 3 선정>'" \
    "각 그룹의 선호 프로필로 식당을 검색하고 추천 점수 순으로 Top 3를 선정했습니다."
  groups_file=$(mktemp "${TMPDIR:-/tmp}/recommend-groups.XXXXXX")
  add_tmp_file "$groups_file"
  : > "$groups_file"

  jq -c '.groups[]' "$assignments_file" | while IFS= read -r group_json; do
    group_index=$(printf '%s' "$group_json" | jq -r '.group_id')
    profile_file=$(mktemp "${TMPDIR:-/tmp}/recommend-group-profile.XXXXXX")
    recommendations_file=$(mktemp "${TMPDIR:-/tmp}/recommend-group-result.XXXXXX")
    add_tmp_file "$profile_file"
    add_tmp_file "$recommendations_file"

    members_json=$(printf '%s' "$group_json" | jq -c '.members')
    build_group_profile_file_from_members "$session_file" "$members_json" "$profile_file"
    recommend_from_profile_file "$profile_file" "$location" "$provider_name" "$recommendations_file"

    group_json=$(jq -n \
      --argjson group_id "$group_index" \
      --argjson members "$members_json" \
      --slurpfile recommendations "$recommendations_file" \
      '{group_id: $group_id, members: $members, recommendations: $recommendations[0]}')
    printf '%s\n' "$group_json" >> "$groups_file"
  done

  web_step \
    "jq -s '<참가자 + 그룹 + 추천 결과 통합>' <그룹결과파일> > <최종결과.json>" \
    "참가자, 그룹, 추천 식당을 하나의 최종 결과로 통합했습니다."
  jq -s \
    --slurpfile session "$session_file" \
    --arg provider "$provider_name" \
    --arg location "$location" \
    --argjson participant_count "$PARTICIPANT_COUNT" \
    --argjson group_count "$GROUP_COUNT" \
    '{session: {participant_count: $participant_count, group_count: $group_count, location: $location}, provider: $provider, participants: $session[0].participants, groups: .}' \
    "$groups_file"
}

print_group_summary() {
  result_file=$1

  jq -r '
    .groups[]
    | .group_id as $group_id
    | (.members | join(", ")) as $members
    | .recommendations[0] as $r
    | if $r == null then
        "Group \(.group_id): no recommendation"
      else
        (.recommendations
        | to_entries[]
        | "Group \($group_id) members=\($members) -> Top \(.key + 1): \(.value.name) | food=\(.value.food) | category=\(.value.category) | score=\(.value.score) | reason=\(.value.reason)")
      end
  ' "$result_file"
}

open_visualization_report() {
  result_file=$1
  visualizer_script="$SCRIPT_DIR/visualization/recommendation_visualizer.py"
  output_html="$SCRIPT_DIR/report.html"

  if [ ! -f "$visualizer_script" ]; then
    printf '%s\n' "Visualization script not found: $visualizer_script" >&2
    return 0
  fi

  if ! MM_VISUALIZER_SKIP_LIVE=1 PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 "$visualizer_script" --input "$result_file" --output "$output_html"; then
    printf '%s\n' "Failed to generate visualization report." >&2
    return 0
  fi

  printf '%s\n' "Visualization report generated: $output_html" >&2

  if command -v xdg-open >/dev/null 2>&1 && { [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; }; then
    xdg-open "$output_html" >/dev/null 2>&1 &
  else
    printf '%s\n' "GUI environment not detected. Open manually: $output_html" >&2
  fi
}

main() {
  provider_name=naver
  location=세종대학교
  mode=
  user_id=
  with_mobile_responses=true
  mobile_session_id=
  session_file_input=
  json_output=false

  while [ "$#" -gt 0 ]; do
    case $1 in
      --collect-session)
        mode=collect-session
        ;;
      --demo)
        mode=demo
        ;;
      --with-mobile-responses)
        with_mobile_responses=true
        ;;
      --without-mobile-responses)
        with_mobile_responses=false
        ;;
      --mobile-session-id)
        shift
        [ "$#" -gt 0 ] || { usage >&2; exit 1; }
        mobile_session_id=$1
        ;;
      --user-id)
        shift
        [ "$#" -gt 0 ] || { usage >&2; exit 1; }
        user_id=$1
        ;;
      --session-file)
        shift
        [ "$#" -gt 0 ] || { usage >&2; exit 1; }
        session_file_input=$1
        mode=session-file
        ;;
      --json-output)
        json_output=true
        ;;
      --provider)
        shift
        [ "$#" -gt 0 ] || { usage >&2; exit 1; }
        provider_name=$1
        ;;
      --location)
        shift
        [ "$#" -gt 0 ] || { usage >&2; exit 1; }
        location=$1
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        printf '%s\n' "Unknown argument: $1" >&2
        usage >&2
        exit 1
        ;;
    esac
    shift
  done

  check_dependencies

  if [ "$mode" = collect-session ]; then
    collect_session_data
    output_file=$(mktemp "${TMPDIR:-/tmp}/recommend-final.XXXXXX")
    add_tmp_file "$output_file"
    recommend_for_groups "$provider_name" "$location" "$SESSION_JSON_FILE" "$GROUP_COUNT" > "$output_file"
    print_group_summary "$output_file"
    open_visualization_report "$output_file"
    return 0
  fi

  if [ "$mode" = demo ]; then
    run_demo_session
    return 0
  fi

  if [ "$mode" = session-file ]; then
    [ -f "$session_file_input" ] || { printf '%s\n' "Session file not found: $session_file_input" >&2; exit 1; }
    SESSION_JSON_FILE=$session_file_input
    PARTICIPANT_COUNT=$(jq -r '.participant_count // (.participants | length)' "$SESSION_JSON_FILE")
    GROUP_COUNT=$(jq -r '.group_count' "$SESSION_JSON_FILE")
    web_step \
      "jq '{participants, group_count}' <세션파일> && mktemp <최종결과파일>" \
      "세션의 참가자 데이터와 그룹 수를 읽고 결과 파일을 준비했습니다."

    output_file=$(mktemp "${TMPDIR:-/tmp}/recommend-session-file-final.XXXXXX")
    add_tmp_file "$output_file"
    recommend_for_groups "$provider_name" "$location" "$SESSION_JSON_FILE" "$GROUP_COUNT" > "$output_file"
    if [ "$json_output" = true ]; then
      cat "$output_file"
    else
      print_group_summary "$output_file"
      open_visualization_report "$output_file"
    fi
    return 0
  fi

  if [ -z "$user_id" ]; then
    printf '%s\n' "--user-id is required unless --collect-session is used" >&2
    usage >&2
    exit 1
  fi

  output_file=$(mktemp "${TMPDIR:-/tmp}/recommend-single-final.XXXXXX")
  add_tmp_file "$output_file"
  recommend_for_single_user "$user_id" "$location" "$provider_name" > "$output_file"
  print_single_user_summary "$output_file"
}

main "$@"
