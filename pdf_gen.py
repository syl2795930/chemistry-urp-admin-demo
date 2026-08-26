# -*- coding: utf-8 -*-
"""
지원자 데이터 -> 지원서 PDF 자동 생성 (구글 스튜디오 대체)
+ 성적증명서/재학증명서 등과 합쳐서 지원자 1인당 PDF 1개로 병합
+ 교수님별 ZIP 묶기
"""
import io
import zipfile
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from pypdf import PdfReader, PdfWriter

# 한글 출력을 위한 내장 CID 폰트 등록 (별도 폰트파일 불필요)
pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
FONT = "HYSMyeongJo-Medium"


def _styles():
    ss = getSampleStyleSheet()
    normal = ParagraphStyle("normal_kr", parent=ss["Normal"], fontName=FONT, fontSize=10, leading=14, wordWrap="CJK")
    title = ParagraphStyle("title_kr", parent=ss["Title"], fontName=FONT, fontSize=16, leading=20, wordWrap="CJK")
    heading = ParagraphStyle("heading_kr", parent=ss["Heading2"], fontName=FONT, fontSize=12, leading=16, wordWrap="CJK")
    return normal, title, heading


def generate_application_pdf(data: dict, photo_bytes: bytes = None, show_receipt_no: bool = True) -> bytes:
    """지원자 dict -> 지원서 표지 PDF(bytes) 생성. (담당자 제공 예시 서식을 최대한 따름)"""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm,
                             leftMargin=15 * mm, rightMargin=15 * mm)
    normal, title, heading = _styles()
    small = ParagraphStyle("small_kr", parent=normal, fontSize=8, leading=11, wordWrap="CJK")
    center = ParagraphStyle("center_kr", parent=normal, alignment=1, wordWrap="CJK")
    right = ParagraphStyle("right_kr", parent=normal, alignment=2, wordWrap="CJK")

    program_name = "2026년도 하계 우수대학원생유치프로그램 연구참여 지원서"
    story = []

    story.append(Paragraph(program_name, title))
    if show_receipt_no:
        story.append(Paragraph(f"접수번호 : {data.get('접수번호') or '-'}", right))
    story.append(Spacer(1, 10))

    def p(txt):
        return Paragraph(str(txt) if txt not in (None, "", "nan") else "-", normal)

    photo_cell = p("사 진\n(3.5*4.5)")
    if photo_bytes:
        try:
            img = Image(io.BytesIO(photo_bytes), width=32 * mm, height=42 * mm)
            photo_cell = img
        except Exception:
            pass

    gpa_str = f"{data.get('평점', '-')} / {data.get('만점기준', '-')}"
    t_school = data.get("편입_전적학교", "")
    is_transfer = bool(str(t_school).strip())
    t_admit_ym = data.get("편입_입학연월", "-") if is_transfer else "-"
    t_major = data.get("편입_전공", "-") if is_transfer else "-"
    t_gpa_str = (f"{data.get('편입_평점', '-')} / {data.get('편입_만점기준', '-')}"
                 if is_transfer else "-")

    # ── 지원자 정보 표 ──
    # - 1지망/2지망 교수님은 이름+연구실명이 길어서 같은 줄에 나란히 두면 읽기 불편하므로 각자 줄에,
    #   대신 값 칸을 넓게(오른쪽 칸까지) 병합해서 한 줄에 최대한 담기게 한다.
    # - 전공명/평점처럼 내용이 짧은 항목은 각자 풀로우로 비워두지 않고 같은 줄에 나란히 배치한다.
    info_data = [
        [p("지원자"), p("성 명(한글)"), p(data.get("성명_한글")), p("성 별"), p(data.get("성별")), photo_cell],
        ["", p("성 명(영문)"), p(data.get("성명_영문")), p("생년월일"), p(data.get("생년월일")), ""],
        [p("지원 교수님\n및 연구실명"), p("1 지 망"), p(data.get("희망지도교수_1지망")), "", "", ""],
        ["", p("2 지 망"), p(data.get("희망지도교수_2지망")), "", "", ""],
        [p("학 력"), p("입학연월"), p(data.get("입학연월")), p("학교명"), p(data.get("학교명")), ""],
        ["", p("전공명"), p(data.get("전공명")), p("평점/만점"), p(gpa_str), ""],
        [p("편입 시\n전적대학"), p("입학연월"), p(t_admit_ym), p("학교명"), p(t_school if is_transfer else "-"), ""],
        ["", p("전공명"), p(t_major), p("평점/만점"), p(t_gpa_str), ""],
    ]
    t = Table(info_data, colWidths=[26 * mm, 24 * mm, 38 * mm, 24 * mm, 36 * mm, 32 * mm])
    t.setStyle(TableStyle([
        ("SPAN", (0, 0), (0, 1)),   # 지원자
        ("SPAN", (5, 0), (5, 7)),  # 사진 (전체 행에 걸쳐 병합)
        ("SPAN", (0, 2), (0, 3)),  # 지원 교수님 및 연구실명 (1지망/2지망 2줄에 걸쳐 병합)
        ("SPAN", (2, 2), (4, 2)),  # 1지망 교수 값 칸을 넓게 병합
        ("SPAN", (2, 3), (4, 3)),  # 2지망 교수 값 칸을 넓게 병합
        ("SPAN", (0, 4), (0, 5)),  # 학력 (2줄에 걸쳐 병합)
        ("SPAN", (0, 6), (0, 7)),  # 편입 시 전적대학 (2줄에 걸쳐 병합)
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (5, 0), (5, 7), "CENTER"),
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("BACKGROUND", (1, 0), (1, -1), colors.whitesmoke),
        ("BACKGROUND", (3, 0), (3, 1), colors.whitesmoke),
        ("BACKGROUND", (3, 4), (3, 7), colors.whitesmoke),
    ]))
    story.append(t)

    # ── 지원동기 / 관심분야 / 대학원진학 / 연락처 / 기숙사 ──
    extra_data = [
        [p("관심분야"), p(data.get("관심분야")), p("대학원 진학\n희망여부"), p(data.get("대학원진학희망"))],
        [p("지원동기"), Paragraph(str(data.get("지원동기", "-")).replace("\n", "<br/>"), small), "", ""],
        [p("연락처"), Paragraph(f"휴대폰: {data.get('휴대폰번호','-')}<br/>E-mail: {data.get('이메일','-')}", normal),
         p("기숙사\n사용여부"), p(data.get("기숙사사용"))],
    ]
    t2 = Table(extra_data, colWidths=[26 * mm, 84 * mm, 30 * mm, 40 * mm])
    t2.setStyle(TableStyle([
        ("SPAN", (1, 1), (3, 1)),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("BACKGROUND", (2, 0), (2, 0), colors.whitesmoke),
        ("BACKGROUND", (2, 2), (2, 2), colors.whitesmoke),
    ]))
    story.append(t2)
    story.append(Spacer(1, 10))

    # ── 개인정보 수집·이용 동의 표 ──
    story.append(Paragraph("■ 개인정보 수집·이용 동의", heading))
    consent_data = [
        [p("수집하는 개인정보"), p("수집목적"), p("보유기간")],
        [Paragraph("성명, 생년월일, 성별, 휴대전화번호, 이메일주소, 희망지도교수, 학사 학교명·전공명·학년 학기·"
                   "기준평점·평점(편입생의 경우 전적학교 정보 포함), 자기소개 및 지원동기, 생활관 사용 여부, "
                   "증명사진, 성적증명서·재학증명서·기타 증빙 서류", small),
         p("연구참여\n프로그램 운영"), p("1년")],
    ]
    t3 = Table(consent_data, colWidths=[112 * mm, 34 * mm, 34 * mm])
    t3.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
    ]))
    story.append(t3)
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "※ 개인정보 수집·이용에 대한 동의를 거부할 권리가 있습니다. 다만 동의를 거부할 경우 "
        "연구참여 프로그램 신청에 제한을 받습니다.", small))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"개인정보 수집·이용 동의 : {data.get('개인정보_필수', '-')}", normal))
    story.append(Spacer(1, 14))

    # ── 붙임서류 안내 ──
    attachments = ["1. 성적증명서 1부(PDF)", "2. 재학증명서 1부(PDF)"]
    n = 3
    if str(data.get("기타자료_링크", "")).strip():
        cnt = len([x for x in str(data.get("기타자료_링크", "")).splitlines() if x.strip()])
        if cnt:
            attachments.append(f"{n}. 기타 우수성 입증 증빙 {cnt}부(PDF)")

    story.append(Paragraph(
        f"귀 대학교 {program_name.split('년도')[0]}년 하계 우수대학원생유치프로그램에 "
        "소정의 서류를 갖추어 지원합니다.", normal))
    story.append(Spacer(1, 4))
    story.append(Paragraph("붙임서류 : " + " / ".join(attachments), normal))
    story.append(Spacer(1, 18))
    story.append(Paragraph(str(data.get("제출일시", "-")), center))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"지원자 　{data.get('성명_한글', '-')}　 (인)", center))
    story.append(Spacer(1, 10))
    story.append(Paragraph("포항공과대학교 화학과 귀하", center))

    doc.build(story)
    return buf.getvalue()


def merge_pdfs(pdf_byte_list) -> bytes:
    """여러 PDF(bytes)를 하나로 병합. PDF가 아닌 항목(사진 등)은 무시됨."""
    writer = PdfWriter()
    for b in pdf_byte_list:
        if not b:
            continue
        try:
            reader = PdfReader(io.BytesIO(b))
            for page in reader.pages:
                writer.add_page(page)
        except Exception:
            continue
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def build_zip_for_professor(applicant_pdfs: dict) -> bytes:
    """
    applicant_pdfs: {파일명(예: "홍길동_포항공과대학교.pdf"): pdf_bytes}
    -> 하나의 ZIP(bytes)으로 묶어서 반환
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, pdf_bytes in applicant_pdfs.items():
            zf.writestr(filename, pdf_bytes)
    return buf.getvalue()
