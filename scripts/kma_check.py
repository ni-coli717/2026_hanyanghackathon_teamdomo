"""기상청 단기예보 API 실호출 점검.
사용: python -m scripts.kma_check   (저장소 루트에서, .streamlit/secrets.toml 의 [kma] 사용)
세 엔드포인트(초단기실황·초단기예보·단기예보)를 호출해 상태와 앞 몇 행을 출력합니다. 키는 출력하지 않습니다.
"""
from __future__ import annotations
import datetime as dt, re, sys
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0"
KST = ZoneInfo("Asia/Seoul")


def load_kma():
    txt = (ROOT / ".streamlit" / "secrets.toml").read_text(encoding="utf-8")
    sec = txt.split("[kma]", 1)[1]
    key = re.search(r'service_key\s*=\s*"([^"]+)"', sec).group(1)
    nx = int(re.search(r"nx\s*=\s*(\d+)", sec).group(1))
    ny = int(re.search(r"ny\s*=\s*(\d+)", sec).group(1))
    return key, nx, ny


def call(path, key, **params):
    try:
        r = requests.get(f"{BASE}/{path}", params=dict(serviceKey=key, pageNo=1, numOfRows=1000, dataType="JSON", **params), timeout=20)
    except requests.RequestException as e:
        print(f"  !! {path}: 접속 실패 / {type(e).__name__}: {str(e).replace(key, '<KEY>')[:300]}")
        return None, []
    body = r.text.replace(key, "<KEY>")
    try:
        js = r.json()
        hdr = js["response"]["header"]
        items = js["response"]["body"]["items"]["item"]
        return hdr, items
    except Exception:
        print(f"  !! {path}: HTTP {r.status_code} / {body[:300]}")
        return None, []


def main():
    key, nx, ny = load_kma()
    now = dt.datetime.now(KST)
    print(f"KST now {now:%Y-%m-%d %H:%M}  grid nx={nx} ny={ny}  key length {len(key)}")

    bt = (now - dt.timedelta(minutes=45)).replace(minute=0)
    hdr, items = call("getUltraSrtNcst", key, base_date=bt.strftime("%Y%m%d"), base_time=bt.strftime("%H00"), nx=nx, ny=ny)
    print("초단기실황", hdr, {i["category"]: i["obsrValue"] for i in items})

    bt = (now - dt.timedelta(minutes=50)).replace(minute=30)
    hdr, items = call("getUltraSrtFcst", key, base_date=bt.strftime("%Y%m%d"), base_time=bt.strftime("%H30"), nx=nx, ny=ny)
    print("초단기예보", hdr, f"{len(items)}건", [(i["fcstTime"], i["category"], i["fcstValue"]) for i in items if i["category"] in ("VEC", "WSD")][:6])

    sys.path.insert(0, str(ROOT))
    from odor_model.predict import fetch_kma_forecast
    try:
        df = fetch_kma_forecast(key, nx, ny)
    except Exception as e:  # noqa: BLE001
        print(f"  !! getVilageFcst: {type(e).__name__}: {str(e).replace(key, '<KEY>')[:300]}")
        return
    print("단기예보", len(df), "행 /", df["source"].iloc[0] if len(df) else "-")
    print(df.head(6).to_string(index=False))


if __name__ == "__main__":
    main()
