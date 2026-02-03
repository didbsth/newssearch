import os
import requests
import json
from google import genai
from newspaper import Article
from datetime import datetime, timedelta

# 환경 설정
NAVER_ID = os.environ['NAVER_CLIENT_ID']
NAVER_SECRET = os.environ['NAVER_CLIENT_SECRET']
client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
MODEL_NAME = 'gemini-2.5-flash'

def get_24h_news():
    # [1단계] 24시간 이내의 AI 관련 기사 탐색
    query = "AI OR ai OR 인공지능"
    url = f"https://openapi.naver.com/v1/search/news.json?query={query}&display=100&sort=date"
    headers = {"X-Naver-Client-Id": NAVER_ID, "X-Naver-Client-Secret": NAVER_SECRET}
    res = requests.get(url, headers=headers).json().get('items', [])
    
    # 시간 필터링 (현재 시간 기준 24시간 전까지)
    filtered_news = []
    now = datetime.now()
    for item in res:
        # 네이버 날짜 형식: "Tue, 04 Feb 2026 10:00:00 +0900"
        pub_date = datetime.strptime(item['pubDate'][:-6], "%a, %d %b %Y %H:%M:%S")
        if now - pub_date <= timedelta(hours=24):
            filtered_news.append(item)
    return filtered_news

def analyze_and_publish():
    news_pool = get_24h_news()
    
    # [2~3단계] 제목 기준 분류 및 중요도(중복도) 판단
    initial_analysis_prompt = f"""
    당신은 ai서비스 브랜드 기획 전문가입니다.
    다음 뉴스 제목들을 분석하여 각 카테고리(경제, 사회, 생활&문화, 산업, 정치, it&과학, 해외)별로 분류하세요.
    같은 주제의 기사가 많을수록 해당 주제를 중요 기사로 선별하세요.
    각 카테고리별로 분석 후보 기사(링크) 10개를 중요도 순으로 나열하세요.
    
    데이터: {news_pool}
    반드시 JSON 형식으로만 응답하세요: {{"카테고리명": ["링크1", "링크2", ...]}}
    """
    
    analysis_res = client.models.generate_content(model=MODEL_NAME, contents=initial_analysis_prompt)
    try:
        # JSON 정제 루틴
        content = analysis_res.text
        target_map = json.loads(content[content.find('{'):content.rfind('}')+1])
    except:
        return print("AI 분류 단계 오류")

    final_sections = ""
    
    # [4~5단계] 본문 분석 및 중복 배제 (대체 로직)
    for category, links in target_map.items():
        unique_articles = []
        seen_contents = ""
        
        for link in links:
            if len(unique_articles) >= 5: break
            try:
                article = Article(link, language='ko')
                article.download()
                article.parse()
                text = article.text[:1500]
                
                # 중복 내용 검증 로직
                check_prompt = f"다음 기사 본문이 기존 기사들과 내용이 80% 이상 겹치나요? '네' 또는 '아니오'로만 답하세요.\n기존: {seen_contents[:1000]}\n신규: {text[:500]}"
                is_duplicate = client.models.generate_content(model=MODEL_NAME, contents=check_prompt).text
                
                if "아니오" in is_duplicate:
                    unique_articles.append({"title": article.title, "text": text, "link": link})
                    seen_contents += " " + text
            except: continue
        
        # 카테고리별 최종 요약 리포트 생성
        if unique_articles:
            summary_prompt = f"당신은 ai서비스 브랜드 기획 전문가로서 다음 기사들을 분석하여 브랜드 인사이트와 함께 요약하세요: {unique_articles}"
            summary_html = client.models.generate_content(model=MODEL_NAME, contents=summary_prompt).text
            final_sections += f"<div>{summary_html}</div>"

    # HTML 완성
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(f"<html><body style='font-family:sans-serif; padding:40px;'><h1>🤖 AI 브랜드 인사이트 리포트</h1>{final_sections}</body></html>")

if __name__ == "__main__":
    analyze_and_publish()
