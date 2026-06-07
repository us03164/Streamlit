
# -*- coding: utf-8 -*-
"""
KBO 경기 결과 챗봇 (Streamlit)
- 채팅창에 날짜를 말하면 그날의 KBO 경기를 '경기당 버튼 1개'로 보여줍니다.
- 종료된 경기 버튼: "원정 VS 홈"(이긴 팀 굵게) + 점수. 누르면 티빙 스포츠
  (YouTube @tvingsports) 하이라이트 검색 결과로 바로 이동합니다.
  검색어 형식: [원정팀 vs 홈팀] yyyy mm dd 하이라이트
- 시작 전 경기 버튼: 선발/최근 성적을 GPT 웹 검색으로 반영해 승부 예측.
- 해당 날짜에 경기가 없으면 가장 가까운 직전 경기일 결과를 보여줍니다.

실행:
    pip install streamlit requests openai python-dotenv
    # .env 파일에 OPENAI_API_KEY=sk-... 저장 (예측 기능 사용 시)
    streamlit run kbo_chat.py
"""

import os
import re
import datetime
import urllib.parse

import requests
import streamlit as st
from dotenv import load_dotenv

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

load_dotenv()

# 설정값
API_URL = "https://api-gw.sports.naver.com/schedule/games"
TVING_CHANNEL = "https://www.youtube.com/@tvingsports/search"
OPENAI_MODEL = "gpt-4o"
WEB_SEARCH_TOOL = "web_search_preview"
MAX_LOOKBACK_DAYS = 14

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Referer": "https://m.sports.naver.com/kbaseball/schedule/index",
    "Accept": "application/json",
}

# YouTube 검색 결과 페이지 파싱용 (데스크톱 브라우저처럼 요청)
YT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

FINISHED = ("RESULT", "END", "FINAL")
BEFORE = ("BEFORE", "READY")
LIVE = ("STARTED", "LIVE", "PLAYING")
CANCELED = ("CANCEL", "POSTPONE", "SUSPEND", "SUSPENDED")


# 네이버 KBO API
@st.cache_data(ttl=60, show_spinner=False)
def fetch_games(date_str):
    params = {
        "fields": (
            "basic,statusCode,statusNum,statusInfo,stadium,"
            "homeStarterName,awayStarterName,winPitcherName,losePitcherName,"
            "homeTeamName,awayTeamName,homeTeamScore,awayTeamScore,gameDateTime"
        ),
        "upperCategoryId": "kbaseball",
        "categoryId": "kbo",
        "fromDate": date_str,
        "toDate": date_str,
        "size": 500,
    }
    resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    result = data.get("result", data)
    games = result.get("games")
    if games is None:
        games = result.get("gameInfos", [])
    return games or []


def get_results_with_fallback(target_date):
    games = fetch_games(target_date.isoformat())
    if games:
        return target_date, games, False
    for i in range(1, MAX_LOOKBACK_DAYS + 1):
        d = target_date - datetime.timedelta(days=i)
        games = fetch_games(d.isoformat())
        if games:
            return d, games, True
    return target_date, [], False


def status_of(game):
    return (game.get("statusCode") or "").upper()


# 날짜 파싱
def parse_date(text, today=None):
    if today is None:
        today = datetime.date.today()
    t = text.strip()

    rel = {"오늘": 0, "금일": 0, "어제": -1, "어저께": -1, "그제": -2, "그저께": -2}
    for k, v in rel.items():
        if k in t:
            return today + datetime.timedelta(days=v)

    m = re.search(r"(\d{4})\s*[년\-./]\s*(\d{1,2})\s*[월\-./]\s*(\d{1,2})", t)
    if m:
        y, mo, d = map(int, m.groups())
        try:
            return datetime.date(y, mo, d)
        except ValueError:
            return None

    m = re.search(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", t)
    if m:
        mo, d = map(int, m.groups())
        try:
            return datetime.date(today.year, mo, d)
        except ValueError:
            return None

    m = re.search(r"(?<!\d)(\d{1,2})\s*[-/.]\s*(\d{1,2})(?!\d)", t)
    if m:
        mo, d = map(int, m.groups())
        try:
            return datetime.date(today.year, mo, d)
        except ValueError:
            return None
    return None


def header_text(target, date_used, games, is_fallback):
    if not games:
        return (
            f"**{target.isoformat()}** 에는 경기가 없었고, 직전 {MAX_LOOKBACK_DAYS}일 안에서도 "
            "경기를 찾지 못했어요. 시즌 기간이 맞는지 확인해 주세요. ⚾"
        )
    if is_fallback:
        return (
            f"**{target.isoformat()}** 에는 경기가 없었어요. 가장 가까운 직전 경기일 "
            f"**{date_used.isoformat()}** 결과를 보여드릴게요. ⚾"
        )
    return f"📅 **{date_used.isoformat()} KBO 경기**"


def lookup(user_input):
    target = parse_date(user_input)
    if target is None:
        return ("조회할 날짜를 인식하지 못했어요. 😅\n\n예) `2026-06-06`, `6월 6일`, `오늘`, `어제`",
                [], None)
    try:
        date_used, games, is_fallback = get_results_with_fallback(target)
    except requests.exceptions.RequestException as e:
        return f"데이터를 가져오는 중 오류가 발생했어요: `{e}`", [], None
    except ValueError:
        return "응답을 해석할 수 없어요 (JSON 파싱 실패).", [], None
    return header_text(target, date_used, games, is_fallback), games, date_used


# 하이라이트 / 예측
def tving_highlight_url(away, home, date):
    # 검색어: [원정팀 vs 홈팀] yyyy mm dd 하이라이트
    query = f"[{away} vs {home}] {date:%Y %m %d} 하이라이트"
    return f"{TVING_CHANNEL}?query=" + urllib.parse.quote(query)


@st.cache_data(ttl=3600, show_spinner=False)
def first_highlight_url(away, home, date):
    """티빙 스포츠 채널에서 해당 경기를 검색해 '첫 번째 영상' 링크를 반환.
    파싱 실패/차단 시에는 검색 페이지 URL로 폴백한다."""
    search_url = tving_highlight_url(away, home, date)
    try:
        resp = requests.get(
            search_url, headers=YT_HEADERS,
            cookies={"CONSENT": "YES+"},  # EU 동의 페이지 우회
            timeout=8,
        )
        resp.raise_for_status()
        html = resp.text
        # ytInitialData 내 첫 영상 ID 추출
        m = re.search(r'"(?:videoRenderer|gridVideoRenderer)":\{"videoId":"([0-9A-Za-z_-]{11})"', html)
        if not m:
            m = re.search(r'"videoId":"([0-9A-Za-z_-]{11})"', html)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
    except Exception:
        pass
    return search_url  # 실패 시 검색 페이지로


def get_openai_client():
    if OpenAI is None or not os.getenv("OPENAI_API_KEY"):
        return None
    try:
        return OpenAI()
    except Exception:
        return None


def predict_matchup(client, game, date):
    away, home = game.get("awayTeamName", "?"), game.get("homeTeamName", "?")
    away_p = game.get("awayStarterName") or "미정"
    home_p = game.get("homeStarterName") or "미정"
    stadium = game.get("stadium", "")
    prompt = (
        f"{date.isoformat()} KBO 리그 경기: {away}(원정) vs {home}(홈), 구장 {stadium}.\n"
        f"예고 선발 투수 — {away}: {away_p}, {home}: {home_p}.\n\n"
        "웹 검색을 사용해 다음을 확인한 뒤 경기 결과를 예측해줘:\n"
        "1) 두 팀의 최근 10경기 성적(승패 흐름)\n"
        "2) 두 선발 투수의 최근 등판 성적과 시즌 평균자책점(ERA)\n"
        "3) 두 팀의 시즌 상대 전적과 홈/원정 성향\n\n"
        "출력 형식(한국어, 간결하게):\n"
        "- 예측 우세팀과 대략적인 승리 확률(%)\n"
        "- 핵심 근거 3~4줄\n"
        "- 마지막 줄에 'AI 예측이며 실제 결과와 다를 수 있음' 명시\n"
        "확실하지 않은 정보는 추측하지 말고 검색 결과에 근거해줘."
    )
    resp = client.responses.create(
        model=OPENAI_MODEL,
        tools=[{"type": WEB_SEARCH_TOOL}],
        input=prompt,
    )
    return resp.output_text


def prediction_message(game, date):
    away, home = game.get("awayTeamName", "?"), game.get("homeTeamName", "?")
    client = get_openai_client()
    if client is None:
        return (
            "🔮 경기 예측 기능은 OpenAI API가 필요해요.\n\n"
            "1) `pip install openai`\n"
            "2) 프로젝트 폴더의 `.env` 파일에 `OPENAI_API_KEY=sk-...` 추가\n"
            "후 다시 시도해 주세요."
        )
    try:
        text = predict_matchup(client, game, date)
    except Exception as e:
        return (
            f"예측 생성 중 오류가 발생했어요: `{e}`\n\n"
            f"(모델명 `{OPENAI_MODEL}` 또는 웹 검색 도구 `{WEB_SEARCH_TOOL}` 가 "
            "사용 중인 OpenAI SDK 버전에서 지원되는지 확인해 주세요.)"
        )
    return (
        f"🔮 **{away} vs {home}** ({date.isoformat()}) 경기 예측\n\n{text}\n\n"
        "_※ AI가 웹 검색을 바탕으로 만든 예측이며 실제 결과와 다를 수 있어요._"
    )


# 경기당 버튼 1개로 표시
def finished_label(game):
    """이긴 팀을 굵게: '**KT** VS SSG   7 : 3'"""
    away, home = game.get("awayTeamName", "?"), game.get("homeTeamName", "?")
    a, h = game.get("awayTeamScore", 0), game.get("homeTeamScore", 0)
    if a > h:
        matchup = f"**{away}** VS {home}"
    elif h > a:
        matchup = f"{away} VS **{home}**"
    else:
        matchup = f"{away} VS {home}"
    return f"📺 {matchup}　　{a} : {h}"


def render_game_cards():
    games = st.session_state.get("last_games", [])
    date_str = st.session_state.get("last_date")
    if not games or not date_str:
        return
    date = datetime.date.fromisoformat(date_str)

    st.markdown("##### 경기를 선택하세요")
    for i, g in enumerate(games):
        code = status_of(g)
        away, home = g.get("awayTeamName", "?"), g.get("homeTeamName", "?")
        key = f"game_{i}_{g.get('gameId', i)}"

        # 종료 → 하나의 링크 버튼(누르면 검색 첫 영상으로 이동)
        if code in FINISHED:
            url = first_highlight_url(away, home, date)
            st.link_button(finished_label(g), url, use_container_width=True)

        # 시작 전 → 하나의 예측 버튼
        elif code in BEFORE:
            dt = g.get("gameDateTime", "")
            tm = dt[11:16] if len(dt) >= 16 else ""
            suffix = f" ({tm} 예정)" if tm else ""
            label = f"🔮 {away} VS {home}{suffix} · 경기 예측"
            if st.button(label, key=key, use_container_width=True):
                with st.spinner("예측을 생성하는 중..."):
                    detail = prediction_message(g, date)
                st.session_state.message_history.append({"role": "assistant", "content": detail})
                st.rerun()

        # 경기 중 → 비활성 버튼(상태/스코어만)
        elif code in LIVE:
            a, h = g.get("awayTeamScore", 0), g.get("homeTeamScore", 0)
            info = g.get("statusInfo", "")
            st.button(f"🔴 {away} VS {home}　{a} : {h} · 경기 중 {info}",
                      key=key, use_container_width=True, disabled=True)

        # 취소/연기 → 비활성 버튼
        elif code in CANCELED:
            info = g.get("statusInfo", "") or "취소/연기"
            st.button(f"🚫 {away} VS {home} · {info}",
                      key=key, use_container_width=True, disabled=True)

        else:
            st.button(f"{away} VS {home} · 상태 {code or '미정'}",
                      key=key, use_container_width=True, disabled=True)


# Streamlit UI
def init_page():
    st.set_page_config(page_title="KBO 경기 챗봇", page_icon="⚾")
    st.header("KBO 경기 챗봇 ⚾")
    st.caption("날짜를 입력하면 경기당 버튼 1개로 결과를 보여드려요. 종료 경기 버튼을 누르면 티빙 하이라이트로 이동합니다. (출처: 네이버 스포츠 · 티빙 스포츠)")


def init_messages():
    if st.sidebar.button("대화 초기화", key="clear") or "message_history" not in st.session_state:
        st.session_state.message_history = [
            {"role": "assistant",
             "content": "안녕하세요! 보고 싶은 날짜를 말해주세요. ⚾\n\n예) `2026-06-06`, `6월 6일`, `어제`"}
        ]
        st.session_state.last_games = []
        st.session_state.last_date = None


def render_sidebar():
    st.sidebar.title("Options")
    st.sidebar.markdown(
        "**입력 예시**\n"
        "- `2026-06-06`\n- `2026년 6월 6일`\n- `6월 6일`\n- `오늘` / `어제` / `그저께`\n\n"
        "**경기 버튼**\n"
        "- 📺 종료 → 누르면 티빙 하이라이트\n"
        "- 🔮 시작 전 → GPT 예측"
    )
    if get_openai_client() is None:
        st.sidebar.info("예측 기능을 쓰려면 `OPENAI_API_KEY`를 설정하세요.")


def main():
    init_page()
    init_messages()
    render_sidebar()

    for msg in st.session_state.message_history:
        st.chat_message(msg["role"]).markdown(msg["content"])

    render_game_cards()

    if user_input := st.chat_input("날짜를 입력해주세요. (예: 2026-06-06)"):
        st.session_state.message_history.append({"role": "user", "content": user_input})
        with st.spinner("경기 결과를 조회 중..."):
            text, games, date_used = lookup(user_input)
        st.session_state.message_history.append({"role": "assistant", "content": text})
        st.session_state.last_games = games
        st.session_state.last_date = date_used.isoformat() if date_used else None
        st.rerun()


if __name__ == "__main__":
    main()
