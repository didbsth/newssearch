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

# 시스템 지침: 모델의 역할을 엄격히 제한
SYSTEM_INSTRUCTION = """
당신은 뉴스 요약 및 데이터 처리 전문가입니다.
1. 모든 답변은 서론, 결론, 인사말 없이 요청한 '본론'만 즉시 출력합니다.
2. 뉴스 요약은 반드시 한국어 3문장으로 구성합니다.
3. 검색 도구를 사용할 때 계획을 말하지 말고 결과만 반환하세요.
"""

def call_gemini_with_retry(prompt, is_json=False, use_search=False):
    """API 호출 및 429 에러 발생 시 재시도 로직"""
    max_retries = 3
    for i in range(max_retries):
        try:
            config_params = {
                "system_instruction": SYSTEM_INSTRUCTION,
            }
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
                print(f"!!! 트래픽 초과(429) 감지. {wait}초 후 재시도합니다... ({i+1}/{max_retries})")
                time.sleep(wait)
            else:
                raise e

def get_24h_news():
    print(">>> [1단계] 네이버 뉴스 제목 수집 중...")
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
                filtered.append({"title": clean_title, "link": item['link']})
        
        print(f">>> {len(filtered)}개의 후보 제목 확보.")
        return filtered
    except: return []

def analyze_and_publish():
    news_pool = get_24h_news()
    if not news_pool: return

    # 2~3단계: 중복 제거 및 카테고리 분류 (유료 티어용 JSON 모드 사용)
    print(">>> [2-3단계] AI 중복 제거 및 카테고리 분류 중...")
    # 중괄호 에러 방지를 위해 변수로 분리
    json_format = '{"카테고리명": [{"title": "제목", "link": "링크"}]}'
    process_prompt = f"""
    아래 뉴스 리스트에서 중복을 제거하고 [경제, 사회, 생활&문화, 산업, 정치, it&과학, 해외]로 분류해.
    형식은 반드시 다음 JSON 구조를 따라야 해: {json_format}
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
        
        for item in items[:5]: # 카테고리당 최대 5개
            link = item.get('link')
            reading_prompt = f"다음 뉴스 링크의 내용을 정독하고 한국어 3문장으로 요약해: {link}"
            
            try:
                # 유료 결제 시 sleep 시간을 1~2초로 줄여도 무방합니다.
                time.sleep(1.5) 
                
                summary = call_gemini_with_retry(reading_prompt, use_search=True)
                
                # 요약 결과가 정상적인지 검증
                if not summary or len(summary) < 20:
                    summary = "기사 내용을 읽어오는 데 실패했거나 요약할 수 없는 페이지입니다."

                unique_articles.append({
                    "title": item.get('title'),
                    "link": link,
                    "summary": summary.strip().replace('\n', '<br>')
                })
                print(f"   + 분석 완료: {item.get('title')[:20]}...")
            except Exception as e:
                print(f"   - 정독 실패: {e}")
                continue

        if unique_articles:
            final_html_body += f"<section style='margin-bottom:30px;'><h2>[{category}]</h2><ul>"
            for a in unique_articles:
                final_html_body += f"<li style='margin-bottom:15px;'><a href='{a['link']}' target='_blank' style='font-weight:bold; color:#0066cc; text-decoration:none;'>{a['title']}</a><p style='margin:5px 0; color:#333;'>{a['summary']}</p></li>"
            final_html_body += "</ul></section><hr style='border:0; border-top:1px solid #eee;'>"

    # HTML 저장
    update_time = (datetime.utcnow() + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M')
    html_template = f"""
    <html>
    <body style='font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 40px; line-height: 1.6; max-width: 900px; margin: auto; color: #333;'>
        <div style='color: #888; text-align: right;'>{update_time} KST</div>
        <h1 style='color: #1a1a1a; border-bottom: 3px solid #1a1a1a; padding-bottom: 10px;'>🤖 AI 뉴스 정독 리포트</h1>
        {final_html_body}
    </body>
    </html>
    """
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_template)
    print(">>> [완료] 리포트 생성 성공.")

if __name__ == "__main__":
    analyze_and_publish()
