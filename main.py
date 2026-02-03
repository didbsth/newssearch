import os
import requests
import json
import re
from google import genai
from newspaper import Article
from datetime import datetime, timedelta

# 1. 설정 및 클라이언트 초기화
NAVER_ID = os.environ['NAVER_CLIENT_ID']
NAVER_SECRET = os.environ['NAVER_CLIENT_SECRET']
client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
MODEL_NAME = 'gemini-2.5-flash'

def get_24h_news():
    """1단계: 최근 24시간 내 AI 관련 기사 수집"""
    query = "AI OR ai OR 인공지능"
    # 최신순으로 100개 수집
    url = f"https://openapi.naver.com/v1/search/news.json?query={query}&display=100&sort=date"
    headers = {"X-Naver-Client-Id": NAVER_ID, "X-Naver-Client-Secret": NAVER_SECRET}
    res = requests.get(url, headers=headers).json().get('items', [])
    
    # 한국 시간(KST) 기준 24시간 필터링 (GitHub Actions는 UTC 기준이므로 9시간 보정)
    now_kst = datetime.utcnow() + timedelta(hours=9)
    filtered = []
    for item in res:
        try:
            pub_date = datetime.strptime(item['pubDate'][:-6], "%a, %d %b %Y %H:%M:%S")
            if now_kst - pub_date <= timedelta(hours=24):
                filtered.append(item)
        except: continue
    return filtered

def analyze_and_publish():
    news_pool = get_24h_news()
    if not news_pool:
        with open("index.html", "w", encoding="utf-8") as f:
            f.write("<html><body><h1>최근 24시간 내 수집된 뉴스가 없습니다.</h1></body></html>")
        return

    # 2~3단계: 제목 기반 분류 및 중복도 가중치 부여
    classification_prompt = f"""
    당신은 AI 서비스 브랜드 기획 전문가입니다. 
    다음 뉴스 제목들을 분석하여 경제/사회/생활&문화/산업/정치/it&과학/해외 7개 카테고리로 분류하세요.
    제목이 비슷하거나 같은 사건을 다룬 기사들은 하나로 묶고, 관련 기사가 많은 주제일수록 리스트 상단에 배치하세요.
    
    데이터: {news_pool}
    
    반드시 다음 JSON 형식으로만 답변하세요:
    {{"카테고리명": ["링크1", "링크2", "링크3", ...]}}
    """
    
    response = client.models.generate_content(model=MODEL_NAME, contents=classification_prompt)
    
    try:
        # JSON 문자열 추출 및 파싱
        json_str = re.search(r'\{.*\}', response.text, re.DOTALL).group()
        category_map = json.loads(json_str)
    except:
        print("AI 응답 파싱 실패. 원문:", response.text)
        return

    final_report_content = ""

    # 4~5단계: 분야별 최대 5개 기사 정독 및 중복 검증 (대체 로직)
    for category, links in category_map.items():
        unique_articles = []
        seen_summaries = "" # 중복 체크용 텍스트 저장
        
        link_index = 0
        while len(unique_articles) < 5 and link_index < len(links):
            target_link = links[link_index]
            link_index += 1
            
            try:
                article = Article(target_link, language='ko')
                article.download()
                article.parse()
                content = article.text[:1500] # 분석용 1500자 추출
                
                # 내용 중복 검증 루프 (AI에게 이전 기사와 겹치는지 확인)
                if unique_articles:
                    check_prompt = f"""
                    새로운 기사 내용이 기존 기사 요약본들과 80% 이상 겹치나요? '네' 또는 '아니오'로만 답하세요.
                    기존 요약: {seen_summaries}
                    새 기사: {content[:500]}
                    """
                    is_dup = client.models.generate_content(model=MODEL_NAME, contents=check_prompt).text
                    if "네" in is_dup:
                        print(f"중복 기사 건너뜀: {article.title}")
                        continue
                
                # 중복이 아니면 요약 진행
                summary_prompt = f"다음 기사를 AI 서비스 브랜드 기획자의 관점에서 3줄 요약하고 전략적 인사이트를 1줄 추가하세요: {content}"
                summary = client.models.generate_content(model=MODEL_NAME, contents=summary_prompt).text
                
                unique_articles.append({
                    "title": article.title,
                    "link": target_link,
                    "summary": summary.replace('\n', '<br>')
                })
                seen_summaries += f" / {summary[:200]}"
            except: continue

        # 카테고리별 HTML 섹션 생성
        if unique_articles:
            final_report_content += f"<section><h2>[{category}] 주요 뉴스</h2><ul>"
            for a in unique_articles:
                final_report_content += f"<li><a href='{a['link']}'><strong>{a['title']}</strong></a><p>{a['summary']}</p></li>"
            final_report_content += "</ul></section><hr>"

    # 6. 최종 HTML 파일 저장 (세련된 CSS 적용)
    html_template = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <title>AI 브랜드 인사이트 리포트</title>
        <style>
            body {{ font-family: 'Pretendard', sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 40px; background: #fdfdfd; }}
            h1 {{ color: #1a1a1a; text-align: center; border-bottom: 3px solid #1a1a1a; padding-bottom: 20px; }}
            h2 {{ color: #2c3e50; background: #edf2f7; padding: 10px 15px; border-left: 5px solid #2c3e50; }}
            ul {{ list-style: none; padding: 0; }}
            li {{ margin-bottom: 30px; border-bottom: 1px solid #eee; padding-bottom: 15px; }}
            a {{ color: #3182ce; text-decoration: none; font-size: 1.1em; }}
            p {{ color: #4a5568; font-size: 0.95em; margin-top: 10px; }}
            hr {{ border: 0; height: 1px; background: #ddd; margin: 40px 0; }}
            .date {{ text-align: right; color: #718096; }}
        </style>
    </head>
    <body>
        <div class="date">{datetime.now().strftime('%Y-%m-%d %H:%M')} KST 업데이트</div>
        <h1>🤖 AI 브랜드 인사이트 리포트</h1>
        {final_report_content}
    </body>
    </html>
    """
    
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_template)

if __name__ == "__main__":
    analyze_and_publish()
