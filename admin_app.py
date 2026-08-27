# -*- coding: utf-8 -*-
"""
관리자 전용 앱.
이 파일은 apply_app.py와 완전히 별도로 배포하세요.
이 앱의 URL은 카페/학과 홈페이지 등 공개된 곳에 절대 게시하지 마세요.
(운영 담당자·관계자만 개별적으로 URL을 전달받아 사용)
"""
import io
import base64
import datetime
import pandas as pd
import streamlit as st

import scoring
import gsheets
import pdf_gen
import theme
import config

st.set_page_config(page_title="관리자 | POSTECH 화학과 연구참여 프로그램", page_icon="🔐", layout="wide")
theme.inject(wide=True)
# 관리자 화면 전반의 글자 크기를 한 단계씩 줄인다 (표 안 내용물은 이미 별도로 줄여둔 상태 —
# 여기서는 제목·본문·사이드바 같은 '표 밖' 글자들). 지원자 사이트는 그동안 따로 다듬어온
# 크기라 여기 영향이 안 가게, admin_app.py 안에서만 덮어쓴다.
theme.inject_css(
    "h1 { font-size:1.5rem !important; }"
    "h2 { font-size:1.25rem !important; }"
    "h3 { font-size:0.95rem !important; }"
    '.stApp [data-testid="stCaptionContainer"] { font-size:12px !important; }'
    '.stApp .stSelectbox label, .stApp .stTextInput label { font-size:13px !important; }'
)


def _prof_name(x) -> str:
    """'이름 교수님(연구실명)' -> '이름'만 추출 (목록 화면에서 스크롤을 줄이기 위함)."""
    return str(x).split(" 교수님")[0].strip() if x else ""


def _pdf_filename(r: dict) -> str:
    """PDF/ZIP 파일명: '이름_1.교수_2.교수.pdf' 형식."""
    prof1 = _prof_name(r.get("희망지도교수_1지망"))
    prof2 = _prof_name(r.get("희망지도교수_2지망"))
    return scoring.safe_name(f"{r['성명_한글']}_1.{prof1}_2.{prof2}") + ".pdf"


def _selected_receipts(editor_key: str, base_df: pd.DataFrame) -> list:
    """data_editor 위젯을 다시 그리기 전에, 세션에 저장된 수정 델타를 읽어서 지금 체크된 행의
    접수번호를 미리 알아낸다. (표보다 위쪽에 아이콘 툴바를 놓으려면 이 값이 먼저 필요함)"""
    state = st.session_state.get(editor_key)
    edited_rows = state.get("edited_rows", {}) if isinstance(state, dict) else {}
    picked = []
    for pos in range(len(base_df)):
        row = base_df.iloc[pos]
        checked = edited_rows.get(pos, {}).get("선택", row["선택"])
        if checked:
            picked.append(row["접수번호"])
    return picked


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["환산성적순서"] = df["환산성적"].map(scoring.GRADE_ORDER).fillna(99)
    df["대학군순서"] = df["대학군"].map(scoring.GROUP_ORDER).fillna(99)
    return df


def _split_links(raw: str):
    """줄바꿈으로 구분된 링크 여러 개를 리스트로 분리 (성적증명서 여러 장, 기타자료 등에 공용으로 사용)."""
    return [x.strip() for x in str(raw or "").splitlines() if x.strip()]


def _etc_links(r: dict):
    """'기타자료_링크' 컬럼(여러 링크가 줄바꿈으로 구분됨)을 리스트로 분리."""
    return _split_links(r.get("기타자료_링크", ""))


def _build_applicant_pdf(r: dict, include_etc: bool = True) -> bytes:
    """지원서 표지(증명사진 포함) + 성적증명서 + 재학증명서 + (include_etc=True일 때) 기타자료를
    한 PDF로 병합. AI 서류확인 팝업처럼 '핵심 서류만' 필요할 때는 include_etc=False로 부른다."""
    photo_bytes = None
    photo_link = r.get("증명사진_링크", "")
    if photo_link:
        try:
            photo_bytes = gsheets.download_file_bytes_from_link(photo_link)
        except Exception:
            photo_bytes = None

    parts = [pdf_gen.generate_application_pdf(r, photo_bytes=photo_bytes)]
    for link in _split_links(r.get("성적증명서_링크", "")):  # 성적증명서(여러 장 가능)
        parts.append(gsheets.download_file_bytes_from_link(link))
    enrollment_link = r.get("재학증명서_링크", "")
    if enrollment_link:
        parts.append(gsheets.download_file_bytes_from_link(enrollment_link))
    if include_etc:
        for link in _etc_links(r):
            parts.append(gsheets.download_file_bytes_from_link(link))
    return pdf_gen.merge_pdfs(parts)


@st.dialog("서류 확인 결과")
def _ai_check_dialog(row_dict: dict):
    """AI확인 배지를 누르면 뜨는 팝업. 사유를 다시 검사(API 재호출) 없이 저장된 값 그대로
    보여주고, 그 자리에서 바로 제출 서류 PDF도 열어볼 수 있게 한다."""
    name = row_dict.get("성명_한글", "")
    receipt = row_dict.get("접수번호", "")
    val = str(row_dict.get("서류확인_AI") or "")
    st.markdown(f"**{name}**")
    if not val or val == "확인완료":
        st.success("특이사항 없음 (정상)")
    elif val == "수기확인완료":
        st.success("담당자가 직접 확인해서 문제없음으로 표시했어요.")
    elif val.startswith("미확인"):
        st.info("아직 검사가 안 됐거나 검사에 실패했어요. 표 위 '🔁 서류 재확인(AI)'을 한 번 눌러보세요.")
    else:
        notes = val.split(" / ")
        st.warning("확인이 필요해요:\n\n" + "\n\n".join(f"- {n}" for n in notes))
        # AI가 놓친 경우(예: 실제로는 다른 서류에 학교명이 있는데 텍스트 인식이 흐릿했던 경우)를
        # 대비해, 담당자가 직접 서류를 보고 문제없다고 판단하면 수동으로 확정할 수 있게 한다.
        # AI가 자동으로 매긴 "확인완료"와 구분되도록 값 자체를 다르게("수기확인완료") 저장한다.
        if st.button("🖊 직접 확인했어요 — 문제없음으로 표시", key=f"manual_ok_{receipt}", use_container_width=True):
            gsheets.update_fields(receipt, {"서류확인_AI": "수기확인완료"})
            gsheets.clear_cache()
            st.success("수기확인완료로 표시했어요.")
            st.rerun()
    st.divider()
    with st.spinner("서류를 불러오는 중..."):
        try:
            merged = _build_applicant_pdf(row_dict, include_etc=False)
            theme.pdf_view_button(base64.b64encode(merged).decode(),
                                   label="📄 제출 서류 PDF 새 탭에서 보기", key="ai_dialog_pdf_btn")
        except Exception as e:
            st.error(f"서류를 불러오지 못했어요: {e}")


def page_admin():
    if not st.session_state.get("admin_authed"):
        st.header("관리자 대시보드")
        with st.container(key="login_box"):
            st.markdown("**관리자 비밀번호를 입력해주세요**")
            pw = st.text_input("관리자 비밀번호", type="password", placeholder="비밀번호 입력",
                                label_visibility="collapsed")
        theme.inject_css(
            f'.st-key-login_box {{ background:#fff; border:1px solid {config.BRAND["primary_light"]}; '
            "border-radius:10px; padding:16px 18px; max-width:360px; margin-top:8px; }"
        )
        if pw != st.secrets.get("app", {}).get("admin_password", ""):
            if pw:
                st.error("비밀번호가 올바르지 않습니다.")
            else:
                st.warning("비밀번호를 입력하세요.")
            return
        st.session_state["admin_authed"] = True
        st.rerun()

    with st.spinner("구글시트에서 지원자 데이터를 불러오는 중..."):
        raw_all = gsheets.read_all_df()

    _NAV_ITEMS = ["📋 지원자 목록", "👥 교수님별 정리", "🗄 데이터 관리",
                  "💬 문의 답변", "📩 소식받기 신청자"]
    if "admin_nav" not in st.session_state:
        st.session_state["admin_nav"] = _NAV_ITEMS[0]
    nav = st.session_state["admin_nav"]
    _NAV_TITLES = {
        "📋 지원자 목록": "지원자 목록",
        "👥 교수님별 정리": "교수님별 정리 / ZIP",
        "🗄 데이터 관리": "데이터 관리 (백업·삭제)",
        "💬 문의 답변": "문의 (Q&A) 답변",
        "📩 소식받기 신청자": "소식받기 신청자",
    }

    # 회차 선택 — 예전엔 큰 드롭다운으로 늘 화면 위쪽을 차지했는데, 여러 탭에서 다 필요한
    # 건 아니라서 제목 옆 오른쪽에 작게 두는 걸로 바꿨다. (값 자체는 여러 탭이 같이 쓰므로
    # 여기서 한 번만 계산해둔다.)
    hcol_l, hcol_r = st.columns([3, 1.1])
    with hcol_l:
        st.header(_NAV_TITLES.get(nav, "관리자 대시보드"))
    with hcol_r:
        other_rounds = sorted(
            r for r in raw_all.get("프로그램구분", pd.Series(dtype=str)).astype(str).unique()
            if r and r != config.PROGRAM["round_key"]
        )
        round_options = [f"이번 회차만 ({config.PROGRAM['round_key']})"] + other_rounds + ["전체 회차"]
        st.write("")
        round_pick = st.selectbox("조회할 회차", round_options, key="round_pick",
                                   label_visibility="collapsed")

    if round_pick.startswith("이번 회차만"):
        raw = raw_all[raw_all["프로그램구분"].astype(str) == config.PROGRAM["round_key"]]
    elif round_pick == "전체 회차":
        raw = raw_all
    else:
        raw = raw_all[raw_all["프로그램구분"].astype(str) == round_pick]
    df = _enrich(raw)

    total = len(df)
    doc_pass = int((df.get("서류합격여부", pd.Series(dtype=str)) == "합격").sum()) if not df.empty else 0
    if nav == "📋 지원자 목록":
        st.markdown(f"**전체 지원자**: {total}명   |   **서류합격(자동판정)**: {doc_pass}명 "
                    f"(환산성적 {scoring.PASS_CUTOFF_GRADE} 이상)")

    with st.sidebar:
        st.markdown(f"#### {config.PROGRAM['round_key']}")
        st.caption(f"지원자 **{total}**명 · 합격 **{doc_pass}**명")
        st.write("")
        with st.container(key="admin_sidebar_nav"):
            for item in _NAV_ITEMS:
                active = st.session_state["admin_nav"] == item
                if st.button(item, key=f"navbtn_{item}", use_container_width=True,
                             type=("primary" if active else "secondary")):
                    st.session_state["admin_nav"] = item
                    st.rerun()
    theme.inject_css(
        # 사이드바 배경은 본문(분홍)과 맞추되, 완전히 하나로 안 보이도록 오른쪽에 옅은 구분선을 준다.
        f'section[data-testid="stSidebar"] {{ background:{config.BRAND["page_bg"]}; '
        f'border-right:1px solid #F1E1EC; '
        "width:190px !important; min-width:190px !important; max-width:190px !important; }"
        # 위쪽/왼쪽 여백을 좀 더 좁혀서 공간을 아낀다.
        'section[data-testid="stSidebar"] > div:first-child { padding-top:50px !important; }'
        'section[data-testid="stSidebar"] > div { padding-top:0.8rem; padding-left:0.6rem !important; '
        "padding-right:0.6rem !important; }"
        # 제목("2027-WURF")과 캡션도 메뉴 버튼과 같은 기준(왼쪽)으로 맞춘다.
        # (가운데 정렬은 메뉴 글자 길이가 제각각이라 시작선이 들쭉날쭉해 보여서, 왼쪽 정렬로 되돌림)
        # 메뉴 버튼은 안쪽에 12px 패딩이 있어서 글자가 그만큼 더 안쪽에서 시작하는데,
        # 제목/캡션은 그 여백이 없어 시작 지점이 어긋나 보였다 — 똑같이 맞춰준다.
        f'section[data-testid="stSidebar"] h4 {{ text-align:left !important; padding-left:12px !important; '
        f'margin-left:0 !important; color:{config.BRAND["primary_dark"]} !important; }}'
        'section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { font-size:12px !important; '
        "white-space:nowrap; text-align:left !important; padding-left:12px !important; }"
        f'section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] strong {{'
        f'color:{config.BRAND["primary"]} !important; font-weight:700 !important; }}'
        # 이번엔 요청대로 사이드바를 고정(항상 펼침)으로 두기 위해 접기 버튼을 숨긴다.
        # (예전에 이걸 숨겼다가, 이미 접혀있던 브라우저에서 다시 펼 방법이 없어졌던 적이 있어서 —
        # 배포 전에 사이드바가 펼쳐진 상태인지 한 번 확인하고 반영하는 게 안전하다.)
        '[data-testid="stSidebarCollapseButton"], [data-testid="collapsedControl"] { display:none !important; }'
        # 메뉴 버튼들 — 왼쪽 정렬로 진짜 메뉴 목록처럼 보이게 한다.
        # (button 자체뿐 아니라, Streamlit이 버튼 안에 한 번 더 넣는 정렬용 div·p까지 같이
        # 왼쪽 정렬을 줘야 실제로 글자가 왼쪽으로 온다 — 겉의 button만 주면 안쪽은 그대로일 수 있음)
        '.st-key-admin_sidebar_nav div[data-testid="stButton"] { margin-bottom:6px; }'
        '.st-key-admin_sidebar_nav.st-key-admin_sidebar_nav button {'
        "text-align:left !important; justify-content:flex-start !important; "
        "border-radius:8px !important; font-size:13px !important; padding:8px 12px !important; }"
        '.st-key-admin_sidebar_nav.st-key-admin_sidebar_nav button div, '
        '.st-key-admin_sidebar_nav.st-key-admin_sidebar_nav button p {'
        "justify-content:flex-start !important; text-align:left !important; width:100% !important; }"
        f'.st-key-admin_sidebar_nav.st-key-admin_sidebar_nav button[kind="secondary"] {{'
        "background:transparent !important; border:none !important; box-shadow:none !important; "
        f'color:#444 !important; }}'
        '.st-key-admin_sidebar_nav.st-key-admin_sidebar_nav button[kind="secondary"] p {'
        "color:#444 !important; font-weight:500 !important; }"
        f'.st-key-admin_sidebar_nav.st-key-admin_sidebar_nav button[kind="primary"] {{'
        f'background:#fff !important; border:none !important; box-shadow:none !important; }}'
        f'.st-key-admin_sidebar_nav.st-key-admin_sidebar_nav button[kind="primary"] p {{'
        f'color:{config.BRAND["primary"]} !important; font-weight:700 !important; }}'
        # 본문(오른쪽) 쪽도 위/왼쪽 여백을 좁힌다. 상단바 고정 높이만큼은 남겨야 겹치지 않는다.
        ".block-container { padding-top:50px !important; padding-left:1.4rem !important; "
        "padding-right:1.4rem !important; }"
    )

    if nav == "📋 지원자 목록":
        if df.empty:
            st.info("접수된 지원자가 없습니다.")
        else:
            # ── 중복 지원 의심: 이메일 또는 휴대폰번호가 겹치는 지원자 ──
            dup_mask = pd.Series(False, index=df.index)
            for col in ["이메일", "휴대폰번호"]:
                if col in df.columns:
                    vals = df[col].astype(str).str.strip()
                    dup_mask = dup_mask | (vals.duplicated(keep=False) & (vals != ""))
            n_noscore = int((df["환산성적"] == "환산불가").sum())
            n_dup = int(dup_mask.sum())
            doc_ai = df.get("서류확인_AI", pd.Series(dtype=str)).astype(str)
            n_doc_review = int(((doc_ai != "") & (~doc_ai.isin(["확인완료", "수기확인완료"]))).sum())

            if "admin_quick_filter" not in st.session_state:
                st.session_state["admin_quick_filter"] = "all"

            qf_now = st.session_state["admin_quick_filter"]
            cardA, cardB, cardC, cardD = st.columns(4)
            with cardA:
                if theme.quick_filter_card("전체 지원자", f"{len(df)}명", "",
                                            key="all", active=(qf_now == "all")):
                    st.session_state["admin_quick_filter"] = "all"
                    st.rerun()
            with cardB:
                if theme.quick_filter_card("환산불가 (확인 필요)", f"{n_noscore}명", "",
                                            key="noscore", active=(qf_now == "noscore")):
                    st.session_state["admin_quick_filter"] = "noscore"
                    st.rerun()
            with cardC:
                if theme.quick_filter_card("중복 지원 의심", f"{n_dup}명", "",
                                            key="dup", active=(qf_now == "dup")):
                    st.session_state["admin_quick_filter"] = "dup"
                    st.rerun()
            with cardD:
                if theme.quick_filter_card("서류 확인 필요(AI)", f"{n_doc_review}명", "",
                                            key="docreview", active=(qf_now == "docreview")):
                    st.session_state["admin_quick_filter"] = "docreview"
                    st.rerun()

            st.write("")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                search = st.text_input("이름 / 학교명 검색", key="admin_search",
                                        placeholder="이름 / 학교명 검색", label_visibility="collapsed")
            with c2:
                f_pass = st.selectbox("서류상태", ["전체", "합격", "미달"], label_visibility="collapsed")
            with c3:
                f_grade = st.selectbox("환산성적", ["전체"] + sorted(df["환산성적"].dropna().unique().tolist()),
                                        label_visibility="collapsed")
            with c4:
                sort_by = st.selectbox("정렬", ["환산성적 → 대학군 → 4.3환산순", "1지망교수 → 환산성적", "제출일시 최신순"],
                                        label_visibility="collapsed")

            view = df.copy()
            qf = st.session_state["admin_quick_filter"]
            if qf == "noscore":
                view = view[view["환산성적"] == "환산불가"]
            elif qf == "dup":
                view = view[dup_mask.reindex(view.index, fill_value=False)]
            elif qf == "docreview":
                dv = view.get("서류확인_AI", pd.Series(dtype=str)).astype(str)
                view = view[(dv != "") & (~dv.isin(["확인완료", "수기확인완료"]))]
            if search.strip():
                s = search.strip()
                view = view[view["성명_한글"].astype(str).str.contains(s) | view["학교명"].astype(str).str.contains(s)]
            if f_pass != "전체":
                view = view[view["서류합격여부"] == f_pass]
            if f_grade != "전체":
                view = view[view["환산성적"] == f_grade]
            if sort_by == "환산성적 → 대학군 → 4.3환산순":
                view = view.sort_values(["환산성적순서", "대학군순서", "4.3환산"], ascending=[True, True, False])
            elif sort_by == "1지망교수 → 환산성적":
                view = view.sort_values(["희망지도교수_1지망", "환산성적순서"], ascending=[True, True])
            else:
                view = view.sort_values("제출일시", ascending=False)

            table_cols = ["접수번호", "성명_한글", "학교명", "환산성적", "대학군", "4.3환산",
                          "편입_전적학교", "편입_환산성적", "편입_대학군", "편입_4.3환산",
                          "희망지도교수_1지망", "희망지도교수_2지망",
                          "기숙사사용", "서류합격여부", "서류확인_AI", "1지망선발여부"]
            view_rows = view[table_cols].copy()

            # data_editor(캔버스 표)를 그리기 전에 하려던 걸, 직접 그리는 행으로 바꿨다 — 이유는
            # 표 위젯은 셀 하나하나에 색깔 배지를 넣을 수 없는 근본적인 한계가 있어서, 서류상태 같은
            # 값을 실제 색깔 배지(초록/빨강/주황)로 보여주려면 행을 직접 그리는 수밖에 없었다.
            # 체크박스·선발여부 선택은 여전히 진짜 위젯이라 그대로 동작한다.
            picked_receipts = [r for r in view_rows["접수번호"] if st.session_state.get(f"row_sel_{r}", False)]
            n_picked = len(picked_receipts)

            # ── 재계산 / 엑셀 다운로드 / 수정 / 서류확인 — 표 위 오른쪽에 작은 아이콘으로 압축 ──
            tcol_l, tcol_r = st.columns([5, 1.6])
            with tcol_l:
                st.markdown(f"<span style='font-size:12px;color:#888;'>{n_picked}명 선택됨</span>" if n_picked
                            else "", unsafe_allow_html=True)
            with tcol_r:
                with st.container(key="icon_toolbar"):
                    ic1, ic2, ic3, ic4, ic5 = st.columns(5)
                    with ic1:
                        recalc_click = st.button("🔄", key="recalc_all_btn", use_container_width=True,
                                                  help="전체 재계산 (대학 목록을 새로 추가했을 때 사용)")
                    with ic2:
                        export_cols = ["접수번호", "성명_한글", "학교명", "환산성적", "대학군", "4.3환산",
                                       "희망지도교수_1지망", "서류합격여부", "1지망선발여부"]
                        xbuf = io.BytesIO()
                        with pd.ExcelWriter(xbuf, engine="openpyxl") as writer:
                            view.drop(columns=["환산성적순서", "대학군순서"], errors="ignore").to_excel(
                                writer, index=False, sheet_name="지원자목록")
                        st.download_button("📊", xbuf.getvalue(),
                                            file_name=f"지원자목록_{datetime.date.today()}.xlsx",
                                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                            use_container_width=True, help="엑셀(xlsx) 다운로드")
                    with ic3:
                        edit_click = st.button("✏️", key="tb_edit", use_container_width=True,
                                                disabled=(n_picked != 1), help="수정")
                    with ic4:
                        doc_check_click = st.button("AI", key="tb_doc_check", use_container_width=True,
                                                     disabled=(n_picked != 1), help="서류 재확인(AI)")
                    with ic5:
                        delete_click = st.button("🗑", key="tb_delete", use_container_width=True,
                                                  disabled=(n_picked != 1), help="지원자 삭제 (중복 지원 등)")
                theme.inject_css(
                    '.st-key-icon_toolbar div[data-testid="stButton"] button,'
                    '.st-key-icon_toolbar div[data-testid="stDownloadButton"] button {'
                    "padding:4px !important; font-size:15px !important; min-height:auto !important; "
                    "height:32px !important; }"
                )

            if delete_click and n_picked == 1:
                st.session_state["delete_confirm_open"] = True

            if st.session_state.get("delete_confirm_open") and n_picked == 1:
                r_del = view[view["접수번호"] == picked_receipts[0]].iloc[0]
                with st.container(key="delete_confirm_box"):
                    st.warning(f"**{r_del['성명_한글']}** ({r_del['접수번호']}) 지원 내역을 정말 삭제할까요? "
                               "제출한 서류 파일은 구글드라이브 휴지통으로 이동돼요(30일간 복구 가능).")
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        if st.button("삭제 확정", key="delete_confirm_yes", type="primary", use_container_width=True):
                            gsheets.trash_applicant_folder_by_row(r_del.to_dict())
                            gsheets.delete_applicant_row(r_del["접수번호"])
                            gsheets.clear_cache()
                            st.session_state.pop("delete_confirm_open", None)
                            st.success("삭제되었습니다.")
                            st.rerun()
                    with dc2:
                        if st.button("취소", key="delete_confirm_no", use_container_width=True):
                            st.session_state.pop("delete_confirm_open", None)
                            st.rerun()

            if recalc_click:
                changed = 0
                with st.spinner("재계산 중..."):
                    for _, r in df.iterrows():
                        group, score43, grade = scoring.compute_score(
                            r.get("학교명"), r.get("만점기준"), r.get("평점"))
                        doc_stat = scoring.doc_status(grade)
                        updates = {}
                        if str(group) != str(r.get("대학군", "")):
                            updates["대학군"] = group
                        if score43 != r.get("4.3환산"):
                            updates["4.3환산"] = score43
                        if str(grade) != str(r.get("환산성적", "")):
                            updates["환산성적"] = grade
                        if str(doc_stat) != str(r.get("서류합격여부", "")):
                            updates["서류합격여부"] = doc_stat
                        if str(r.get("편입_전적학교", "")).strip():
                            t_group, t_score43, t_grade = scoring.compute_score(
                                r.get("편입_전적학교"), r.get("편입_만점기준"), r.get("편입_평점"))
                            if str(t_group) != str(r.get("편입_대학군", "")):
                                updates["편입_대학군"] = t_group
                            if t_score43 != r.get("편입_4.3환산"):
                                updates["편입_4.3환산"] = t_score43
                            if str(t_grade) != str(r.get("편입_환산성적", "")):
                                updates["편입_환산성적"] = t_grade
                        if updates:
                            gsheets.update_fields(r["접수번호"], updates)
                            changed += 1
                    if changed:
                        gsheets.clear_cache()
                st.success(f"{changed}명 갱신됨" if changed else "바뀐 내용 없음")
                if changed:
                    st.rerun()

            if doc_check_click and n_picked == 1:
                r_dc = view[view["접수번호"] == picked_receipts[0]].iloc[0]
                with st.spinner("서류에서 글자를 인식하는 중..."):
                    transcript_links = _split_links(r_dc.get("성적증명서_링크", ""))
                    transcript_texts = []
                    for link in transcript_links:
                        fbytes = gsheets.download_file_bytes_from_link(link)
                        fname = gsheets.get_file_name_from_link(link)
                        transcript_texts.append(gsheets.ocr_document_text(fbytes, fname))
                    enrollment_link = r_dc.get("재학증명서_링크", "")
                    enrollment_text = ""
                    if enrollment_link:
                        fbytes = gsheets.download_file_bytes_from_link(enrollment_link)
                        fname = gsheets.get_file_name_from_link(enrollment_link)
                        enrollment_text = gsheets.ocr_document_text(fbytes, fname)
                    all_notes = scoring.check_documents_combined(
                        {"성적증명서": "\n".join(transcript_texts), "재학증명서": enrollment_text},
                        r_dc.get("학교명"), r_dc.get("평점"))
                result_text = " / ".join(all_notes) if all_notes else "확인완료"
                gsheets.update_fields(r_dc["접수번호"], {"서류확인_AI": result_text})
                gsheets.clear_cache()
                st.session_state["doc_check_result"] = all_notes
                st.session_state["doc_check_name"] = r_dc["성명_한글"]
                st.session_state["doc_check_receipt"] = r_dc["접수번호"]
                # 결과 옆에서 서류를 바로 볼 수 있게, 병합 PDF도 같이 만들어서 base64로 저장해둔다
                # (다른 탭에서 다시 다운로드하거나 구글드라이브에 안 들어가도 되게).
                try:
                    merged_pdf = _build_applicant_pdf(r_dc.to_dict(), include_etc=False)
                    st.session_state["doc_check_pdf_b64"] = base64.b64encode(merged_pdf).decode()
                except Exception:
                    st.session_state["doc_check_pdf_b64"] = None

            # 결과는 '지금 선택된 학생'의 것일 때만 보여준다 — 다른 학생을 고르거나 선택을 해제하면
            # 이전 결과가 그대로 남아있지 않도록.
            if (st.session_state.get("doc_check_result") is not None
                    and n_picked == 1 and picked_receipts[0] == st.session_state.get("doc_check_receipt")):
                notes = st.session_state["doc_check_result"]
                name_shown = st.session_state.get("doc_check_name", "")
                if notes:
                    st.warning(f"**{name_shown}** 서류 확인 결과:\n\n" + "\n\n".join(f"- {n}" for n in notes))
                else:
                    st.success(f"**{name_shown}** 서류에서 입력하신 학교명·평점을 확인했어요. 특이사항 없음.")
                if st.session_state.get("doc_check_pdf_b64"):
                    theme.pdf_view_button(
                        st.session_state["doc_check_pdf_b64"],
                        label=f"📄 {name_shown} 서류 PDF 새 탭에서 보기", key="doc_check_pdf_btn")

            _ROW_WIDTHS = [0.25, 0.6, 0.55, 0.95, 0.55, 0.55, 0.55,
                           0.85, 0.65, 0.55, 0.65,
                           0.65, 0.65, 0.4, 0.6, 0.55, 0.65]
            _ROW_HEADERS = ["", "접수번호", "성명", "대학", "환산성적", "대학군", "4.3환산",
                            "편입대학", "편입환산", "편입군", "편입4.3",
                            "1지망", "2지망", "기숙사", "서류상태", "AI확인", "선발여부"]
            # 칸이 좁아서 줄인 이름들은, 마우스를 올리면 원래 이름이 뜨도록 안내(title)를 같이 넣는다.
            _ROW_HEADER_FULL = ["", "접수번호", "성명", "학교명(대학)", "환산성적", "대학군", "4.3환산",
                                "편입 전 전적대학", "편입 전 환산성적", "편입 전 대학군", "편입 전 4.3환산",
                                "1지망 교수", "2지망 교수", "기숙사 사용여부", "서류상태", "AI 서류확인", "선발여부"]
            _DOC_BADGE = {
                "합격": ("#EAF3DE", "#27500A"), "미달": ("#FCEBEB", "#791F1F"),
                "환산불가": ("#FDEECB", "#8A5A0A"),
            }

            def _ai_badge(val: str):
                """AI 서류확인 값에 따라 표에 보여줄 짧은 라벨과 배지 색을 정한다."""
                v = str(val or "").strip()
                if not v:
                    return ("#eee", "#999", "정상")
                if v == "확인완료":
                    return ("#EAF3DE", "#27500A", "확인완료")
                if v == "수기확인완료":
                    return ("#E3F0E9", "#1D5C3F", "수기확인")
                if v.startswith("미확인"):
                    return ("#EFEFEF", "#666666", "미확인")
                return ("#FDEECB", "#8A5A0A", "확인필요")

            _ai_btn_css = []
            with st.container(key="applicant_table_box"):
                with st.container(key="table_header_row"):
                    hcols = st.columns(_ROW_WIDTHS)
                    for hc, htext, hfull in zip(hcols, _ROW_HEADERS, _ROW_HEADER_FULL):
                        hc.markdown(f"<span title='{hfull}' style='font-size:11px;"
                                    f"color:{config.BRAND['primary_dark']};font-weight:700;'>{htext}</span>",
                                    unsafe_allow_html=True)

                for _, r in view_rows.iterrows():
                    receipt = r["접수번호"]
                    with st.container(key=f"arow_{receipt}"):
                        rc = st.columns(_ROW_WIDTHS)
                        with rc[0]:
                            st.checkbox("", key=f"row_sel_{receipt}", label_visibility="collapsed")
                        rc[1].markdown(f"<span style='font-size:12px;'>{receipt}</span>", unsafe_allow_html=True)
                        rc[2].markdown(f"<span style='font-size:12px;font-weight:600;'>{r['성명_한글']}</span>",
                                       unsafe_allow_html=True)
                        rc[3].markdown(f"<span style='font-size:12px;'>{r['학교명']}</span>", unsafe_allow_html=True)
                        rc[4].markdown(f"<span style='font-size:12px;'>{r['환산성적']}</span>", unsafe_allow_html=True)
                        rc[5].markdown(f"<span style='font-size:12px;'>{r['대학군']}</span>", unsafe_allow_html=True)
                        rc[6].markdown(f"<span style='font-size:12px;'>{r['4.3환산']}</span>", unsafe_allow_html=True)
                        rc[7].markdown(f"<span style='font-size:12px;'>{r['편입_전적학교'] or '-'}</span>",
                                       unsafe_allow_html=True)
                        rc[8].markdown(f"<span style='font-size:12px;'>{r['편입_환산성적'] or '-'}</span>",
                                       unsafe_allow_html=True)
                        rc[9].markdown(f"<span style='font-size:12px;'>{r['편입_대학군'] or '-'}</span>",
                                       unsafe_allow_html=True)
                        rc[10].markdown(f"<span style='font-size:12px;'>{r['편입_4.3환산'] or '-'}</span>",
                                        unsafe_allow_html=True)
                        rc[11].markdown(f"<span style='font-size:12px;'>{_prof_name(r['희망지도교수_1지망'])}</span>",
                                        unsafe_allow_html=True)
                        rc[12].markdown(f"<span style='font-size:12px;'>{_prof_name(r['희망지도교수_2지망'])}</span>",
                                        unsafe_allow_html=True)
                        rc[13].markdown(f"<span style='font-size:12px;'>{r['기숙사사용']}</span>", unsafe_allow_html=True)
                        with rc[14]:
                            bg, fg = _DOC_BADGE.get(r["서류합격여부"], ("#eee", "#555"))
                            st.markdown(
                                f'<span style="background:{bg};color:{fg};padding:2px 7px;border-radius:10px;'
                                f'font-size:11px;font-weight:600;">{r["서류합격여부"]}</span>',
                                unsafe_allow_html=True)
                        with rc[15]:
                            ai_bg, ai_fg, ai_label = _ai_badge(r.get("서류확인_AI"))
                            ai_hint = " ⓘ" if ai_label in ("확인필요", "미확인") else ""
                            if st.button(f"{ai_label}{ai_hint}", key=f"ai_open_{receipt}",
                                         use_container_width=True):
                                # view_rows는 표시용으로 컬럼을 줄여둔 것이라 성적증명서·재학증명서
                                # 링크가 없다 — 팝업에서 실제 서류를 보여주려면 전체 컬럼이 있는
                                # view에서 이 학생 행을 다시 찾아 넘겨야 한다.
                                full_row = view[view["접수번호"] == receipt].iloc[0].to_dict()
                                _ai_check_dialog(full_row)
                            # 이 행 컨테이너 안에는 실제 <button>이 이 배지 버튼 하나뿐이라,
                            # 행의 key만으로 바로 지정해서 상태별 색을 입힐 수 있다.
                            _ai_btn_css.append(
                                f'.st-key-arow_{receipt} div[data-testid="stButton"] {{'
                                "display:flex !important; justify-content:center !important; }"
                                f'.st-key-arow_{receipt} div[data-testid="stButton"] button {{'
                                f'background:{ai_bg} !important; color:{ai_fg} !important; border:none !important; '
                                "font-size:11px !important; padding:2px 6px !important; min-height:auto !important; "
                                "white-space:nowrap !important; text-align:center !important; "
                                "justify-content:center !important; display:flex !important; width:auto !important; }"
                                f'.st-key-arow_{receipt} div[data-testid="stButton"] button div, '
                                f'.st-key-arow_{receipt} div[data-testid="stButton"] button p {{'
                                "justify-content:center !important; text-align:center !important; "
                                "width:100% !important; margin:0 !important; font-size:11px !important; }"
                            )
                        with rc[16]:
                            options = ["", "O", "X", "대기"]
                            cur_val = r["1지망선발여부"] if r["1지망선발여부"] in options else ""
                            new_val = st.selectbox(
                                "", options, index=options.index(cur_val),
                                key=f"row_status_{receipt}", label_visibility="collapsed")
                            if new_val != cur_val:
                                gsheets.update_fields(receipt, {"1지망선발여부": new_val})
                                gsheets.clear_cache()
                                st.rerun()
            theme.inject_css(
                f'.st-key-applicant_table_box {{ background:#fff;border:1px solid {config.BRAND["primary_light"]};'
                "border-radius:10px;padding:14px 8px; }"
                # 컬럼이 16개라 칸 사이 기본 여백도 줄여서 공간을 확보
                'div[class*="st-key-arow_"] div[data-testid="stHorizontalBlock"],'
                'div[class*="st-key-table_header_row"] div[data-testid="stHorizontalBlock"] {'
                "gap:0.15rem !important; }"
                # 선발여부 드롭다운 자체의 여백도 줄여서 칸을 덜 차지하게
                'div[class*="st-key-arow_"] div[data-testid="stSelectbox"] [data-baseweb="select"] > div {'
                "justify-content:center !important; text-align:center !important; }"
                'div[class*="st-key-arow_"] div[data-testid="stSelectbox"] > div {'
                "min-height:auto !important; }"
                'div[class*="st-key-arow_"] div[data-testid="stSelectbox"] [data-baseweb="select"] > div {'
                "padding:2px 4px !important; font-size:11px !important; min-height:28px !important; }"
                # 값 텍스트가 더 안쪽(자식 div/span)에 한 번 더 감싸져 있을 수 있어, 그 안까지
                # font-size/정렬을 직접 지정한다 (AI확인 버튼과 같은 유형의 문제 예방).
                'div[class*="st-key-arow_"] div[data-testid="stSelectbox"] [data-baseweb="select"] > div * {'
                "font-size:11px !important; text-align:center !important; }"
                # 헤더 줄(접수번호/성명/대학/환산성적...)에 연한 자주색 배경
                f'.st-key-table_header_row {{ background:{config.BRAND["page_bg"]};border-radius:6px;'
                "padding:7px 4px;margin-bottom:4px; }"
                'div[class*="st-key-table_header_row"] div[data-testid="stHorizontalBlock"] { align-items:center !important; }'
                # 체크박스와 텍스트 줄이 안 맞던 것 — 행 전체를 세로 가운데 정렬
                'div[class*="st-key-arow_"] div[data-testid="stHorizontalBlock"] { align-items:center !important; }'
                'div[class*="st-key-arow_"] div[data-testid="stCheckbox"] { padding-top:0 !important; }'
                # 행 사이 구분선
                'div[class*="st-key-arow_"] { border-bottom:1px solid #F1E5EF; padding:4px 0; }'
                # 세로 칸 구분선(연하게) — 데이터 행에만
                'div[class*="st-key-arow_"] div[data-testid="stHorizontalBlock"] > div {'
                "border-right:1px solid #F6EFF4; }"
                # 접수번호·성명·대학(1~3번째 칸)까지는 왼쪽 정렬 그대로 두고, 그 뒤 칸(환산성적부터
                # 선발여부까지)은 전부 가운데 정렬로 통일한다. 헤더 칸도 그 컬럼과 정렬을 맞춘다.
                # (부모 div에만 text-align을 주면 안쪽 p/span까지 안 먹는 경우가 있어서,
                # markdown 컨테이너·문단·스팬 전부에 직접 !important로 지정한다.)
                'div[class*="st-key-arow_"] div[data-testid="stHorizontalBlock"] > div.stColumn.stColumn:nth-child(n+5),'
                'div[class*="st-key-table_header_row"] div[data-testid="stHorizontalBlock"] > div.stColumn.stColumn:nth-child(n+5) {'
                "text-align:center !important; }"
                'div[class*="st-key-arow_"] div[data-testid="stHorizontalBlock"] > div.stColumn.stColumn:nth-child(n+5) '
                '[data-testid="stMarkdownContainer"],'
                'div[class*="st-key-arow_"] div[data-testid="stHorizontalBlock"] > div.stColumn.stColumn:nth-child(n+5) p,'
                'div[class*="st-key-table_header_row"] div[data-testid="stHorizontalBlock"] > div.stColumn.stColumn:nth-child(n+5) '
                '[data-testid="stMarkdownContainer"],'
                'div[class*="st-key-table_header_row"] div[data-testid="stHorizontalBlock"] > div.stColumn.stColumn:nth-child(n+5) p {'
                "text-align:center !important; width:100% !important; }"
                'div[class*="st-key-arow_"] div[data-testid="stHorizontalBlock"] > div.stColumn.stColumn:nth-child(n+5) span {'
                "display:block !important; text-align:center !important; }"
                'div[class*="st-key-arow_"] div[data-testid="stHorizontalBlock"] > div.stColumn.stColumn:nth-child(n+5) '
                'div[data-testid="stButton"] button {'
                "margin:0 auto !important; display:flex !important; justify-content:center !important; }"
                + "".join(_ai_btn_css)
            )

            # 1명만 선택했을 때: 그 자리에서 바로 정보 수정
            if edit_click and n_picked == 1:
                st.session_state["edit_target"] = picked_receipts[0]

            if st.session_state.get("edit_target") in view["접수번호"].values:
                r_one = view[view["접수번호"] == st.session_state["edit_target"]].iloc[0].to_dict()
                with st.form("edit_applicant_form"):
                    st.caption(f"**{r_one['성명_한글']}** ({r_one['접수번호']}) 정보 수정 — 바꿀 항목만 고쳐서 저장하세요.")
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        e_prof1 = st.selectbox("희망지도교수 (1지망)", scoring.PROFESSORS,
                                                index=scoring.PROFESSORS.index(r_one["희망지도교수_1지망"])
                                                if r_one["희망지도교수_1지망"] in scoring.PROFESSORS else None)
                        e_school = st.text_input("학사 학교명", value=r_one.get("학교명", ""))
                        e_major = st.text_input("학사 전공명", value=r_one.get("전공명", ""))
                        e_scale = st.selectbox("기준평점(만점)", ["4.5 만점", "4.3 만점"],
                                                index=["4.5 만점", "4.3 만점"].index(r_one["만점기준"])
                                                if r_one.get("만점기준") in ["4.5 만점", "4.3 만점"] else None)
                        e_phone = st.text_input("휴대폰번호", value=r_one.get("휴대폰번호", ""))
                    with ec2:
                        e_prof2 = st.selectbox("희망지도교수 (2지망)", scoring.PROFESSORS,
                                                index=scoring.PROFESSORS.index(r_one["희망지도교수_2지망"])
                                                if r_one["희망지도교수_2지망"] in scoring.PROFESSORS else None)
                        e_admit_ym = st.text_input("입학 연월", value=r_one.get("입학연월", ""))
                        e_gpa = st.text_input("평점", value=r_one.get("평점", ""))
                        e_dorm = st.selectbox("생활관(기숙사) 사용 여부", ["O", "X"],
                                               index=["O", "X"].index(r_one["기숙사사용"])
                                               if r_one.get("기숙사사용") in ["O", "X"] else None)
                        e_email = st.text_input("이메일", value=r_one.get("이메일", ""))
                    e_motivation = st.text_area("자기소개 및 지원동기", value=r_one.get("지원동기", ""), height=140)
                    c_save, c_cancel = st.columns(2)
                    with c_save:
                        save_edit = st.form_submit_button("이 학생 정보 저장", type="primary", use_container_width=True)
                    with c_cancel:
                        cancel_edit = st.form_submit_button("취소", use_container_width=True)

                if cancel_edit:
                    st.session_state.pop("edit_target", None)
                    st.rerun()

                if save_edit:
                    updates = {}
                    for field, new_val in [
                        ("희망지도교수_1지망", e_prof1), ("희망지도교수_2지망", e_prof2),
                        ("학교명", e_school), ("전공명", e_major), ("입학연월", e_admit_ym),
                        ("만점기준", e_scale), ("평점", e_gpa), ("휴대폰번호", e_phone),
                        ("이메일", e_email), ("기숙사사용", e_dorm), ("지원동기", e_motivation),
                    ]:
                        if str(new_val) != str(r_one.get(field, "")):
                            updates[field] = new_val

                    if {"학교명", "만점기준", "평점"} & updates.keys():
                        group, score43, grade = scoring.compute_score(
                            updates.get("학교명", r_one.get("학교명")),
                            updates.get("만점기준", r_one.get("만점기준")),
                            updates.get("평점", r_one.get("평점")))
                        updates["대학군"] = group
                        updates["4.3환산"] = score43
                        updates["환산성적"] = grade
                        updates["서류합격여부"] = scoring.doc_status(grade)

                    if updates:
                        gsheets.update_fields(r_one["접수번호"], updates)
                        gsheets.clear_cache()
                        st.success(f"{len(updates)}개 항목이 저장되었습니다.")
                        st.session_state.pop("edit_target", None)
                        st.rerun()
                    else:
                        st.info("바뀐 내용이 없습니다.")

    if nav == "👥 교수님별 정리":
        if df.empty:
            st.info("접수된 지원자가 없습니다.")
        else:
            st.subheader("교수님별 지원자 현황")
            status_cols = ["접수번호", "성명_한글", "학교명", "환산성적", "대학군", "4.3환산",
                           "편입_전적학교", "편입_환산성적", "편입_대학군", "편입_4.3환산",
                           "기숙사사용", "서류합격여부"]

            def _show_prof_list_with_zip(field_col: str, pick: str):
                pv = df[df[field_col] == pick].sort_values(
                    ["환산성적순서", "대학군순서", "4.3환산"], ascending=[True, True, False])
                st.markdown(f"**{pick} — {len(pv)}명**")
                pick_df = pv[[c for c in status_cols if c in pv.columns]].rename(columns={
                    "학교명": "현재 대학", "환산성적": "현재 환산성적", "대학군": "현재 대학군", "4.3환산": "현재 4.3환산",
                    "편입_전적학교": "편입 전 대학", "편입_환산성적": "편입 환산성적",
                    "편입_대학군": "편입 대학군", "편입_4.3환산": "편입 4.3환산", "기숙사사용": "기숙사",
                })
                pick_df.insert(0, "선택", True)
                edited_pick = st.data_editor(
                    pick_df, use_container_width=True, hide_index=True, key=f"zip_pick_{field_col}_{pick}",
                    column_config={"선택": st.column_config.CheckboxColumn("선택")})
                chosen = edited_pick[edited_pick["선택"]]
                zip_key = f"{field_col}_{scoring.safe_name(_prof_name(pick))}"
                if st.button(f"선택한 {len(chosen)}명 지원서류 ZIP 생성", disabled=chosen.empty, key=f"zipbtn_{zip_key}"):
                    with st.spinner("구글드라이브에서 파일을 모아 병합 후 ZIP으로 묶는 중... "
                                     "(인원이 많으면 시간이 걸릴 수 있어요)"):
                        applicant_pdfs = {}
                        for receipt in chosen["접수번호"]:
                            r = pv[pv["접수번호"] == receipt].iloc[0]
                            merged = _build_applicant_pdf(r.to_dict())
                            fname = _pdf_filename(r.to_dict())
                            applicant_pdfs[fname] = merged
                            photo_link = r.get("증명사진_링크", "")
                            if photo_link:
                                photo_bytes = gsheets.download_file_bytes_from_link(photo_link)
                                photo_name = gsheets.get_file_name_from_link(photo_link)
                                applicant_pdfs[scoring.safe_name(f"{r['성명_한글']}_증명사진_") + photo_name] = photo_bytes
                        st.session_state["prof_zip_bytes"] = pdf_gen.build_zip_for_professor(applicant_pdfs)
                        st.session_state["prof_zip_name"] = zip_key
                if st.session_state.get("prof_zip_bytes") and st.session_state.get("prof_zip_name") == zip_key:
                    st.download_button(
                        "ZIP 다운로드", st.session_state["prof_zip_bytes"],
                        file_name=f"{zip_key}_지원서류.zip", mime="application/zip", key=f"zipdl_{zip_key}")

            col_l, col_r = st.columns([1, 1])
            with col_l:
                theme.prof_summary_table(
                    df["희망지도교수_1지망"].dropna().value_counts().to_dict(),
                    df["희망지도교수_2지망"].dropna().value_counts().to_dict(),
                    "prof_row_pick", all_profs_list=scoring.PROFESSORS)

            pick = st.session_state.get("prof_row_pick")
            with col_r:
                if not pick:
                    st.caption("← 왼쪽 표에서 교수님을 선택하면 여기에 요약이 나와요.")
                else:
                    n1 = int((df["희망지도교수_1지망"] == pick).sum())
                    n2 = int((df["희망지도교수_2지망"] == pick).sum())
                    st.markdown(f"**{pick}**")
                    st.caption(f"1지망 {n1}명 · 2지망 {n2}명")
                    if st.button(f"1지망 목록 보기 ({n1}명)", key="view_as_1", use_container_width=True,
                                 disabled=(n1 == 0)):
                        st.session_state["prof_view_which"] = "1"
                    if st.button(f"2지망 목록 보기 ({n2}명)", key="view_as_2", use_container_width=True,
                                 disabled=(n2 == 0)):
                        st.session_state["prof_view_which"] = "2"

            # 세부 지원자 표는 컬럼이 12개나 돼서 폭이 좁으면 다시 스크롤이 생기므로,
            # 위 2단 레이아웃과 별개로 화면 전체 폭을 그대로 쓴다.
            if pick:
                which = st.session_state.get("prof_view_which")
                if which == "1" and n1:
                    _show_prof_list_with_zip("희망지도교수_1지망", pick)
                elif which == "2" and n2:
                    _show_prof_list_with_zip("희망지도교수_2지망", pick)

    if nav == "🗄 데이터 관리":
        st.markdown(
            "개인정보 보유기간은 **1년**입니다. 지난 자료는 아래 순서로 정리해주세요.\n"
            "① 백업 ZIP 다운로드 → ② 보관 → ③ 삭제 (삭제해도 드라이브 휴지통에서 30일간 복구 가능)"
        )
        if raw_all.empty:
            st.info("접수된 지원자가 없습니다.")
        else:
            all_df = _enrich(raw_all)
            rounds = sorted(all_df["프로그램구분"].astype(str).unique().tolist(), reverse=True)
            pick_round = st.selectbox("회차 선택", rounds, key="manage_round_pick")
            year_df = all_df[all_df["프로그램구분"].astype(str) == pick_round]
            st.write(f"**{pick_round} 지원자: {len(year_df)}명**")

            colA, colB = st.columns(2)
            with colA:
                if st.button("① 백업 ZIP 다운로드 준비", key="backup_btn"):
                    with st.spinner("파일을 모으는 중..."):
                        buf_zip = io.BytesIO()
                        with __import__("zipfile").ZipFile(buf_zip, "w") as zf:
                            # 엑셀 요약
                            ebuf = io.BytesIO()
                            with pd.ExcelWriter(ebuf, engine="openpyxl") as writer:
                                year_df.drop(columns=["환산성적순서", "대학군순서"], errors="ignore").to_excel(
                                    writer, index=False, sheet_name=scoring.safe_name(pick_round)[:31])
                            zf.writestr(f"{scoring.safe_name(pick_round)}_지원자목록.xlsx", ebuf.getvalue())
                            # 원본 파일들
                            for _, r in year_df.iterrows():
                                folder = scoring.safe_name(f"{r['접수번호']}_{r['성명_한글']}")
                                for col in ["성적증명서_링크", "재학증명서_링크", "기타자료_링크", "증명사진_링크"]:
                                    link = r.get(col, "")
                                    if link:
                                        try:
                                            fbytes = gsheets.download_file_bytes_from_link(link)
                                            fname = gsheets.get_file_name_from_link(link)
                                            zf.writestr(f"{folder}/{fname}", fbytes)
                                        except Exception as e:
                                            zf.writestr(f"{folder}/오류_{col}.txt", str(e))
                        st.session_state["backup_zip"] = buf_zip.getvalue()
                        st.session_state["backup_round"] = pick_round
                if st.session_state.get("backup_zip") and st.session_state.get("backup_round") == pick_round:
                    st.download_button(f"{pick_round} 백업 ZIP 다운로드", st.session_state["backup_zip"],
                                        file_name=f"{scoring.safe_name(pick_round)}_백업.zip", mime="application/zip")

            with colB:
                st.markdown("**② 삭제 (백업 완료 후 진행하세요)**")
                confirm1 = st.checkbox(f"{pick_round} 자료를 백업 완료했습니다.")
                confirm2 = st.text_input("삭제하려면 '삭제확인'을 입력하세요")
                if st.button("이 회차 자료 삭제 (드라이브 휴지통 이동 + 시트 행 삭제)", type="secondary"):
                    if not confirm1:
                        st.error("먼저 백업 완료 체크박스를 선택해주세요.")
                    elif confirm2 != "삭제확인":
                        st.error("'삭제확인' 문구를 정확히 입력해주세요.")
                    else:
                        progress = st.progress(0.0)
                        def _cb(i, total):
                            progress.progress(i / total if total else 1.0)
                        with st.spinner("삭제 중..."):
                            n = gsheets.archive_and_delete_round(all_df, pick_round, progress_cb=_cb)
                            gsheets.clear_cache()
                        st.success(f"{n}건 삭제 완료 (드라이브 휴지통에서 30일간 복구 가능)")
                        st.session_state.pop("backup_zip", None)
                        st.rerun()

    if nav == "💬 문의 답변":
        try:
            qdf = gsheets.read_all_questions()
        except Exception:
            qdf = None

        if qdf is None or qdf.empty:
            st.info("등록된 문의가 없습니다.")
        else:
            f_status = st.selectbox("상태 필터", ["전체", "답변대기", "답변완료"])
            view_q = qdf.sort_values("등록일시", ascending=False)
            if f_status == "답변대기":
                view_q = view_q[view_q["답변여부"] != "Y"]
            elif f_status == "답변완료":
                view_q = view_q[view_q["답변여부"] == "Y"]

            for _, r in view_q.iterrows():
                status = "✅ 답변완료" if str(r.get("답변여부")) == "Y" else "⏳ 답변대기"
                with st.expander(f"[{status}] {r.get('이름') or '익명'} — {r.get('등록일시')}"):
                    st.write(r.get("질문", ""))
                    answer_key = f"answer_{r.get('id')}"
                    default_answer = r.get("답변", "") if str(r.get("답변여부")) == "Y" else ""
                    new_answer = st.text_area("답변 작성", value=default_answer, key=answer_key)
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("답변 저장", key=f"save_{r.get('id')}"):
                            gsheets.answer_question(str(r.get("id")), new_answer)
                            st.success("답변이 저장되었습니다.")
                            st.rerun()
                    with c2:
                        if st.button("문의 삭제", key=f"del_{r.get('id')}", type="secondary"):
                            gsheets.delete_question(str(r.get("id")))
                            st.success("삭제되었습니다.")
                            st.rerun()

    if nav == "📩 소식받기 신청자":
        sub_df = gsheets.read_all_subscribers()
        if sub_df.empty:
            st.info("아직 신청자가 없습니다.")
        else:
            n_research = int((sub_df["연구참여소식"] == "Y").sum())
            n_admission = int((sub_df["입시정보"] == "Y").sum())
            st.markdown(f"**전체 {len(sub_df)}명** · 연구참여 소식 {n_research}명 · 입시정보 {n_admission}명")
            st.dataframe(sub_df.sort_values("등록일시", ascending=False), use_container_width=True, hide_index=True)
            st.download_button("이메일 목록 CSV 다운로드", sub_df.to_csv(index=False).encode("utf-8-sig"),
                                file_name="소식받기_신청자.csv", mime="text/csv")


theme.topbar("관리자 | POSTECH 화학과 연구참여 프로그램")
page_admin()
