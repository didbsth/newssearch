import os
import requests
import json
import re
import time
from google import genai
from google.genai import types
from datetime import datetime, timedelta

# 환경 설정
NAVER_ID = os.environ['NAVER_CLIENT_ID']
NAVER_SECRET = os.environ['NAVER_CLIENT_SECRET']
client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
MODEL_NAME = 'gemini-2.0-flash'

# 시스템 지침: 모델의 행동 강령 설정
SYSTEM_INSTRUCTION = """
당신은 뉴스 요약 전문가입니다.
1. 모든 답변은 인사말이나 부연 설명 없이 '본론'만 출력합니다.
2. 요약 시 반드시 한국어 3문장으로 구성합니다.
3. 검색 도구를 사용할 때 진행 상황을 말하지 마세요.
4. 모든 시도가 실패했을 경우에만 지정된 실패 문구를 출력합니다.
"""

def call_gemini_with_retry(prompt, is_json=False, use_search=False):
    max_retries = 3
    for i in range(max_retries):
        try:
            config_params = {"system_instruction": SYSTEM_INSTRUCTION}
            if is_json:
                config_params["response_mime_type"] = "application/json"
            if use_search:
                config_params["tools"] = [types.Tool(google_search=types.GoogleSearch())]

            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(**config_params)
            )
            return response.text
        except Exception as e:
            if "429" in str(e) and i < max_retries - 1:
                wait = (i + 1) * 5
                print(f"!!! 트래픽 초과(429) 감지. {wait}초 후 재시도... ({i+1}/{max_retries})")
                time.sleep(wait)
            else:
                raise e

def get_24h_news():
    print(">>> [1단계] 네이버 뉴스 제목 및 스니펫 수집 중...")
    query = "AI OR ai OR 인공지능"
    url = f"https://openapi.naver.com/v1/search/news.json?query={query}&display=100&sort=date"
    headers = {"X-Naver-Client-Id": NAVER_ID, "X-Naver-Client-Secret": NAVER_SECRET}
    
    try:
        response = requests.get(url, headers=headers)
        items = response.json().get('items', [])
        now_kst = datetime.utcnow() + timedelta(hours=9)
        filtered = []
        
        for item in items:
            pub_date = datetime.strptime(item['pubDate'][:-6], "%a, %d %b %Y %H:%M:%S")
            if now_kst - pub_date <= timedelta(hours=24):
                clean_title = re.sub(r'<[^>]*>', '', item['title'])
                # [수정] 스니펫(description) 추가 수집
                clean_desc = re.sub(r'<[^>]*>', '', item['description'])
                filtered.append({
                    "title": clean_title, 
                    "link": item['link'],
                    "desc": clean_desc
                })
        
        print(f">>> {len(filtered)}개의 후보 제목 확보.")
        return filtered
    except: return []

def analyze_and_publish():
    news_pool = get_24h_news()
    if not news_pool: return

    print(">>> [2-3단계] AI 중복 제거 및 카테고리 분류 중...")
    # [수정] 분류 단계에서도 desc를 함께 넘겨 정확도를 높임
    json_format = '{"카테고리명": [{"title": "제목", "link": "링크", "desc": "설명"}]}'
    process_prompt = f"""
    아래 뉴스 리스트에서 중복을 제거하고 분류해. 
    JSON 구조: {json_format}
    데이터: {news_pool[:50]}
    """
    
    try:
        res_text = call_gemini_with_retry(process_prompt, is_json=True)
        category_map = json.loads(res_text)
    except Exception as e:
        print(f"!!! 분류 실패: {e}")
        return

    final_html_body = ""

    # 4단계: 개별 기사 정독 및 분석
    for category, items in category_map.items():
        if not items: continue
        print(f">>> [{category}] 분야 분석 시작...")
        unique_articles = []
        
        for item in items[:5]:
            title = item.get('title')
            link = item.get('link')
            desc = item.get('desc', '')
            
            # [수정] 로직 강화 프롬프트
            reading_prompt = f"""
            작업 지시:
            1. 우선 다음 링크에 접속하여 본문을 정독하세요: {link}
            2. 만약 위 링크의 접속이 제한(403, 봇 차단 등)된다면, 구글 검색 도구를 사용하여 기사 제목 '{title}'으로 다른 언론사 기사를 3개 탐색하고 그 본문들을 읽으세요.
            3. 본문 기반으로 한국어 3문장 요약을 생성하세요.
            4. **만약 주요 링크와 검색된 3개의 다른 기사들까지 모두 접속이 제한되어 본문을 읽을 수 없다면, 반드시 토씨 하나 틀리지 말고 다음 문구만 출력하세요: "다른 기사 3개 접속 시도, 모든 기사 접속이 제한되었습니다"**
            5. 제공된 참고 메모(스니펫)는 본문 탐색 시 검증용으로만 사용하고, 요약은 최대한 탐색한 본문을 기반으로 하세요.
            
            참고 메모: {desc}
            """
            
            try:
                time.sleep(1.5) 
                summary = call_gemini_with_retry(reading_prompt, use_search=True)
                
                unique_articles.append({
                    "title": title,
                    "link": link,
                    "summary": summary.strip().replace('\n', '<br>')
                })
                print(f"   + 분석 완료: {title[:20]}...")
            except Exception as e:
                print(f"   - 정독 실패: {e}")
                continue

        if unique_articles:
            final_html_body += f"<section style='margin-bottom:30px;'><h2>[{category}]</h2><ul>"
            for a in unique_articles:
                final_html_body += f"<li style='margin-bottom:15px;'><a href='{a['link']}' target='_blank' style='font-weight:bold; color:#0066cc; text-decoration:none;'>{a['title']}</a><p style='margin:5px 0; color:#333;'>{a['summary']}</p></li>"
            final_html_body += "</ul></section><hr style='border:0; border-top:1px solid #eee;'>"

    # HTML 저장 로직 (이전과 동일)
    update_time = (datetime.utcnow() + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M')
    html_template = f"<html><body style='font-family:sans-serif; padding:40px;'><div>{update_time} KST</div><h1>🤖 AI 뉴스 정독 리포트</h1>{final_html_body}</body></html>"
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_template)
    print(">>> [완료] 리포트 생성 성공.")

if __name__ == "__main__":
    analyze_and_publish()
