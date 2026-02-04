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

# [추가] 공통 시스템 지침: 모델의 태도를 고정합니다.
SYSTEM_INSTRUCTION = """
당신은 뉴스 요약 및 데이터 처리 전문가입니다.
1. 모든 답변은 서론, 결론, '알겠습니다' 같은 인사말 없이 '본론'만 즉시 출력합니다.
2. 요약 요청 시 반드시 한국어 3문장으로 구성합니다.
3. 검색 도구를 사용할 때 '검색하겠습니다'라는 말을 절대 내뱉지 마세요. 결과만 보여주세요.
"""

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
                clean_title = re.sub(r'<[^>]*>', '', item['title'])
                filtered.append({"title": clean_title, "link": item['link']})
        
        print(f">>> {len(filtered)}개의 후보 제목 확보.")
        return filtered
    except: return []

def analyze_and_publish():
    news_pool = get_24h_news()
    if not news_pool: return

    # 2~3단계: 중복 제거 및 카테고리 분류
    print(">>> [2-3단계] AI 중복 제거 및 카테고리 분류 중...")
    process_prompt = f"""
    아래 뉴스 제목 리스트를 분석해:
    1. 동일한 사건을 다루는 중복 제목은 하나만 남기고 제거해.
    2. 남은 고유 기사들을 [경제, 사회, 생활&문화, 산업, 정치, it&과학, 해외] 카테고리로 분류해.
    3. 반드시 순수 JSON 형식으로만 응답해. 예: {{"경제": [{"title": "제목", "link": "링크"}]}}
    데이터: {news_pool}
    """
    
    try:
        res = client.models.generate_content(
            model=MODEL_NAME, 
            contents=process_prompt,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION)
        )
        # JSON만 추출하기 위한 정규식
        json_match = re.search(r'\{.*\}', res.text, re.DOTALL)
        category_map = json.loads(json_match.group())
    except Exception as e:
        print(f"!!! 중복 제거 및 분류 실패: {e}")
        return

    final_html_body = ""

    # 4단계: 개별 기사 정독 및 분석
    for category, items in category_map.items():
        if not items: continue
        print(f">>> [{category}] 분야 분석 시작...")
        unique_articles = []
        
        for item in items[:5]: # RPM 제한을 고려해 카테고리당 5개 제한
            link = item.get('link')
            # [수정] 프롬프트를 더 엄격하게 변경
            reading_prompt = f"다음 뉴스 링크의 본문을 정독하고 한국어 3문장으로 요약하세요. 불필요한 설명은 생략하십시오: {link}"
            
            try:
                time.sleep(4) # Rate Limit 방지
                
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=reading_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION, # 시스템 지침 재강조
                        tools=[types.Tool(google_search=types.GoogleSearch())]
                    )
                )
                
                # [수정] 결과 텍스트가 비어있지 않은지 확인하고 정제
                summary = response.text.strip()
                if not summary or "요약해 드리겠습니다" in summary:
                    # 가끔 검색 로그만 남는 경우를 대비해 텍스트 파트 재확인
                    summary = "기사 내용을 분석하는 데 실패했습니다. (검색 결과 미도달)"

                unique_articles.append({
                    "title": item.get('title'),
                    "link": link,
                    "summary": summary.replace('\n', '<br>')
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

    # HTML 저장
    update_time = (datetime.utcnow() + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M')
    html_template = f"""
    <html>
    <body style='font-family: sans-serif; padding: 40px; line-height: 1.6; max-width: 800px; margin: auto;'>
        <div style='color: #666;'>{update_time} KST</div>
        <h1 style='border-bottom: 2px solid #333;'>🤖 AI 뉴스 정독 리포트</h1>
        {final_html_body}
    </body>
    </html>
    """
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_template)
    print(">>> [완료] 리포트 생성 성공.")

if __name__ == "__main__":
    analyze_and_publish()
