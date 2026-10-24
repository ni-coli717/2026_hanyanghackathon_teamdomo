"""case-crossover 모델 객체(pickle 가능하도록 별도 모듈). 학습은 odor_model.case_crossover."""
from __future__ import annotations
import numpy as np
from scipy.special import expit


class CCModel:
    """조건부 로지스틱 계수를 가진 sklearn 풍 객체. predict_proba 는 sigmoid(점수) — 순위용 점수이지 확률이 아니다."""
    def __init__(self, columns, coef, mean, scale):
        self.columns, self.coef_, self.mean_, self.scale_ = list(columns), np.asarray(coef, float), np.asarray(mean, float), np.asarray(scale, float)

    def decision_function(self, X):
        Z = (np.asarray(X[self.columns], float) - self.mean_) / self.scale_
        return Z @ self.coef_

    def predict_proba(self, X):
        p = expit(self.decision_function(X)); return np.c_[1 - p, p]


class UniformType:
    """냄새 종류는 더 이상 묻지 않는다. predict_rows 호환용."""
    def __init__(self, classes): self.classes_ = list(classes)
    def predict_proba(self, X): return np.full((len(X), len(self.classes_)), 1.0 / len(self.classes_))


