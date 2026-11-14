"""코넥트(Ko-nect) 주민 설문 — Streamlit 앱

응답은 구글 시트에 한 줄씩 쌓입니다. 열 이름과 값 형식은 기존 구글 설문
내보내기와 같습니다(복수 선택은 ", "로 이어 붙임).

실행:  streamlit run survey_app.py
설정:  .streamlit/secrets.toml (secrets.toml.example 참고)
"""
import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

# ---------------------------------------------------------------- 문항 정의
# 설문에 실제로 쓰던 소개 글이 있으면 아래 문장을 그 글로 바꾸세요.
INTRO_TEXT = (
    "코넥트(Ko-nect)는 운양동 주민의 기록과 기상 자료로, 우리 구역에 "
    "앞으로 6시간 동안 냄새가 날 가능성을 지도에 '낮음·보통·높음'으로 "
    "보여 주는 앱입니다. 냄새가 날 때 강도만 골라 기록하면 그 기록이 "
    "모여 예보가 우리 동네에 맞게 고쳐집니다."
)

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


# ---------------------------------------------------------------- 저장
def sheet_configured() -> bool:
    try:
        return "gcp_service_account" in st.secrets and "sheet_id" in st.secrets
    except Exception:
        return False


@st.cache_resource(show_spinner=False)
def open_sheet():
    import gspread

    client = gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    ws = client.open_by_key(st.secrets["sheet_id"]).sheet1
    if not ws.row_values(1):  # 빈 시트면 머리글을 먼저 씀
        ws.append_row(HEADER, value_input_option="RAW")
    return ws


def save_row(row: list) -> None:
    if sheet_configured():
        # RAW: 응답이 '='로 시작해도 수식으로 실행되지 않게 글자 그대로 저장
        open_sheet().append_row(row, value_input_option="RAW")
        return
    new_file = not LOCAL_CSV.exists()
    with LOCAL_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(HEADER)
        w.writerow(row)


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
    st.write("보내 주신 응답은 이름 없이 모아, 예보를 고치는 데만 씁니다.")
    st.stop()

st.title("운양동 냄새 설문")
st.write("운양동 악취에 대한 경험과 앱 '코넥트'에 대한 생각을 묻습니다. 3분쯤 걸립니다.")
st.caption("이름·연락처는 받지 않습니다. 12번을 뺀 모든 문항에 답해 주세요.")

if not sheet_configured():
    st.info("구글 시트 설정이 없어 응답이 이 컴퓨터의 responses_local.csv 에 저장됩니다. (시험용)")

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
    if missing:
        st.error("아직 답하지 않은 문항이 있습니다: " + ", ".join(f"{m}번" for m in missing))
    else:
        now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
        row = [now, a1, a2, ", ".join(a3), ", ".join(a4), a5, a6, a7, a8, a9,
               ", ".join(a10), ", ".join(a11), a12]
        try:
            save_row(row)
        except Exception:
            st.error("저장하지 못했습니다. 잠시 뒤 다시 '제출'을 눌러 주세요.")
        else:
            st.session_state["done"] = True
            st.rerun()
