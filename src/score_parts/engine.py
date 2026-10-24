"""MusicXML parsing and deterministic part engraving."""

from __future__ import annotations

import copy
import hashlib
import io
import os
import re
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree as ET

import verovio
from pypdf import PdfReader, PdfWriter
from reportlab.graphics import renderPDF
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from svglib.svglib import svg2rlg


def _strip_namespaces(root: ET.Element) -> None:
    for element in root.iter():
        if "}" in element.tag:
            element.tag = element.tag.rsplit("}", 1)[1]


def _read_musicxml(path: Path) -> ET.Element:
    if not path.is_file():
        raise ValueError(f"Input file does not exist: {path}")
    if path.suffix.lower() == ".mxl":
        with zipfile.ZipFile(path) as archive:
            name = None
            if "META-INF/container.xml" in archive.namelist():
                container = ET.fromstring(archive.read("META-INF/container.xml"))
                for element in container.iter():
                    if element.tag.rsplit("}", 1)[-1] == "rootfile":
                        name = element.get("full-path")
                        break
            if not name:
                candidates = [
                    item for item in archive.namelist()
                    if item.lower().endswith(".xml") and not item.startswith("META-INF/")
                ]
                if not candidates:
                    raise ValueError("MXL archive contains no MusicXML score")
                name = candidates[0]
            data = archive.read(name)
    elif path.suffix.lower() in {".musicxml", ".xml"}:
        data = path.read_bytes()
    else:
        raise ValueError("Input must be .mxl, .musicxml, or .xml")
    root = ET.fromstring(data)
    _strip_namespaces(root)
    if root.tag != "score-partwise":
        raise ValueError("Only partwise MusicXML scores are supported")
    if root.find("part-list") is None:
        raise ValueError("MusicXML has no part-list")
    return root


def _parts(root: ET.Element) -> list[tuple[str, str]]:
    result = []
    actual = {part.get("id") for part in root.findall("part")}
    for part in root.findall("./part-list/score-part"):
        part_id = part.get("id")
        if part_id in actual:
            result.append((part_id, (part.findtext("part-name") or part_id).strip()))
    if not result:
        raise ValueError("MusicXML has no instrument parts")
    return result


def inspect_score(path: Path) -> dict:
    root = _read_musicxml(path)
    counts = {part.get("id"): len(part.findall("measure")) for part in root.findall("part")}
    return {
        "source": str(path.resolve()),
        "title": _title(root, path.stem),
        "parts": [
            {"id": part_id, "name": name, "measures": counts[part_id]}
            for part_id, name in _parts(root)
        ],
    }


def _title(root: ET.Element, fallback: str) -> str:
    for candidate in (
        root.findtext("work/work-title"),
        root.findtext("movement-title"),
        *[element.text for element in root.findall("./credit/credit-words")],
    ):
        if candidate and candidate.strip():
            return candidate.strip().splitlines()[0].strip()
    return fallback


def _safe_name(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    if not value:
        value = "Untitled"
    if value.upper().split(".")[0] in {
        "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4",
        "LPT1", "LPT2", "LPT3", "LPT4",
    }:
        value = f"_{value}"
    return value[:100].rstrip(" .")


def _single_part(root: ET.Element, part_id: str) -> bytes:
    result = copy.deepcopy(root)
    for part in list(result.findall("part")):
        if part.get("id") != part_id:
            result.remove(part)
    part_list = result.find("part-list")
    for child in list(part_list):
        if child.tag != "score-part" or child.get("id") != part_id:
            part_list.remove(child)
    for measure in result.findall("./part/measure"):
        for print_element in list(measure.findall("print")):
            measure.remove(print_element)
    for credit in list(result.findall("credit")):
        result.remove(credit)
    return ET.tostring(result, encoding="utf-8", xml_declaration=True)


def _measure_fingerprint(root: ET.Element, part_id: str) -> str:
    part = next((part for part in root.findall("part") if part.get("id") == part_id), None)
    if part is None:
        raise ValueError(f"Missing part: {part_id}")
    digest = hashlib.sha256()
    for measure in part.findall("measure"):
        digest.update((measure.get("number") or "").encode("utf-8"))
        for child in measure:
            if child.tag != "print":
                digest.update(ET.tostring(child, encoding="utf-8"))
    return digest.hexdigest()


def _pdf_from_svg(svg: str) -> bytes:
    drawing = svg2rlg(io.BytesIO(svg.encode("utf-8")))
    if drawing is None or not drawing.width or not drawing.height:
        raise RuntimeError("SVG engraving could not be converted to PDF")
    stream = io.BytesIO()
    page = canvas.Canvas(stream, pagesize=(595.276, 841.890))
    page.scale(595.276 / drawing.width, 841.890 / drawing.height)
    renderPDF.draw(drawing, page, 0, 0)
    page.save()
    return stream.getvalue()


def _header_font(text: str) -> str:
    if text.isascii():
        return "Helvetica"
    font_name = "ScorePartsCJK"
    if font_name in pdfmetrics.getRegisteredFontNames():
        return font_name
    for file in ("msyh.ttc", "simsun.ttc", "msjh.ttc"):
        path = Path("C:/Windows/Fonts") / file
        if path.exists():
            pdfmetrics.registerFont(TTFont(font_name, str(path), subfontIndex=0))
            return font_name
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light"


def _page_label(title: str, instrument: str, page: int) -> bytes:
    title_font = _header_font(title)
    instrument_font = _header_font(instrument)
    stream = io.BytesIO()
    paper = canvas.Canvas(stream, pagesize=(595.276, 841.890))
    center = 595.276 / 2
    if page == 1:
        title_size = 18.0
        while title_size > 9 and pdfmetrics.stringWidth(title, title_font, title_size) > 525:
            title_size -= 1
        paper.setFont(title_font, title_size)
        paper.drawCentredString(center, 841.890 - 25.5, title)
        paper.setFont(instrument_font, 11)
        paper.drawCentredString(center, 841.890 - 42.5, instrument)
    else:
        paper.setFont(title_font, 9)
        paper.drawString(51.02, 841.890 - 31.18, title[:80])
        paper.setFont(instrument_font, 9)
        paper.drawCentredString(center, 841.890 - 31.18, instrument[:80])
        paper.setFont("Helvetica", 9)
        paper.drawRightString(544.25, 841.890 - 31.18, str(page))
    paper.save()
    return stream.getvalue()


@contextmanager
def _verovio_resources() -> Iterator[str]:
    source = Path(resources.files("verovio") / "data")
    if source.is_dir() and str(source).isascii():
        yield str(source)
        return
    candidates = [
        Path(tempfile.gettempdir()),
        Path(os.environ.get("PUBLIC", "C:/Users/Public")) / "Documents",
        Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")),
    ]
    for base in candidates:
        if not str(base).isascii() or not base.is_dir():
            continue
        temporary = None
        try:
            temporary = tempfile.TemporaryDirectory(prefix="score-parts-", dir=base)
            target = Path(temporary.name) / "verovio-data"
            shutil.copytree(source, target)
        except OSError:
            if temporary:
                temporary.cleanup()
            continue
        try:
            yield str(target)
        finally:
            temporary.cleanup()
        return
    raise RuntimeError("No writable ASCII path is available for Verovio font resources")


def _engrave(xml: bytes, title: str, instrument: str, resource_path: str, scale: int) -> PdfWriter:
    toolkit = verovio.toolkit(False)
    if not toolkit.setResourcePath(resource_path):
        raise RuntimeError("Verovio could not load its music fonts")
    toolkit.setOptions({
        "pageWidth": 2100,
        "pageHeight": 2970,
        "pageMarginLeft": 120,
        "pageMarginRight": 120,
        "pageMarginTop": 200,
        "pageMarginBottom": 130,
        "scale": scale,
        "header": "none",
        "footer": "none",
    })
    if not toolkit.loadData(xml.decode("utf-8")):
        raise RuntimeError(f"Verovio could not read part: {instrument}")
    count = toolkit.getPageCount()
    if count < 1:
        raise RuntimeError(f"No pages produced for part: {instrument}")
    writer = PdfWriter()
    for number in range(1, count + 1):
        page = PdfReader(io.BytesIO(_pdf_from_svg(toolkit.renderToSVG(number)))).pages[0]
        label = PdfReader(io.BytesIO(_page_label(title, instrument, number))).pages[0]
        writer.add_page(page)
        writer.pages[-1].merge_page(label)
    writer.add_metadata({"/Title": f"{title} - {instrument}"})
    return writer


def convert(input_path: Path, output_dir: Path, *, title: str | None = None,
            chosen_parts: list[str] | None = None, scale: int = 70,
            overwrite: bool = False, filename_pattern: str = "{title} - {part}",
            on_part=None) -> list[tuple[str, int, Path]]:
    root = _read_musicxml(input_path)
    all_parts = _parts(root)
    title = title or _title(root, input_path.stem)
    requested = set(chosen_parts or [])
    unknown = requested - {part_id for part_id, name in all_parts} - {name for part_id, name in all_parts}
    if unknown:
        raise ValueError(f"Unknown part(s): {', '.join(sorted(unknown))}")
    selected = [(part_id, name) for part_id, name in all_parts
                if not requested or part_id in requested or name in requested]
    if not 25 <= scale <= 100:
        raise ValueError("Scale must be between 25 and 100")
    if set(re.findall(r"\{([^{}]+)\}", filename_pattern)) - {"title", "part", "id"}:
        raise ValueError("Filename pattern supports only {title}, {part}, and {id}")
    try:
        targets = [output_dir / (_safe_name(filename_pattern.format(
            title=_safe_name(title), part=_safe_name(name), id=_safe_name(part_id))) + ".pdf")
                   for part_id, name in selected]
    except (KeyError, ValueError) as error:
        raise ValueError(f"Invalid filename pattern: {error}") from error
    if len({str(path).casefold() for path in targets}) != len(targets):
        targets = [output_dir / (_safe_name(filename_pattern.format(
            title=_safe_name(title), part=_safe_name(name), id=_safe_name(part_id)))
            + f" - {_safe_name(part_id)}.pdf") for part_id, name in selected]
    if len({str(path).casefold() for path in targets}) != len(targets):
        raise ValueError("Filename pattern produces duplicate PDF filenames")
    existing = [path for path in targets if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"Output exists (use --overwrite): {existing[0]}")
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    with _verovio_resources() as resource_path:
        for (part_id, name), target in zip(selected, targets):
            if on_part:
                on_part(part_id, name)
            xml = _single_part(root, part_id)
            if _measure_fingerprint(root, part_id) != _measure_fingerprint(ET.fromstring(xml), part_id):
                raise RuntimeError(f"Part content changed during extraction: {name}")
            writer = _engrave(xml, title, name, resource_path, scale)
            with tempfile.NamedTemporaryFile(dir=output_dir, suffix=".pdf", delete=False) as file:
                temporary = Path(file.name)
            try:
                with temporary.open("wb") as file:
                    writer.write(file)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            results.append((name, len(writer.pages), target))
    return results
