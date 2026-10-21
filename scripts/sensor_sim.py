"""센서 노드 시뮬레이터(테스트 전용). 보드 없이 파이프라인·화면을 검증한다. 화면에는 항상 '시뮬레이터'로 표기.
사용: python -m scripts.sensor_sim --site S1 S2 S3 --hours 72 [--post]  (--post 면 설정된 저장소에 기록, 아니면 CSV 출력)
생성 규칙: 기준 ADC 2600±드리프트, 밤(21~05시)·북동풍 가정 구간에 '사건'(ADC −300~−600, VOC +80~+200) 삽입, 습도에 따른 완만한 변동."""
from __future__ import annotations
import argparse, math, random
import pandas as pd
from core.config import now_kst
from core.sensor_store import open_sensor_store


def simulate(site: str, hours: int, seed: int = 7, end=None):
    rnd = random.Random(f'{site}{seed}')
    end = end or pd.Timestamp(now_kst()).floor('min'); start = end - pd.Timedelta(hours=hours)
    rows, t, heater = [], start, 0
    phase = {'S1': 0, 'S2': 25, 'S3': 0}[site]          # S2 는 S1 보다 25분 늦게 반응
    while t < end:
        h = t.hour + t.minute / 60
        rh = 60 + 20 * math.sin((h - 4) / 24 * 2 * math.pi) + rnd.gauss(0, 2)
        tc = 14 + 6 * math.sin((h - 14) / 24 * 2 * math.pi) + rnd.gauss(0, .5)
        base = 2600 + 40 * math.sin(heater / 86400 * 2 * math.pi) + 3 * (rh - 60)
        ev = 0.0
        day = (t - start).days
        if (day % 2 == 0) and (21 <= h or h < 2):          # 격일 밤 사건
            m = ((h - 21) % 24) * 60 - phase
            if 0 <= m <= 150: ev = math.sin(m / 150 * math.pi)
        if site == 'S3': ev *= 0.4 if rnd.random() < .5 else 0   # 하성은 다른 패턴
        adc = base - 450 * ev + rnd.gauss(0, 8)
        voc = 90 + 140 * ev + 0.3 * (rh - 60) + rnd.gauss(0, 4)
        rows.append(dict(site_id=site, ts=t.isoformat(), adc_mq137=int(adc), voc_index=int(max(0, voc)),
                         humidity_pct=round(rh, 1), temperature_c=round(tc, 1), heater_sec=heater, rssi=-60, fw_version='sim'))
        t += pd.Timedelta(minutes=1); heater += 60
    return rows


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--site', nargs='+', default=['S1', 'S2', 'S3'])
    ap.add_argument('--hours', type=int, default=72); ap.add_argument('--post', action='store_true'); ap.add_argument('--out', default='')
    a = ap.parse_args()
    rows = [r for s in a.site for r in simulate(s, a.hours)]
    if a.post:
        store, label = open_sensor_store(); n = store.insert_readings(rows); print(f'{label}: {n}행 기록 (시뮬레이터)')
    else:
        out = a.out or 'artifacts/sensor_sim.csv'; pd.DataFrame(rows).to_csv(out, index=False); print(out, len(rows))


if __name__ == '__main__':
    main()
