import os
import requests
import json
import re
from google import genai
from google.genai import types
from datetime import datetime, timedelta

# 1. 환경 설정 및 클라이언트 초기화
NAVER_ID = os.environ['NAVER_CLIENT_ID']
NAVER_SECRET = os.environ['NAVER_CLIENT_SECRET']
client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
MODEL_NAME = 'gemini-2.5-flash'

def get_24h_news():
    """1단계: 최근 24시간 내 AI 관련 기사 수집 (네이버 API)"""
    print(">>> [1단계] 네이버 뉴스 API 호출 중...")
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
                    # HTML 태그 제거
                    item['title'] = re.sub(r'<[^>]*>', '', item['title'])
                    item['description'] = re.sub(r'<[^>]*>', '', item['description'])
                    filtered_news.append(item)
            except: continue
        
        print(f">>> 필터링 완료: 최근 24시간 내 기사 {len(filtered_news)}개 발견")
        return filtered_news
    except Exception as e:
        print(f"!!! 뉴스 API 호출 에러: {e}")
        return []

def analyze_and_publish():
    news_pool = get_24h_news()
    
    if not news_pool:
        final_html_body = "<h2>최근 24시간 내 수집된 AI 관련 뉴스가 없습니다.</h2>"
    else:
        # [2~3단계] AI 분류 및 중복도 기반 선별
        print(">>> [2단계] AI에게 카테고리 분류 요청 중...")
        classification_prompt = f"""
        당신은 ai서비스 브랜드 기획 전문가입니다.
        다음 뉴스 목록을 분석하여 [경제, 사회, 생활&문화, 산업, 정치, it&과학, 해외] 카테고리로 분류하세요.
        제목을 기준으로 중복되거나 같은 내용이라고 추정되는 기사들을 정리하고, 중복이 많은 사건일수록 우선순위를 높이세요.
        
        데이터: {news_pool}
        반드시 다음 JSON 형식으로만 답변하세요:
        {{"카테고리명": [ {{"title": "제목", "link": "주소"}}, ... ]}}
        """
        
        response = client.models.generate_content(model=MODEL_NAME, contents=classification_prompt)
        try:
            json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            category_map = json.loads(json_match.group())
        except:
            print("!!! AI 응답 파싱 실패")
            category_map = {}

        final_html_body = ""

        # [4~5단계] 구글 인프라 활용 본문 분석 및 요약 제공
        for category, items in category_map.items():
            print(f">>> [{category}] 분야 직접 링크 분석 시작...")
            unique_articles = []
            seen_summaries = "" # 중복 배제용
            
            for item in items[:10]: # 후보 중 상위 5개 선별 루프
                if len(unique_articles) >= 5: break
                link = item.get('link')
                
                # 구글 검색 도구(Grounding)를 사용하여 기사 전문을 읽도록 지시
                analysis_prompt = f"""
                당신은 ai서비스 브랜드 기획 전문가입니다.
                다음 뉴스 링크에 직접 접속하여 기사 전문을 분석하고 핵심 내용을 요약해 주세요: {link}
                
                - 만약 기사 내용이 이미 분석한 다음 내용과 겹친다면 '중복'이라고만 답변하세요: {seen_summaries}
                """
                
                try:
                    # Google Search Retrieval 도구 활성화
                    res = client.models.generate_content(
                        model=MODEL_NAME,
                        contents=analysis_prompt,
                        config=types.GenerateContentConfig(
                            tools=[types.Tool(google_search=types.GoogleSearch())]
                        )
                    )
                    
                    analysis_text = res.text
                    if "중복" not in analysis_text:
                        unique_articles.append({
                            "title": item.get('title'),
                            "link": link,
                            "summary": analysis_text.replace('\n', '<br>')
                        })
                        seen_summaries += analysis_text[:200]
                        print(f"   + 분석 완료: {item.get('title')[:15]}...")
                except: continue

            if unique_articles:
                final_html_body += f"<section><h2>[{category}] 주요 뉴스</h2><ul>"
                for a in unique_articles:
                    final_html_body += f"<li><a href='{a['link']}' target='_blank'><strong>{a['title']}</strong></a><p>{a['summary']}</p></li>"
                final_html_body += "</ul></section><hr>"

    # 6. 최종 HTML 생성 (사용자 제공 스타일 유지)
    update_time = (datetime.utcnow() + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M')
    html_template = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <title>AI 브랜드 인사이트 리포트</title>
        <style>
            body {{ font-family: 'Pretendard', sans-serif; line-height: 1.6; color: #333; max-width: 850px; margin: 0 auto; padding: 40px; background: #fdfdfd; }}
            h1 {{ color: #1a1a1a; text-align: center; border-bottom: 3px solid #1a1a1a; padding-bottom: 20px; }}
            h2 {{ color: #2c3e50; background: #edf2f7; padding: 10px 15px; border-left: 5px solid #2c3e50; margin-top: 40px; }}
            ul {{ list-style: none; padding: 0; }}
            li {{ margin-bottom: 30px; border-bottom: 1px solid #eee; padding-bottom: 15px; }}
            a {{ color: #3182ce; text-decoration: none; font-size: 1.15em; font-weight: bold; }}
            p {{ color: #4a5568; font-size: 0.98em; margin-top: 12px; background: #fff; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
            .date {{ text-align: right; color: #718096; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="date">{update_time} KST 업데이트</div>
        <h1>🤖 AI 브랜드 인사이트 리포트</h1>
        {final_html_body}
    </body>
    </html>
    """
    
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_template)
    print(">>> [완료] 구글 인프라 기반 리포트가 성공적으로 생성되었습니다.")

if __name__ == "__main__":
    analyze_and_publish()
