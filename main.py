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

def get_24h_news():
    """1단계: 24시간 내 뉴스 제목들만 수집"""
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
                # 불필요한 태그 제거 및 제목/링크만 추출
                clean_title = re.sub(r'<[^>]*>', '', item['title'])
                filtered.append({"title": clean_title, "link": item['link']})
        
        print(f">>> {len(filtered)}개의 후보 제목 확보.")
        return filtered
    except: return []

def analyze_and_publish():
    news_pool = get_24h_news()
    if not news_pool: return

    # 2~3단계: 중복 제거 및 카테고리 분류 통합 호출 (할당량 절약)
    print(">>> [2-3단계] AI 중복 제거 및 카테고리 분류 중...")
    process_prompt = f"""
    아래 뉴스 제목 리스트를 분석해:
    1. 동일한 사건을 다루는 중복 제목은 하나만 남기고 모두 제거해.
    2. 남은 고유 기사들을 [경제, 사회, 생활&문화, 산업, 정치, it&과학, 해외] 카테고리로 분류해.
    3. 결과는 반드시 마크다운 없이 순수 JSON으로만 반환해.
    데이터: {news_pool}
    """
    
    try:
        res = client.models.generate_content(model=MODEL_NAME, contents=process_prompt)
        json_text = re.search(r'\{.*\}', res.text, re.DOTALL).group()
        category_map = json.loads(json_text)
    except:
        print("!!! 중복 제거 및 분류 실패")
        return

    final_html_body = ""

    # 4단계: 개별 기사 정독 및 분석
    for category, items in category_map.items():
        print(f">>> [{category}] 분야 분석 시작...")
        unique_articles = []
        
        for item in items[:5]: # 할당량 보호를 위해 카테고리당 최대 5개
            link = item.get('link')
            reading_prompt = f"다음 링크의 웹페이지 전체 소스에 접근하여 본문을 정독하고 3문장으로 요약해: {link}"
            
            try:
                # 429 에러 방지를 위한 호출 전 대기 (RPM 제한 준수)
                time.sleep(4) 
                
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=reading_prompt,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())]
                    )
                )
                
                unique_articles.append({
                    "title": item.get('title'),
                    "link": link,
                    "summary": response.text.strip().replace('\n', '<br>')
                })
                print(f"   + 분석 완료: {item.get('title')[:15]}...")
            except Exception as e:
                print(f"   - 정독 실패: {e}")
                continue

        if unique_articles:
            final_html_body += f"<section><h2>[{category}]</h2><ul>"
            for a in unique_articles:
                final_html_body += f"<li><a href='{a['link']}' target='_blank'><strong>{a['title']}</strong></a><p>{a['summary']}</p></li>"
            final_html_body += "</ul></section><hr>"

    # HTML 저장 로직 동일
    update_time = (datetime.utcnow() + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M')
    html_template = f"<html><body style='font-family:sans-serif; padding:40px;'><div>{update_time} KST</div><h1>🤖 AI 정독 리포트</h1>{final_html_body}</body></html>"
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_template)
    print(">>> [완료] 리포트 생성 성공.")

if __name__ == "__main__":
    analyze_and_publish()
