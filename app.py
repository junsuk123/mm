#!/usr/bin/env python3
"""
실시간 식당 추천 시스템 웹 GUI
Flask 기반 대시보드로 사용자 입력 수집 및 실시간 시각화
"""

from flask import Flask, render_template, request, jsonify
import json
import subprocess
import os
import tempfile
import threading
import webbrowser
import socket
from datetime import datetime
import uuid

from grouping_utils import build_groups
from naver_restaurant_api import search_restaurants

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(BASE_DIR, 'dataset')
MOBILE_SESSIONS_FILE = os.path.join(DATASET_DIR, 'mobile_sessions.json')
DEMO_SESSION_FILE = os.path.join(DATASET_DIR, 'demo_session.json')
MOCK_RESTAURANTS_FILE = os.path.join(DATASET_DIR, 'mock_restaurants.json')

app = Flask(__name__)
app.secret_key = 'restaurant-recommendation-secret-key'

# 임시 세션 데이터 저장소
sessions_store = {}
cli_jobs = {}
cli_jobs_lock = threading.Lock()

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
        'provider': session_data.get('provider', 'mock'),
        'status': session_data.get('status', 'collecting'),
        'mobile_enabled': bool(session_data.get('mobile_enabled')),
        'join_url': session_data.get('join_url', ''),
        'participants': session_data.get('participants', [])
    }
    save_mobile_sessions(data)

def ensure_session_loaded(session_id):
    if session_id in sessions_store:
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
        'provider': persisted.get('provider', 'mock'),
        'status': persisted.get('status', 'collecting'),
        'mobile_enabled': bool(persisted.get('mobile_enabled')),
        'join_url': persisted.get('join_url', '')
    }
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

def load_demo_participants():
    try:
        with open(DEMO_SESSION_FILE, 'r', encoding='utf-8') as f:
            demo_session = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    participants = []
    for participant in demo_session.get('participants', []):
        cloned = json.loads(json.dumps(participant, ensure_ascii=False))
        cloned.setdefault('source', 'demo')
        participants.append(cloned)
    return participants

def load_mock_restaurants():
    try:
        with open(MOCK_RESTAURANTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

def next_user_id(session_data, prefix='U'):
    return f'{prefix}{len(session_data["participants"]) + 1:02d}'

def build_participant(data, session_data, source='manual'):
    user_id = data.get('user_id') or next_user_id(session_data, 'M' if source == 'mobile' else 'U')
    return {
        'user_id': user_id,
        'source': source,
        'submitted_at': datetime.now().isoformat(),
        'preferences': {
            'like': {
                'high': normalize_list(data.get('like_high', [])),
                'low': normalize_list(data.get('like_low', data.get('like_mid', [])))
            },
            'dislike': {
                'high': normalize_list(data.get('dislike_high', [])),
                'low': normalize_list(data.get('dislike_low', data.get('dislike_mid', [])))
            },
            'recent': {
                'high': normalize_list(data.get('recent_high', [])),
                'low': normalize_list(data.get('recent_low', data.get('recent_mid', [])))
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
    """중분류 카테고리 목록"""
    categories = get_menu_categories()
    if category in categories:
        return list(categories[category].keys())
    return []

def get_foods(category, subcategory):
    """소분류 음식 목록"""
    categories = get_menu_categories()
    if category in categories and subcategory in categories[category]:
        return categories[category][subcategory]
    return []

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

@app.route('/')
def index():
    """메인 대시보드"""
    return render_template('index.html')

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

@app.route('/api/network-info')
def api_network_info():
    """QR에 넣을 수 있는 접속 주소 후보."""
    port = int(os.environ.get('PORT', 5000))
    env_base_url = os.environ.get('MM_PUBLIC_BASE_URL', '').rstrip('/')
    urls = get_reachable_base_urls(port)
    if env_base_url:
        urls.insert(0, env_base_url)
    unique_urls = list(dict.fromkeys(urls))
    recommended = env_base_url or (unique_urls[1] if len(unique_urls) > 1 else unique_urls[0])
    return jsonify({'base_urls': unique_urls, 'recommended': recommended})

@app.route('/api/session/create', methods=['POST'])
def create_session():
    """새 추천 세션 생성"""
    data = request.json or {}
    session_id = str(uuid.uuid4())[:8]
    mobile_enabled = bool(data.get('mobile_enabled', False))
    include_demo_participants = bool(data.get('include_demo_participants', True))
    public_base_url = (data.get('public_base_url') or os.environ.get('MM_PUBLIC_BASE_URL') or request.host_url).rstrip('/')
    join_url = f'{public_base_url}/join/{session_id}'
    participants = load_demo_participants() if include_demo_participants else []
    
    session_data = {
        'id': session_id,
        'created': datetime.now().isoformat(),
        'participants': participants,
        'groups': int(data.get('groups', 2)),
        'location': data.get('location', '세종대학교'),
        'provider': data.get('provider', 'mock'),
        'status': 'collecting',
        'mobile_enabled': mobile_enabled,
        'join_url': join_url if mobile_enabled else ''
    }
    
    sessions_store[session_id] = session_data
    persist_mobile_session(session_data)
    return jsonify({
        'session_id': session_id,
        'join_url': session_data['join_url'],
        'mobile_enabled': mobile_enabled,
        'provider': session_data['provider'],
        'participant_count': len(participants),
        'participants': participants
    })

@app.route('/api/session/<session_id>/add-participant', methods=['POST'])
def add_participant(session_id):
    """참가자 추가"""
    if not ensure_session_loaded(session_id):
        return jsonify({'error': 'Session not found'}), 404
    
    session_data = sessions_store[session_id]
    data = request.json or {}
    source = data.get('source', 'manual')
    if session_data.get('status') != 'collecting':
        return jsonify({'error': 'Session is closed'}), 409
    if source == 'mobile' and not session_data.get('mobile_enabled'):
        return jsonify({'error': 'Mobile collection is disabled'}), 403

    participant = build_participant(data, session_data, source)
    
    session_data['participants'].append(participant)
    persist_mobile_session(session_data)
    return jsonify({'success': True, 'participant': participant, 'participant_count': len(session_data['participants'])})

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
        'participants': session_data['participants']
    }
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write('\n')
    return path

def make_cli_payload(command, completed_stdout, completed_stderr, returncode):
    result = json.loads(completed_stdout)
    result['cli'] = {
        'command': ' '.join(command),
        'stderr': completed_stderr,
        'stdout': completed_stdout,
        'returncode': returncode,
    }
    return result

def append_cli_job_event(job_id, event):
    with cli_jobs_lock:
        job = cli_jobs.get(job_id)
        if not job:
            return
        job.setdefault('events', []).append({
            'time': datetime.now().isoformat(timespec='seconds'),
            **event
        })

def update_cli_job(job_id, **updates):
    with cli_jobs_lock:
        job = cli_jobs.get(job_id)
        if not job:
            return
        job.update(updates)

def run_cli_recommendations_job(job_id, session_id, session_data):
    provider = session_data.get('provider', 'mock')
    location = session_data.get('location', '세종대학교')
    session_file = build_cli_session_file(session_data)
    command = [
        'sh',
        os.path.join(BASE_DIR, 'recommend.sh'),
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
        append_cli_job_event(job_id, {'type': 'output', 'text': 'recommend.sh 프로세스를 시작했습니다.'})

        assert process.stderr is not None
        for line in process.stderr:
            clean_line = line.rstrip('\n')
            stderr_lines.append(clean_line)
            if clean_line.startswith('[cmd] '):
                append_cli_job_event(job_id, {'type': 'command', 'text': clean_line[6:]})
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

        session_data['status'] = 'completed'
        session_data['result_file'] = output_file
        persist_mobile_session(session_data)
        append_cli_job_event(job_id, {'type': 'output', 'text': '완료: 추천 결과 JSON을 웹 화면으로 전달했습니다.'})
        update_cli_job(job_id, status='completed', result=output)
    except Exception as e:
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
    grouped_members = build_groups(participants, group_count)
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
            session_data.get('provider', 'mock')
        )
        
        groups.append({
            'group_id': group_idx,
            'members': members,
            'recommendations': recommendations[:3]
        })
    
    return groups

def aggregate_preferences(members):
    """그룹 선호도 집계"""
    like_high = []
    like_low = []
    dislike_high = []
    dislike_low = []
    recent = []
    
    for p in members:
        prefs = p['preferences']
        like_high.extend(leaf_values(prefs['like'].get('high', [])))
        like_low.extend(leaf_values(prefs['like'].get('low', [])))
        dislike_high.extend(leaf_values(prefs.get('dislike', {}).get('high', [])))
        dislike_low.extend(leaf_values(prefs.get('dislike', {}).get('low', [])))
        recent.extend(leaf_values(prefs['recent'].get('high', []) + prefs['recent'].get('low', [])))
    
    return {
        'positive': list(dict.fromkeys(like_high + like_low)),
        'like_high': list(dict.fromkeys(like_high)),
        'like_low': list(dict.fromkeys(like_low)),
        'dislike_high': list(dict.fromkeys(dislike_high)),
        'dislike_low': list(dict.fromkeys(dislike_low)),
        'recent': list(dict.fromkeys(recent))
    }

def build_recommendation_reason(restaurant, profile):
    """점수에 사용된 단순 규칙을 사람이 읽는 설명으로 변환"""
    parts = []
    if restaurant['category'] in profile['like_high']:
        parts.append(f"matched preferred category {restaurant['category']}")
    if restaurant['food'] in profile['like_low']:
        parts.append(f"matched preferred food {restaurant['food']}")
    if restaurant['category'] in profile['recent'] or restaurant['food'] in profile['recent']:
        parts.append("recently eaten category or food was penalized")
    if restaurant['category'] in profile['dislike_high']:
        parts.append(f"disliked category {restaurant['category']} was penalized")
    if restaurant['food'] in profile['dislike_low']:
        parts.append(f"disliked food {restaurant['food']} was strongly penalized")
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

def get_restaurant_recommendations(profile, location, provider='mock'):
    """그룹 프로필로 인근 식당 후보를 가져와 점수화."""
    try:
        search_terms = list(dict.fromkeys(profile['positive'] + profile['recent']))
        if provider == 'naver':
            restaurants = search_restaurants(search_terms, location)
        else:
            restaurants = search_mock_restaurants(search_terms, location)

        candidates = []
        for r in restaurants:
            matched_terms = r.get('matched_terms', [r.get('food', '')])
            score = 0.0
            if r['category'] in profile['like_high']:
                score += 0.5
            if r['food'] in profile['like_low']:
                score += 0.3
            if any(term in profile['recent'] for term in matched_terms) or r['category'] in profile['recent'] or r['food'] in profile['recent']:
                score -= 0.5
            if r['category'] in profile['dislike_high']:
                score -= 0.8
            if r['food'] in profile['dislike_low']:
                score -= 1.0
            
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
        return candidates[:3]
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
