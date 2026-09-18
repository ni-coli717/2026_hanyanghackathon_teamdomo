from __future__ import annotations

from datetime import datetime, timedelta
import os
from zoneinfo import ZoneInfo

import streamlit as st


KST = ZoneInfo("Asia/Seoul")
SCHEDULED_TIMES = ["07:30", "12:30", "18:30", "22:00"]
SCHEDULE_TOLERANCE_MINUTES = 15
ZONE_PUBLIC_NAMES = {
    "Z1": "한강변·라베니체 인근",
    "Z2": "운양역 인근",
    "Z3": "모담산·학교 인근",
}


def now_kst() -> datetime:
    return datetime.now(KST)


def classify_collection_mode(moment: datetime | None = None) -> tuple[str, str]:
    moment = moment or now_kst()
    moment = moment.replace(tzinfo=KST) if moment.tzinfo is None else moment.astimezone(KST)
    for value in SCHEDULED_TIMES:
        hour, minute = map(int, value.split(":"))
        target = moment.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if abs((moment - target).total_seconds()) <= SCHEDULE_TOLERANCE_MINUTES * 60:
            return "scheduled", "현재 정기 관측 시간입니다."
    return "spontaneous", "추가 제보로 기록됩니다."


def observation_window(moment):
    moment = moment.replace(tzinfo=KST) if moment.tzinfo is None else moment.astimezone(KST)
    candidates=[]
    for value in SCHEDULED_TIMES:
        hour,minute=map(int,value.split(':'))
        candidates.append(moment.replace(hour=hour,minute=minute,second=0,microsecond=0))
    nearest=min(candidates,key=lambda x:abs((moment-x).total_seconds()))
    return nearest if abs((moment-nearest).total_seconds())<=SCHEDULE_TOLERANCE_MINUTES*60 else moment.replace(minute=(moment.minute//30)*30,second=0,microsecond=0)


def setting(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)
    except Exception:
        value = default
    return str(os.getenv(name, value or default))


def measurement_url() -> str:
    return setting("MEASUREMENT_APP_URL", "")


def data_mode() -> str:
    return setting("DATA_MODE", "demo").lower()


def nested_setting(section: str, key: str, default: str = "") -> str:
    try:
        value = st.secrets.get(section, {}).get(key, default)
    except Exception:
        value = default
    return os.getenv(f"{section}_{key}".upper(), str(value))
