# -*- coding: utf-8 -*-
"""
대학군 분류 + 환산성적(등급) 계산 로직.
- 기존 app.py에 있던 UNIVERSITY_GROUPS / GRADE_THRESHOLDS 로직을 그대로 가져와 정리했습니다.
- 이 파일은 순수 계산 함수만 담당하므로, 학교 목록/기준표가 바뀌면 이 파일만 고치면 됩니다.
"""
import re

# ── 참여 교수진 (연구실) ─────────────────────────────────────────────
LABS = {
    "유기화학": [
        {"name": "이영호", "lab": "유기합성화학 연구실", "url": "https://yhr.postech.ac.kr/"},
        {"name": "장영태", "lab": "센서와 분자영상 연구실", "url": "http://ytchang.postech.ac.kr/"},
        {"name": "조승환", "lab": "촉매유기반응 연구실", "url": "http://chogroup.postech.ac.kr/"},
        {"name": "지형민", "lab": "유기합성반응 연구실", "url": "http://chi.postech.ac.kr"},
        {"name": "김현우", "lab": "지속가능 유기반응 연구실", "url": "https://scns.postech.ac.kr"},
    ],
    "무기화학": [
        {"name": "최희철", "lab": "나노재료화학 연구실", "url": "https://www.nmrl.postech.ac.kr/"},
        {"name": "이인수", "lab": "나노입자재료 연구실", "url": "http://npml.postech.ac.kr"},
        {"name": "서대하", "lab": "시스템 나노의학 및 세포 이미징 연구실", "url": "http://small.postech.ac.kr"},
    ],
    "물리화학": [
        {"name": "주태하", "lab": "극초고속 동력학 연구실", "url": "http://femto.postech.ac.kr"},
        {"name": "김성지", "lab": "나노광학 & 나노의학 연구실", "url": "http://www.nanotrio.com"},
        {"name": "심지훈", "lab": "재료설계 이론 연구실", "url": "http://dmft.postech.ac.kr"},
        {"name": "류순민", "lab": "나노물질 분광학 연구실", "url": "http://sunryu.postech.ac.kr/"},
        {"name": "김경환", "lab": "X-선 회절 및 분광학 연구실", "url": "https://www.xlcr.postech.ac.kr/"},
    ],
    "분석화학": [
        {"name": "서종철", "lab": "분자집합체 구조화학 연구실", "url": "http://scimms.postech.ac.kr"},
        {"name": "최창혁", "lab": "전기촉매반응 연구실", "url": "https://www.ecatlab.com/"},
    ],
    "고분자화학": [
        {"name": "김원종", "lab": "의료용 고분자 연구실", "url": "http://bmpl.postech.ac.kr"},
        {"name": "박문정", "lab": "에너지 나노재료 연구실", "url": "https://parkgroup.postech.ac.kr/Parkgroup/index.do"},
        {"name": "박수진", "lab": "고분자기반 에너지 소재 연구실", "url": "http://nfmspark.wixsite.com/nfmspark"},
    ],
    "생화학": [
        {"name": "임현석", "lab": "화학생물학 연구실", "url": "http://cbl.postech.ac.kr"},
        {"name": "권도훈", "lab": "구조생화학 연구실", "url": "https://kwonlab.postech.ac.kr/home"},
    ],
}
PROFESSORS = sorted([f"{p['name']} 교수님({p['lab']})" for labs in LABS.values() for p in labs])

# 분야(유기화학/무기화학/...)별로 묶고, 각 분야 안에서는 이름 가나다순으로 정렬한 선택 목록.
# 분야 제목 줄("── 유기화학 ──")은 실제로 고를 수 없는 구분선 역할만 한다 (is_group_header로 구분).
PROFESSORS_GROUPED = []
for _field in sorted(LABS.keys()):
    PROFESSORS_GROUPED.append(f"── {_field} ──")
    PROFESSORS_GROUPED.extend(sorted(f"{p['name']} 교수님({p['lab']})" for p in LABS[_field]))


def is_group_header(x) -> bool:
    """드롭다운의 분야 제목 줄(구분선)인지 확인 — 실수로 이걸 선택하면 안 되므로 검증에 쓴다."""
    s = str(x)
    return s.startswith("── ") and s.endswith(" ──")

# ── 대학별 그룹 분류 ────────────────────────────────────────────────
UNIVERSITY_GROUPS = {
    "A": ["POSTECH", "포스텍", "포항공과대학교", "포항공대", "서울대학교", "서울대", "KAIST", "카이스트", "한국과학기술원"],
    "B+": ["고려대학교", "고려대", "연세대학교", "연세대"],
    "B0": ["한양대학교", "한양대", "이화여자대학교", "이화여대", "서강대학교", "서강대", "성균관대학교", "성균관대", "UNIST", "유니스트", "울산과학기술원"],
    "B-": ["한국교원대학교", "한국교원대", "중앙대학교", "중앙대", "광주과학기술원", "광주과기원", "GIST", "지스트", "대구경북과학기술원", "DGIST", "디지스트"],
    "C+": ["서울시립대학교", "서울시립대", "경희대학교", "경희대", "건국대학교", "건국대"],
    "C0": ["부산대학교", "부산대", "동국대학교", "동국대", "숙명여자대학교", "숙명여대", "경북대학교", "경북대", "아주대학교", "아주대", "서울과학기술대학교", "서울과기대", "인하대학교", "인하대", "단국대학교", "단국대"],
    "D": ["삼육대학교", "삼육대", "덕성여자대학교", "덕성여대", "광운대학교", "광운대", "숭실대학교", "숭실대", "국민대학교", "국민대", "서울여자대학교", "서울여대", "성신여자대학교", "성신여대", "전남대학교", "전남대", "충남대학교", "충남대", "한양대학교 ERICA", "한양대 ERICA", "한양대학교 에리카", "한양대 에리카", "세종대학교", "세종대", "동덕여자대학교", "동덕여대", "가톨릭대학교", "가톨릭대"],
    "E": ["명지대학교", "명지대", "상명대학교", "상명대", "경기대학교", "경기대", "가천대학교", "가천대", "인천대학교", "인천대", "단국대학교 천안", "단국대 천안"],
    "F": ["부경대학교", "부경대", "국립부경대학교", "충북대학교", "충북대", "강원대학교", "강원대", "고려대학교 세종", "고려대 세종", "인제대학교", "인제대", "수원대학교", "수원대", "영남대학교", "영남대", "동아대학교", "동아대", "울산대학교", "울산대", "조선대학교", "조선대", "창원대학교", "창원대", "계명대학교", "계명대", "경상국립대학교", "국립경상대학교", "경상대학교", "경상대"],
    "G": ["경성대학교", "경성대", "동의대학교", "동의대", "동국대학교 경주", "동국대 경주", "군산대학교", "군산대", "원광대학교", "원광대", "공주대학교", "공주대", "제주대학교", "제주대", "신라대학교", "신라대", "금오공과대학교", "금오공대", "한림대학교", "한림대", "순천향대학교", "순천향대", "목포대학교", "목포대", "한남대학교", "한남대", "순천대학교", "순천대", "대전대학교", "대전대", "한서대학교", "한서대", "강릉원주대학교", "강릉원주대", "국립강릉원주대학교", "건양대학교", "건양대", "중원대학교", "중원대", "선문대학교", "선문대", "경일대학교", "경일대", "청주대학교", "청주대", "안동대학교", "안동대", "경남대학교", "경남대", "전북대학교", "전북대"],
}

# ── 대학군별 성적 → 등급 환산 기준표 ───────────────────────────────
GRADE_THRESHOLDS = {
    "A": [("A+", 3.4), ("A0", 3.1), ("A-", 2.8), ("B+", 2.5), ("B0", 2.2), ("B-", 1.9)],
    "B+": [("A+", 3.7), ("A0", 3.4), ("A-", 3.1), ("B+", 2.8), ("B0", 2.5), ("B-", 2.2)],
    "B0": [("A+", 3.8), ("A0", 3.5), ("A-", 3.2), ("B+", 2.9), ("B0", 2.6), ("B-", 2.3)],
    "B-": [("A+", 3.9), ("A0", 3.6), ("A-", 3.3), ("B+", 3.0), ("B0", 2.7), ("B-", 2.4)],
    "C+": [("A+", 4.1), ("A0", 3.8), ("A-", 3.5), ("B+", 3.2), ("B0", 2.9), ("B-", 2.6)],
    "C0": [("A+", 4.2), ("A0", 3.9), ("A-", 3.6), ("B+", 3.3), ("B0", 3.0), ("B-", 2.7)],
    "D": [("A+", 4.3), ("A0", 4.0), ("A-", 3.7), ("B+", 3.4), ("B0", 3.1), ("B-", 2.8)],
    "E": [("A0", 4.3), ("A-", 4.1), ("B+", 3.8), ("B0", 3.5), ("B-", 3.2), ("C+", 2.9), ("C0", 2.6), ("C-", 2.3)],
    "F": [("A-", 4.3), ("B+", 4.1), ("B0", 3.8), ("B-", 3.5), ("C+", 3.2), ("C0", 2.9), ("C-", 2.6)],
    "G": [("B+", 4.3), ("B0", 4.1), ("B-", 3.7), ("C+", 3.4), ("C0", 3.1), ("C-", 2.8)],
}
GRADE_ORDER = {"A+": 1, "A0": 2, "A-": 3, "B+": 4, "B0": 5, "B-": 6, "C+": 7, "C0": 8, "C-": 9,
               "C+~": 10, "C- 미만": 11, "환산불가": 99}
GROUP_ORDER = {"A": 1, "B+": 2, "B0": 3, "B-": 4, "C+": 5, "C0": 6, "D": 7, "E": 8, "F": 9, "G": 10, "환산불가": 99}

# 서류 합격 컷 (환산성적 이 등급까지 통과). GRADE_ORDER 값 기준 <= 이 값이면 합격.
PASS_CUTOFF_GRADE = "B-"


def norm(x):
    return re.sub(r"\s+", "", str(x)).lower()


def get_group(school):
    s = norm(school)
    if not s:
        return "환산불가"
    items = [(len(norm(n)), g, norm(n)) for g, ns in UNIVERSITY_GROUPS.items() for n in ns]
    for _, g, n in sorted(items, reverse=True):
        if n and n in s:
            return g
    return "환산불가"


def parse_gpa(x):
    try:
        t = str(x).strip().replace(" ", "")
        if t in ["", "미산출", "환산불가", "nan", "None"]:
            return None
        return float(t)
    except Exception:
        return None


def to43(gpa, scale):
    v = parse_gpa(gpa)
    if v is None:
        return None
    return round(v * 4.3 / 4.5, 3) if "4.5" in str(scale) else round(v, 3)


def get_grade(group, score):
    if group not in GRADE_THRESHOLDS or score is None:
        return "환산불가"
    for grade, th in GRADE_THRESHOLDS[group]:
        if score >= th:
            return grade
    return "C+~" if group in ["A", "B+", "B0", "B-", "C+", "C0", "D"] else "C- 미만"


def compute_score(school, scale, gpa):
    """학교명/만점기준/평점 -> (대학군, 4.3환산, 환산성적등급) 계산."""
    group = get_group(school)
    score43 = to43(gpa, scale)
    grade = get_grade(group, score43)
    return group, score43, grade


def is_document_pass(grade):
    """서류합격 여부: 환산성적 등급이 PASS_CUTOFF_GRADE 이상이면 합격."""
    order = GRADE_ORDER.get(grade, 99)
    cutoff = GRADE_ORDER.get(PASS_CUTOFF_GRADE, 6)
    return order <= cutoff


def doc_status(grade):
    """서류상태: '합격' / '미달' / '환산불가' 3단계로 구분."""
    if grade == "환산불가":
        return "환산불가"
    return "합격" if is_document_pass(grade) else "미달"


def safe_name(x):
    return re.sub(r'[\\/:*?"<>|]', "_", str(x).strip()) or "unknown"


def check_document_text(ocr_text: str, school: str, gpa: str, check_gpa: bool = True) -> list:
    """OCR로 인식한 서류 텍스트 안에 학생이 입력한 학교명·평점이 실제로 등장하는지
    가볍게 점검한다. 완벽한 서류 검증이 아니라 '한 번 더 확인해볼 만한 부분'을 짚어주는
    용도라, 결과는 참고용 안내 메시지 목록으로 반환한다 (빈 목록이면 특이사항 없음).
    check_gpa=False로 두면 평점은 검사하지 않는다 — 재학증명서에는 평점이 안 나오므로,
    성적증명서를 검사할 때만 True로 넘겨야 한다."""
    notes = []
    text = str(ocr_text or "")
    if not text.strip() or text.startswith("[인식 실패"):
        notes.append("서류에서 글자를 인식하지 못했어요 (사진이 흐리거나 형식이 특이할 수 있어요).")
        return notes

    norm_text = re.sub(r"\s+", "", text)

    school_key = re.sub(r"\s+", "", str(school or "").replace("대학교", "").replace("대학", ""))
    if school_key and school_key not in norm_text:
        notes.append(f"서류 안에서 '{school}' 표기를 찾지 못했어요 — 학교명을 다시 확인해보세요.")

    gpa_str = str(gpa or "").strip()
    if check_gpa and gpa_str:
        try:
            gpa_val = float(gpa_str)
            # 소수점 표기가 조금 다를 수 있어(3.85 vs 3.850 등) 정수부.소수1~2자리 정도로 느슨하게 찾는다.
            candidates = {f"{gpa_val:.1f}", f"{gpa_val:.2f}", gpa_str}
            if not any(c in text for c in candidates):
                notes.append(f"서류 안에서 입력하신 평점 '{gpa_str}'과 일치하는 숫자를 찾지 못했어요.")
        except ValueError:
            pass
    return notes


def check_documents_combined(texts_by_label: dict, school: str, gpa: str) -> list:
    """성적증명서·재학증명서 등 여러 서류의 OCR 텍스트를 한꺼번에 놓고 검사한다.
    학교명은 어느 서류에든 한 군데라도 있으면 통과로 보고(성적증명서에만 있거나
    재학증명서에만 있어도 문제로 안 잡는다), 평점은 texts_by_label의 '성적증명서'
    항목에서만 확인한다. texts_by_label 예: {'성적증명서': '...', '재학증명서': '...'}
    (성적증명서가 여러 장이면 미리 합쳐서 한 문자열로 넣으면 된다)."""
    notes = []
    all_text = "\n".join(t for t in texts_by_label.values() if t)
    all_failed = all((not t) or str(t).startswith("[인식 실패") for t in texts_by_label.values())
    if not all_text.strip() or all_failed:
        notes.append("서류에서 글자를 인식하지 못했어요 (사진이 흐리거나 형식이 특이할 수 있어요).")
        return notes

    norm_all = re.sub(r"\s+", "", all_text)
    school_key = re.sub(r"\s+", "", str(school or "").replace("대학교", "").replace("대학", ""))
    if school_key and school_key not in norm_all:
        notes.append(f"제출하신 서류들에서 '{school}' 표기를 찾지 못했어요 — 학교명을 다시 확인해보세요.")

    gpa_str = str(gpa or "").strip()
    transcript_text = str(texts_by_label.get("성적증명서", ""))
    if gpa_str and transcript_text:
        try:
            gpa_val = float(gpa_str)
            candidates = {f"{gpa_val:.1f}", f"{gpa_val:.2f}", gpa_str}
            if not any(c in transcript_text for c in candidates):
                notes.append(f"성적증명서에서 입력하신 평점 '{gpa_str}'과 일치하는 숫자를 찾지 못했어요.")
        except ValueError:
            pass
    return notes
