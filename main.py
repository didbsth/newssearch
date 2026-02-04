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
당신은 뉴스 요약 및 지식 전달 전문가입니다.
1. 모든 답변은 인사말이나 부연 설명 없이 '본론'만 출력합니다.
2. 요약 시 반드시 한국어 3문장으로 구성합니다.
3. 전문 용어나 기술적 단어는 일반인이 이해하기 쉽게 풀어서 쓰거나, 괄호를 활용해 설명을 덧붙이세요. (예: LLM(거대언어모델))
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
                print(f"!!! 트래픽 초과(429). {wait}초 후 재시도... ({i+1}/{max_retries})")
                time.sleep(wait)
            else:
                raise e

def get_expanded_keywords(base_keyword):
    """[요구사항 2] 키워드 유의어 생성 및 검증"""
    print(f">>> [준비] '{base_keyword}' 관련 유의어 생성 및 검증 중...")
    prompt = f"""
    사용자가 검색하려는 키워드: '{base_keyword}'
    1. 이 키워드와 의미상 매우 유사하거나 뉴스 검색 시 함께 사용하기 좋은 유의어를 최대 3개 생성하세요.
    2. 생성된 유의어가 원래 키워드의 의미 범위를 너무 벗어나는지 스스로 검토하세요.
    3. 최종적으로 검색에 사용할 키워드 리스트를 JSON 배열 형식으로 반환하세요.
    결과 예시: ["인공지능", "AI", "LLM", "생성형 AI"]
    """
    try:
        res = call_gemini_with_retry(prompt, is_json=True)
        keywords = json.loads(res)
        if base_keyword not in keywords:
            keywords.insert(0, base_keyword)
        print(f">>> 확정된 검색어: {keywords}")
        return keywords
    except:
        return [base_keyword]

def get_24h_news(keywords):
    """[요구사항 1] 입력받은 키워드들로 뉴스 수집"""
    print(f">>> [1단계] 네이버 뉴스 수집 중...")
    all_filtered = []
    seen_links = set()
    
    headers = {"X-Naver-Client-Id": NAVER_ID, "X-Naver-Client-Secret": NAVER_SECRET}
    now_kst = datetime.utcnow() + timedelta(hours=9)

    for kw in keywords:
        url = f"https://openapi.naver.com/v1/search/news.json?query={kw}&display=50&sort=date"
        try:
            response = requests.get(url, headers=headers)
            items = response.json().get('items', [])
            
            for item in items:
                link = item['link']
                if link in seen_links: continue
                
                pub_date = datetime.strptime(item['pubDate'][:-6], "%a, %d %b %Y %H:%M:%S")
                if now_kst - pub_date <= timedelta(hours=24):
                    clean_title = re.sub(r'<[^>]*>', '', item['title'])
                    clean_desc = re.sub(r'<[^>]*>', '', item['description'])
                    all_filtered.append({
                        "title": clean_title, 
                        "link": link,
                        "desc": clean_desc
                    })
                    seen_links.add(link)
        except:
            continue
            
    print(f">>> 총 {len(all_filtered)}개의 고유 기사 확보.")
    return all_filtered

def verify_relevancy(summary, base_keyword):
    """[요구사항 3] 요약문이 원래 키워드와 관련 있는지 검토"""
    prompt = f"다음 뉴스 요약 내용이 '{base_keyword}'와(과) 관련이 있는 내용인지 판단하여 YES 또는 NO로만 대답하세요.\n\n요약 내용: {summary}"
    try:
        res = call_gemini_with_retry(prompt).strip().upper()
        return "YES" in res
    except:
        return True # 판단 실패 시 기본적으로 포함

def analyze_and_publish():
    # [요구사항 1] 키워드 입력
    user_input = input("뉴스 리포트를 생성할 키워드를 입력하세요: ")
    if not user_input: return

    # [요구사항 2] 키워드 확장
    search_keywords = get_expanded_keywords(user_input)
    
    news_pool = get_24h_news(search_keywords)
    if not news_pool: 
        print("최근 24시간 내 관련 기사가 없습니다.")
        return

    print(">>> [2-3단계] AI 중복 제거 및 카테고리 분류 중...")
    json_format = '{"카테고리명": [{"title": "제목", "link": "링크", "desc": "설명"}]}'
    process_prompt = f"아래 뉴스 리스트에서 중복을 제거하고 주제별로 분류해. JSON 구조: {json_format}\n데이터: {news_pool[:40]}"
    
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
            
            # [요구사항 4] 전문 용어 풀이 지시 포함
            reading_prompt = f"""
            작업 지시:
            1. 본문 정독: {link}
            2. 접속 제한 시 구글 검색으로 '{title}' 관련 기사 3개 탐색 후 정독.
            3. 본문 기반으로 한국어 3문장 요약을 생성하세요.
            4. **[필수] 전문 용어(Jargon)나 어려운 기술 용어는 괄호를 사용해 친절하게 풀어서 설명하세요.**
            5. 모든 시도 실패 시 "다른 기사 3개 접속 시도, 모든 기사 접속이 제한되었습니다" 출력.
            참고 메모: {desc}
            """
            
            try:
                time.sleep(1.2) 
                summary = call_gemini_with_retry(reading_prompt, use_search=True)
                
                # [요구사항 3] 키워드 연관성 검토
                if not verify_relevancy(summary, user_input):
                    print(f"   - 제외(연관성 낮음): {title[:20]}...")
                    continue

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

    # HTML 저장
    update_time = (datetime.utcnow() + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M')
    html_template = f"""
    <html>
    <body style='font-family:sans-serif; padding:40px; line-height:1.6;'>
        <div style='color:#888;'>{update_time} KST / 검색 키워드: {user_input}</div>
        <h1>🤖 AI 뉴스 정독 리포트</h1>
        {final_html_body}
    </body>
    </html>
    """
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_template)
    print(">>> [완료] 리포트 생성 성공.")

if __name__ == "__main__":
    analyze_and_publish()
