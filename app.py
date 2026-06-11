#!/usr/bin/env python3
"""
실시간 식당 추천 시스템 웹 GUI
Flask 기반 대시보드로 사용자 입력 수집 및 실시간 시각화
"""

from flask import Flask, render_template, request, jsonify, session
import json
import subprocess
import os
import tempfile
from datetime import datetime
import uuid

from grouping_utils import build_groups
from naver_restaurant_api import search_restaurants

app = Flask(__name__)
app.secret_key = 'restaurant-recommendation-secret-key'

# 임시 세션 데이터 저장소
sessions_store = {}

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
        with open('dataset/menu_categories.json', 'r', encoding='utf-8') as f:
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

@app.route('/')
def index():
    """메인 대시보드"""
    return render_template('index.html')

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

@app.route('/api/session/create', methods=['POST'])
def create_session():
    """새 추천 세션 생성"""
    data = request.json
    session_id = str(uuid.uuid4())[:8]
    
    session_data = {
        'id': session_id,
        'created': datetime.now().isoformat(),
        'participants': [],
        'groups': int(data.get('groups', 2)),
        'location': data.get('location', '세종대학교'),
        'status': 'collecting'
    }
    
    sessions_store[session_id] = session_data
    return jsonify({'session_id': session_id})

@app.route('/api/session/<session_id>/add-participant', methods=['POST'])
def add_participant(session_id):
    """참가자 추가"""
    if session_id not in sessions_store:
        return jsonify({'error': 'Session not found'}), 404
    
    data = request.json
    user_id = data.get('user_id', f'U{len(sessions_store[session_id]["participants"]) + 1:02d}')
    
    participant = {
        'user_id': user_id,
        'preferences': {
            'like': {
                'high': data.get('like_high', []),
                'low': data.get('like_low', data.get('like_mid', []))
            },
            'dislike': {
                'high': data.get('dislike_high', []),
                'low': data.get('dislike_low', data.get('dislike_mid', []))
            },
            'recent': {
                'high': data.get('recent_high', []),
                'low': data.get('recent_low', data.get('recent_mid', []))
            }
        }
    }
    
    sessions_store[session_id]['participants'].append(participant)
    return jsonify({'success': True, 'participant_count': len(sessions_store[session_id]['participants'])})

@app.route('/api/session/<session_id>/generate-recommendations', methods=['POST'])
def generate_recommendations(session_id):
    """추천 생성"""
    if session_id not in sessions_store:
        return jsonify({'error': 'Session not found'}), 404
    
    session_data = sessions_store[session_id]

    try:
        recommendations = generate_group_recommendations(session_data)
        
        output = {
            'session': {
                'participant_count': len(session_data['participants']),
                'group_count': session_data['groups'],
                'location': session_data['location']
            },
            'provider': 'naver',
            'participants': session_data['participants'],
            'groups': recommendations
        }
        
        # 결과 저장
        output_file = f'/tmp/session_{session_id}_result.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        
        session_data['status'] = 'completed'
        session_data['result_file'] = output_file
        
        return jsonify({'success': True, 'result': output})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
        recommendations = get_restaurant_recommendations(group_profile, session_data['location'])
        
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
        like_high.extend(prefs['like'].get('high', []))
        like_low.extend(prefs['like'].get('low', []))
        dislike_high.extend(prefs.get('dislike', {}).get('high', []))
        dislike_low.extend(prefs.get('dislike', {}).get('low', []))
        recent.extend(prefs['recent']['high'] + prefs['recent'].get('low', []))
    
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

def get_restaurant_recommendations(profile, location):
    """식당 추천 (Naver local search 사용)"""
    try:
        search_terms = list(dict.fromkeys(profile['positive'] + profile['recent']))
        restaurants = search_restaurants(search_terms, location)

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
                'score': round(score, 3),
                'reason': build_recommendation_reason(r, profile),
                'rating': r.get('rating', '')
            })

        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates[:3]
    except Exception as e:
        print(f"Error getting recommendations: {e}")
        return []

@app.route('/api/session/<session_id>')
def get_session(session_id):
    """세션 조회"""
    if session_id not in sessions_store:
        return jsonify({'error': 'Session not found'}), 404
    
    return jsonify(sessions_store[session_id])

if __name__ == '__main__':
    app.run(debug=True, port=5000, host='127.0.0.1')
