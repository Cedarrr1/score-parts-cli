"""Local checks for generated PDF parts, using PDFium for raster review."""

from __future__ import annotations

import io
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader


A4_WIDTH_PT = 595.276
A4_HEIGHT_PT = 841.890


def finding(code: str, severity: str, message: str, *, page: int | None = None,
            evidence: str = "", source: str = "local") -> dict:
    return {
        "code": code, "severity": severity, "message": message,
        "page": page, "evidence": evidence, "source": source, "resolved": False,
    }


def _ink_bounds(page, width: int = 900):
    page_width, _ = page.get_size()
    picture = page.render(scale=width / page_width).to_pil()
    mask = picture.convert("L").point(lambda value: 255 if value < 245 else 0)
    return mask.getbbox(), picture.size


def check_pdf(path: Path, title: str, instrument: str, expected_measures: int) -> dict:
    result = {"file": str(path), "pages": 0, "expected_measures": expected_measures,
              "paper": "A4", "findings": []}
    issues = result["findings"]
    if expected_measures < 1:
        issues.append(finding("no_measures", "error", "源声部没有小节"))
    try:
        reader = PdfReader(path)
        document = pdfium.PdfDocument(path)
    except Exception as error:
        issues.append(finding("invalid_pdf", "error", "PDF 无法打开", evidence=str(error)))
        return result
    try:
        result["pages"] = len(document)
        if not len(document):
            issues.append(finding("empty_pdf", "error", "PDF 没有页面"))
            return result
        if len(reader.pages) != len(document):
            issues.append(finding("page_count", "error", "PDF 页数读取结果不一致"))
        for index in range(len(document)):
            number = index + 1
            page = document[index]
            width_pt, height_pt = page.get_size()
            if abs(width_pt - A4_WIDTH_PT) > 1 or abs(height_pt - A4_HEIGHT_PT) > 1:
                issues.append(finding("paper_size", "error", "页面不是 A4", page=number,
                                      evidence=f"{width_pt:.1f} × {height_pt:.1f} pt"))
            bounds, image_size = _ink_bounds(page)
            page.close()
            if bounds is None:
                issues.append(finding("blank_page", "error", "页面没有可见内容", page=number))
                continue
            x0, y0, x1, y1 = bounds
            image_width, image_height = image_size
            if min(x0, y0, image_width - x1, image_height - y1) <= 2:
                issues.append(finding("edge_ink", "warning", "页面边缘有内容，检查是否裁切", page=number))
            elif min(x0, image_width - x1) < image_width * 0.025:
                issues.append(finding("tight_margin", "warning", "左右边距较窄，请检查打印效果", page=number))
            if number == len(document) and len(document) > 1 and y1 < image_height * 0.43:
                issues.append(finding("sparse_last_page", "review", "末页内容较少，可检查分页与翻页位置", page=number,
                                      evidence=f"最下方内容位于页面高度的 {y1 / image_height:.0%}"))
            if number < len(document) and y1 > image_height * 0.88:
                issues.append(finding("page_turn_review", "review", "本页谱面接近页底，请人工检查翻页是否方便", page=number,
                                      evidence=f"最下方内容位于页面高度的 {y1 / image_height:.0%}"))
        first_text = reader.pages[0].extract_text() or ""
        if title.casefold() not in first_text.casefold():
            issues.append(finding("missing_title", "warning", "首页未检测到曲名文字", page=1,
                                  evidence=f"期望：{title}"))
        if instrument.casefold() not in first_text.casefold():
            issues.append(finding("missing_part_name", "warning", "首页未检测到声部名", page=1,
                                  evidence=f"期望：{instrument}"))
    finally:
        document.close()
    return result


def render_page_png(path: Path, page_number: int, *, width: int = 1200) -> bytes:
    document = pdfium.PdfDocument(path)
    try:
        if not 1 <= page_number <= len(document):
            raise ValueError(f"Page {page_number} is out of range")
        page = document[page_number - 1]
        page_width, _ = page.get_size()
        picture = page.render(scale=width / page_width).to_pil()
        page.close()
        stream = io.BytesIO()
        picture.save(stream, format="PNG")
        return stream.getvalue()
    finally:
        document.close()
