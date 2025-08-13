# app.py
from flask import Flask, render_template, request
from pathlib import Path
from dotenv import load_dotenv
import os, requests, re
import weather_core

# ========== 1) .env 로드 ==========
dotenv_path = Path(__file__).with_name('.env')
load_dotenv(dotenv_path=dotenv_path, override=True)

# ========== 2) 키 읽기 ==========
NAVER_MAPS_KEY_ID = (os.getenv("NCLOUD_API_KEY_ID") or "").strip()   # Maps(Geocoding/Directions)용
NAVER_MAPS_KEY    = (os.getenv("NCLOUD_API_KEY") or "").strip()
NAVER_SEARCH_ID   = (os.getenv("NAVER_CLIENT_ID") or "").strip()     # 지역 검색(Open API)용
NAVER_SEARCH_SEC  = (os.getenv("NAVER_CLIENT_SECRET") or "").strip()

print("[NAVER MAPS] key_id?", bool(NAVER_MAPS_KEY_ID), " key?", bool(NAVER_MAPS_KEY))
print("[NAVER SEARCH] client_id?", bool(NAVER_SEARCH_ID), " secret?", bool(NAVER_SEARCH_SEC))

# ========== 3) 엔드포인트 ==========
# Geocoding/Directions는 두 도메인 모두 쓰는 사례가 있어 폴백 가능하게 둠
GEOCODE_URLS = [
    "https://naveropenapi.apigw.ntruss.com/map-geocode/v2/geocode",
    "https://maps.apigw.ntruss.com/map-geocode/v2/geocode",
]
DIRECTIONS_URLS = [
    "https://maps.apigw.ntruss.com/map-direction-15/v1/driving",
    "https://naveropenapi.apigw.ntruss.com/map-direction-15/v1/driving",
]
LOCAL_SEARCH_URL = "https://openapi.naver.com/v1/search/local.json"

# ========== 4) 공통 헤더 ==========
HEADERS_MAPS = {
    "X-NCP-APIGW-API-KEY-ID": NAVER_MAPS_KEY_ID,
    "X-NCP-APIGW-API-KEY":    NAVER_MAPS_KEY,
    "Accept": "application/json",
    "User-Agent": "ai-route/1.0",
}
HEADERS_SEARCH = {
    "X-Naver-Client-Id":     NAVER_SEARCH_ID,
    "X-Naver-Client-Secret": NAVER_SEARCH_SEC,
}

# ========== 5) 유틸: 지오코딩 + 지역검색 폴백 ==========
_TAG_RE = re.compile(r"<[^>]+>")

def _clean(s: str) -> str:
    s = _TAG_RE.sub("", s or "")
    return re.sub(r"\s+", " ", s).strip()

def geocode_address(addr: str):
    """네이버 지오코딩: 주소 -> (lng, lat) float. 실패 시 None."""
    if not (NAVER_MAPS_KEY_ID and NAVER_MAPS_KEY):
        print("[geocode] maps key missing")
        return None
    for url in GEOCODE_URLS:
        try:
            r = requests.get(url, headers=HEADERS_MAPS, params={"query": addr}, timeout=10)
            print(f"[geocode] {addr} {r.status_code} {url}")
            r.raise_for_status()
            items = (r.json() or {}).get("addresses") or []
            if not items:
                continue
            x, y = items[0].get("x"), items[0].get("y")
            if not x or not y:
                continue
            return float(x), float(y)
        except Exception as e:
            print("[geocode][err]", e)
            continue
    return None

def local_search_to_coords(query: str):
    """
    네이버 Local Search: 장소명 → 주소(roadAddress/ address) → 지오코딩 → (lng, lat)
    실패 시 None
    """
    if not (NAVER_SEARCH_ID and NAVER_SEARCH_SEC):
        print("[local] search key missing")
        return None
    try:
        r = requests.get(
            LOCAL_SEARCH_URL,
            headers=HEADERS_SEARCH,
            params={"query": query, "display": 5, "start": 1},
            timeout=10,
        )
        print(f"[local] {query} {r.status_code}")
        r.raise_for_status()
        items = (r.json() or {}).get("items") or []
        for it in items:
            road = _clean(it.get("roadAddress") or "")  # 도로명
            jibun = _clean(it.get("address") or "")     # 지번
            addr = road or jibun
            if not addr:
                continue
            xy = geocode_address(addr)
            if xy:
                return xy
    except Exception as e:
        print("[local][err]", e)
    return None

def resolve_to_coords(text: str):
    """주소 우선 → 실패 시 장소명 폴백 → 그래도 실패면 '역' 붙여 한 번 더."""
    text = (text or "").strip()
    # 1) 주소 시도
    xy = geocode_address(text)
    if xy:
        return xy
    # 2) 장소명 시도
    xy = local_search_to_coords(text)
    if xy:
        return xy
    # 3) 흔한 접미사 한 번 덧붙여 재시도
    if not text.endswith(("역", "터미널", "공항")):
        for q in (f"{text} 역", f"{text} 터미널", f"{text} 공항"):
            xy = geocode_address(q) or local_search_to_coords(q)
            if xy:
                return xy
    return None

def call_directions(sx: float, sy: float, ex: float, ey: float):
    """
    Directions 15 폴백 호출.
    성공하면 (json, None), 실패하면 (None, logs 문자열)
    """
    last_log = []
    params = {
        "start": f"{sx},{sy}",
        "goal":  f"{ex},{ey}",
        "option": "trafast",   # trafast / traoptimal / tracomfort / trashybrid / shortest
        "cartype": 1,
    }
    for url in DIRECTIONS_URLS:
        try:
            r = requests.get(
                url, headers=HEADERS_MAPS, params=params, timeout=20
            )
            ct = r.headers.get("Content-Type", "")
            body = r.text or ""
            print(f"[directions] {r.status_code} {url} ct={ct} len={len(body)}")
            last_log.append(f"url={url} code={r.status_code} ct={ct} len={len(body)}")
            if r.status_code == 200 and body.strip():
                try:
                    return r.json(), None
                except Exception as e:
                    print("[directions][json err]", e)
        except Exception as e:
            print("[directions][req err]", e)
    return None, " | ".join(last_log)

# ========== 6) Flask ==========
app = Flask(__name__)

@app.get("/")
def home():
    return render_template("home.html")

# ----- 날씨 -----
@app.route("/weather", methods=["GET", "POST"])
def weather():
    weather_info = None
    error_msg = None
    if request.method == "POST":
        city = (request.form.get("city") or "").strip()
        try:
            lat, lon, country = weather_core.get_coordinates(city)
            curr = weather_core.get_current_weather(lat, lon)
            icon_url = f"https://openweathermap.org/img/wn/{curr['icon']}@2x.png"

            forecast_list = weather_core.get_forecast(lat, lon)
            daily_df = weather_core.process_forecast_data(forecast_list)
            graph_file = weather_core.plot_forecast(daily_df, city, country)

            air = weather_core.get_air_pollution(lat, lon)
            convenience = weather_core.analyze_convenience(
                forecast_list, current_weather=curr, air_pollution_data=air
            )

            weather_info = {
                "city": city,
                "country": country,
                "desc": curr["desc"],
                "temp": curr["temp"],
                "icon_url": icon_url,
                "graph": graph_file,
                "convenience": convenience,
                "air": air,
            }
        except Exception as e:
            error_msg = str(e)
    return render_template("index.html", weather=weather_info, error=error_msg)

# ----- AI 경로 -----
@app.route("/ai_route", methods=["GET", "POST"])
def ai_route():
    routes, error, raw = None, None, None

    if request.method == "POST":
        start = (request.form.get("start") or "").strip()
        end   = (request.form.get("end") or "").strip()
        try:
            if not (NAVER_MAPS_KEY_ID and NAVER_MAPS_KEY):
                raise RuntimeError("네이버 지도 API 키가 설정되지 않았습니다(.env의 NCLOUD_API_KEY_ID/NCLOUD_API_KEY 확인).")

            sp = resolve_to_coords(start)
            ep = resolve_to_coords(end)
            if not sp:
                raise ValueError(f"주소/장소를 찾지 못했습니다: {start}")
            if not ep:
                raise ValueError(f"주소/장소를 찾지 못했습니다: {end}")

            sx, sy = sp  # (lng, lat)
            ex, ey = ep

            js, logs = call_directions(sx, sy, ex, ey)
            if not js:
                raise RuntimeError(f"Directions 응답이 비었거나 JSON이 아닙니다. logs={logs}")

            raw = js
            routes = []
            route_obj = js.get("route") or {}
            for kind, arr in route_obj.items():
                if not isinstance(arr, list):
                    continue
                for it in arr:
                    sm   = it.get("summary") or {}
                    path = it.get("path") or []  # [[lng, lat], ...]
                    routes.append({
                        "type": kind,
                        "distance_km": round((sm.get("distance", 0) / 1000.0), 1),
                        "duration_min": round((sm.get("duration", 0) / 60000.0), 1),
                        "toll": sm.get("tollFare", 0),
                        "fuel": sm.get("fuelPrice", 0) or 0,
                        "path": path,
                    })

            if not routes:
                raise RuntimeError("경로를 찾지 못했습니다. 입력을 더 구체화하거나 다른 옵션으로 시도해 주세요.")

        except Exception as e:
            error = str(e)
            print("[ai_route][error]", e)

    return render_template("ai_route.html", routes=routes, error=error, raw=raw)


if __name__ == "__main__":
    app.run(debug=True)
