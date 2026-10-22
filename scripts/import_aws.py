"""기상자료개방포털 AWS 시간자료 CSV(EUC-KR) → 표준 기상 표.
사용: python -m scripts.import_aws data/external/aws/OBS_AWS_TIM_427_441_20260401_20260930.csv [--station 427] [--out data/external/aws/weather_427.csv]
출력 열: window_start(KST, tz-naive), station_id, wind_from_deg, wind_speed, humidity_pct, temperature_c, rain_1h_mm, pressure_hpa, weather_basis
 - 풍향 결측·무풍: wind_from_deg 는 그대로 NaN/값 유지, 풍속 <0.5 는 calm 으로 분석 단계에서 처리
 - 441 현지기압 500 은 결측으로 바꿈
"""
from __future__ import annotations
import argparse
import pandas as pd

RENAME = {'지점': 'station_id', '일시': 'window_start', '기온(°C)': 'temperature_c', '풍향(deg)': 'wind_from_deg',
          '풍속(m/s)': 'wind_speed', '강수량(mm)': 'rain_1h_mm', '현지기압(hPa)': 'pressure_hpa', '습도(%)': 'humidity_pct'}


def load_aws(path: str) -> pd.DataFrame:
    for enc in ('euc-kr', 'cp949', 'utf-8-sig'):
        try:
            df = pd.read_csv(path, encoding=enc); break
        except UnicodeDecodeError:
            continue
    df = df.rename(columns=RENAME)
    df['window_start'] = pd.to_datetime(df['window_start'])
    df['station_id'] = df['station_id'].astype(str)
    for c in ('temperature_c', 'wind_from_deg', 'wind_speed', 'rain_1h_mm', 'pressure_hpa', 'humidity_pct'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df.loc[df['pressure_hpa'] <= 600, 'pressure_hpa'] = pd.NA
    df['rain_1h_mm'] = df['rain_1h_mm'].fillna(0.0)
    df['weather_basis'] = 'observed_public_reference'
    cols = ['window_start', 'station_id', 'wind_from_deg', 'wind_speed', 'humidity_pct', 'temperature_c', 'rain_1h_mm', 'pressure_hpa', 'weather_basis']
    return df[cols].sort_values(['station_id', 'window_start']).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('path'); ap.add_argument('--station', default='427'); ap.add_argument('--out', default='')
    a = ap.parse_args()
    df = load_aws(a.path)
    one = df[df.station_id == a.station]
    out = a.out or f'data/external/aws/weather_{a.station}.csv'
    one.to_csv(out, index=False, encoding='utf-8-sig')
    full = pd.date_range(one.window_start.min(), one.window_start.max(), freq='h')
    print(f'{a.station}: {len(one)}행 {one.window_start.min()} ~ {one.window_start.max()}  누락 시각 {len(full) - len(one)}  풍향 결측 {one.wind_from_deg.isna().sum()}  → {out}')


if __name__ == '__main__':
    main()
