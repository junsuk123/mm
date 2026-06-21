#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
DATA_ROOT=${MM_ENTERPRISE_DATA_ROOT:-"$PROJECT_ROOT/enterprise_analytics"}
SESSIONS_DIR="$DATA_ROOT/sessions"
ARCHIVES_DIR="$DATA_ROOT/archives"
EXPORTER="$PROJECT_ROOT/src/enterprise_analytics.py"

usage() {
  cat <<'EOF'
Usage:
  sh scripts/enterprise_data.sh export --input RESULT.json [--session-id ID]
  sh scripts/enterprise_data.sh list
  sh scripts/enterprise_data.sh inspect SESSION_ID
  sh scripts/enterprise_data.sh verify [SESSION_ID]
  sh scripts/enterprise_data.sh archive SESSION_ID
  sh scripts/enterprise_data.sh archive SESSION_ID --include-restricted --confirm-legal-review
  sh scripts/enterprise_data.sh delete SESSION_ID --yes

Environment:
  MM_ENTERPRISE_DATA_ROOT  Export root (default: ./enterprise_analytics)
  PYTHON                   Python command (default: .venv/bin/python or python3)
EOF
}

if [ -n "${PYTHON:-}" ]; then
  PYTHON_CMD=$PYTHON
elif [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
  PYTHON_CMD="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_CMD=python3
fi

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf '%s\n' "Missing required command: $1" >&2
    exit 1
  }
}

validate_session_id() {
  case $1 in
    ''|*[!A-Za-z0-9_-]*)
      printf '%s\n' "Invalid session ID: $1" >&2
      exit 1
      ;;
  esac
}

verify_session_dir() {
  session_dir=$1
  for filename in \
    analysis_summary.json \
    participants_anonymized.csv \
    groups.csv \
    recommendations.csv \
    release_manifest.json \
    SUBMISSION_README.md
  do
    [ -s "$session_dir/$filename" ] || {
      printf '%s\n' "Missing or empty file: $session_dir/$filename" >&2
      return 1
    }
  done

  jq -e '
    .privacy.participant_names_removed == true
    and .privacy.device_ids_removed == true
    and (.session.participant_count | type == "number")
    and (.groups | type == "array")
  ' "$session_dir/analysis_summary.json" >/dev/null

  jq -e '
    (.default_external_files | index("analysis_summary.json")) != null
    and
    ((.restricted_files | index("participants_anonymized.csv")) != null)
  ' "$session_dir/release_manifest.json" >/dev/null

  if rg -n \
    '("device_id"|"display_name"|"original_user_id"|"join_url"|"mapx"|"mapy"|"submitted_at")' \
    "$session_dir/analysis_summary.json" \
    "$session_dir/groups.csv" \
    "$session_dir/recommendations.csv" >/dev/null 2>&1
  then
    printf '%s\n' "Potential identifier field found in external-candidate files: $session_dir" >&2
    return 1
  fi
}

mkdir -p "$SESSIONS_DIR" "$ARCHIVES_DIR"
require_command jq
require_command rg

command_name=${1:-}
[ -n "$command_name" ] || {
  usage
  exit 1
}
shift

case $command_name in
  export)
    input=
    session_id=
    while [ "$#" -gt 0 ]; do
      case $1 in
        --input)
          shift
          [ "$#" -gt 0 ] || { usage; exit 1; }
          input=$1
          ;;
        --session-id)
          shift
          [ "$#" -gt 0 ] || { usage; exit 1; }
          session_id=$1
          ;;
        *)
          usage
          exit 1
          ;;
      esac
      shift
    done
    [ -f "$input" ] || {
      printf '%s\n' "Result JSON not found: $input" >&2
      exit 1
    }
    if [ -n "$session_id" ]; then
      validate_session_id "$session_id"
      output_dir=$("$PYTHON_CMD" "$EXPORTER" \
        --input "$input" \
        --session-id "$session_id" \
        --output-root "$SESSIONS_DIR")
    else
      output_dir=$("$PYTHON_CMD" "$EXPORTER" \
        --input "$input" \
        --output-root "$SESSIONS_DIR")
    fi
    verify_session_dir "$output_dir"
    printf '%s\n' "$output_dir"
    ;;

  list)
    find "$SESSIONS_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort
    ;;

  inspect)
    session_id=${1:-}
    validate_session_id "$session_id"
    session_dir="$SESSIONS_DIR/$session_id"
    [ -d "$session_dir" ] || {
      printf '%s\n' "Session analytics not found: $session_id" >&2
      exit 1
    }
    jq '{
      session_id,
      generated_at,
      session,
      aggregates,
      groups: [.groups[] | {
        group_id,
        member_count,
        shared_preference_count,
        recommended_restaurant,
        recommendation_score
      }]
    }' "$session_dir/analysis_summary.json"
    ;;

  verify)
    session_id=${1:-}
    if [ -n "$session_id" ]; then
      validate_session_id "$session_id"
      verify_session_dir "$SESSIONS_DIR/$session_id"
      printf '%s\n' "Verified: $session_id"
    else
      found=false
      for session_dir in "$SESSIONS_DIR"/*; do
        [ -d "$session_dir" ] || continue
        found=true
        verify_session_dir "$session_dir"
        printf '%s\n' "Verified: $(basename "$session_dir")"
      done
      [ "$found" = true ] || printf '%s\n' "No enterprise analytics sessions."
    fi
    ;;

  archive)
    session_id=${1:-}
    include_restricted=${2:-}
    legal_confirmation=${3:-}
    validate_session_id "$session_id"
    session_dir="$SESSIONS_DIR/$session_id"
    [ -d "$session_dir" ] || {
      printf '%s\n' "Session analytics not found: $session_id" >&2
      exit 1
    }
    verify_session_dir "$session_dir"
    require_command tar
    require_command sha256sum
    timestamp=$(date -u +%Y%m%dT%H%M%SZ)
    if [ -z "$include_restricted" ]; then
      archive="$ARCHIVES_DIR/${session_id}_${timestamp}_external.tar.gz"
      tar -C "$session_dir" -czf "$archive" \
        analysis_summary.json \
        groups.csv \
        recommendations.csv \
        release_manifest.json \
        SUBMISSION_README.md
    elif [ "$include_restricted" = "--include-restricted" ] \
      && [ "$legal_confirmation" = "--confirm-legal-review" ]
    then
      archive="$ARCHIVES_DIR/${session_id}_${timestamp}_restricted.tar.gz"
      tar -C "$SESSIONS_DIR" -czf "$archive" "$session_id"
    else
      printf '%s\n' \
        "Restricted archive requires --include-restricted --confirm-legal-review" >&2
      exit 1
    fi
    sha256sum "$archive" > "$archive.sha256"
    printf '%s\n' "$archive"
    ;;

  delete)
    session_id=${1:-}
    confirm=${2:-}
    validate_session_id "$session_id"
    [ "$confirm" = "--yes" ] || {
      printf '%s\n' "Deletion requires --yes" >&2
      exit 1
    }
    session_dir="$SESSIONS_DIR/$session_id"
    [ -d "$session_dir" ] || {
      printf '%s\n' "Session analytics not found: $session_id" >&2
      exit 1
    }
    rm -rf -- "$session_dir"
    printf '%s\n' "Deleted: $session_id"
    ;;

  -h|--help|help)
    usage
    ;;

  *)
    usage
    exit 1
    ;;
esac
