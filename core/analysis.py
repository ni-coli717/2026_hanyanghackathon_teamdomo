from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency


SECTORS = ["북", "북동", "동", "남동", "남", "남서", "서", "북서"]


def add_sector(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["sector"] = pd.Categorical(
        out.wd.map(lambda x: SECTORS[int((x + 22.5) // 45) % 8] if pd.notna(x) else np.nan),
        categories=SECTORS, ordered=True,
    )
    return out


def sector_rates(windows: pd.DataFrame) -> pd.DataFrame:
    valid = add_sector(windows.dropna(subset=["label", "wd"]))
    if valid.empty:
        return pd.DataFrame(columns=["sector", "감지율", "표본"])
    return valid.groupby("sector", observed=False).agg(감지율=("label", "mean"), 표본=("label", "size")).reset_index()


def chi_square(windows: pd.DataFrame) -> float | None:
    valid = add_sector(windows.dropna(subset=["label", "wd"]))
    table = pd.crosstab(valid.sector, valid.label)
    if table.shape[0] < 2 or table.shape[1] < 2:
        return None
    return float(chi2_contingency(table)[1])


def alignment_summary(windows: pd.DataFrame, source_ids: list[str]) -> pd.DataFrame:
    rows = []
    valid = windows.dropna(subset=["label"])
    for sid in source_ids:
        col = f"align_{sid}"
        if col not in valid:
            continue
        aligned = valid[valid[col] > 0.7]
        rest = valid[valid[col] <= 0.7]
        a_rate = aligned.label.mean() if len(aligned) else np.nan
        r_rate = rest.label.mean() if len(rest) else np.nan
        ratio = a_rate / r_rate if pd.notna(r_rate) and r_rate > 0 else np.nan
        rows.append({"후보": sid, "정렬 시 감지율": a_rate, "기타 감지율": r_rate, "감지율 배수": ratio, "정렬 표본": len(aligned)})
    return pd.DataFrame(rows)

