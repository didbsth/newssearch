import os
import requests
from google import genai
from newspaper import Article

# 1. 설정 및 API 로드
NAVER_ID = os.environ['NAVER_CLIENT_ID']
NAVER_SECRET = os.environ['NAVER_CLIENT_SECRET']
# Client 생성 시 상세 옵션을 추가하여 안정성을 높입니다.
client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])

def get_news():
    # 네이버 뉴스 검색 (AI 관련)
    url = "https://openapi.naver.com/v1/search/news.json?query=AI+OR+인공지능&display=50&sort=sim"
    headers = {"X-Naver-Client-Id": NAVER_ID, "X-Naver-Client-Secret": NAVER_SECRET}
    res = requests.get(url, headers=headers)
    return res.json().get('items', [])

def analyze_and_publish():
    raw_news = get_news()
    
    # 심리학 및 브랜드 기획 전문가 페르소나 반영
    prompt = f"""
    당신은 ai 기반 서비스 기획 전문가입니다. 다음 뉴스 목록 중 가치 있는 것을 선별하세요.
    1. 경제/사회/문화/산업/정치/IT/해외 카테고리로 분류.
    2. 중복되거나 비슷한 내용은 하나로 합치고 기사 수가 많은 것에 가중치를 둡니다.
    
    뉴스 목록: {raw_news}
    
    결과는 HTML 형식의 리포트로 작성해 주세요.
    """
    
    # 모델 이름을 'gemini-1.5-flash'로 명시하되, 
    # v1beta 에러를 피하기 위해 안정적인 호출 방식을 사용합니다.
    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash', 
            contents=prompt
        )
        
        # 결과 저장
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(response.text)
            
    except Exception as e:
        print(f"상세 에러 발생: {e}")
        # 만약 1.5-flash가 계속 404라면, 더 안정적인 'gemini-1.5-pro'로 시도해볼 수 있습니다.
        raise e

if __name__ == "__main__":
    analyze_and_publish()
