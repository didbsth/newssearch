import os
import requests
import json
import re
import time
from google import genai
from newspaper import Article, Config
from datetime import datetime, timedelta

# 1. 환경 설정 및 클라이언트 초기화
NAVER_ID = os.environ['NAVER_CLIENT_ID']
NAVER_SECRET = os.environ['NAVER_CLIENT_SECRET']
client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
MODEL_NAME = 'gemini-2.5-flash'

# 뉴스 수집을 위한 브라우저 설정 (차단 방지)
config = Config()
config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
config.request_timeout = 10

def get_24h_news():
    print(">>> [1단계] 네이버 뉴스 API 호출 중...")
    query = "AI OR ai OR 인공지능"
    url = f"https://openapi.naver.com/v1/search/news.json?query={query}&display=100&sort=date"
    headers = {"X-Naver-Client-Id": NAVER_ID, "X-Naver-Client-Secret": NAVER_SECRET}
    
    try:
        response = requests.get(url, headers=headers)
        res_data = response.json().get('items', [])
        
        # 깃허브 서버(UTC) 기준 한국 시간(KST) 보정 (+9시간)
        now_kst = datetime.utcnow() + timedelta(hours=9)
        filtered_news = []
        
        for item in res_data:
            # pubDate 파싱: "Tue, 03 Feb 2026 10:00:00 +0900"
            try:
                pub_date = datetime.strptime(item['pubDate'][:-6], "%a, %d %b %Y %H:%M:%S")
                if now_kst - pub_date <= timedelta(hours=24):
                    filtered_news.append(item)
            except Exception as e:
                continue
        
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
        print(">>> [2단계] AI에게 카테고리 분류 및 중요도 선별 요청 중...")
        classification_prompt = f"""
        당신은 AI 서비스 브랜드 기획 전문가입니다.
        다음 뉴스 목록을 분석하여 [경제, 사회, 생활&문화, 산업, 정치, it&과학, 해외] 7개 카테고리로 분류하세요.
        내용이 겹치는 기사는 하나로 묶고, 관련 기사가 많은 주제를 리스트 상단에 두세요.
        
        데이터: {news_pool}
        
        반드시 다음 JSON 형식으로만 답변하세요:
        {{"카테고리명": ["링크1", "링크2", "링크3", ...]}}
        """
        
        response = client.models.generate_content(model=MODEL_NAME, contents=classification_prompt)
        
        try:
            # JSON만 추출하는 정규식
            json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            category_map = json.loads(json_match.group())
        except Exception as e:
            print(f"!!! AI 응답 파싱 실패: {e}")
            category_map = {}

        final_html_body = ""

        # [4~5단계] 분야별 기사 본문 분석 및 중복 배제 루프
        for category, links in category_map.items():
            print(f">>> [{category}] 카테고리 본문 분석 시작 (후보: {len(links)}개)")
            unique_articles = []
            seen_context = "" # 중복 체크용 텍스트 저장소
            
            link_index = 0
            while len(unique_articles) < 5 and link_index < len(links):
                target_link = links[link_index]
                link_index += 1
                
                try:
                    article = Article(target_link, config=config, language='ko')
                    article.download()
                    article.parse()
                    
                    content = article.text.strip()
                    if len(content) < 200: continue # 본문이 너무 짧으면 패스
                    
                    # AI를 이용한 본문 중복 검증
                    if unique_articles:
                        check_prompt = f"이 기사 내용이 기존 기사들과 80% 이상 중복되나요? '네' 혹은 '아니오'로만 답하세요.\n기존내용: {seen_context[:500]}\n새기사: {content[:500]}"
                        is_dup = client.models.generate_content(model=MODEL_NAME, contents=check_prompt).text
                        if "네" in is_dup:
                            print(f"   - 중복 기사 발견 및 건너뜀: {article.title[:20]}...")
                            continue
                    
                    # 요약 및 인사이트 생성
                    summary_prompt = f"AI 서비스 기획자 관점에서 다음 기사를 3줄 요약하고 브랜드 인사이트 1줄을 추가하세요:\n{content[:1500]}"
                    summary = client.models.generate_content(model=MODEL_NAME, contents=summary_prompt).text
                    
                    unique_articles.append({
                        "title": article.title,
                        "link": target_link,
                        "summary": summary.replace('\n', '<br>')
                    })
                    seen_context += f" {content[:300]}"
                    print(f"   + 기사 추가 완료: {article.title[:20]}...")
                    
                except Exception as e:
                    continue

            # HTML 섹션 구성
            if unique_articles:
                final_html_body += f"<section><h2>[{category}] 주요 뉴스</h2><ul>"
                for a in unique_articles:
                    final_html_body += f"<li><a href='{a['link']}' target='_blank'><strong>{a['title']}</strong></a><p>{a['summary']}</p></li>"
                final_html_body += "</ul></section><hr>"

    # 6. 최종 HTML 파일 생성 (CSS 포함)
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
            a:hover {{ text-decoration: underline; }}
            p {{ color: #4a5568; font-size: 0.98em; margin-top: 12px; background: #fff; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
            hr {{ border: 0; height: 1px; background: #ddd; margin: 40px 0; }}
            .date {{ text-align: right; color: #718096; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="date">{update_time} KST 업데이트</div>
        <h1>🤖 AI 브랜드 인사이트 리포트</h1>
        {final_report_content if 'final_report_content' in locals() else final_html_body}
    </body>
    </html>
    """
    
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_template)
    print(">>> [완료] index.html 파일이 성공적으로 생성되었습니다.")

if __name__ == "__main__":
    analyze_and_publish()
