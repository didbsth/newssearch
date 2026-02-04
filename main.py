import os
import requests
import json
import re
from google import genai
from google.genai import types # 도구 설정을 위해 추가
from datetime import datetime, timedelta

# 1. 환경 설정 및 클라이언트 초기화
NAVER_ID = os.environ['NAVER_CLIENT_ID']
NAVER_SECRET = os.environ['NAVER_CLIENT_SECRET']
client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
MODEL_NAME = 'gemini-2.0-flash' # 정독 능력이 뛰어난 최신 모델 권장

def get_24h_news():
    """1단계: 네이버 API를 통해 뉴스 목록 수집 (기존 방식 유지)"""
    print(">>> [1단계] 네이버 뉴스 리스트 수집 중...")
    query = "AI OR ai OR 인공지능"
    url = f"https://openapi.naver.com/v1/search/news.json?query={query}&display=100&sort=date"
    headers = {"X-Naver-Client-Id": NAVER_ID, "X-Naver-Client-Secret": NAVER_SECRET}
    
    try:
        response = requests.get(url, headers=headers)
        res_data = response.json().get('items', [])
        now_kst = datetime.utcnow() + timedelta(hours=9)
        filtered_news = []
        
        for item in res_data:
            try:
                pub_date = datetime.strptime(item['pubDate'][:-6], "%a, %d %b %Y %H:%M:%S")
                if now_kst - pub_date <= timedelta(hours=24):
                    item['title'] = re.sub(r'<[^>]*>', '', item['title'])
                    filtered_news.append(item)
            except: continue
        
        print(f">>> {len(filtered_news)}개의 최신 기사 확보 완료.")
        return filtered_news
    except Exception as e:
        print(f"!!! 뉴스 수집 에러: {e}")
        return []

def analyze_and_publish():
    news_pool = get_24h_news()
    if not news_pool: return

    # [2단계] 분류 (Gemini에게 목록 전달)
    print(">>> [2단계] 카테고리 분류 중...")
    classification_prompt = f"다음 뉴스 목록을 분석하여 경제, 사회, 생활&문화, 산업, 정치, it&과학, 해외 카테고리로 분류하고 JSON 형식으로만 답하세요: {news_pool}"
    
    res = client.models.generate_content(model=MODEL_NAME, contents=classification_prompt)
    try:
        json_match = re.search(r'\{.*\}', res.text, re.DOTALL)
        category_map = json.loads(json_match.group())
    except: return

    final_html_body = ""

    # [3단계] 구글 인프라를 이용한 기사 전문 정독 및 분석
    for category, items in category_map.items():
        print(f">>> [{category}] 분야 기사 정독 시작...")
        unique_articles = []
        
        for item in items[:5]: # 각 분야 상위 5개 분석
            link = item.get('link')
            
            # [핵심] Gemini에게 구글 검색 도구를 사용하여 해당 링크를 정독하라고 지시합니다.
            # 이 명령은 사이트의 방어벽을 우회하여 본문 전체를 파악하게 합니다.
            reading_prompt = f"""
            다음 뉴스 링크에 접속하여 기사의 '전체 본문'을 정독한 후 내용을 요약해 주세요.
            링크: {link}
            
            요구사항:
            1. 웹사이트 메뉴나 광고 정보는 무시하고 기사 내용에만 집중하세요.
            2. 기사의 핵심 내용을 3~4문장으로 정리하세요.
            """
            
            try:
                # google_search 도구를 활성화하여 호출
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=reading_prompt,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())]
                    )
                )
                
                analysis_text = response.text
                unique_articles.append({
                    "title": item.get('title'),
                    "link": link,
                    "summary": analysis_text.replace('\n', '<br>')
                })
                print(f"   + 정독 완료: {item.get('title')[:15]}...")
            except Exception as e:
                print(f"   - 정독 실패 ({item.get('title')[:10]}): {e}")
                continue

        if unique_articles:
            final_html_body += f"<section><h2>[{category}] 주요 뉴스</h2><ul>"
            for a in unique_articles:
                final_html_body += f"<li><a href='{a['link']}' target='_blank'><strong>{a['title']}</strong></a><p>{a['summary']}</p></li>"
            final_html_body += "</ul></section><hr>"

    # 4단계: HTML 생성 및 저장 (기존 방식 유지)
    update_time = (datetime.utcnow() + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M')
    html_template = f"<html><body style='font-family:sans-serif; padding:40px;'><div>{update_time} KST</div><h1>🤖 AI 뉴스 정독 리포트</h1>{final_html_body}</body></html>"
    
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_template)
    print(">>> [완료] 구글 인프라 기반 리포트 생성 성공.")

if __name__ == "__main__":
    analyze_and_publish()
