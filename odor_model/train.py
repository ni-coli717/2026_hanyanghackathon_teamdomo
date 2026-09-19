"""운양동 악취 예측 모델 학습·평가.

사용:  python train.py --data 운양동_악취관측_20260618_20260916.xlsx --out artifacts/

산출:
  artifacts/odor_model.joblib      감지 분류기(로지스틱 회귀) + 유형 분류기 + 전처리 + 메타
  artifacts/evaluation.md          시간순 분할 평가표(기준선 비교, 혼동행렬)
  artifacts/zone_windows.csv       구역×시간창 학습표
  artifacts/candidates.csv         구역→후보 방위·거리표
"""
from __future__ import annotations
import argparse, json, os, warnings
import numpy as np, pandas as pd, joblib
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import (precision_score, recall_score, f1_score, roc_auc_score, brier_score_loss,
                             confusion_matrix, accuracy_score)
try:
    from .features import (build_zone_windows, add_lag_features, make_features, candidate_table, load_geo,
                           type_target, TYPE_CLASSES)
except ImportError:  # python train.py 직접 실행
    from features import (build_zone_windows, add_lag_features, make_features, candidate_table, load_geo,
                          type_target, TYPE_CLASSES)

warnings.filterwarnings("ignore")

SPLITS = {  # 사전 고정 시간순 분할
    "train": ("2026-06-18", "2026-08-25"),
    "valid": ("2026-08-26", "2026-09-08"),
    "test":  ("2026-09-09", "2026-09-16"),   # 실제 공개 기상값 구간
}
THRESH_FIXED = 0.5


def metrics(y, p, thr):
    yhat = (p >= thr).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, yhat, labels=[0, 1]).ravel()
    def safe(f):
        try: return f()
        except Exception: return float("nan")
    return dict(n=len(y), pos=int(y.sum()), thr=thr, acc=accuracy_score(y, yhat),
                precision=precision_score(y, yhat, zero_division=np.nan), recall=recall_score(y, yhat, zero_division=np.nan),
                f1=f1_score(y, yhat, zero_division=np.nan),
                auc=safe(lambda: roc_auc_score(y, p)) if len(set(y)) > 1 else float("nan"),
                brier=brier_score_loss(y, p), tp=tp, fp=fp, fn=fn, tn=tn)


def fmt(m):
    def f(v): return "계산 불가" if (isinstance(v, float) and np.isnan(v)) else (f"{v:.3f}" if isinstance(v, float) else str(v))
    return f"| {f(m['acc'])} | {f(m['precision'])} | {f(m['recall'])} | {f(m['f1'])} | {f(m['auc'])} | {f(m['brier'])} | TP {m['tp']} / FP {m['fp']} / FN {m['fn']} / TN {m['tn']} |"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True); ap.add_argument("--out", default="artifacts")
    ap.add_argument("--geo", default=None)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    geo = load_geo(a.geo)

    obs = pd.read_excel(a.data, sheet_name="관측데이터")
    zw = add_lag_features(build_zone_windows(obs))
    zw.to_csv(os.path.join(a.out, "zone_windows.csv"), index=False, encoding="utf-8-sig")
    candidate_table(geo).to_csv(os.path.join(a.out, "candidates.csv"), index=False, encoding="utf-8-sig")

    lab = zw[zw.label.notna()].copy(); lab["label"] = lab.label.astype(int)
    d = lab.window_start.dt.date.astype(str)
    part = {k: lab[(d >= s) & (d <= e)] for k, (s, e) in SPLITS.items()}

    X = {k: make_features(v, geo) for k, v in part.items()}
    y = {k: v.label.values for k, v in part.items()}
    Xl = {k: make_features(v, geo, use_lag=True) for k, v in part.items()}

    # ---- 주 모델: 규제 로지스틱 회귀 (기상만)
    lr = Pipeline([("sc", StandardScaler()), ("lr", LogisticRegression(C=0.5, class_weight="balanced", max_iter=2000))])
    lr.fit(X["train"], y["train"])
    # ---- 확장 비교: 랜덤 포레스트
    rf = RandomForestClassifier(n_estimators=400, min_samples_leaf=5, class_weight="balanced_subsample", random_state=7)
    rf.fit(X["train"], y["train"])
    # ---- 선택: 직전 창 감지율 포함(nowcast 전용)
    lr_lag = Pipeline([("sc", StandardScaler()), ("lr", LogisticRegression(C=0.5, class_weight="balanced", max_iter=2000))])
    lr_lag.fit(Xl["train"], y["train"])

    # 검증 자료로 임계값 1개 선택(평가 자료는 보지 않음)
    pv = lr.predict_proba(X["valid"])[:, 1]
    cands = np.arange(0.2, 0.81, 0.05)
    f1s = [f1_score(y["valid"], (pv >= t).astype(int), zero_division=0) for t in cands]
    thr_valid = float(cands[int(np.argmax(f1s))])

    # ---- 평가표
    lines = ["# 운양동 악취 감지 예측 모델 — 평가 (예비 실험·미보정)", "",
             f"- 학습표: 구역×시간창 {len(lab)}건 (양성 {int(lab.label.sum())}, {lab.label.mean():.1%})",
             "- 정답: 유효 응답 3명 이상 구역·시간창에서 감지 비율 50% 이상 = 1",
             "- 입력: 풍향 sin/cos·이동 벡터·풍속·무풍·습도·기온·강수·시간대·계절·구역·후보 정렬도 (같은 창의 관측값은 입력에서 제외)",
             "- 분할(사전 고정): " + ", ".join(f"{k} {s}~{e} ({len(part[k])}건, 양성 {int(part[k].label.sum())})" for k, (s, e) in SPLITS.items()),
             f"- 임계값: 사전 고정 {THRESH_FIXED} / 검증 자료에서 F1 최대 임계값 {thr_valid:.2f} (평가 자료 미사용)",
             "- 6/18~9/8 구간의 기상과 주민 기록은 생성 자료이며, 9/9~9/16 기상은 공개 관측값·주민 기록은 시뮬레이션이다. 아래 수치는 실제 성능이 아니라 파이프라인 검증 결과로 읽는다.", "",
             "## 평가 자료(9/9~9/16, 마지막 구간) 성능", "",
             "| 모델 | 임계값 | 정확도 | 정밀도 | 재현율 | F1 | AUC | Brier | 혼동행렬 |", "|---|---|---|---|---|---|---|---|---|"]
    yt = y["test"]
    def row(name, p, thr):
        m = metrics(yt, np.asarray(p, float), thr); return f"| {name} | {thr:.2f} " + fmt(m)
    maj = np.zeros(len(yt)); always = np.ones(len(yt))
    persist = part["test"].prev_label.fillna(0).astype(int).values
    lines += [row("기준선: 다수 클래스(항상 0)", maj, 0.5), row("기준선: 항상 감지(항상 1)", always, 0.5),
              row("기준선: 지속성(직전 창 상태)", persist, 0.5),
              row("로지스틱 회귀(기상)", lr.predict_proba(X["test"])[:, 1], THRESH_FIXED),
              row("로지스틱 회귀(기상)", lr.predict_proba(X["test"])[:, 1], thr_valid),
              row("랜덤 포레스트(기상)", rf.predict_proba(X["test"])[:, 1], THRESH_FIXED),
              row("로지스틱 회귀(기상+직전 창)", lr_lag.predict_proba(Xl["test"])[:, 1], THRESH_FIXED)]
    lines += ["", "## 검증 자료(8/26~9/8) 성능", "", "| 모델 | 임계값 | 정확도 | 정밀도 | 재현율 | F1 | AUC | Brier | 혼동행렬 |", "|---|---|---|---|---|---|---|---|---|"]
    yv = y["valid"]
    def rowv(name, p, thr):
        m = metrics(yv, np.asarray(p, float), thr); return f"| {name} | {thr:.2f} " + fmt(m)
    lines += [rowv("기준선: 지속성", part["valid"].prev_label.fillna(0).astype(int).values, 0.5),
              rowv("로지스틱 회귀(기상)", pv, THRESH_FIXED), rowv("로지스틱 회귀(기상)", pv, thr_valid),
              rowv("랜덤 포레스트(기상)", rf.predict_proba(X["valid"])[:, 1], THRESH_FIXED)]

    # 계수
    coef = pd.Series(lr.named_steps["lr"].coef_[0], index=X["train"].columns).sort_values(key=abs, ascending=False)
    lines += ["", "## 로지스틱 회귀 표준화 계수 (크기순, 상위 12)", "", "| 특징 | 계수 |", "|---|---|"]
    lines += [f"| {k} | {v:+.3f} |" for k, v in coef.head(12).items()]
    lines += ["", "정렬도(align_*) 계수는 풍향에서 파생된 값이며 발생원의 독립적 증거로 해석하지 않는다."]

    # ---- 유형 분류기: 감지된 개인 기록에서 축산계/하수계/기타 (풍향·시간 기반)
    det = obs[(obs.collection_mode == "scheduled") & (obs.odor_detected.astype(str).str.lower() == "true")].copy()
    det["window_start"] = pd.to_datetime(det.window_id.str[2:15], format="%Y%m%d-%H%M")
    det = det.rename(columns={"wind_speed_10min_ms": "wind_speed", "wind_from_sector_center_deg": "wind_from_deg", "rain_rolling_1h_mm": "rain_1h_mm"})
    det["y"] = det.odor_type.map(type_target)
    dd = det.window_start.dt.date.astype(str)
    tr = det[dd <= SPLITS["train"][1]]; te = det[dd >= SPLITS["test"][0]]
    tclf = Pipeline([("sc", StandardScaler()), ("lr", LogisticRegression(C=0.5, max_iter=2000))])
    tclf.fit(make_features(tr, geo), tr.y)
    acc_t = accuracy_score(te.y, tclf.predict(make_features(te, geo))) if len(te) else float("nan")
    maj_t = te.y.value_counts(normalize=True).max() if len(te) else float("nan")
    lines += ["", "## 냄새 유형 추정기 (감지 기록 대상, 3분류)", "",
              f"- 학습 {len(tr)}건 / 평가 {len(te)}건, 평가 정확도 {acc_t:.3f} (다수 클래스 기준 {maj_t:.3f})",
              "- 주민의 주관 분류를 풍향·시간대로 재현하는 보조 모델이다. '축산계 추정'은 냄새 느낌의 분류이지 특정 시설 판정이 아니다."]

    with open(os.path.join(a.out, "evaluation.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    joblib.dump(dict(detect_model=lr, detect_model_rf=rf, detect_model_lag=lr_lag, type_model=tclf, type_classes=list(tclf.classes_),
                     feature_columns=list(X["train"].columns), geo=geo, thr_fixed=THRESH_FIXED, thr_valid=thr_valid,
                     splits=SPLITS, trained_on=os.path.basename(a.data), status="예비 실험·미보정",
                     train_positive_rate=float(lab.label.mean())),
                os.path.join(a.out, "odor_model.joblib"))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
