from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import math

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


NUMERIC_FEATURES = ["wd_sin", "wd_cos", "ws", "temp", "humidity", "rain", "hour_sin", "hour_cos", "is_night", "pressure", "dp_3h", "align_D1", "align_D2", "align_D3"]
CATEGORICAL_FEATURES = ["zone_id"]


@dataclass
class ModelBundle:
    models: dict
    metrics: pd.DataFrame
    confusion: dict
    feature_importance: pd.DataFrame
    trained_at: str
    n_train: int
    n_test: int
    n_pos: int


def training_status(windows: pd.DataFrame) -> tuple[bool, str]:
    valid = windows.dropna(subset=["label"]) if not windows.empty else pd.DataFrame()
    positives = int(valid.label.sum()) if not valid.empty else 0
    if positives < 10:
        return False, f"양성 관측창 {positives}개 — 학습에는 10개 이상이 필요합니다."
    if valid.label.nunique() < 2:
        return False, "한 종류의 결과만 있어 모델을 비교할 수 없습니다."
    if valid.window_at.dt.normalize().nunique() < 2:
        return False, "시간 기준 평가를 위한 날짜가 부족합니다."
    return True, "학습 조건 충족"


def _scores(name: str, y_true, y_pred, n_train: int, n_test: int, n_pos: int) -> dict:
    p, r, f, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
    return {"모델": name, "정확도": accuracy_score(y_true, y_pred), "정밀도": p, "재현율": r, "F1": f, "학습 창": n_train, "평가 창": n_test, "평가 양성": n_pos}


def train_models(windows: pd.DataFrame) -> ModelBundle:
    valid = windows.dropna(subset=["label"]).copy().sort_values("window_at")
    ok, message = training_status(valid)
    if not ok:
        raise ValueError(message)
    test_day = valid.window_at.dt.normalize().max()
    train = valid[valid.window_at.dt.normalize() < test_day]
    test = valid[valid.window_at.dt.normalize() == test_day]
    if train.label.nunique() < 2 or test.empty:
        raise ValueError("마지막 날짜 분할 후 학습/평가 클래스가 부족합니다.")
    numeric = [c for c in NUMERIC_FEATURES if c in valid.columns]
    features = numeric + CATEGORICAL_FEATURES
    pre = ColumnTransformer([
        ("num", Pipeline([("imputer", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), numeric),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
    ])
    estimators = {
        "로지스틱 회귀": LogisticRegression(C=1.0, class_weight="balanced", max_iter=1000, random_state=20212),
        "랜덤포레스트": RandomForestClassifier(n_estimators=200, max_depth=4, class_weight="balanced", random_state=20212),
    }
    y_train = train.label.astype(int)
    y_test = test.label.astype(int)
    metrics = []
    confusions = {}
    majority = int(y_train.mean() >= 0.5)
    pred = np.full(len(test), majority)
    metrics.append(_scores("기준선 1 · 다수 클래스", y_test, pred, len(train), len(test), int(y_test.sum())))
    confusions["기준선 1 · 다수 클래스"] = confusion_matrix(y_test, pred, labels=[0, 1])
    rule = ((test.align_D1 > 0.7) & (test.ws < 3)).astype(int)
    metrics.append(_scores("기준선 2 · 방향 규칙", y_test, rule, len(train), len(test), int(y_test.sum())))
    confusions["기준선 2 · 방향 규칙"] = confusion_matrix(y_test, rule, labels=[0, 1])
    models = {}
    importance_rows = []
    for name, estimator in estimators.items():
        pipe = Pipeline([("pre", pre), ("model", estimator)])
        pipe.fit(train[features], y_train)
        pred = pipe.predict(test[features])
        metrics.append(_scores(name, y_test, pred, len(train), len(test), int(y_test.sum())))
        confusions[name] = confusion_matrix(y_test, pred, labels=[0, 1])
        models[name] = pipe
        feature_names = pipe.named_steps["pre"].get_feature_names_out()
        values = pipe.named_steps["model"].coef_[0] if name == "로지스틱 회귀" else pipe.named_steps["model"].feature_importances_
        for feature, value in zip(feature_names, values):
            importance_rows.append({"모델": name, "변수": feature.replace("num__", "").replace("cat__", ""), "영향도": float(value), "절대 영향도": abs(float(value))})
    return ModelBundle(models, pd.DataFrame(metrics), confusions, pd.DataFrame(importance_rows), datetime.now().isoformat(timespec="seconds"), len(train), len(test), int(y_test.sum()))


def save_bundle(bundle: ModelBundle, path: str | Path = "data/models/latest.joblib") -> str:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, destination)
    return str(destination)


def load_bundle(path: str | Path = "data/models/latest.joblib") -> ModelBundle | None:
    target = Path(path)
    try:
        return joblib.load(target) if target.exists() else None
    except Exception:
        return None

