#!/usr/bin/env python3
"""
실시간 식당 추천 시스템 웹 GUI
Flask 기반 대시보드로 사용자 입력 수집 및 실시간 시각화
"""

from flask import Flask, render_template, request, jsonify
from contextlib import contextmanager
import fcntl
import hashlib
import json
import subprocess
import os
import re
import shlex
import shutil
import sys
import tempfile
import threading
import time
import webbrowser
import socket
from datetime import datetime
import uuid

from naver_restaurant_api import search_restaurants

SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SOURCE_DIR)
DATASET_DIR = os.path.join(BASE_DIR, 'dataset')
MOBILE_SESSIONS_FILE = os.path.join(DATASET_DIR, 'mobile_sessions.json')
DEMO_SESSION_FILE = os.path.join(DATASET_DIR, 'demo_session.json')
MOCK_RESTAURANTS_FILE = os.path.join(DATASET_DIR, 'mock_restaurants.json')
ALIAS_WORDS_FILE = os.path.join(DATASET_DIR, 'alias_words.json')
PARTICIPANTS_DIR = os.path.join(DATASET_DIR, 'participants')
DEVICE_INDEX_FILE = os.path.join(DATASET_DIR, 'device_index.json')
PARTICIPANT_LOCK_FILE = os.path.join(DATASET_DIR, '.participants.lock')
DEMO_PARTICIPANT_COUNT = 10
DEMO_SESSION_ID = 'demo-baseline'
DEMO_TIMESTAMP = '2026-06-20T00:00:00'
DEVICE_ID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$')
PARTICIPANT_ID_PATTERN = re.compile(r'^U[0-9]{4}$')
LEGACY_AUTO_ALIAS_PATTERN = re.compile(r'^M[0-9]+$')

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))
app.secret_key = 'restaurant-recommendation-secret-key'

# 임시 세션 데이터 저장소
sessions_store = {}
cli_jobs = {}
cli_jobs_lock = threading.Lock()
cli_events = []
cli_events_lock = threading.Lock()
cli_event_next_id = 0
participant_records_lock = threading.Lock()

@contextmanager
def participant_file_lock():
    """여러 Flask 프로세스에서도 기기 폴더 생성·수정을 직렬화한다."""
    os.makedirs(DATASET_DIR, exist_ok=True)
    with open(PARTICIPANT_LOCK_FILE, 'a+', encoding='utf-8') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

def sanitize_cli_text(text):
    """사용자 PC의 절대 경로를 웹 로그에 노출하지 않는다."""
    value = str(text)
    value = value.replace(BASE_DIR + os.sep, './').replace(BASE_DIR, '.')
    value = value.replace(os.path.expanduser('~') + os.sep, '~/')
    value = re.sub(r'/tmp/(?:mm-web-session|recommend-[A-Za-z0-9-]+)\.[A-Za-z0-9]+(?:\.json)?', '<임시파일>', value)
    return value

def append_cli_event(event_type, text):
    """웹 터미널에 표시할 서버 전체 CLI 이벤트."""
    global cli_event_next_id
    with cli_events_lock:
        cli_events.append({
            'id': cli_event_next_id,
            'time': datetime.now().isoformat(timespec='seconds'),
            'type': event_type,
            'text': sanitize_cli_text(text)
        })
        cli_event_next_id += 1
        # 개발 서버를 오래 켜 두어도 메모리가 계속 늘어나지 않게 제한한다.
        if len(cli_events) > 5000:
            del cli_events[:1000]

append_cli_event(
    'command',
    ' '.join(shlex.quote(part) for part in ['./.venv/bin/python', *sys.argv])
)
append_cli_event('output', 'Flask 서버가 프로젝트 디렉터리에서 시작되었습니다.')

def load_mobile_sessions():
    """Persisted QR/mobile collection data."""
    if not os.path.exists(MOBILE_SESSIONS_FILE):
        return {'latest_session_id': None, 'sessions': {}}
    try:
        with open(MOBILE_SESSIONS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data.setdefault('latest_session_id', None)
        data.setdefault('sessions', {})
        return data
    except (OSError, json.JSONDecodeError):
        return {'latest_session_id': None, 'sessions': {}}

def save_mobile_sessions(data):
    os.makedirs(DATASET_DIR, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix='mobile_sessions.', suffix='.json', dir=DATASET_DIR)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(temp_path, MOBILE_SESSIONS_FILE)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

def save_json_atomic(path, data):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix='.write-', suffix='.json', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

def validate_device_id(value):
    device_id = str(value or '').strip()
    return device_id if DEVICE_ID_PATTERN.fullmatch(device_id) else ''

def participant_directory(participant_id):
    return os.path.join(PARTICIPANTS_DIR, participant_id)

def participant_profile_path(participant_id):
    return os.path.join(participant_directory(participant_id), 'profile.json')

def participant_device_path(participant_id):
    return os.path.join(participant_directory(participant_id), 'device.json')

def participant_meals_directory(participant_id):
    return os.path.join(participant_directory(participant_id), 'meals')

def participant_recommendations_directory(participant_id):
    return os.path.join(participant_directory(participant_id), 'recommendations')

def participant_exclusions_path(participant_id):
    return os.path.join(participant_directory(participant_id), 'exclusions.json')

def participant_session_access_path(participant_id):
    return os.path.join(participant_directory(participant_id), 'session_access.json')

def participant_location_settings_path(participant_id):
    return os.path.join(participant_directory(participant_id), 'location_settings.json')

def load_json_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

def load_participant_profile(participant_id):
    if not PARTICIPANT_ID_PATTERN.fullmatch(str(participant_id or '')):
        return None
    return load_json_file(participant_profile_path(participant_id))

def load_participant_device(participant_id):
    if not PARTICIPANT_ID_PATTERN.fullmatch(str(participant_id or '')):
        return None
    return load_json_file(participant_device_path(participant_id))

def load_alias_words():
    data = load_json_file(ALIAS_WORDS_FILE) or {}
    adjectives = [
        str(value).strip()
        for value in data.get('adjectives', [])
        if str(value).strip()
    ]
    animals = [
        str(value).strip()
        for value in data.get('animals', [])
        if str(value).strip()
    ]
    if len(adjectives) != 100 or len(set(adjectives)) != 100:
        raise ValueError('alias_words.json must contain 100 unique adjectives')
    if len(animals) != 100 or len(set(animals)) != 100:
        raise ValueError('alias_words.json must contain 100 unique animals')
    return adjectives, animals

def used_participant_names(exclude_participant_id=''):
    names = set()
    if not os.path.isdir(PARTICIPANTS_DIR):
        return names
    for participant_id in os.listdir(PARTICIPANTS_DIR):
        if participant_id == exclude_participant_id:
            continue
        if not PARTICIPANT_ID_PATTERN.fullmatch(participant_id):
            continue
        profile = load_participant_profile(participant_id) or {}
        name = str(profile.get('user_id') or '').strip()
        if name:
            names.add(name)
    return names

def generate_device_alias(device_id, participant_id=''):
    adjectives, animals = load_alias_words()
    used_names = used_participant_names(participant_id)
    digest = hashlib.sha256(device_id.encode('utf-8')).digest()
    start_index = int.from_bytes(digest[:4], 'big') % 10000
    for offset in range(10000):
        combination_index = (start_index + offset) % 10000
        adjective = adjectives[combination_index // 100]
        animal = animals[combination_index % 100]
        alias = f'{adjective} {animal}'
        if alias not in used_names:
            return alias
    raise ValueError('No automatic aliases are available')

def resolve_participant_display_name(
    requested_name,
    device_id,
    participant_id='',
    previous_profile=None
):
    requested_name = str(requested_name or '').strip()
    previous_profile = previous_profile or {}
    previous_name = str(previous_profile.get('user_id') or '').strip()
    previous_was_auto = bool(previous_profile.get('auto_generated_name', False))
    previous_was_legacy = bool(
        previous_name and LEGACY_AUTO_ALIAS_PATTERN.fullmatch(previous_name)
    )
    if requested_name and requested_name != previous_name:
        return requested_name, False
    if previous_was_auto and previous_name:
        return previous_name, True
    if previous_was_legacy:
        return generate_device_alias(device_id, participant_id), True
    if requested_name:
        return requested_name, False
    if previous_name:
        return previous_name, False
    return generate_device_alias(device_id, participant_id), True

def migrate_legacy_auto_aliases():
    """M01 형태의 기존 자동 이름을 새 동물 별칭으로 교체한다."""
    migrated = []
    if not os.path.isdir(PARTICIPANTS_DIR):
        return migrated
    with participant_records_lock:
        with participant_file_lock():
            for participant_id in sorted(os.listdir(PARTICIPANTS_DIR)):
                if not PARTICIPANT_ID_PATTERN.fullmatch(participant_id):
                    continue
                profile = load_participant_profile(participant_id) or {}
                if profile.get('source') != 'mobile':
                    continue
                current_name = str(profile.get('user_id') or '').strip()
                if not LEGACY_AUTO_ALIAS_PATTERN.fullmatch(current_name):
                    continue
                device = load_participant_device(participant_id) or {}
                device_id = validate_device_id(device.get('device_identifier'))
                if not device_id:
                    continue
                profile['user_id'] = generate_device_alias(device_id, participant_id)
                profile['auto_generated_name'] = True
                profile['updated_at'] = datetime.now().isoformat()
                save_json_atomic(participant_profile_path(participant_id), profile)
                migrated.append(participant_id)
    return migrated

def participant_updated_at(participant_id):
    profile = load_participant_profile(participant_id) or {}
    device = load_participant_device(participant_id) or {}
    return max(
        str(profile.get('updated_at') or profile.get('created_at') or ''),
        str(device.get('updated_at') or '')
    )

def scan_device_participant_ids(device_id):
    matches = []
    if not os.path.isdir(PARTICIPANTS_DIR):
        return matches
    for participant_id in sorted(os.listdir(PARTICIPANTS_DIR)):
        if not PARTICIPANT_ID_PATTERN.fullmatch(participant_id):
            continue
        device = load_participant_device(participant_id) or {}
        if device.get('device_identifier') == device_id:
            matches.append(participant_id)
    return matches

def load_device_index():
    data = load_json_file(DEVICE_INDEX_FILE) or {}
    devices = data.get('devices', {})
    return devices if isinstance(devices, dict) else {}

def save_device_index(devices):
    save_json_atomic(DEVICE_INDEX_FILE, {
        'updated_at': datetime.now().isoformat(),
        'devices': devices
    })

def merge_json_directory(source_dir, target_dir):
    if not os.path.isdir(source_dir):
        return
    os.makedirs(target_dir, exist_ok=True)
    for filename in os.listdir(source_dir):
        source_path = os.path.join(source_dir, filename)
        if not os.path.isfile(source_path):
            continue
        target_path = os.path.join(target_dir, filename)
        if os.path.exists(target_path):
            stem, extension = os.path.splitext(filename)
            target_path = os.path.join(
                target_dir,
                f'{stem}_merged_{uuid.uuid4().hex[:8]}{extension}'
            )
        shutil.copy2(source_path, target_path)

def remap_participant_id_in_sessions(source_participant_id, target_participant_id):
    mobile_data = load_mobile_sessions()
    changed = False
    for session in mobile_data.get('sessions', {}).values():
        participants = session.get('participants', [])
        rewritten = []
        seen_ids = set()
        for participant in participants:
            participant = dict(participant)
            if (
                participant.get('participant_id') == source_participant_id
                or participant.get('user_id') == source_participant_id
            ):
                participant['participant_id'] = target_participant_id
                participant['user_id'] = target_participant_id
                changed = True
            participant_id = participant.get('participant_id') or participant.get('user_id')
            if participant_id in seen_ids:
                changed = True
                continue
            seen_ids.add(participant_id)
            rewritten.append(participant)
        session['participants'] = rewritten
        session['selected_participant_ids'] = list(dict.fromkeys(
            target_participant_id if value == source_participant_id else value
            for value in session.get('selected_participant_ids', [])
        ))
    if changed:
        save_mobile_sessions(mobile_data)

    for session in sessions_store.values():
        participants = session.get('participants', [])
        rewritten = []
        seen_ids = set()
        for participant in participants:
            participant = dict(participant)
            if (
                participant.get('participant_id') == source_participant_id
                or participant.get('user_id') == source_participant_id
            ):
                participant['participant_id'] = target_participant_id
                participant['user_id'] = target_participant_id
            participant_id = participant.get('participant_id') or participant.get('user_id')
            if participant_id in seen_ids:
                continue
            seen_ids.add(participant_id)
            rewritten.append(participant)
        session['participants'] = rewritten

def merge_meal_records(target_participant_id, source_participant_id):
    dates = set()
    for participant_id in (target_participant_id, source_participant_id):
        meals_dir = participant_meals_directory(participant_id)
        if not os.path.isdir(meals_dir):
            continue
        dates.update(
            filename[:-5]
            for filename in os.listdir(meals_dir)
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}\.json', filename)
        )

    for date in dates:
        target_path = os.path.join(
            participant_meals_directory(target_participant_id),
            f'{date}.json'
        )
        source_path = os.path.join(
            participant_meals_directory(source_participant_id),
            f'{date}.json'
        )
        target = load_json_file(target_path) or {
            'participant_id': target_participant_id,
            'date': date,
            'meals': {}
        }
        source = load_json_file(source_path) or {'meals': {}}
        for meal_type, candidate in source.get('meals', {}).items():
            existing = target.get('meals', {}).get(meal_type)
            if (
                not isinstance(existing, dict)
                or str(candidate.get('submitted_at') or '')
                >= str(existing.get('submitted_at') or '')
            ):
                target.setdefault('meals', {})[meal_type] = candidate
        latest = max(
            (
                str(meal.get('submitted_at') or '')
                for meal in target.get('meals', {}).values()
                if isinstance(meal, dict)
            ),
            default=''
        )
        target['participant_id'] = target_participant_id
        target['updated_at'] = latest
        save_json_atomic(target_path, target)

def merge_participant_folders(target_participant_id, source_participant_id):
    if target_participant_id == source_participant_id:
        return
    target_profile = load_participant_profile(target_participant_id) or {}
    source_profile = load_participant_profile(source_participant_id) or {}
    if str(source_profile.get('updated_at') or '') > str(target_profile.get('updated_at') or ''):
        source_profile['created_at'] = min(
            filter(None, [
                str(target_profile.get('created_at') or ''),
                str(source_profile.get('created_at') or '')
            ]),
            default=str(source_profile.get('created_at') or '')
        )
        save_json_atomic(participant_profile_path(target_participant_id), source_profile)

    merge_meal_records(target_participant_id, source_participant_id)
    merge_json_directory(
        os.path.join(participant_directory(source_participant_id), 'submissions'),
        os.path.join(participant_directory(target_participant_id), 'submissions')
    )
    merge_json_directory(
        participant_recommendations_directory(source_participant_id),
        participant_recommendations_directory(target_participant_id)
    )

    exclusions = load_participant_exclusions(target_participant_id)
    for exclusion in load_participant_exclusions(source_participant_id):
        if not any(restaurant_matches(existing, exclusion) for existing in exclusions):
            exclusions.append(exclusion)
    save_json_atomic(participant_exclusions_path(target_participant_id), {
        'participant_id': target_participant_id,
        'restaurants': exclusions,
        'updated_at': datetime.now().isoformat()
    })

    target_location = load_participant_location_settings(target_participant_id)
    source_location = load_participant_location_settings(source_participant_id)
    if (
        str(source_location.get('updated_at') or '')
        > str(target_location.get('updated_at') or '')
    ):
        save_json_atomic(
            participant_location_settings_path(target_participant_id),
            {
                **source_location,
                'participant_id': target_participant_id
            }
        )

    access = load_participant_session_access(target_participant_id)
    source_access = load_participant_session_access(source_participant_id)
    sessions = {
        entry.get('session_id'): entry
        for entry in access.get('sessions', [])
        if entry.get('session_id')
    }
    for entry in source_access.get('sessions', []):
        session_id = entry.get('session_id')
        if not session_id:
            continue
        existing = sessions.get(session_id)
        if not existing or str(entry.get('last_accessed_at') or '') > str(existing.get('last_accessed_at') or ''):
            sessions[session_id] = entry
    access['participant_id'] = target_participant_id
    access['sessions'] = sorted(
        sessions.values(),
        key=lambda entry: str(entry.get('last_accessed_at') or '')
    )
    save_json_atomic(participant_session_access_path(target_participant_id), access)

    remap_participant_id_in_sessions(source_participant_id, target_participant_id)
    shutil.rmtree(participant_directory(source_participant_id))

def resolve_participant_id_for_device(device_id, create=False):
    """기기 UUID를 정확히 하나의 사용자 폴더로 해석하고 중복 폴더를 병합한다."""
    device_id = validate_device_id(device_id)
    if not device_id:
        return ''

    devices = load_device_index()
    indexed_id = str(devices.get(device_id) or '')
    matches = scan_device_participant_ids(device_id)
    if indexed_id and indexed_id not in matches:
        indexed_device = load_participant_device(indexed_id) or {}
        if indexed_device.get('device_identifier') == device_id:
            matches.append(indexed_id)
    matches = sorted(set(matches))

    if matches:
        canonical_id = min(matches, key=lambda participant_id: int(participant_id[1:]))
        for duplicate_id in matches:
            if duplicate_id != canonical_id:
                merge_participant_folders(canonical_id, duplicate_id)
        devices[device_id] = canonical_id
        save_device_index(devices)
        return canonical_id

    if not create:
        return ''
    participant_id = next_participant_id()
    devices[device_id] = participant_id
    save_device_index(devices)
    return participant_id

def ensure_unique_device_participants():
    """전체 기기 인덱스를 재구축하고 발견된 중복 폴더를 한 번에 병합한다."""
    with participant_records_lock:
        with participant_file_lock():
            device_ids = []
            if os.path.isdir(PARTICIPANTS_DIR):
                for participant_id in sorted(os.listdir(PARTICIPANTS_DIR)):
                    if not PARTICIPANT_ID_PATTERN.fullmatch(participant_id):
                        continue
                    device = load_participant_device(participant_id) or {}
                    device_id = validate_device_id(device.get('device_identifier'))
                    if device_id and device_id not in device_ids:
                        device_ids.append(device_id)
            devices = {}
            for device_id in device_ids:
                participant_id = resolve_participant_id_for_device(device_id)
                if participant_id:
                    devices[device_id] = participant_id
            save_device_index(devices)
            return devices

def load_participant_exclusions(participant_id):
    data = load_json_file(participant_exclusions_path(participant_id)) or {}
    restaurants = data.get('restaurants', [])
    if not isinstance(restaurants, list):
        restaurants = []
    return [item for item in restaurants if isinstance(item, dict)]

def load_participant_recommendations(participant_id):
    recommendation_dir = participant_recommendations_directory(participant_id)
    if not os.path.isdir(recommendation_dir):
        return []
    records = []
    for filename in sorted(os.listdir(recommendation_dir), reverse=True):
        if not filename.endswith('.json'):
            continue
        record = load_json_file(os.path.join(recommendation_dir, filename))
        if isinstance(record, dict):
            records.append(record)
    return records

def navigation_feature_enabled():
    return str(
        os.environ.get('MM_NAVER_DIRECTIONS_ENABLED', '1')
    ).strip().lower() not in ('0', 'false', 'no', 'off')

def load_participant_location_settings(participant_id):
    data = load_json_file(participant_location_settings_path(participant_id)) or {}
    consent_status = str(data.get('consent_status') or 'unknown')
    if consent_status not in ('unknown', 'granted', 'denied'):
        consent_status = 'unknown'
    return {
        'participant_id': participant_id,
        'enabled': bool(data.get('enabled', True)),
        'consent_status': consent_status,
        'consented_at': data.get('consented_at'),
        'updated_at': data.get('updated_at')
    }

def navigation_settings_payload(participant_id):
    settings = load_participant_location_settings(participant_id)
    return {
        **settings,
        'global_enabled': navigation_feature_enabled(),
        'effective_enabled': (
            navigation_feature_enabled()
            and settings['enabled']
            and settings['consent_status'] == 'granted'
        )
    }

def save_participant_location_settings(
    participant_id,
    *,
    enabled=None,
    consent_status=None
):
    settings = load_participant_location_settings(participant_id)
    now = datetime.now().isoformat()
    if enabled is not None:
        settings['enabled'] = bool(enabled)
    if consent_status is not None:
        if consent_status not in ('unknown', 'granted', 'denied'):
            raise ValueError('Invalid location consent status')
        settings['consent_status'] = consent_status
        if consent_status in ('granted', 'denied'):
            settings['consented_at'] = now
    settings['updated_at'] = now
    save_json_atomic(participant_location_settings_path(participant_id), settings)
    return navigation_settings_payload(participant_id)

def load_recommendation_for_session(participant_id, session_id):
    if not session_id:
        return None
    for record in load_participant_recommendations(participant_id):
        if record.get('session_id') != session_id:
            continue
        if record.get('feedback', {}).get('status', 'pending') != 'pending':
            continue
        return record
    return None

def legacy_session_access_entries(participant_id):
    entries_by_session = {}

    submission_dir = os.path.join(participant_directory(participant_id), 'submissions')
    if os.path.isdir(submission_dir):
        for filename in sorted(os.listdir(submission_dir)):
            if not filename.endswith('.json'):
                continue
            record = load_json_file(os.path.join(submission_dir, filename))
            if not isinstance(record, dict):
                continue
            session_id = str(record.get('session_id') or '').strip()
            accessed_at = str(
                record.get('submitted_at')
                or record.get('updated_at')
                or record.get('created_at')
                or ''
            ).strip()
            if session_id:
                entries_by_session[session_id] = {
                    'session_id': session_id,
                    'first_accessed_at': accessed_at,
                    'last_accessed_at': accessed_at,
                    'access_count': 1,
                    'source': 'submission_migration'
                }

    for recommendation in reversed(load_participant_recommendations(participant_id)):
        session_id = str(recommendation.get('session_id') or '').strip()
        accessed_at = str(recommendation.get('recommended_at') or '').strip()
        if not session_id or session_id in entries_by_session:
            continue
        entries_by_session[session_id] = {
            'session_id': session_id,
            'first_accessed_at': accessed_at,
            'last_accessed_at': accessed_at,
            'access_count': 1,
            'source': 'recommendation_migration'
        }

    return sorted(
        entries_by_session.values(),
        key=lambda item: item.get('last_accessed_at', '')
    )

def load_participant_session_access(participant_id):
    data = load_json_file(participant_session_access_path(participant_id))
    if isinstance(data, dict) and isinstance(data.get('sessions'), list):
        return data
    return {
        'participant_id': participant_id,
        'sessions': legacy_session_access_entries(participant_id)
    }

def previous_visited_session_id(participant_id, current_session_id):
    sessions = load_participant_session_access(participant_id).get('sessions', [])
    for entry in reversed(sessions):
        session_id = str(entry.get('session_id') or '').strip()
        if session_id and session_id != current_session_id:
            return session_id
    return ''

def record_session_access(participant_id, session_id, device_id='', source='qr'):
    session_id = str(session_id or '').strip()
    if not session_id:
        return load_participant_session_access(participant_id)

    now = datetime.now().isoformat()
    data = load_participant_session_access(participant_id)
    sessions = [
        entry for entry in data.get('sessions', [])
        if isinstance(entry, dict) and entry.get('session_id')
    ]
    matching = next(
        (entry for entry in sessions if entry.get('session_id') == session_id),
        None
    )
    if matching:
        matching['last_accessed_at'] = now
        matching['access_count'] = int(matching.get('access_count', 0)) + 1
        matching['source'] = source
    else:
        sessions.append({
            'session_id': session_id,
            'first_accessed_at': now,
            'last_accessed_at': now,
            'access_count': 1,
            'source': source
        })

    data.update({
        'participant_id': participant_id,
        'device_identifier': validate_device_id(device_id),
        'sessions': sessions,
        'last_session_id': session_id,
        'updated_at': now
    })
    save_json_atomic(participant_session_access_path(participant_id), data)
    return data

def list_participant_records():
    records = []
    if not os.path.isdir(PARTICIPANTS_DIR):
        return records
    for participant_id in sorted(os.listdir(PARTICIPANTS_DIR)):
        if not PARTICIPANT_ID_PATTERN.fullmatch(participant_id):
            continue
        profile = load_participant_profile(participant_id)
        device = load_participant_device(participant_id)
        if not profile or not device:
            continue
        submission_dir = os.path.join(participant_directory(participant_id), 'submissions')
        submission_count = len([
            name for name in os.listdir(submission_dir)
            if name.endswith('.json')
        ]) if os.path.isdir(submission_dir) else 0
        records.append({
            'participant_id': participant_id,
            'user_id': profile.get('user_id', ''),
            'source': profile.get('source', 'mobile'),
            'updated_at': profile.get('updated_at', ''),
            'submission_count': submission_count,
            'meal_day_count': len(load_participant_meals(participant_id)),
            'exclusion_count': len(load_participant_exclusions(participant_id)),
            'recommendation_count': len(load_participant_recommendations(participant_id)),
            'session_access_count': len(
                load_participant_session_access(participant_id).get('sessions', [])
            ),
            'files': [
                'device.json',
                'profile.json',
                'exclusions.json',
                'location_settings.json',
                'session_access.json',
                'meals/',
                'recommendations/',
                'submissions/'
            ]
        })
    return records

def find_participant_id_by_device(device_id):
    device_id = validate_device_id(device_id)
    if not device_id:
        return ''
    with participant_records_lock:
        with participant_file_lock():
            return resolve_participant_id_for_device(device_id)

def next_participant_id():
    highest = 0
    if os.path.isdir(PARTICIPANTS_DIR):
        for name in os.listdir(PARTICIPANTS_DIR):
            if PARTICIPANT_ID_PATTERN.fullmatch(name):
                highest = max(highest, int(name[1:]))
    return f'U{highest + 1:04d}'

def load_profile_by_device(device_id):
    participant_id = find_participant_id_by_device(device_id)
    if not participant_id:
        return None
    profile = load_participant_profile(participant_id)
    if not profile:
        return None
    return {'participant_id': participant_id, **profile}

def normalize_meal_data(data):
    meal_type = str(data.get('meal_type') or '').strip()
    if meal_type not in ('lunch', 'dinner'):
        raise ValueError('Select lunch or dinner')
    return {
        'date': datetime.now().date().isoformat(),
        'meal_type': meal_type
    }

def load_participant_meals(participant_id):
    meals_dir = participant_meals_directory(participant_id)
    if not os.path.isdir(meals_dir):
        return []
    records = []
    for filename in sorted(os.listdir(meals_dir), reverse=True):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}\.json', filename):
            continue
        record = load_json_file(os.path.join(meals_dir, filename))
        if record:
            records.append(record)
    return records

def save_participant_meals(participant_id, participant, session_id, submitted_at):
    meal_data = participant.get('meal_data')
    if not meal_data:
        return None
    path = os.path.join(participant_meals_directory(participant_id), f"{meal_data['date']}.json")
    record = load_json_file(path) or {
        'participant_id': participant_id,
        'date': meal_data['date'],
        'meals': {}
    }
    meal_type = meal_data['meal_type']
    existing = record.get('meals', {}).get(meal_type)
    if (
        isinstance(existing, dict)
        and str(existing.get('submitted_at') or '') > str(submitted_at or '')
    ):
        return record
    record.setdefault('meals', {})[meal_type] = {
        'submitted_at': submitted_at,
        'session_id': session_id,
        'preferences': participant.get('preferences', {})
    }
    record['updated_at'] = max(
        (
            str(meal.get('submitted_at') or '')
            for meal in record['meals'].values()
            if isinstance(meal, dict)
        ),
        default=str(submitted_at or '')
    )
    record['session_id'] = session_id
    save_json_atomic(path, record)
    return record

def save_participant_record(participant, session_id):
    device_id = validate_device_id(participant.get('device_id'))
    if not device_id:
        raise ValueError('Invalid device ID')

    with participant_records_lock:
        with participant_file_lock():
            participant_id = resolve_participant_id_for_device(device_id, create=True)
            now = datetime.now().isoformat()
            submitted_at = str(participant.get('submitted_at') or now)
            previous = load_participant_profile(participant_id) or {}
            display_name, auto_generated_name = resolve_participant_display_name(
                participant.get('user_id'),
                device_id,
                participant_id,
                previous
            )
            should_update_profile = (
                not previous
                or submitted_at >= str(previous.get('updated_at') or '')
            )
            profile = previous
            if should_update_profile:
                profile = {
                    'user_id': display_name,
                    'auto_generated_name': auto_generated_name,
                    'source': participant.get('source', 'mobile'),
                    'created_at': previous.get('created_at', submitted_at),
                    'updated_at': submitted_at,
                    'preferences': participant.get('preferences', {})
                }
            device = {
                'identifier_type': 'browser_uuid',
                'device_identifier': device_id,
                'updated_at': now
            }
            if should_update_profile:
                save_json_atomic(participant_profile_path(participant_id), profile)
            save_json_atomic(participant_device_path(participant_id), device)

            submission_dir = os.path.join(participant_directory(participant_id), 'submissions')
            timestamp = datetime.now().strftime('%Y%m%dT%H%M%S%f')
            submission = {
                'participant_id': participant_id,
                'user_id': display_name,
                'auto_generated_name': auto_generated_name,
                'source': participant.get('source', 'mobile'),
                'created_at': profile.get('created_at', submitted_at),
                'updated_at': submitted_at,
                'preferences': participant.get('preferences', {}),
                'session_id': session_id,
                'submitted_at': submitted_at,
                'meal_data': participant.get('meal_data')
            }
            save_json_atomic(
                os.path.join(submission_dir, f'{timestamp}_{session_id}.json'),
                submission
            )
            save_participant_meals(
                participant_id,
                participant,
                session_id,
                submitted_at
            )
            record_session_access(
                participant_id,
                session_id,
                device_id,
                source='survey_submission'
            )
            participant['participant_id'] = participant_id
            participant['display_name'] = profile.get('user_id', '')
            participant['user_id'] = participant_id
            participant['submitted_at'] = profile.get('updated_at', submitted_at)
            participant['preferences'] = profile.get('preferences', {})
            participant['excluded_restaurants'] = load_participant_exclusions(participant_id)
            return participant_id

def restaurant_matches(first, second):
    first_id = str(first.get('restaurant_id') or '').strip()
    second_id = str(second.get('restaurant_id') or '').strip()
    if first_id and second_id and first_id == second_id:
        return True
    return (
        str(first.get('name') or '').strip() == str(second.get('name') or '').strip()
        and str(first.get('address') or '').strip() == str(second.get('address') or '').strip()
        and bool(str(first.get('name') or '').strip())
    )

def save_restaurant_exclusion(participant_id, restaurant, recommendation_id):
    now = datetime.now().isoformat()
    exclusion = {
        'restaurant_id': str(restaurant.get('restaurant_id') or '').strip(),
        'name': str(restaurant.get('name') or '').strip(),
        'address': str(restaurant.get('address') or '').strip(),
        'category': str(restaurant.get('category') or '').strip(),
        'food': str(restaurant.get('food') or '').strip(),
        'excluded_at': now,
        'recommendation_id': recommendation_id
    }
    data = load_json_file(participant_exclusions_path(participant_id)) or {
        'participant_id': participant_id,
        'restaurants': []
    }
    restaurants = [
        item for item in data.get('restaurants', [])
        if isinstance(item, dict)
    ]
    if not any(restaurant_matches(item, exclusion) for item in restaurants):
        restaurants.append(exclusion)
    data['restaurants'] = restaurants
    data['updated_at'] = now
    save_json_atomic(participant_exclusions_path(participant_id), data)
    return exclusion

def update_recommendation_feedback(participant_id, recommendation_id, action, restaurant=None):
    recommendation_dir = participant_recommendations_directory(participant_id)
    path = os.path.join(recommendation_dir, f'{recommendation_id}.json')
    record = load_json_file(path)
    if not isinstance(record, dict):
        raise ValueError('Recommendation history not found')

    now = datetime.now().isoformat()
    feedback = record.setdefault('feedback', {})
    if action == 'dismiss':
        feedback['status'] = 'dismissed'
        feedback['dismissed_at'] = now
    elif action == 'exclude':
        recommendation = next(
            (
                item for item in record.get('recommendations', [])
                if isinstance(item, dict) and restaurant_matches(item, restaurant or {})
            ),
            None
        )
        if not recommendation:
            raise ValueError('Restaurant was not found in the recommendation history')
        exclusion = save_restaurant_exclusion(
            participant_id,
            recommendation,
            recommendation_id
        )
        excluded_ids = feedback.setdefault('excluded_restaurant_ids', [])
        exclusion_key = exclusion.get('restaurant_id') or exclusion.get('name')
        if exclusion_key and exclusion_key not in excluded_ids:
            excluded_ids.append(exclusion_key)
        feedback['status'] = 'excluded'
        feedback['updated_at'] = now
    else:
        raise ValueError('Unsupported feedback action')

    save_json_atomic(path, record)
    return record

def save_recommendation_histories(session_id, result):
    saved_at = datetime.now().isoformat()
    timestamp = datetime.now().strftime('%Y%m%dT%H%M%S%f')
    for group in result.get('groups', []):
        recommendations = [
            item for item in group.get('recommendations', [])
            if isinstance(item, dict)
        ]
        for participant_id in group.get('members', []):
            participant_id = str(participant_id or '')
            if not PARTICIPANT_ID_PATTERN.fullmatch(participant_id):
                continue
            if not os.path.isdir(participant_directory(participant_id)):
                continue
            recommendation_id = f'{timestamp}_{session_id}'
            record = {
                'recommendation_id': recommendation_id,
                'participant_id': participant_id,
                'session_id': session_id,
                'group_id': group.get('group_id'),
                'recommended_at': saved_at,
                'recommendations': recommendations,
                'feedback': {'status': 'pending'}
            }
            save_json_atomic(
                os.path.join(
                    participant_recommendations_directory(participant_id),
                    f'{recommendation_id}.json'
                ),
                record
            )

def persist_mobile_session(session_data):
    if not session_data.get('mobile_enabled'):
        return
    data = load_mobile_sessions()
    session_id = session_data['id']
    data['latest_session_id'] = session_id
    data['sessions'][session_id] = {
        'id': session_id,
        'created': session_data.get('created'),
        'updated': datetime.now().isoformat(),
        'groups': session_data.get('groups', 2),
        'location': session_data.get('location', '세종대학교'),
        'provider': session_data.get('provider', 'naver'),
        'recommendation_filters': session_data.get('recommendation_filters', {}),
        'use_exclusions': bool(session_data.get('use_exclusions', True)),
        'status': session_data.get('status', 'collecting'),
        'mobile_enabled': bool(session_data.get('mobile_enabled')),
        'join_url': session_data.get('join_url', ''),
        'selected_participant_ids': session_data.get('selected_participant_ids', []),
        'sample_participant_ids': session_data.get('sample_participant_ids', []),
        'participants': session_data.get('participants', [])
    }
    save_mobile_sessions(data)

def ensure_session_loaded(session_id):
    if session_id in sessions_store:
        changed = ensure_demo_participants_in_session(sessions_store[session_id])
        changed = sync_session_participant_display_names(
            sessions_store[session_id]
        ) or changed
        if changed:
            persist_mobile_session(sessions_store[session_id])
        return True
    data = load_mobile_sessions()
    persisted = data.get('sessions', {}).get(session_id)
    if not persisted:
        return False
    sessions_store[session_id] = {
        'id': persisted.get('id', session_id),
        'created': persisted.get('created', datetime.now().isoformat()),
        'participants': persisted.get('participants', []),
        'groups': int(persisted.get('groups', 2)),
        'location': persisted.get('location', '세종대학교'),
        'provider': persisted.get('provider', 'naver'),
        'recommendation_filters': persisted.get('recommendation_filters', {}),
        'use_exclusions': bool(persisted.get('use_exclusions', True)),
        'status': persisted.get('status', 'collecting'),
        'mobile_enabled': bool(persisted.get('mobile_enabled')),
        'join_url': persisted.get('join_url', ''),
        'selected_participant_ids': persisted.get('selected_participant_ids', []),
        'sample_participant_ids': persisted.get('sample_participant_ids', [])
    }
    if ensure_demo_participants_in_session(sessions_store[session_id]):
        persist_mobile_session(sessions_store[session_id])
    if sync_session_participant_display_names(sessions_store[session_id]):
        persist_mobile_session(sessions_store[session_id])
    return True

def normalize_list(value):
    if isinstance(value, list):
        return [item for item in value if item]
    if value:
        return [value]
    return []

def leaf_value(value):
    if isinstance(value, str):
        return value.split('|')[-1]
    return value

def leaf_values(values):
    return [leaf_value(value) for value in values if value]

def middle_values(values):
    mids = []
    for value in values:
        parts = str(value).split('|')
        if len(parts) >= 2:
            mids.append('|'.join(parts[:2]))
    return list(dict.fromkeys(mids))

def ensure_demo_participant_records():
    """demo_session.json의 10명을 모바일 참가자와 같은 폴더 구조로 동기화한다."""
    demo_data = load_json_file(DEMO_SESSION_FILE) or {}
    demo_participants = demo_data.get('participants', [])
    if not isinstance(demo_participants, list):
        demo_participants = []

    synchronized_ids = []
    for index, demo in enumerate(demo_participants[:DEMO_PARTICIPANT_COUNT], start=1):
        if not isinstance(demo, dict):
            continue
        participant_id = f'U{index:04d}'
        device_id = f'demo-{index:04d}'
        preferences = demo.get('preferences', {})
        display_name = str(demo.get('user_id') or participant_id)
        profile = {
            'user_id': display_name,
            'source': 'demo',
            'created_at': DEMO_TIMESTAMP,
            'updated_at': DEMO_TIMESTAMP,
            'preferences': preferences
        }
        device = {
            'identifier_type': 'example',
            'device_identifier': device_id,
            'updated_at': DEMO_TIMESTAMP
        }
        exclusions = load_json_file(participant_exclusions_path(participant_id)) or {
            'participant_id': participant_id,
            'restaurants': [],
            'updated_at': DEMO_TIMESTAMP
        }
        location_settings = load_json_file(
            participant_location_settings_path(participant_id)
        ) or {
            'participant_id': participant_id,
            'enabled': False,
            'consent_status': 'denied',
            'consented_at': DEMO_TIMESTAMP,
            'updated_at': DEMO_TIMESTAMP
        }
        session_access = load_json_file(participant_session_access_path(participant_id)) or {
            'participant_id': participant_id,
            'device_identifier': device_id,
            'sessions': [{
                'session_id': DEMO_SESSION_ID,
                'first_accessed_at': DEMO_TIMESTAMP,
                'last_accessed_at': DEMO_TIMESTAMP,
                'access_count': 1,
                'source': 'demo_seed'
            }],
            'last_session_id': DEMO_SESSION_ID,
            'updated_at': DEMO_TIMESTAMP
        }
        submission = {
            'participant_id': participant_id,
            **profile,
            'session_id': DEMO_SESSION_ID,
            'submitted_at': DEMO_TIMESTAMP,
            'meal_data': {
                'date': DEMO_TIMESTAMP[:10],
                'meal_type': 'lunch'
            }
        }
        meal_record = {
            'participant_id': participant_id,
            'date': DEMO_TIMESTAMP[:10],
            'meals': {
                'lunch': {
                    'submitted_at': DEMO_TIMESTAMP,
                    'session_id': DEMO_SESSION_ID,
                    'preferences': preferences
                }
            },
            'updated_at': DEMO_TIMESTAMP,
            'session_id': DEMO_SESSION_ID
        }

        save_json_atomic(participant_profile_path(participant_id), profile)
        save_json_atomic(participant_device_path(participant_id), device)
        save_json_atomic(participant_exclusions_path(participant_id), exclusions)
        save_json_atomic(
            participant_location_settings_path(participant_id),
            location_settings
        )
        save_json_atomic(participant_session_access_path(participant_id), session_access)
        save_json_atomic(
            os.path.join(
                participant_directory(participant_id),
                'submissions',
                f'20260620T000000000000_{DEMO_SESSION_ID}.json'
            ),
            submission
        )
        save_json_atomic(
            os.path.join(
                participant_meals_directory(participant_id),
                f'{DEMO_TIMESTAMP[:10]}.json'
            ),
            meal_record
        )
        os.makedirs(participant_recommendations_directory(participant_id), exist_ok=True)
        synchronized_ids.append(participant_id)

    return synchronized_ids

def load_demo_participants():
    ensure_demo_participant_records()
    participants = []
    for index in range(1, DEMO_PARTICIPANT_COUNT + 1):
        participant_id = f'U{index:04d}'
        participant = load_stored_participant(participant_id)
        if participant and participant.get('source') == 'demo':
            participants.append(participant)
    return participants

def ensure_demo_participants_in_session(session_data):
    """기존 세션에도 샘플 10명을 앞쪽에 중복 없이 포함한다."""
    demo_participants = load_demo_participants()
    demo_ids = {
        participant['participant_id']
        for participant in demo_participants
    }
    existing = session_data.get('participants', [])
    actual_participants = [
        participant
        for participant in existing
        if participant.get('participant_id') not in demo_ids
    ]
    merged = demo_participants + actual_participants
    changed = (
        [participant.get('participant_id') for participant in existing]
        != [participant.get('participant_id') for participant in merged]
    )
    session_data['participants'] = merged
    session_data['sample_participant_ids'] = sorted(demo_ids)
    session_data['selected_participant_ids'] = [
        participant_id
        for participant_id in session_data.get('selected_participant_ids', [])
        if participant_id not in demo_ids
    ]
    return changed

def sync_session_participant_display_names(session_data):
    changed = False
    for participant in session_data.get('participants', []):
        participant_id = str(
            participant.get('participant_id')
            or participant.get('user_id')
            or ''
        )
        if not PARTICIPANT_ID_PATTERN.fullmatch(participant_id):
            continue
        profile = load_participant_profile(participant_id) or {}
        display_name = str(profile.get('user_id') or '').strip()
        if display_name and participant.get('display_name') != display_name:
            participant['display_name'] = display_name
            changed = True
    return changed

def load_stored_participant(participant_id):
    profile = load_participant_profile(participant_id)
    device = load_participant_device(participant_id)
    if not profile or not device:
        return None
    return {
        'participant_id': participant_id,
        'device_id': device.get('device_identifier', ''),
        'user_id': participant_id,
        'display_name': profile.get('user_id', participant_id),
        'source': profile.get('source', 'mobile'),
        'submitted_at': profile.get('updated_at', profile.get('created_at', '')),
        'preferences': profile.get('preferences', {}),
        'excluded_restaurants': load_participant_exclusions(participant_id)
    }

def load_selected_participants(participant_ids):
    participants = []
    seen = set()
    for participant_id in participant_ids:
        participant_id = str(participant_id or '').strip()
        if participant_id in seen or not PARTICIPANT_ID_PATTERN.fullmatch(participant_id):
            continue
        participant = load_stored_participant(participant_id)
        if participant:
            participants.append(participant)
            seen.add(participant_id)
    return participants

def load_mock_restaurants():
    try:
        with open(MOCK_RESTAURANTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

def build_participant(data, session_data, source='manual'):
    device_id = validate_device_id(data.get('device_id'))
    if source == 'mobile' and not device_id:
        raise ValueError('A valid device ID is required')
    requested_name = str(data.get('user_id') or '').strip()
    like_high = normalize_list(data.get('like_high', []))
    like_low = normalize_list(data.get('like_low', []))
    recent_high = normalize_list(data.get('recent_high', []))
    recent_low = normalize_list(data.get('recent_low', []))
    if len(like_high) != 2 or len(set(like_high)) != 2:
        raise ValueError('Select exactly two preferred categories')
    if len(like_low) != 4 or any(
        sum(value.startswith(f'{category}|') for value in like_low) != 2
        for category in like_high
    ):
        raise ValueError('Select exactly two foods for each preferred category')
    if len(recent_high) != 1 or len(recent_low) != 1:
        raise ValueError('Select one recent category and one recent food')
    if not recent_low[0].startswith(f'{recent_high[0]}|'):
        raise ValueError('Recent food must belong to the selected category')
    meal_data = normalize_meal_data(data)
    return {
        'device_id': device_id,
        'user_id': requested_name,
        'source': source,
        'submitted_at': datetime.now().isoformat(),
        'meal_data': meal_data,
        'preferences': {
            'like': {
                'high': like_high,
                'low': like_low
            },
            'recent': {
                'high': recent_high,
                'low': recent_low
            }
        }
    }

def run_shell_command(cmd):
    """셸 명령어 실행"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout, result.returncode
    except Exception as e:
        return str(e), 1

def build_groups_with_cli(participants, group_count):
    """그룹 계산은 Python 알고리즘 대신 jq 기반 scripts/grouping_cli.sh에 위임한다."""
    fd, session_path = tempfile.mkstemp(prefix='mm-grouping-session.', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({'participants': participants}, f, ensure_ascii=False)
        completed = subprocess.run(
            [
                'sh',
                os.path.join(BASE_DIR, 'scripts', 'grouping_cli.sh'),
                '--session-file',
                session_path,
                '--group-count',
                str(group_count)
            ],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            check=True
        )
        return json.loads(completed.stdout).get('groups', [])
    finally:
        try:
            os.unlink(session_path)
        except OSError:
            pass

def get_menu_categories():
    """메뉴 카테고리 로드"""
    try:
        with open(os.path.join(DATASET_DIR, 'menu_categories.json'), 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data
    except:
        return {}

def get_category_list():
    """대분류 카테고리 목록"""
    categories = get_menu_categories()
    return list(categories.keys())

def get_subcategories(category):
    """대분류 아래의 소분류 목록."""
    categories = get_menu_categories()
    values = categories.get(category, [])
    if isinstance(values, dict):
        return list(values.keys())
    if isinstance(values, list):
        return values
    return []

def get_foods(category, subcategory):
    """레거시 중분류 아래의 음식 목록."""
    categories = get_menu_categories()
    values = categories.get(category, {})
    if isinstance(values, dict) and subcategory in values:
        return values[subcategory]
    return []

def get_foods_by_category(category):
    """대분류 아래의 소분류 목록(레거시 중분류 구조도 지원)."""
    values = get_menu_categories().get(category, [])
    if isinstance(values, list):
        return values
    foods = []
    if isinstance(values, dict):
        for nested_values in values.values():
            foods.extend(nested_values)
    return list(dict.fromkeys(foods))

def get_reachable_base_urls(port=5000):
    urls = [f'http://127.0.0.1:{port}']
    seen_hosts = {'127.0.0.1', 'localhost'}

    def add_host(host):
        if not host or host in seen_hosts:
            return
        if host.startswith('127.') or host == '0.0.0.0':
            return
        seen_hosts.add(host)
        urls.append(f'http://{host}:{port}')

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_DGRAM):
            add_host(info[4][0])
    except socket.gaierror:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('8.8.8.8', 80))
            add_host(sock.getsockname()[0])
    except OSError:
        pass

    return urls

def normalize_base_url(value):
    base_url = str(value or '').strip().rstrip('/')
    if not base_url:
        return ''
    if not base_url.startswith(('http://', 'https://')):
        base_url = f'http://{base_url}'
    return base_url

def get_public_base_url(client_base_url=''):
    env_base_url = normalize_base_url(os.environ.get('MM_PUBLIC_BASE_URL'))
    if env_base_url:
        return env_base_url
    return normalize_base_url(client_base_url)

@app.route('/')
def index():
    """메인 대시보드"""
    return render_template('index.html')

@app.route('/api/cli-events')
def get_cli_events():
    """서버 시작 이후 실행된 CLI 명령 스트림."""
    after = request.args.get('after', '-1')
    try:
        after_id = int(after)
    except ValueError:
        after_id = -1
    with cli_events_lock:
        events = [event for event in cli_events if event['id'] > after_id]
    return jsonify({'events': events})

@app.route('/join/<session_id>')
def mobile_join(session_id):
    """QR로 접속하는 모바일 설문 화면"""
    return render_template('mobile.html', session_id=session_id)

@app.route('/api/categories')
def api_categories():
    """카테고리 API"""
    return jsonify(get_category_list())

@app.route('/api/subcategories/<category>')
def api_subcategories(category):
    """중분류 API"""
    return jsonify(get_subcategories(category))

@app.route('/api/foods/<category>/<subcategory>')
def api_foods(category, subcategory):
    """음식 API"""
    return jsonify(get_foods(category, subcategory))

@app.route('/api/foods/<category>')
def api_foods_by_category(category):
    return jsonify(get_foods_by_category(category))

@app.route('/api/foods')
def api_foods_by_category_query():
    """슬래시가 포함된 카테고리명도 안전하게 처리한다."""
    category = str(request.args.get('category') or '').strip()
    return jsonify(get_foods_by_category(category))

@app.route('/api/network-info')
def api_network_info():
    """QR에 넣을 수 있는 접속 주소 후보."""
    port = int(os.environ.get('PORT', 5000))
    env_base_url = get_public_base_url()
    urls = get_reachable_base_urls(port)
    if env_base_url:
        urls.insert(0, env_base_url)
    unique_urls = list(dict.fromkeys(urls))
    recommended = env_base_url or (unique_urls[1] if len(unique_urls) > 1 else unique_urls[0])
    return jsonify({'base_urls': unique_urls, 'recommended': recommended})

@app.route('/api/participant/<device_id>')
def get_participant_profile(device_id):
    """기기에 저장된 최신 설문 프로필."""
    profile = load_profile_by_device(device_id)
    if not profile or profile.get('source') != 'mobile':
        return jsonify({
            'profile': None,
            'previous_session_id': None,
            'last_recommendation': None
        })
    participant_id = profile['participant_id']
    current_session_id = str(request.args.get('session_id') or '').strip()
    with participant_records_lock:
        previous_session_id = previous_visited_session_id(
            participant_id,
            current_session_id
        )
        record_session_access(
            participant_id,
            current_session_id,
            device_id,
            source='qr_access'
        )
        last_recommendation = load_recommendation_for_session(
            participant_id,
            previous_session_id
        )
    return jsonify({
        'profile': profile,
        'previous_session_id': previous_session_id or None,
        'last_recommendation': last_recommendation,
        'navigation': navigation_settings_payload(participant_id)
    })

@app.route('/api/participant/<device_id>/location-settings', methods=['GET', 'POST'])
def participant_location_settings(device_id):
    """사용자별 위치 길찾기 동의와 ON/OFF 설정."""
    participant_id = find_participant_id_by_device(device_id)
    if not participant_id:
        return jsonify({'error': 'Participant not found'}), 404

    if request.method == 'GET':
        return jsonify(navigation_settings_payload(participant_id))

    data = request.json or {}
    enabled = data.get('enabled')
    consent_status = data.get('consent_status')
    if enabled is not None and not isinstance(enabled, bool):
        return jsonify({'error': 'enabled must be a boolean'}), 400
    if consent_status is not None:
        consent_status = str(consent_status)
    try:
        with participant_records_lock:
            with participant_file_lock():
                settings = save_participant_location_settings(
                    participant_id,
                    enabled=enabled,
                    consent_status=consent_status
                )
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    return jsonify({'success': True, 'navigation': settings})

@app.route('/api/participant/<device_id>/recommendation-feedback', methods=['POST'])
def save_recommendation_feedback(device_id):
    """지난 추천을 닫거나 특정 식당을 사용자 제외 목록에 추가한다."""
    participant_id = find_participant_id_by_device(device_id)
    if not participant_id:
        return jsonify({'error': 'Participant not found'}), 404

    data = request.json or {}
    recommendation_id = str(data.get('recommendation_id') or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', recommendation_id):
        return jsonify({'error': 'Invalid recommendation ID'}), 400

    action = str(data.get('action') or '').strip()
    restaurant = data.get('restaurant')
    if restaurant is not None and not isinstance(restaurant, dict):
        return jsonify({'error': 'restaurant must be an object'}), 400

    try:
        with participant_records_lock:
            record = update_recommendation_feedback(
                participant_id,
                recommendation_id,
                action,
                restaurant
            )
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

    return jsonify({
        'success': True,
        'feedback': record.get('feedback', {}),
        'excluded_restaurants': load_participant_exclusions(participant_id)
    })

@app.route('/api/session/<session_id>/participant-recommendation/<device_id>')
def get_current_session_participant_recommendation(session_id, device_id):
    """현재 세션의 CLI 추천 완료 여부와 해당 사용자의 그룹 추천을 반환한다."""
    if not ensure_session_loaded(session_id):
        return jsonify({'error': 'Session not found'}), 404

    participant_id = find_participant_id_by_device(device_id)
    session_data = sessions_store[session_id]
    if not participant_id:
        return jsonify({
            'status': session_data.get('status', 'collecting'),
            'participant_id': None,
            'recommendation': None
        })

    recommendation = load_recommendation_for_session(participant_id, session_id)
    return jsonify({
        'status': session_data.get('status', 'collecting'),
        'participant_id': participant_id,
        'recommendation': recommendation,
        'navigation': navigation_settings_payload(participant_id)
    })

@app.route('/api/participant/<device_id>/meals')
def get_participant_meals(device_id):
    """기기에 연결된 사용자의 날짜별 점심·저녁 기록."""
    participant_id = find_participant_id_by_device(device_id)
    if not participant_id:
        return jsonify({'participant_id': None, 'meals': []})
    return jsonify({
        'participant_id': participant_id,
        'meals': load_participant_meals(participant_id)
    })

@app.route('/api/participants')
def get_participant_records():
    """관리자 화면용 사용자 폴더 목록."""
    ensure_demo_participant_records()
    ensure_unique_device_participants()
    migrate_legacy_auto_aliases()
    return jsonify({'participants': list_participant_records()})

@app.route('/api/session/create', methods=['POST'])
def create_session():
    """선택한 저장 사용자를 묶는 추천 세션 생성."""
    data = request.json or {}
    ensure_unique_device_participants()
    migrate_legacy_auto_aliases()
    session_id = str(uuid.uuid4())[:8]
    mobile_enabled = True
    public_base_url = get_public_base_url(data.get('public_base_url')) or normalize_base_url(request.host_url)
    join_url = f'{public_base_url}/join/{session_id}'
    selected_participant_ids = data.get('participant_ids', [])
    if not isinstance(selected_participant_ids, list):
        return jsonify({'error': 'participant_ids must be a list'}), 400
    demo_participants = load_demo_participants()
    demo_ids = {
        participant['participant_id']
        for participant in demo_participants
    }
    selected_participants = [
        participant
        for participant in load_selected_participants(selected_participant_ids)
        if participant.get('participant_id') not in demo_ids
    ]
    participants = demo_participants + selected_participants
    try:
        walking_minutes = int(data.get('walking_minutes', 0) or 0)
        review_top_n = int(data.get('review_top_n', 0) or 0)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid recommendation filter'}), 400
    if walking_minutes not in {0, 5, 10, 15, 20, 25, 30}:
        return jsonify({'error': 'walking_minutes must be 0 or 5-30 in 5-minute steps'}), 400
    if review_top_n not in {0, 1, 3, 5}:
        return jsonify({'error': 'review_top_n must be 0, 1, 3, or 5'}), 400
    
    session_data = {
        'id': session_id,
        'created': datetime.now().isoformat(),
        'participants': participants,
        'selected_participant_ids': [
            participant['participant_id']
            for participant in selected_participants
        ],
        'sample_participant_ids': sorted(demo_ids),
        'groups': int(data.get('groups', 2)),
        'location': data.get('location', '세종대학교'),
        'provider': data.get('provider', 'naver'),
        'recommendation_filters': {
            'walking_minutes': walking_minutes,
            'review_top_n': review_top_n
        },
        'use_exclusions': bool(data.get('use_exclusions', True)),
        'status': 'collecting',
        'mobile_enabled': mobile_enabled,
        'join_url': join_url if mobile_enabled else ''
    }
    
    sessions_store[session_id] = session_data
    persist_mobile_session(session_data)
    return jsonify({
        'session_id': session_id,
        'join_url': session_data['join_url'],
        'public_base_url': public_base_url,
        'mobile_enabled': mobile_enabled,
        'provider': session_data['provider'],
        'recommendation_filters': session_data['recommendation_filters'],
        'use_exclusions': session_data['use_exclusions'],
        'participant_count': len(participants),
        'sample_participant_count': len(demo_participants),
        'participants': participants
    })

@app.route('/api/session/<session_id>/add-participant', methods=['POST'])
def add_participant(session_id):
    """참가자 추가"""
    if not ensure_session_loaded(session_id):
        return jsonify({'error': 'Session not found'}), 404
    
    session_data = sessions_store[session_id]
    data = request.json or {}
    source = data.get('source', '')
    if session_data.get('status') != 'collecting':
        return jsonify({'error': 'Session is closed'}), 409
    if source != 'mobile':
        return jsonify({'error': 'Participants must submit from the mobile survey'}), 403

    try:
        participant = build_participant(data, session_data, source)
        save_participant_record(participant, session_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    existing_index = next(
        (
            index for index, existing in enumerate(session_data['participants'])
            if (
                existing.get('participant_id') == participant.get('participant_id')
                or existing.get('device_id') == participant['device_id']
            )
        ),
        None
    )
    if existing_index is None:
        session_data['participants'].append(participant)
    else:
        session_data['participants'][existing_index] = participant
    persist_mobile_session(session_data)
    return jsonify({
        'success': True,
        'participant': participant,
        'participant_count': len(session_data['participants']),
        'updated_existing': existing_index is not None
    })

@app.route('/api/session/<session_id>/close', methods=['POST'])
def close_session(session_id):
    """QR/mobile collection close button."""
    if not ensure_session_loaded(session_id):
        return jsonify({'error': 'Session not found'}), 404
    session_data = sessions_store[session_id]
    session_data['status'] = 'closed'
    persist_mobile_session(session_data)
    return jsonify({'success': True, 'participant_count': len(session_data['participants'])})

def build_cli_session_file(session_data):
    fd, path = tempfile.mkstemp(prefix='mm-web-session.', suffix='.json')
    payload = {
        'participant_count': len(session_data['participants']),
        'group_count': int(session_data['groups']),
        'recommendation_filters': session_data.get('recommendation_filters', {}),
        'use_exclusions': bool(session_data.get('use_exclusions', True)),
        'participants': session_data['participants']
    }
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write('\n')
    return path

def make_cli_payload(command, completed_stdout, completed_stderr, returncode):
    result = json.loads(completed_stdout)
    result['cli'] = {
        'command': sanitize_cli_text(' '.join(command)),
        'stderr': completed_stderr,
        'stdout': completed_stdout,
        'returncode': returncode,
    }
    return result

def append_cli_job_event(job_id, event):
    safe_event = {
        **event,
        'text': sanitize_cli_text(event.get('text', ''))
    }
    append_cli_event(safe_event.get('type', 'output'), safe_event.get('text', ''))
    with cli_jobs_lock:
        job = cli_jobs.get(job_id)
        if not job:
            return
        job.setdefault('events', []).append({
            'time': datetime.now().isoformat(timespec='seconds'),
            **safe_event
        })

def update_cli_job(job_id, **updates):
    with cli_jobs_lock:
        job = cli_jobs.get(job_id)
        if not job:
            return
        job.update(updates)

def run_cli_recommendations_job(job_id, session_id, session_data):
    provider = session_data.get('provider', 'naver')
    location = session_data.get('location', '세종대학교')
    session_file = build_cli_session_file(session_data)
    command = [
        'sh',
        os.path.join(BASE_DIR, 'scripts', 'recommend.sh'),
        '--session-file',
        session_file,
        '--provider',
        provider,
        '--location',
        location,
        '--json-output'
    ]
    env = os.environ.copy()
    env['MM_STEP_DELAY_SEC'] = '0.65'
    try:
        process = subprocess.Popen(
            command,
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        stderr_lines = []

        append_cli_job_event(job_id, {'type': 'command', 'text': ' '.join(command)})
        append_cli_job_event(job_id, {'type': 'output', 'text': 'scripts/recommend.sh 프로세스를 시작했습니다.'})

        assert process.stderr is not None
        for line in process.stderr:
            clean_line = line.rstrip('\n')
            stderr_lines.append(clean_line)
            if clean_line.startswith('[cmd] '):
                append_cli_job_event(job_id, {'type': 'command', 'text': clean_line[6:]})
                time.sleep(0.25)
            elif clean_line.startswith('[out] '):
                append_cli_job_event(job_id, {'type': 'output', 'text': clean_line[6:]})
            else:
                append_cli_job_event(job_id, {'type': 'output', 'text': clean_line})

        assert process.stdout is not None
        stdout = process.stdout.read()
        returncode = process.wait(timeout=120)
        stderr = '\n'.join(stderr_lines)
        if returncode != 0:
            raise RuntimeError(stderr or stdout or f'CLI failed with code {returncode}')

        output = make_cli_payload(command, stdout, stderr, returncode)
        output_file = f'/tmp/session_{session_id}_result.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        with participant_records_lock:
            save_recommendation_histories(session_id, output)
        session_data['status'] = 'completed'
        session_data['result_file'] = output_file
        if session_id in sessions_store:
            sessions_store[session_id]['status'] = 'completed'
            sessions_store[session_id]['result_file'] = output_file
        persist_mobile_session(session_data)
        append_cli_job_event(job_id, {'type': 'output', 'text': '완료: 추천 결과 JSON을 웹 화면으로 전달했습니다.'})
        update_cli_job(job_id, status='completed', result=output)
    except Exception as e:
        if session_id in sessions_store:
            sessions_store[session_id]['status'] = 'failed'
        append_cli_job_event(job_id, {'type': 'output', 'text': f'오류: {e}'})
        update_cli_job(job_id, status='failed', error=str(e))
    finally:
        try:
            os.unlink(session_file)
        except OSError:
            pass

def start_cli_recommendation_job(session_id, session_data):
    job_id = str(uuid.uuid4())[:8]
    with cli_jobs_lock:
        cli_jobs[job_id] = {
            'id': job_id,
            'session_id': session_id,
            'status': 'running',
            'events': [],
            'result': None,
            'error': None,
            'created': datetime.now().isoformat(timespec='seconds')
        }
    thread = threading.Thread(
        target=run_cli_recommendations_job,
        args=(job_id, session_id, json.loads(json.dumps(session_data, ensure_ascii=False))),
        daemon=True
    )
    thread.start()
    return job_id

@app.route('/api/session/<session_id>/generate-recommendations', methods=['POST'])
def generate_recommendations(session_id):
    """추천 생성"""
    if not ensure_session_loaded(session_id):
        return jsonify({'error': 'Session not found'}), 404
    
    session_data = sessions_store[session_id]
    if not session_data['participants']:
        return jsonify({'error': 'No participants'}), 400

    job_id = start_cli_recommendation_job(session_id, session_data)
    return jsonify({'success': True, 'job_id': job_id})

@app.route('/api/job/<job_id>')
def get_cli_job(job_id):
    with cli_jobs_lock:
        job = cli_jobs.get(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        return jsonify(job)

def generate_group_recommendations(session_data):
    """그룹별 추천 생성"""
    groups = []
    participants = session_data['participants']
    group_count = session_data['groups']
    grouped_members = build_groups_with_cli(participants, group_count)
    members_by_id = {participant['user_id']: participant for participant in participants}
    
    for group in grouped_members:
        group_idx = group['group_id']
        members = group['members']
        
        if not members:
            continue
        
        # 그룹 프로필 생성
        group_profile = aggregate_preferences([members_by_id[user_id] for user_id in members if user_id in members_by_id])
        
        # 추천 식당 조회
        recommendations = get_restaurant_recommendations(
            group_profile,
            session_data['location'],
            session_data.get('provider', 'naver')
        )
        
        groups.append({
            'group_id': group_idx,
            'members': members,
            'member_names': [
                members_by_id[user_id].get('display_name')
                or members_by_id[user_id].get('original_user_id')
                or members_by_id[user_id].get('user_id')
                or '이름 없음'
                for user_id in members
                if user_id in members_by_id
            ],
            'recommendations': recommendations[:1]
        })
    
    return groups

def aggregate_preferences(members):
    """그룹 선호도 집계"""
    like_high = []
    like_low = []
    recent = []
    
    for p in members:
        prefs = p['preferences']
        like_high.extend(leaf_values(prefs['like'].get('high', [])))
        like_low.extend(leaf_values(prefs['like'].get('low', [])))
        recent.extend(leaf_values(prefs['recent'].get('low', [])))
    
    return {
        'positive': list(dict.fromkeys(like_high + like_low)),
        'like_high': list(dict.fromkeys(like_high)),
        'like_low': list(dict.fromkeys(like_low)),
        'recent': list(dict.fromkeys(recent))
    }

def build_recommendation_reason(restaurant, profile):
    """점수에 사용된 단순 규칙을 사람이 읽는 설명으로 변환"""
    parts = []
    if restaurant['category'] in profile['like_high']:
        parts.append(f"matched preferred category {restaurant['category']}")
    if restaurant['food'] in profile['like_low']:
        parts.append(f"matched preferred food {restaurant['food']}")
    return "; ".join(parts) if parts else "selected as the best available candidate from the search results"

def search_mock_restaurants(search_terms, location):
    restaurants = []
    seen_ids = set()
    for term in search_terms:
        for restaurant in load_mock_restaurants():
            if (
                restaurant.get('food') == term
                or restaurant.get('category') == term
                or term in restaurant.get('name', '')
            ):
                restaurant_id = restaurant.get('restaurant_id')
                if restaurant_id in seen_ids:
                    continue
                seen_ids.add(restaurant_id)
                item = dict(restaurant)
                item['matched_terms'] = [term]
                item['address'] = item.get('address') or item.get('location') or location
                item['roadAddress'] = item.get('roadAddress') or item.get('address') or item.get('location') or location
                item['link'] = item.get('link', '')
                restaurants.append(item)
    return restaurants

def get_restaurant_recommendations(profile, location, provider='naver'):
    """그룹 프로필로 인근 식당 후보를 가져와 점수화."""
    try:
        search_terms = list(dict.fromkeys(profile['positive']))
        if provider == 'naver':
            restaurants = search_restaurants(search_terms, location)
        else:
            restaurants = search_mock_restaurants(search_terms, location)

        candidates = []
        for r in restaurants:
            matched_terms = r.get('matched_terms', [r.get('food', '')])
            if (
                any(term in profile['recent'] for term in matched_terms)
                or r['food'] in profile['recent']
                or r.get('subcategory') in profile['recent']
            ):
                continue

            score = 0.0
            if r['category'] in profile['like_high']:
                score += 0.5
            if r['food'] in profile['like_low']:
                score += 0.3
            
            candidates.append({
                'restaurant_id': r['restaurant_id'],
                'name': r['name'],
                'food': r['food'],
                'category': r['category'],
                'location': r['location'],
                'address': r.get('roadAddress') or r.get('address', ''),
                'link': r.get('link', ''),
                'distance_m': r.get('distance_m', ''),
                'score': round(score, 3),
                'reason': build_recommendation_reason(r, profile),
                'rating': r.get('rating', '')
            })

        candidates.sort(key=lambda x: (-x['score'], x['distance_m'] if isinstance(x.get('distance_m'), (int, float)) else 999999))
        return candidates[:1]
    except Exception as e:
        print(f"Error getting recommendations: {e}")
        return []

@app.route('/api/session/<session_id>')
def get_session(session_id):
    """세션 조회"""
    if not ensure_session_loaded(session_id):
        return jsonify({'error': 'Session not found'}), 404
    
    return jsonify(sessions_store[session_id])

def open_browser_once(host, port):
    """Open the admin UI once after the dev server starts."""
    if os.environ.get('MM_AUTO_OPEN', '1') in ('0', 'false', 'False', 'no'):
        return
    if app.debug and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        return

    url = f'http://127.0.0.1:{port}'
    timer = threading.Timer(1.0, lambda: webbrowser.open_new_tab(url))
    timer.daemon = True
    timer.start()

if __name__ == '__main__':
    host = '0.0.0.0'
    port = int(os.environ.get('PORT', 5000))
    open_browser_once(host, port)
    app.run(debug=True, port=port, host=host)
