from pathlib import Path
from dotenv import load_dotenv
import os, requests

load_dotenv(Path(__file__).with_name('.env'), override=True)

kid = (os.getenv("NCLOUD_API_KEY_ID") or "").strip()
ksec = (os.getenv("NCLOUD_API_KEY") or "").strip()

headersU = {  # 대문자
    "X-NCP-APIGW-API-KEY-ID": kid,
    "X-NCP-APIGW-API-KEY": ksec,
    "Accept": "application/json",
}
headersL = {  # 소문자 (게이트웨이는 보통 대소문자 무시하지만 혹시 몰라 둘 다 시험)
    "x-ncp-apigw-api-key-id": kid,
    "x-ncp-apigw-api-key": ksec,
    "Accept": "application/json",
}

print("kid len:", len(kid), "val:", repr(kid))
print("ksec len:", len(ksec), "val:", repr(ksec))

url = "https://maps.apigw.ntruss.com/map-geocode/v2/geocode"  # 이 도메인 추천
for h in (headersU, headersL):
    r = requests.get(url, headers=h, params={"query":"서울역"}, timeout=10)
    print("try:", "upper" if h is headersU else "lower",
          "status:", r.status_code, r.text[:180])

CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

url = "https://openapi.naver.com/v1/search/local.json"
params = {
    "query": "서울역",
    "display": 5,
    "start": 1,
    "sort": "random"
}
headers = {
    "X-Naver-Client-Id": CLIENT_ID,
    "X-Naver-Client-Secret": CLIENT_SECRET
}

res = requests.get(url, headers=headers, params=params)
print(res.status_code, res.json())
print("MAPS_ID endswith:", os.getenv("NCLOUD_API_KEY_ID","")[-6:])
print("MAPS_KEY endswith:", os.getenv("NCLOUD_API_KEY","")[-6:])
