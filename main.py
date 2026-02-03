import os
import requests
import json
import re
from google import genai
from datetime import datetime, timedelta

# 1. 환경 설정 및 클라이언트 초기화
NAVER_ID = os.environ['NAVER_CLIENT_ID']
NAVER_SECRET = os.environ['NAVER_CLIENT_SECRET']
client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
MODEL_NAME = 'gemini-2.5-flash'

def get_24h_news():
    """1단계: 최근 24시간 내 AI 관련 기사 수집"""
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
                    item['title'] = re.sub(r'<[^>]*>', '', item['title'])
                    item['description'] = re.sub(r'<[^>]*>', '', item['description'])
                    filtered_news.append(item)
            except: continue
        
        print(f">>> 필터링 완료: 최근 24시간 내 기사 {len(filtered_news)}개 발견")
        return filtered_news
    except Exception as e:
        print(f"!!! 뉴스 API 호출 에러: {e}")
        return []

def get_full_text_securely(url):
    """방어벽을 우회하여 기사 전문을 수집 (Jina Reader 방식)"""
    try:
        # 이 주소는 뉴스 사이트의 보안을 우회하여 본문만 텍스트로 변환해줍니다.
        jina_url = f"https://r.jina.ai/{url}"
        # 브라우저처럼 보이게 헤더 설정
        headers = {"Accept": "application/json"}
        response = requests.get(jina_url, headers=headers, timeout=15)
        if response.status_code == 200:
            return response.json().get('data', {}).get('content', "")
        return ""
    except:
        return ""

def analyze_and_publish():
    news_pool = get_24h_news()
    
    if not news_pool:
        final_html_body = "<h2>최근 24시간 내 수집된 AI 관련 뉴스가 없습니다.</h2>"
    else:
        # [2~3단계] 제목 기준 분류 및 중복도 선별
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

        # [4~5단계] 분야별 전문 분석 및 요약 제공
        for category, items in category_map.items():
            print(f">>> [{category}] 분야 직접 링크 분석 시작...")
            unique_articles = []
            
            for item in items[:10]: # 후보 중 상위 5개 선별
                if len(unique_articles) >= 5: break
                link = item.get('link')
                
                # 방어벽 우회하여 전문 가져오기
                full_text = get_full_text_securely(link)
                
                # 본문이 너무 짧거나 가져오지 못했다면 스킵
                if len(full_text) < 300:
                    print(f"   - 본문 수집 실패 혹은 내용 부족으로 건너뜀: {link}")
                    continue

                # 전문을 기반으로 분석 수행
                analysis_prompt = f"""
                당신은 ai서비스 브랜드 기획 전문가입니다.
                다음 기사 전문을 정독하고 핵심 내용을 요약해 주세요.
                
                기사 전문: {full_text[:5000]}
                """
                
                try:
                    res = client.models.generate_content(model=MODEL_NAME, contents=analysis_prompt)
                    unique_articles.append({
                        "title": item.get('title'),
                        "link": link,
                        "summary": res.text.replace('\n', '<br>')
                    })
                    print(f"   + 분석 완료: {item.get('title')[:15]}...")
                except: continue

            if unique_articles:
                final_html_body += f"<section><h2>[{category}] 주요 뉴스</h2><ul>"
                for a in unique_articles:
                    final_html_body += f"<li><a href='{a['link']}' target='_blank'><strong>{a['title']}</strong></a><p>{a['summary']}</p></li>"
                final_html_body += "</ul></section><hr>"

    # 6. 최종 HTML 생성
    update_time = (datetime.utcnow() + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M')
    html_template = f"<html><body style='font-family:sans-serif; padding:40px;'><div>{update_time} KST 업데이트</div><h1>🤖 AI 브랜드 인사이트 리포트</h1>{final_html_body}</body></html>"
    
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_template)
    print(">>> [완료] 리포트 생성 성공")

if __name__ == "__main__":
    analyze_and_publish()
    print(">>> [완료] 구글 인프라 기반 리포트가 성공적으로 생성되었습니다.")

if __name__ == "__main__":
    analyze_and_publish()
