# weather_core.py
import os
import re
from datetime import datetime, timedelta

import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # 서버에서 파일 저장 전용
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams
from dotenv import load_dotenv

# ---- 한글 폰트(윈도우: 맑은 고딕) ----
rcParams["axes.unicode_minus"] = False
for f in font_manager.findSystemFonts(fontext="ttf"):
    if "Malgun" in f or "malgun" in f:
        rcParams["font.family"] = "Malgun Gothic"
        break

load_dotenv()
API_KEY = os.getenv("OPENWEATHER_API_KEY", "7e77589d4905c6f37edf42ecbabc3c4a").strip()  # 하드코딩 제거!

GEO_URL = "https://api.openweathermap.org/geo/1.0/direct"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
CURRENT_URL  = "https://api.openweathermap.org/data/2.5/weather"
AIR_POLLUTION_URL = "https://api.openweathermap.org/data/2.5/air_pollution"

def _safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s.strip())

def get_coordinates(city_name: str):
    if not API_KEY:
        raise RuntimeError("OPENWEATHER_API_KEY가 비어 있습니다(.env 설정 확인).")
    params = {"q": city_name.strip(), "limit": 1, "appid": API_KEY}
    r = requests.get(GEO_URL, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError(f"'{city_name}'에 해당하는 도시를 찾을 수 없습니다.")
    return data[0]["lat"], data[0]["lon"], data[0]["country"]

def get_current_weather(lat: float, lon: float):
    params = {"lat": lat, "lon": lon, "appid": API_KEY, "units": "metric", "lang": "kr"}
    r = requests.get(CURRENT_URL, params=params, timeout=10)
    r.raise_for_status()
    js = r.json()
    try:
        return {
            "desc": js["weather"][0]["description"],
            "temp": js["main"]["temp"],
            "icon": js["weather"][0]["icon"],
        }
    except (KeyError, IndexError):
        raise ValueError("날씨 데이터 형식이 예상과 다릅니다(API 키/쿼리 확인).")

def get_forecast(lat: float, lon: float):
    params = {"lat": lat, "lon": lon, "appid": API_KEY, "units": "metric", "lang": "kr"}
    r = requests.get(FORECAST_URL, params=params, timeout=10)
    r.raise_for_status()
    js = r.json()
    return js.get("list", [])

def get_air_pollution(lat: float, lon: float):
    """대기질: aqi(1~5), components(pm2_5 등) 반환"""
    params = {"lat": lat, "lon": lon, "appid": API_KEY}
    r = requests.get(AIR_POLLUTION_URL, params=params, timeout=10)
    r.raise_for_status()
    js = r.json()
    try:
        return js["list"][0]
    except (KeyError, IndexError):
        # 대기질 정보가 없을 수도 있음
        return None

def process_forecast_data(forecast_list):
    df = pd.DataFrame([{
        "datetime": item["dt_txt"],
        "temp": item["main"]["temp"]
    } for item in forecast_list if "dt_txt" in item and "main" in item])
    df["date"] = pd.to_datetime(df["datetime"]).dt.date
    daily = df.groupby("date")["temp"].agg(["mean", "max", "min"]).reset_index()
    return daily

def plot_forecast(daily_df, city_name, country_code):
    plt.figure()
    plt.plot(daily_df["date"], daily_df["mean"], marker="o", label="평균")
    plt.plot(daily_df["date"], daily_df["max"], marker="o", label="최고")
    plt.plot(daily_df["date"], daily_df["min"], marker="o", label="최저")
    plt.title(f"{city_name} ({country_code}) 5일 기온")
    plt.xlabel("날짜"); plt.ylabel("°C"); plt.grid(True); plt.legend(); plt.tight_layout()
    os.makedirs("static", exist_ok=True)
    fname = f"forecast_{_safe_name(city_name)}_{_safe_name(country_code)}.png"
    abs_path = os.path.join(os.path.abspath("static"), fname)
    plt.savefig(abs_path); plt.close()
    print("[forecast] saved:", abs_path)
    return fname  # 파일명만 반환

# --------- AI 세차/주차 지수(점수 기반) ---------
def analyze_convenience(forecast_list, current_weather=None, air_pollution_data=None):
    """
    반환:
    {
      "carwash": {"score": int, "reasons": [..]},
      "parking": {"tip": "실내 권장|야외 가능", "reasons": [..]}
    }
    """
    now = datetime.utcnow()
    until = now + timedelta(hours=24)

    def parse_dt(s): return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    next24 = [x for x in forecast_list if "dt_txt" in x and parse_dt(x["dt_txt"]) <= until]

    will_rain = any(
        (it.get("weather", [{}])[0].get("main") in ("Rain", "Drizzle", "Thunderstorm", "Snow"))
        for it in next24
    )
    strong_wind = any(
        (it.get("wind", {}).get("speed", 0) >= 10) or (it.get("wind", {}).get("gust", 0) >= 14)
        for it in next24
    )
    if current_weather:
        desc = str(current_weather.get("desc", ""))
        if ("비" in desc) or ("눈" in desc) or ("rain" in desc.lower()) or ("snow" in desc.lower()):
            will_rain = True

    # --- 세차 점수 ---
    carwash_score = 100
    carwash_reasons = []

    if will_rain:
        carwash_score -= 50
        carwash_reasons.append("🚫 24시간 내 비/눈 예보")

    if air_pollution_data:
        try:
            aqi = air_pollution_data["main"]["aqi"]      # 1~5
            pm2_5 = air_pollution_data["components"]["pm2_5"]
            if aqi >= 4:
                carwash_score -= 30
                carwash_reasons.append(f"😷 미세먼지 나쁨 (PM2.5 {pm2_5}µg/m³)")
            elif aqi == 3:
                carwash_score -= 15
                carwash_reasons.append(f"😐 미세먼지 약간 나쁨 (PM2.5 {pm2_5}µg/m³)")
        except KeyError:
            pass  # 일부 지역은 구성 값이 없을 수 있음

    if strong_wind:
        carwash_score -= 10
        carwash_reasons.append("💨 강풍으로 흙먼지 가능")

    if not carwash_reasons:
        carwash_reasons.append("✅ 세차하기 좋은 날씨!")
    carwash_score = max(0, int(round(carwash_score)))

    # --- 주차 팁 ---
    reasons_park = []
    if will_rain:
        reasons_park.append("강수/적설 가능")
    if strong_wind:
        reasons_park.append("강풍 가능")
    parking_tip = "실내 권장" if reasons_park else "야외 가능"

    return {
        "carwash": {"score": carwash_score, "reasons": carwash_reasons},
        "parking": {"tip": parking_tip, "reasons": reasons_park or ["특이사항 없음"]},
    }
