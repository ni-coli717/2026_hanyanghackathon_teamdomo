"""코넥트(Ko-nect) 주민 설문 — Streamlit 앱

응답은 구글 시트에 한 줄씩 쌓입니다. 열 이름과 값 형식은 기존 구글 설문
내보내기와 같습니다(복수 선택은 ", "로 이어 붙임).

실행:  streamlit run survey_app.py
설정:  .streamlit/secrets.toml (secrets.toml.example 참고)
"""
import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

# ---------------------------------------------------------------- 문항 정의
INTRO_TEXT = (
    "코넥트는 운양동에 냄새가 날 가능성을 미리 알려 주는 앱입니다.\n\n"
    "① 주민이 냄새를 느꼈을 때 남긴 기록(시각 · 구역 · 강도)과\n"
    "② 기상청의 바람 · 습도 자료를 합쳐서,\n"
    "③ 앞으로 6시간 동안 우리 구역의 냄새 가능성을 낮음 · 보통 · 높음으로 알려 줍니다.\n\n"
    "기록은 이름 없이 구역 단위로만 쓰이고, 기록이 쌓일수록 예보를 다시 학습합니다.\n"
    "아직 시험 단계라 예보가 틀릴 수 있습니다."
)
USE_NOTICE = "응답은 이름 없이 모아 대회 설명서와 포스터에 통계로만 쓰입니다."

Q1 = "1. 사는 곳과 가장 가까운 곳"
Q2 = "2. 최근 3개월 동안 집 근처에서 악취를 느낀 적"
Q3 = "3. 주로 언제 느꼈나요? (해당하는 것 모두)"
Q4 = "4. 냄새가 날 때 한 일 (해당하는 것 모두)"
Q5 = "5. [예보] 우리 구역에 몇 시쯤 냄새가 날 가능성이 높은지 알려 주는 기능을 쓸 생각이 있다"
Q6 = "6. [기록] 냄새가 날 때 앱에서 강도만 골라 기록하는 데 참여할 생각이 있다 (단추 두 번, 위치는 구역만 확인)"
Q7 = "7. [기기] 냄새 가능성이 높아지기 전에 집 공기청정기가 알아서 켜지는 기능을 쓸 생각이 있다"
Q8 = "8. [알림] 냄새 가능성이 높을 때 미리 알림을 받고 싶다 (준비 중인 기능)"
Q9 = "9. 내 기록이 이름 없이 구역 단위로 모여, 예보를 고치고 시청에 건의하는 자료로 쓰이는 것에 대해"
Q10 = "10. 예보가 있다면 어디에 쓰고 싶나요? (해당하는 것 모두)"
Q11 = "11. 걱정되는 점 (해당하는 것 모두)"
Q12 = "12. 바라는 기능이나 하고 싶은 말 (선택)"

HEADER = ["타임스탬프", Q1, Q2, Q3, Q4, Q5, Q6, Q7, Q8, Q9, Q10, Q11, Q12]

Q1_OPTS = [
    "한강변 (북쪽 · 라베니체 일대)",
    "운양역 (가운데 · 운양역 일대)",
    "모담산 (남쪽 · 모담산 · 학교 일대)",
    "운양동 밖",
]
Q2_OPTS = ["없음", "한 달에 1~2번", "일주일에 1~2번", "거의 매일"]
Q3_OPTS = [
    "새벽 (0~6시)", "아침 (6~9시)", "낮 (9~18시)",
    "저녁 (18~21시)", "밤 (21~24시)", "느낀 적 없음",
]
Q4_OPTS = ["창문 닫기", "공기청정기 켜기", "민원 넣기", "그냥 참기", "느낀 적 없음"]
Q10_OPTS = [
    "창문 닫기 · 환기 시간 정하기",
    "산책 · 외출 시간 정하기",
    "공기청정기 미리 켜기",
    "민원을 넣을 때 근거로",
    "쓸 일이 없다",
]
Q11_OPTS = [
    "예보가 틀릴까 봐",
    "위치 정보가 남는 것",
    "기록하기 귀찮을 것 같다",
    "쓰는 사람이 적으면 소용없을 것 같다",
    "없음",
]
SCALE = [1, 2, 3, 4, 5]
LOCAL_CSV = Path(__file__).with_name("responses_local.csv")

KST = ZoneInfo("Asia/Seoul")
# 응답 기간(한국 시간). 이 기간 밖에서는 설문 대신 안내 화면만 보입니다.
OPEN_FROM = datetime(2026, 11, 11, 21, 0, 0, tzinfo=KST)
OPEN_UNTIL = datetime(2026, 11, 13, 23, 59, 59, tzinfo=KST)
# 응답이 쌓인 구글 시트. 값이 있으면 Secrets의 sheet_id 대신 이 시트를 씁니다.
SHEET_ID = "1KqLCP-H94xwLiA_KWmWQtKPoFol25qxYQcGxS-Ogu4c"
# 실제 조사로 전환할 때만 False로 변경하고 검토 자료와 수집 응답을 분리합니다.
PRE_SURVEY_REVIEW = True


# ---------------------------------------------------------------- 저장
def sheet_configured() -> bool:
    try:
        has_sheet = bool(SHEET_ID) or "sheet_id" in st.secrets
        return has_sheet and ("gcp_json" in st.secrets or "gcp_service_account" in st.secrets)
    except Exception:
        return False


@st.cache_resource(show_spinner=False)
def open_sheet():
    import gspread

    if "gcp_json" in st.secrets:  # JSON 키 파일 내용을 통째로 붙여넣은 경우
        info = json.loads(st.secrets["gcp_json"], strict=False)
    else:
        info = dict(st.secrets["gcp_service_account"])
    client = gspread.service_account_from_dict(info)
    return client.open_by_key(SHEET_ID or st.secrets["sheet_id"]).sheet1


@st.cache_data(ttl=600, show_spinner=False)
def response_count():
    """시트에 쌓인 응답 수(머리글 제외). 읽지 못하면 None."""
    try:
        return max(len(open_sheet().col_values(1)) - 1, 0)
    except Exception:
        return None


def save_row(row: list) -> None:
    if sheet_configured():
        ws = open_sheet()
        if not ws.row_values(1):  # 빈 시트면 머리글을 먼저 씀
            ws.append_row(HEADER, value_input_option="RAW")
        # RAW: 응답이 '='로 시작해도 수식으로 실행되지 않게 글자 그대로 저장
        ws.append_row(row, value_input_option="RAW")
        return
    new_file = not LOCAL_CSV.exists()
    with LOCAL_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(HEADER)
        w.writerow(row)


def validate_choices(a2, a3, a4, a10, a11):
    errors = []
    for number, values, exclusive in (
        (3, a3, "느낀 적 없음"), (4, a4, "느낀 적 없음"),
        (10, a10, "쓸 일이 없다"), (11, a11, "없음"),
    ):
        if exclusive in values and len(values) > 1:
            errors.append(f"{number}번: '{exclusive}'은 다른 항목과 함께 고를 수 없습니다.")
    if a2 == "없음" and (a3 != ["느낀 적 없음"] or a4 != ["느낀 적 없음"]):
        errors.append("2번에서 '없음'을 골랐다면 3·4번도 '느낀 적 없음'을 골라 주세요.")
    elif a2 and a2 != "없음" and ("느낀 적 없음" in a3 or "느낀 적 없음" in a4):
        errors.append("2번의 악취 경험과 3·4번 답변을 다시 확인해 주세요.")
    return errors


# ---------------------------------------------------------------- 화면 부품
def multi(label: str, options: list, key: str, other: bool = True) -> list:
    """체크박스 묶음. 고른 항목(기타는 적은 글)을 목록으로 돌려줌."""
    st.markdown(f"**{label}**")
    picked = [o for i, o in enumerate(options) if st.checkbox(o, key=f"{key}_{i}")]
    if other:
        text = st.text_input("기타 (직접 입력)", key=f"{key}_other", max_chars=100).strip()
        if text:
            picked.append(text.replace(",", " "))
    return picked


def scale(label: str, low: str, high: str, key: str):
    st.markdown(f"**{label}**")
    v = st.radio(label, SCALE, index=None, horizontal=True, key=key, label_visibility="collapsed")
    st.caption(f"1 = {low} · 5 = {high}")
    return v


# ---------------------------------------------------------------- 본문
st.set_page_config(page_title="운양동 냄새 설문", page_icon="📝", layout="centered")

if st.session_state.get("done"):
    st.title("응답해 주셔서 고맙습니다")
    st.write(USE_NOTICE)
    st.stop()

now_kst = datetime.now(KST)
if not (OPEN_FROM <= now_kst <= OPEN_UNTIL):
    period = (f"{OPEN_FROM.year}년 {OPEN_FROM.month}월 {OPEN_FROM.day}일 {OPEN_FROM.hour}시 ~ "
              f"{OPEN_UNTIL.month}월 {OPEN_UNTIL.day}일")
    if now_kst < OPEN_FROM:
        st.title("설문 준비 중입니다")
        st.write(f"{'검토 기간' if PRE_SURVEY_REVIEW else '응답 기간'}: {period}")
    else:
        st.title("설문이 마감되었습니다")
        st.write(f"{'검토 기간' if PRE_SURVEY_REVIEW else '응답 기간'}: {period}")
        n = response_count() if sheet_configured() else None
        if n is not None:
            st.metric("검토 대상" if PRE_SURVEY_REVIEW else "응답 수", f"{n}건")
        if PRE_SURVEY_REVIEW:
            st.write("운양동 악취 경험과 코넥트 이용 의향을 살펴보는 설문입니다.")
        else:
            st.write("설문에 참여해 주셔서 고맙습니다.")
            st.write(USE_NOTICE)
        st.caption("지금은 응답을 받지 않습니다.")
    if PRE_SURVEY_REVIEW:
        with st.expander("자료 안내"):
            st.write("실제 조사 전 설문 흐름과 분석 방법을 검토하는 페이지입니다. "
                     "기간과 건수는 사전 검토용으로 구성한 자료를 기준으로 표시합니다.")
    st.stop()

st.title("운양동 냄새 설문")
st.write("운양동 악취에 대한 경험과 앱 '코넥트'에 대한 생각을 묻습니다. 3분쯤 걸립니다.")
st.caption("이름·연락처는 받지 않습니다. 12번을 뺀 모든 문항에 답해 주세요.")
st.caption(USE_NOTICE)
if PRE_SURVEY_REVIEW:
    st.caption("조사 전 검토 화면입니다. 입력한 내용은 검토 자료에 추가됩니다.")

if not sheet_configured():
    st.error("현재 응답을 안전하게 저장할 수 없어 접수가 중단되었습니다. 잠시 뒤 다시 방문해 주세요.")
    st.stop()

with st.form("survey"):
    st.subheader("악취 경험")
    st.markdown(f"**{Q1}**")
    a1 = st.radio(Q1, Q1_OPTS, index=None, key="q1", label_visibility="collapsed")
    st.markdown(f"**{Q2}**")
    a2 = st.radio(Q2, Q2_OPTS, index=None, key="q2", label_visibility="collapsed")
    a3 = multi(Q3, Q3_OPTS, "q3", other=False)
    a4 = multi(Q4, Q4_OPTS, "q4")

    st.divider()
    st.subheader("앱 '코넥트' 소개")
    st.write(INTRO_TEXT)
    st.caption("소개를 읽은 뒤 아래 문항에 답해 주세요.")

    a5 = scale(Q5, "전혀 없다", "꼭 쓰겠다", "q5")
    a6 = scale(Q6, "전혀 없다", "꼭 쓰겠다", "q6")
    a7 = scale(Q7, "전혀 없다", "꼭 쓰겠다", "q7")
    a8 = scale(Q8, "전혀 없다", "꼭 쓰겠다", "q8")
    a9 = scale(Q9, "꺼려진다", "괜찮다", "q9")
    a10 = multi(Q10, Q10_OPTS, "q10")
    a11 = multi(Q11, Q11_OPTS, "q11")
    st.markdown(f"**{Q12}**")
    a12 = st.text_area(Q12, key="q12", max_chars=500, label_visibility="collapsed").strip()

    submitted = st.form_submit_button("제출", type="primary", use_container_width=True)

if submitted:
    answers = {Q1: a1, Q2: a2, Q3: a3, Q4: a4, Q5: a5, Q6: a6, Q7: a7, Q8: a8, Q9: a9, Q10: a10, Q11: a11}
    missing = [q.split(".")[0] for q, a in answers.items() if a is None or a == []]
    choice_errors = validate_choices(a2, a3, a4, a10, a11)
    if not (OPEN_FROM <= datetime.now(KST) <= OPEN_UNTIL):
        st.error("응답 기간이 끝났습니다. 작성한 내용은 제출되지 않았습니다.")
    elif missing:
        st.error("아직 답하지 않은 문항이 있습니다: " + ", ".join(f"{m}번" for m in missing))
    elif choice_errors:
        for message in choice_errors:
            st.error(message)
    else:
        now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
        row = [now, a1, a2, ", ".join(a3), ", ".join(a4), a5, a6, a7, a8, a9,
               ", ".join(a10), ", ".join(a11), a12]
        try:
            save_row(row)
        except Exception:
            st.error("저장하지 못했습니다. 잠시 뒤 다시 '제출'을 눌러 주세요.")
        else:
            response_count.clear()
            st.session_state["done"] = True
            st.rerun()
