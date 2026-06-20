#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
MENU_TREE_FILE="$PROJECT_ROOT/dataset/menu_categories.json"

usage() {
  printf '%s\n' "Usage: sh scripts/grouping_cli.sh --session-file PATH --group-count NUMBER" >&2
}

session_file=
group_count=

while [ "$#" -gt 0 ]; do
  case $1 in
    --session-file)
      shift
      [ "$#" -gt 0 ] || { usage; exit 1; }
      session_file=$1
      ;;
    --group-count)
      shift
      [ "$#" -gt 0 ] || { usage; exit 1; }
      group_count=$1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf '%s\n' "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
  shift
done

[ -n "$session_file" ] || { usage; exit 1; }
[ -f "$session_file" ] || { printf '%s\n' "Session file not found: $session_file" >&2; exit 1; }

case $group_count in
  ''|*[!0-9]*|0)
    printf '%s\n' "Group count must be a positive integer." >&2
    exit 1
    ;;
esac

jq --slurpfile menu "$MENU_TREE_FILE" --argjson group_count "$group_count" '
  def unique_values:
    reduce .[] as $value ([]; if index($value) then . else . + [$value] end);

  def choose_main_categories($requested):
    ($menu[0] | keys_unsorted) as $menu_order
    | ($requested | map(select($menu[0][.] != null)) | unique_values) as $valid
    | if ($valid | length) >= 2 then $valid[:2]
      else
        (if ($valid | length) > 0
         then ($menu_order | index($valid[0])) + 1
         else 0
         end) as $start
        | (($menu_order[$start:] + $menu_order[:$start]) | map(select($valid | index(.) | not))) as $defaults
        | ($valid + $defaults)[:2]
      end;

  def legacy_subcategories($like; $main):
    (($like.low // []) + ($like.mid // []))
    | map(
        select(type == "string")
        | split("|")
        | select(length >= 2 and .[0] == $main)
        | .[1]
      )
    | unique_values;

  def participant_terms:
    (.preferences // {}) as $preferences
    | if ($preferences.preferred | type) == "array" then
        [
          $preferences.preferred[]
          | .main as $main
          | $main,
            (.subcategories[]? | "\($main)|\(.)")
        ]
        | unique_values
      else
        ($preferences.like // {}) as $like
        | choose_main_categories(
            ($like.high // [])
            | map(select(type == "string") | split("|")[0])
          ) as $mains
        | [
            $mains[] as $main
            | (legacy_subcategories($like; $main)) as $legacy
            | (
                if ($legacy | length) > 0
                then $legacy
                else ($menu[0][$main] // [])[:2]
                end
              )[:2] as $subcategories
            | $main,
              ($subcategories[] | "\($main)|\(.)")
          ]
        | unique_values
      end;

  def jaccard($first; $second):
    (($first | unique_values) as $a
     | ($second | unique_values) as $b
     | (($a + $b) | unique_values) as $union
     | if ($union | length) == 0 then 0
       else ([ $a[] as $value | select($b | index($value)) ] | length) / ($union | length)
       end);

  def cluster_similarity($first; $second; $terms):
    [
      $first.members[] as $first_id
      | $second.members[] as $second_id
      | jaccard($terms[$first_id]; $terms[$second_id])
    ] as $scores
    | if ($scores | length) == 0 then 0 else ($scores | add) / ($scores | length) end;

  def candidate_pairs($clusters; $terms):
    [
      range(0; $clusters | length) as $first_index
      | range($first_index + 1; $clusters | length) as $second_index
      | ($clusters[$first_index]) as $first
      | ($clusters[$second_index]) as $second
      | cluster_similarity($first; $second; $terms) as $similarity
      | (($first.members | length) + ($second.members | length)) as $combined_size
      | ([$first.first_index, $second.first_index] | min) as $earliest_index
      | ([$first.first_index, $second.first_index] | max) as $latest_index
      | {
          first_index: $first_index,
          second_index: $second_index,
          key: [
            $similarity,
            -$combined_size,
            -$earliest_index,
            -$latest_index,
            -$first_index
          ]
        }
    ];

  def merge_once($clusters; $terms):
    (candidate_pairs($clusters; $terms) | max_by(.key)) as $best
    | ($clusters[$best.first_index]) as $first
    | ($clusters[$best.second_index]) as $second
    | (
        [
          range(0; $clusters | length) as $index
          | select($index != $best.first_index and $index != $best.second_index)
          | $clusters[$index]
        ]
        + [{
            members: ($first.members + $second.members),
            first_index: ([$first.first_index, $second.first_index] | min)
          }]
      )
    | sort_by(.first_index);

  (.participants // []) as $participants
  | if $group_count <= 0 or ($participants | length) == 0 then
      {groups: []}
    else
      (reduce $participants[] as $participant (
        {};
        .[$participant.user_id] = ($participant | participant_terms)
      )) as $terms
      | [
          $participants
          | to_entries[]
          | {members: [.value.user_id], first_index: .key}
        ] as $initial_clusters
      | ([$group_count, ($initial_clusters | length)] | min) as $target_count
      | (
          $initial_clusters
          | until(length <= $target_count; merge_once(.; $terms))
        ) as $clusters
      | {
          groups: (
            [
              $clusters
              | to_entries[]
              | {group_id: (.key + 1), members: .value.members}
            ]
            + [
                range(($clusters | length) + 1; $group_count + 1)
                | {group_id: ., members: []}
              ]
          )
        }
    end
' "$session_file"
