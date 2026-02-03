import os
import requests
import json
from google import genai
from newspaper import Article

# 1. 환경 설정
NAVER_ID = os.environ['NAVER_CLIENT_ID']
NAVER_SECRET = os.environ['NAVER_CLIENT_SECRET']
client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])

# 2026년 표준 모델명으로 고정합니다.
MODEL_NAME = 'gemini-2.5-flash'

def get_news():
    # 'AI'와 '인공지능' 키워드로 최신 뉴스 50개를 가져옵니다.
    query = "AI OR 인공지능"
    url = f"https://openapi.naver.com/v1/search/news.json?query={query}&display=50&sort=sim"
    headers = {"X-Naver-Client-Id": NAVER_ID, "X-Naver-Client-Secret": NAVER_SECRET}
    res = requests.get(url, headers=headers)
    return res.json().get('items', [])

def analyze_and_publish():
    raw_news = get_news()
    
    # 심리학 연구원 및 브랜드 기획자로서의 페르소나를 주입합니다.
    prompt = f"""
    당신은 ai서비스 브랜드 기획 전문가입니다.
    제공된 뉴스 목록에서 다음 기준에 따라 '오늘의 인사이트 리포트'를 작성하세요.
    
    1. 카테고리 분류: 경제, 사회, 생활&문화, 산업, 정치, it&과학, 해외

    2. 중복 제거: 비슷한 내용은 하나로 합치고, 기사가 많은 사건일수록 중요하게 다룹니다.
    
    데이터: {raw_news}
    
    형식: 세련된 디자인의 HTML 코드로 작성하세요. (CSS 포함, head/body 태그 구성)
    """
    
    try:
        # 확인된 모델명을 사용하여 콘텐츠 생성
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
        )
        
        # 생성된 HTML 결과물 저장
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(response.text)
        print(f"성공: {MODEL_NAME} 모델로 리포트를 생성했습니다.")
            
    except Exception as e:
        print(f"최종 실행 중 에러 발생: {e}")
        raise e

if __name__ == "__main__":
    analyze_and_publish()
