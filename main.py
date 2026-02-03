import os
import requests
import json
import re
from google import genai
from datetime import datetime, timedelta

# 1. 설정
NAVER_ID = os.environ['NAVER_CLIENT_ID']
NAVER_SECRET = os.environ['NAVER_CLIENT_SECRET']
client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
MODEL_NAME = 'gemini-2.5-flash'

def get_24h_news():
    print(">>> [1단계] 뉴스 수집 중...")
    query = "AI OR ai OR 인공지능"
    url = f"https://openapi.naver.com/v1/search/news.json?query={query}&display=100&sort=date"
    headers = {"X-Naver-Client-Id": NAVER_ID, "X-Naver-Client-Secret": NAVER_SECRET}
    
    try:
        res = requests.get(url, headers=headers).json().get('items', [])
        now_kst = datetime.utcnow() + timedelta(hours=9)
        filtered = []
        for item in res:
            try:
                pub_date = datetime.strptime(item['pubDate'][:-6], "%a, %d %b %Y %H:%M:%S")
                if now_kst - pub_date <= timedelta(hours=24):
                    # HTML 태그 미리 제거하여 데이터 순도 높임
                    item['title'] = re.sub(r'<[^>]*>', '', item['title'])
                    item['description'] = re.sub(r'<[^>]*>', '', item['description'])
                    filtered.append(item)
            except: continue
        return filtered
    except: return []

def get_clean_full_text(url):
    """방어벽 우회 및 본문 추출 로직 강화"""
    try:
        # 1. Jina Reader 호출 (본문 위주 추출 시도)
        jina_url = f"https://r.jina.ai/{url}"
        response = requests.get(jina_url, timeout=15)
        text = response.text
        
        # '내비게이션 메뉴'나 '로그인' 등 무의미한 단어가 본문보다 많으면 실패로 간주
        if "메뉴" in text[:200] or "navigation" in text.lower() or len(text) < 400:
            return ""
        return text
    except:
        return ""

def analyze_and_publish():
    news_pool = get_24h_news()
    if not news_pool: return

    # [분류 단계 생략] ... (기존 코드와 동일)

    final_html_body = ""
    for category, items in category_map.items():
        unique_articles = []
        for item in items[:5]:
            link = item.get('link')
            
            # 전문 수집 시도
            full_text = get_clean_full_text(link)
            
            # [핵심] 전문 수집 실패(메뉴만 읽힘) 시, 네이버 요약(description)을 본문으로 강제 할당
            analysis_target = full_text if full_text else item.get('desc', '내용 없음')
            
            # AI에게 "메뉴는 무시하고 알맹이만 분석하라"고 다시 한번 강조
            prompt = f"""
            다음 기사 데이터를 읽고 핵심 내용을 요약하세요. 
            만약 데이터에 웹사이트 메뉴나 UI 정보가 포함되어 있다면 이를 철저히 무시하고 기사 내용에만 집중하세요.

            기사 데이터: {analysis_target[:3000]}
            """
            
            try:
                res = client.models.generate_content(model=MODEL_NAME, contents=prompt)
                unique_articles.append(f"<li><a href='{link}'>{item.get('title')}</a><p>{res.text}</p></li>")
            except: continue

        if unique_articles:
            final_html_body += f"<h2>{category}</h2><ul>{''.join(unique_articles)}</ul>"

    # [HTML 저장 생략] ...
