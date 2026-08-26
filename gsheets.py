# -*- coding: utf-8 -*-
"""
구글시트(지원자 데이터 저장) + 구글드라이브(첨부파일 저장) 연동.

- 구글시트는 서비스 계정으로 접근합니다. (시트는 서비스 계정으로도 문제없이 씁니다)
- 구글드라이브 업로드는 "서비스 계정 저장용량 0GB" 문제 때문에, 담당자님의 실제 구글 계정으로
  로그인(OAuth)해서 그 계정 소유로 업로드하는 방식을 씁니다. (get_refresh_token.py 참고)

st.secrets 에 아래 형태로 값이 있어야 합니다. (SETUP_GUIDE.md 참고)

[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "xxx@xxx.iam.gserviceaccount.com"
client_id = "..."
token_uri = "https://oauth2.googleapis.com/token"

[google_oauth]
client_id = "OAuth 클라이언트 ID (Desktop app)"
client_secret = "OAuth 클라이언트 보안 비밀번호"
refresh_token = "get_refresh_token.py 실행 후 얻은 값"

[app]
sheet_id = "구글시트_ID"
drive_folder_id = "구글드라이브_루트폴더_ID"
admin_password = "관리자비밀번호"
"""
import io
import base64
import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime.datetime:
    """서버(Streamlit Cloud 등)는 보통 UTC로 돌아서 datetime.now()를 그냥 쓰면 시간이
    9시간 어긋난다. 제출시각·문의등록시각 등 사람이 보는 시간은 항상 이 함수로 구한다."""
    return datetime.datetime.now(KST)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

# Cloud Vision API(서류 텍스트 인식, 무료 티어: 월 1,000건까지) 접근 범위.
# 시트에 쓰는 서비스 계정 키를 그대로 재사용하되, 이 스코프만 추가로 받아서 쓴다.
VISION_SCOPES = [
    "https://www.googleapis.com/auth/cloud-vision",
]

# 드라이브는 "이 앱이 만든 파일에만 접근" 범위로 최소화 (내 드라이브 전체 접근 아님)
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
]

WORKSHEET_NAME = "지원자"

# 시트 컬럼 순서 (이 순서가 곧 구글시트의 실제 열 순서가 됩니다)
HEADERS = [
    "접수번호", "제출일시", "프로그램구분",
    "성명_한글", "성명_영문", "생년월일", "성별", "휴대폰번호", "이메일",
    "희망지도교수_1지망", "희망지도교수_2지망",
    "학교명", "전공명", "입학연월", "학년학기", "만점기준", "평점",
    "편입_전적학교", "편입_전공", "편입_입학연월", "편입_만점기준", "편입_평점",
    "대학군", "4.3환산", "환산성적",
    "관심분야", "대학원진학희망", "희망과정", "기숙사사용", "지원동기",
    "성적증명서_링크", "재학증명서_링크", "기타자료_링크", "증명사진_링크",
    "개인정보_필수", "개인정보_선택",
    "서류합격여부", "1지망선발여부", "비고",
    "편입_대학군", "편입_4.3환산", "편입_환산성적",  # 기존 행들의 열 위치가 밀리지 않도록 맨 끝에 추가
    "서류확인_AI",
]


@st.cache_resource(show_spinner=False)
def _get_creds():
    """구글시트 접근용 (서비스 계정)."""
    info = dict(st.secrets["gcp_service_account"])
    return Credentials.from_service_account_info(info, scopes=SCOPES)


@st.cache_resource(show_spinner=False)
def _get_gc():
    return gspread.authorize(_get_creds())


@st.cache_resource(show_spinner=False)
def _get_vision_creds():
    info = dict(st.secrets["gcp_service_account"])
    return Credentials.from_service_account_info(info, scopes=VISION_SCOPES)


@st.cache_resource(show_spinner=False)
def _get_vision_service():
    from googleapiclient.discovery import build as _build
    return _build("vision", "v1", credentials=_get_vision_creds(), cache_discovery=False)


def ocr_document_text(file_bytes: bytes, filename: str) -> str:
    """서류 파일(이미지 또는 PDF)에서 글자를 인식해서 텍스트로 반환한다 (Google Cloud Vision,
    무료 티어). 사진으로 찍어 올린 서류도 인식된다. 인식 실패/오류 시 빈 문자열을 반환한다."""
    service = _get_vision_service()
    is_pdf = filename.lower().endswith(".pdf")
    b64 = base64.b64encode(file_bytes).decode()
    try:
        if is_pdf:
            # PDF는 파일 단위 인식(files.annotate)을 쓴다. 동기 처리는 최대 5페이지까지 지원.
            body = {
                "requests": [{
                    "inputConfig": {"content": b64, "mimeType": "application/pdf"},
                    "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                    "pages": [1, 2, 3, 4, 5],
                }]
            }
            resp = service.files().annotate(body=body).execute()
            pages = resp.get("responses", [{}])[0].get("responses", [])
            texts = [p.get("fullTextAnnotation", {}).get("text", "") for p in pages]
            return "\n".join(t for t in texts if t)
        else:
            body = {"requests": [{"image": {"content": b64},
                                   "features": [{"type": "DOCUMENT_TEXT_DETECTION"}]}]}
            resp = service.images().annotate(body=body).execute()
            return resp.get("responses", [{}])[0].get("fullTextAnnotation", {}).get("text", "")
    except Exception as e:
        return f"[인식 실패: {e}]"


@st.cache_resource(show_spinner=False)
def _get_drive_creds():
    """구글드라이브 접근용 (담당자 개인 계정, OAuth refresh token 사용)."""
    o = st.secrets["google_oauth"]
    return UserCredentials(
        token=None,
        refresh_token=o["refresh_token"],
        client_id=o["client_id"],
        client_secret=o["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=DRIVE_SCOPES,
    )


@st.cache_resource(show_spinner=False)
def _get_drive():
    return build("drive", "v3", credentials=_get_drive_creds())



def _get_worksheet():
    gc = _get_gc()
    sh = gc.open_by_key(st.secrets["app"]["sheet_id"])
    try:
        ws = sh.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=2000, cols=len(HEADERS) + 5)
    first_row = ws.row_values(1)
    if first_row != HEADERS:
        ws.update("A1", [HEADERS])
    return ws


@st.cache_data(ttl=20, show_spinner=False)
def read_all_df() -> pd.DataFrame:
    ws = _get_worksheet()
    records = ws.get_all_records()
    if not records:
        return pd.DataFrame(columns=HEADERS)
    df = pd.DataFrame(records)
    for c in HEADERS:
        if c not in df.columns:
            df[c] = ""
    return df[HEADERS]


def clear_cache():
    """지원자 정보를 수정/삭제한 직후 등, 방금 바뀐 내용을 바로 화면에 반영해야 할 때 호출."""
    read_all_df.clear()


def append_applicant(row: dict) -> str:
    """
    지원자 행을 시트에 추가하고, 실제로 저장된 행 위치를 기준으로 접수번호를 확정해서 반환한다.

    기존 방식(제출 전에 '현재까지 몇 명인지 세어서 +1')은 두 학생이 거의 동시에 제출하면
    같은 접수번호가 배정될 수 있는 문제가 있었다. 이 함수는 구글시트 append가 끝난 '이후',
    실제로 배정된 행 번호를 기준으로 접수번호를 매기기 때문에 동시 제출에도 안전하다.
    (구글시트 API의 append는 동시 요청이 와도 서로 다른 행을 순서대로 배정하도록 보장한다.)

    접수번호 형식: "26-008" (연도 뒤 2자리 + 그 회차 안에서의 순번, 3자리).
    '프로그램구분'(예: "2027-WURF")을 기준으로 순번을 매기므로, 접수 시작 연도가 프로그램
    연도와 달라도(예: 2026년 10월에 2027 WURF 접수) 항상 정확한 회차 기준으로 번호가 매겨진다.
    (회차가 순차적으로 진행되는 한, 같은 해에 두 회차가 동시에 겹쳐 접수번호가 헷갈릴 일은 없다.)
    """
    import re
    ws = _get_worksheet()
    round_key = str(row.get("프로그램구분", "")) or now_kst().strftime("%Y") + "-X"
    yr_part, _, _short_part = round_key.partition("-")
    prefix = yr_part[-2:] or now_kst().strftime("%y")
    values = [str(row.get(h, "")) for h in HEADERS]
    resp = ws.append_row(values, value_input_option="USER_ENTERED")

    receipt_no = row.get("접수번호", "")
    updated_range = (resp or {}).get("updates", {}).get("updatedRange", "")
    m = re.search(r"![A-Z]+(\d+)", updated_range)
    if m:
        row_idx = int(m.group(1))
        round_col = HEADERS.index("프로그램구분") + 1
        # 헤더(1행) 다음부터, 방금 저장된 이 행까지의 '프로그램구분' 값을 읽어 같은 회차만 센다.
        # append가 끝난 시점에는 이 행 값도 이미 저장돼 있으므로 동시 제출이어도 안전하게 카운트된다.
        rounds_so_far = ws.col_values(round_col)[1:row_idx]
        seq = sum(1 for r in rounds_so_far if str(r) == round_key) or 1
        receipt_no = f"{prefix}-{seq:03d}"
        ws.update_cell(row_idx, HEADERS.index("접수번호") + 1, receipt_no)
    return receipt_no


def update_fields(receipt_no: str, updates: dict):
    """접수번호로 행을 찾아 지정된 컬럼들만 갱신."""
    ws = _get_worksheet()
    cell = ws.find(str(receipt_no), in_column=HEADERS.index("접수번호") + 1)
    if cell is None:
        raise ValueError(f"접수번호 {receipt_no} 를 찾을 수 없습니다.")
    row_idx = cell.row
    for key, val in updates.items():
        if key not in HEADERS:
            continue
        col_idx = HEADERS.index(key) + 1
        ws.update_cell(row_idx, col_idx, str(val))


# ── 구글드라이브 파일 저장 ──────────────────────────────────────────

def _with_retry(func, tries: int = 3):
    """구글 API 호출 중 가끔 생기는 일시적 네트워크 끊김(BrokenPipeError 등)을 흡수한다.
    잠깐 쉬었다가 최대 tries번까지 자동으로 다시 시도. 다운로드뿐 아니라 폴더 생성/파일
    업로드 쪽에서도 같은 종류의 오류가 나서, 아예 공용 함수로 뺐다."""
    import time
    last_err = None
    for attempt in range(tries):
        try:
            return func()
        except (BrokenPipeError, ConnectionError, OSError) as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise last_err


def _find_or_create_subfolder(name: str, parent_id: str) -> str:
    drive = _get_drive()
    q = (f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' "
         f"and '{parent_id}' in parents and trashed = false")
    res = _with_retry(lambda: drive.files().list(
        q=q, fields="files(id, name)",
        supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="allDrives"
    ).execute())
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    folder = _with_retry(lambda: drive.files().create(body=meta, fields="id", supportsAllDrives=True).execute())
    return folder["id"]


def upload_applicant_file(round_name: str, applicant_folder_name: str, filename: str,
                           file_bytes: bytes, mimetype: str) -> str:
    """구글드라이브 [최상위 폴더]/[회차 폴더]/[지원자 폴더]/파일 구조로 업로드 후 webViewLink 반환."""
    drive = _get_drive()
    root_id = st.secrets["app"]["drive_folder_id"]
    round_id = _find_or_create_subfolder(round_name, root_id)
    folder_id = _find_or_create_subfolder(applicant_folder_name, round_id)
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mimetype, resumable=False)
    meta = {"name": filename, "parents": [folder_id]}
    f = _with_retry(lambda: drive.files().create(
        body=meta, media_body=media, fields="id, webViewLink", supportsAllDrives=True).execute())
    return f.get("webViewLink", "")


def download_file_bytes_from_link(view_link: str) -> bytes:
    """webViewLink (또는 file id)로부터 파일 바이트 다운로드.
    가끔 네트워크가 순간적으로 끊기면서(BrokenPipeError 등) 실패하는 경우가 있어,
    그런 일시적인 오류는 잠깐 쉬었다가 최대 3번까지 자동으로 다시 시도한다."""
    import time
    drive = _get_drive()
    file_id = view_link
    if "/d/" in view_link:
        file_id = view_link.split("/d/")[1].split("/")[0]
    from googleapiclient.http import MediaIoBaseDownload

    last_err = None
    for attempt in range(3):
        try:
            request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return buf.getvalue()
        except (BrokenPipeError, ConnectionError, OSError) as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise last_err


def get_file_name_from_link(view_link: str) -> str:
    drive = _get_drive()
    file_id = view_link
    if "/d/" in view_link:
        file_id = view_link.split("/d/")[1].split("/")[0]
    meta = drive.files().get(fileId=file_id, fields="name", supportsAllDrives=True).execute()
    return meta.get("name", "file")


# ── 연도별 아카이브 / 삭제 (용량 관리 + 개인정보 보유기간 준수) ──────

def _parent_folder_id_from_link(view_link: str):
    """파일 링크로부터 그 파일이 들어있는 (지원자) 폴더의 id를 역으로 찾는다.
    폴더 이름 규칙이 바뀌어도 항상 정확하게 동작한다 (이름으로 재구성하지 않음)."""
    drive = _get_drive()
    file_id = view_link
    if "/d/" in view_link:
        file_id = view_link.split("/d/")[1].split("/")[0]
    meta = drive.files().get(fileId=file_id, fields="parents", supportsAllDrives=True).execute()
    parents = meta.get("parents") or []
    return parents[0] if parents else None


def trash_applicant_folder_by_row(row: dict):
    """행에 저장된 파일 링크를 이용해 그 지원자의 폴더를 찾아 휴지통으로 이동
    (30일간 복구 가능, 완전삭제 아님)."""
    drive = _get_drive()
    for col in ["성적증명서_링크", "재학증명서_링크", "증명사진_링크"]:
        link = row.get(col, "")
        if not link:
            continue
        folder_id = _parent_folder_id_from_link(link)
        if folder_id:
            drive.files().update(fileId=folder_id, body={"trashed": True}, supportsAllDrives=True).execute()
            return


def delete_applicant_row(receipt_no: str):
    """시트에서 해당 접수번호 행을 삭제."""
    ws = _get_worksheet()
    cell = ws.find(str(receipt_no), in_column=HEADERS.index("접수번호") + 1)
    if cell is not None:
        ws.delete_rows(cell.row)


def archive_and_delete_round(df: "pd.DataFrame", round_key: str, progress_cb=None):
    """
    지정한 회차('프로그램구분' 값, 예: "2027-WURF")의 지원자 전체를
    - 구글드라이브 폴더는 휴지통으로 이동
    - 구글시트 행은 삭제
    (호출 전에 반드시 UI에서 백업 ZIP을 먼저 다운로드하도록 안내할 것)
    """
    targets = df[df["프로그램구분"].astype(str) == round_key]
    # 시트 행 인덱스가 삭제할수록 밀리므로, 접수번호가 큰 것부터(뒤에서부터) 처리
    targets = targets.sort_values("접수번호", ascending=False)
    total = len(targets)
    for i, (_, row) in enumerate(targets.iterrows()):
        trash_applicant_folder_by_row(row.to_dict())
        delete_applicant_row(row["접수번호"])
        if progress_cb:
            progress_cb(i + 1, total)
    return total


# ── FAQ · Q&A 문의 게시판 (별도 워크시트) ────────────────────────────
QNA_WORKSHEET_NAME = "문의"
QNA_HEADERS = ["id", "등록일시", "이름", "비밀번호", "질문", "답변", "답변여부"]

SUB_WORKSHEET_NAME = "소식구독"
SUB_HEADERS = ["등록일시", "이메일", "연구참여소식", "입시정보"]


def _get_qna_worksheet():
    gc = _get_gc()
    sh = gc.open_by_key(st.secrets["app"]["sheet_id"])
    try:
        ws = sh.worksheet(QNA_WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=QNA_WORKSHEET_NAME, rows=1000, cols=len(QNA_HEADERS) + 2)
    first_row = ws.row_values(1)
    if first_row != QNA_HEADERS:
        ws.update("A1", [QNA_HEADERS])
    return ws


def read_all_questions() -> pd.DataFrame:
    ws = _get_qna_worksheet()
    records = ws.get_all_records()
    if not records:
        return pd.DataFrame(columns=QNA_HEADERS)
    df = pd.DataFrame(records)
    for c in QNA_HEADERS:
        if c not in df.columns:
            df[c] = ""
    return df[QNA_HEADERS]


def append_question(name: str, pw: str, text: str) -> str:
    """질문 등록. 고유 id(문자열, 타임스탬프 기반)를 반환."""
    ws = _get_qna_worksheet()
    qid = now_kst().strftime("%Y%m%d%H%M%S%f")
    now = now_kst().strftime("%Y-%m-%d %H:%M")
    ws.append_row([qid, now, name or "익명", pw, text, "", "N"], value_input_option="USER_ENTERED")
    return qid


def answer_question(qid: str, answer_text: str):
    """관리자 답변 등록."""
    ws = _get_qna_worksheet()
    cell = ws.find(str(qid), in_column=QNA_HEADERS.index("id") + 1)
    if cell is None:
        raise ValueError(f"문의 id {qid} 를 찾을 수 없습니다.")
    row_idx = cell.row
    ws.update_cell(row_idx, QNA_HEADERS.index("답변") + 1, answer_text)
    ws.update_cell(row_idx, QNA_HEADERS.index("답변여부") + 1, "Y")


def edit_question(qid: str, new_text: str):
    """본인 확인(비밀번호)이 끝난 지원자가 자기 문의 내용을 고칠 때 사용."""
    ws = _get_qna_worksheet()
    cell = ws.find(str(qid), in_column=QNA_HEADERS.index("id") + 1)
    if cell is None:
        raise ValueError(f"문의 id {qid} 를 찾을 수 없습니다.")
    ws.update_cell(cell.row, QNA_HEADERS.index("질문") + 1, new_text)


def delete_question(qid: str):
    ws = _get_qna_worksheet()
    cell = ws.find(str(qid), in_column=QNA_HEADERS.index("id") + 1)
    if cell is not None:
        ws.delete_rows(cell.row)


# ── 소식 구독 (홈 화면의 별도 구독 신청 — 지원서와 무관) ──────────────────
def _get_sub_worksheet():
    gc = _get_gc()
    sh = gc.open_by_key(st.secrets["app"]["sheet_id"])
    try:
        ws = sh.worksheet(SUB_WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=SUB_WORKSHEET_NAME, rows=1000, cols=len(SUB_HEADERS) + 2)
    first_row = ws.row_values(1)
    if first_row != SUB_HEADERS:
        ws.update("A1", [SUB_HEADERS])
    return ws


def add_subscriber(email: str, news_research: bool, news_admission: bool):
    """홈 화면 '소식 받기' 신청을 시트에 기록한다."""
    ws = _get_sub_worksheet()
    now = now_kst().strftime("%Y-%m-%d %H:%M")
    ws.append_row(
        [now, email, "Y" if news_research else "N", "Y" if news_admission else "N"],
        value_input_option="USER_ENTERED",
    )


@st.cache_data(ttl=20, show_spinner=False)
def read_all_subscribers() -> pd.DataFrame:
    """관리자 화면에서 '소식 받기' 신청자 목록을 볼 때 사용."""
    ws = _get_sub_worksheet()
    records = ws.get_all_records()
    if not records:
        return pd.DataFrame(columns=SUB_HEADERS)
    df = pd.DataFrame(records)
    for c in SUB_HEADERS:
        if c not in df.columns:
            df[c] = ""
    return df[SUB_HEADERS]


def send_notification_email(to_addr: str, subject: str, body: str):
    """문의글이 새로 등록되면 관리자 이메일로 알려준다.
    Gmail SMTP + 앱 비밀번호 방식을 쓴다 — 드라이브 업로드용 OAuth에 메일 발송 권한까지
    새로 추가하면 다시 동의 화면을 거쳐야 해서, 완전히 독립적인 더 간단한 방식을 쓰는 것.
    (secrets의 [smtp] sender_email / app_password 가 필요 — SETUP_GUIDE.md 참고)
    설정이 없거나 실패하면 예외를 그대로 올린다 — 호출부에서 부가 기능으로 취급해 처리할 것."""
    import smtplib
    from email.mime.text import MIMEText

    smtp_cfg = st.secrets.get("smtp", {})
    sender = smtp_cfg.get("sender_email")
    app_pw = smtp_cfg.get("app_password")
    if not sender or not app_pw:
        raise RuntimeError("SMTP 설정(secrets의 [smtp] 섹션)이 없습니다.")

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_addr
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, app_pw)
        server.sendmail(sender, [to_addr], msg.as_string())

