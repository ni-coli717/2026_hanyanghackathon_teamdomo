"""서버 정기 작업: 기상청 예보 → 악취 모델 → 사전 작동 판단 → Supabase device_plan 저장.

실행 위치: GitHub Actions(15분마다) 또는 PC에서 수동.
  python -m scripts.plan_devices                 # 기상청 단기예보 사용
  python -m scripts.plan_devices --demo          # 시연: 지금부터 1~6시간 뒤에 북동풍·습한 밤 날씨가 온다고 가정
  python -m scripts.plan_devices --dry-run       # 저장하지 않고 결과만 출력
설정(환경변수 우선, 없으면 .streamlit/secrets.toml):
  KMA_SERVICE_KEY / [kma] service_key, nx, ny
  SUPABASE_URL / [database] url
  SUPABASE_SECRET_KEY / [database] key   ← service_role(secret) 키. 서버에서만 사용
"""
from __future__ import annotations

import argparse, datetime as dt, json, os, re, sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from odor_model.predict import load_model, predict_rows, fetch_kma_forecast   # noqa: E402
from odor_model.prerun import plan                                            # noqa: E402

KST = ZoneInfo("Asia/Seoul")


def _secrets_section(name: str) -> dict:
    p = ROOT / ".streamlit" / "secrets.toml"
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")
    m = re.search(rf"^\[{name}\][^\n]*\n(.*?)(?=^\[|\Z)", text, flags=re.S | re.M)
    out = {}
    for k, v in re.findall(r'^(\w+)\s*=\s*"?([^"#\n]*)"?', m.group(1) if m else "", flags=re.M):
        out[k] = v.strip()
    return out


def config() -> dict:
    kma, db = _secrets_section("kma"), _secrets_section("database")
    return dict(kma_key=os.getenv("KMA_SERVICE_KEY") or kma.get("service_key", ""),
                nx=int(os.getenv("KMA_NX") or kma.get("nx") or 55), ny=int(os.getenv("KMA_NY") or kma.get("ny") or 129),
                url=(os.getenv("SUPABASE_URL") or db.get("url", "")).rstrip("/"),
                key=os.getenv("SUPABASE_SECRET_KEY") or db.get("key", ""))


class Supa:
    def __init__(self, url, key):
        if not url.startswith("https://") or not key:
            raise SystemExit("Supabase url/secret key 설정이 없습니다.")
        self.base = url + "/rest/v1/"
        self.h = {"apikey": key, "Content-Type": "application/json"}
        if not key.startswith("sb_"):            # 예전 JWT 형식 키면 Authorization 도 필요
            self.h["Authorization"] = f"Bearer {key}"

    def get(self, table, **params):
        r = requests.get(self.base + table, headers=self.h, params=params, timeout=20); r.raise_for_status(); return r.json()

    def upsert(self, table, rows):
        r = requests.post(self.base + table, headers={**self.h, "Prefer": "resolution=merge-duplicates,return=minimal"},
                          data=json.dumps(rows, ensure_ascii=False, default=str), timeout=20); r.raise_for_status()

    def insert(self, table, rows):
        r = requests.post(self.base + table, headers={**self.h, "Prefer": "return=minimal"},
                          data=json.dumps(rows, ensure_ascii=False, default=str), timeout=20); r.raise_for_status()


def demo_weather(now: pd.Timestamp) -> pd.DataFrame:
    """시연용 가상 예보: 지금+1h 부터 3시간 북북동풍(강 건너 방향)·습한 날씨, 앞뒤는 남서풍·건조. 실측 아님.
    값은 현재 번들 모델이 '높음'을 내는 조건(북풍 계열·습도 높음, 실제 제보 분석 결과와 같은 방향)으로 골랐다."""
    t0 = now.floor("h")
    rows = []
    for k in range(0, 8):
        hot = 1 <= k <= 3
        rows.append(dict(window_start=t0 + pd.Timedelta(hours=k), wind_from_deg=20.0 if hot else 225.0,
                         wind_speed=2.5 if hot else 3.0, humidity_pct=95.0 if hot else 55.0,
                         temperature_c=15.0, rain_1h_mm=0.0, basis="demo", source="시연 가상 예보"))
    return pd.DataFrame(rows)


def ts(v):
    return None if v is None else pd.Timestamp(v).tz_localize(KST).isoformat()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", default="", help="판단 기준 시각(KST, 테스트용)")
    a = ap.parse_args()
    cfg = config()
    now = pd.Timestamp(a.now) if a.now else pd.Timestamp(dt.datetime.now(KST).replace(tzinfo=None))

    demo_csv = ROOT / "data" / "private" / "demo_forecast.csv"
    if a.demo:
        weather, basis, issued = demo_weather(now), "demo", "시연 가상 예보"
        # 앱 지도도 같은 가상 예보를 보도록 남긴다(core/analysis_service.demo_forecast, 6시간 유효, 저장소에 안 올라감)
        demo_csv.parent.mkdir(parents=True, exist_ok=True)
        weather.to_csv(demo_csv, index=False, encoding="utf-8")
    else:
        if demo_csv.exists():
            demo_csv.unlink()   # 실제 예보로 돌아오면 지도도 실제 예보로
        if not cfg["kma_key"]:
            raise SystemExit("기상청 서비스키가 없습니다(KMA_SERVICE_KEY).")
        try:
            weather = fetch_kma_forecast(cfg["kma_key"], cfg["nx"], cfg["ny"])
        except Exception as e:  # noqa: BLE001
            # 예보를 못 받으면 옛 일정(ON 등)을 그대로 두지 않고 '판단 보류'로 바꿔 둔다. 기기는 직전 상태를 유지한다.
            print(f"예보 조회 실패 · {e}")
            if not a.dry_run:
                db = Supa(cfg["url"], cfg["key"])
                for d in db.get("devices", select="device_id"):
                    db.upsert("device_plan", [dict(device_id=d["device_id"], computed_at=dt.datetime.now(KST).isoformat(), basis="kma",
                                                   issued="", action="HOLD", state="hold", reason=f"예보 조회 실패 · {str(e)[:80]}",
                                                   next_on_at=None, next_odor_at=None, next_off_at=None, episodes=[])])
                    db.insert("device_log", [dict(device_id=d["device_id"], kind="plan", detail=f"예보 조회 실패 · HOLD · {str(e)[:120]}")])
            raise SystemExit(1)
        basis, issued = "kma", str(weather["source"].iloc[0]) if len(weather) else ""
    m = load_model()
    preds = predict_rows(weather, m)
    print(f"[{now:%Y-%m-%d %H:%M}] {basis} {issued} · 예보 {weather.window_start.min():%m-%d %H}~{weather.window_start.max():%m-%d %H}시")
    print(preds.pivot_table(index="window_start", columns="zone_id", values="level", aggfunc="first").head(10).to_string())

    devices = [dict(device_id="DRY", zone_id="U01", lead_min=40, tail_min=30, trigger_level="높음")] if a.dry_run else None
    db = None if a.dry_run else Supa(cfg["url"], cfg["key"])
    if db:
        devices = db.get("devices", select="device_id,zone_id,lead_min,tail_min,trigger_level")
        old = {r["device_id"]: r for r in db.get("device_plan", select="device_id,action,next_on_at")}
    for d in devices:
        r = plan(preds, d["zone_id"], now, lead_min=d["lead_min"], tail_min=d["tail_min"], trigger=d["trigger_level"])
        nxt = r["next"] or {}
        row = dict(device_id=d["device_id"], computed_at=dt.datetime.now(KST).isoformat(), basis=basis, issued=issued,
                   action=r["action"], state=r["state"], reason=r["reason"],
                   next_on_at=ts(nxt.get("on_at")), next_odor_at=ts(nxt.get("odor_start")), next_off_at=ts(nxt.get("off_at")),
                   episodes=[{k: (ts(v) if k in ("odor_start", "odor_end", "on_at", "off_at") else v) for k, v in e.items()}
                             for e in r["episodes"]])
        print(f"  {d['device_id']} ({d['zone_id']}, {d['lead_min']}분 전): {r['action']} · {r['reason']}")
        if db:
            db.upsert("device_plan", [row])
            prev = old.get(d["device_id"], {})
            if prev.get("action") != row["action"] or (prev.get("next_on_at") or "")[:16] != (row["next_on_at"] or "")[:16]:
                db.insert("device_log", [dict(device_id=d["device_id"], kind="plan", detail=f"{basis} · {r['action']} · {r['reason']}")])


if __name__ == "__main__":
    main()
