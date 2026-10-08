"""Command-line entry point for MusicXML-to-PDF part extraction."""

from __future__ import annotations

import argparse
import copy
import io
import re
import shutil
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from html import escape
from importlib import resources
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree as ET

import cairosvg
import verovio
from pypdf import PdfReader, PdfWriter


A4_WIDTH_PX = 793.7008
A4_HEIGHT_PX = 1122.5197


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


def _pdf_from_svg(svg: str) -> bytes:
    return cairosvg.svg2pdf(
        bytestring=svg.encode("utf-8"),
        output_width=A4_WIDTH_PX,
        output_height=A4_HEIGHT_PX,
    )


def _page_label(title: str, instrument: str, page: int) -> bytes:
    title = escape(title)
    instrument = escape(instrument)
    if page == 1:
        title_size = min(6.5, max(3.4, 120 / max(len(title), 1)))
        text = (
            f'<text x="105" y="13" text-anchor="middle" font-size="{title_size:.1f}" '
            f'font-weight="bold">{title}</text>'
            f'<text x="105" y="19" text-anchor="middle" font-size="4">{instrument}</text>'
        )
    else:
        text = (
            f'<text x="18" y="11" font-size="3.2">{title}</text>'
            f'<text x="105" y="11" text-anchor="middle" font-size="3.2">{instrument}</text>'
            f'<text x="192" y="11" text-anchor="end" font-size="3.2">{page}</text>'
        )
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm" '
        'viewBox="0 0 210 297">'
        f'<g font-family="Arial, sans-serif" fill="#111">{text}</g></svg>'
    )
    return _pdf_from_svg(svg)


@contextmanager
def _verovio_resources() -> Iterator[str]:
    source = Path(resources.files("verovio") / "data")
    if source.is_dir() and str(source).isascii():
        yield str(source)
        return
    with tempfile.TemporaryDirectory(prefix="score-parts-") as directory:
        target = Path(directory) / "verovio-data"
        shutil.copytree(source, target)
        if not str(target).isascii():
            raise RuntimeError("Verovio requires an ASCII path for its font resources")
        yield str(target)


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
        page.merge_page(label)
        writer.add_page(page)
    writer.add_metadata({"/Title": f"{title} - {instrument}"})
    return writer


def convert(input_path: Path, output_dir: Path, *, title: str | None = None,
            chosen_parts: list[str] | None = None, scale: int = 70,
            overwrite: bool = False) -> list[tuple[str, int, Path]]:
    root = _read_musicxml(input_path)
    all_parts = _parts(root)
    title = title or _title(root, input_path.stem)
    requested = set(chosen_parts or [])
    unknown = requested - {part_id for part_id, name in all_parts} - {name for part_id, name in all_parts}
    if unknown:
        raise ValueError(f"Unknown part(s): {', '.join(sorted(unknown))}")
    selected = [(part_id, name) for part_id, name in all_parts
                if not requested or part_id in requested or name in requested]
    targets = [output_dir / f"{_safe_name(title)} - {_safe_name(name)}.pdf" for _, name in selected]
    if len({str(path).lower() for path in targets}) != len(targets):
        raise ValueError("Part names produce duplicate PDF filenames")
    existing = [path for path in targets if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"Output exists (use --overwrite): {existing[0]}")
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    with _verovio_resources() as resource_path:
        for (part_id, name), target in zip(selected, targets):
            writer = _engrave(_single_part(root, part_id), title, name, resource_path, scale)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="score-parts",
        description="Export one A4 PDF per instrument from an MXL or MusicXML score.",
    )
    parser.add_argument("input", type=Path, help=".mxl, .musicxml, or .xml score")
    parser.add_argument("-o", "--output", type=Path, default=Path("parts"), help="Output directory (default: parts)")
    parser.add_argument("--title", help="Override the score title")
    parser.add_argument("--part", action="append", help="Part name or ID; repeat to select multiple parts")
    parser.add_argument("--list-parts", action="store_true", help="List parts without exporting")
    parser.add_argument("--scale", type=int, default=70, help="Engraving scale, 25-100 (default: 70)")
    parser.add_argument("--overwrite", action="store_true", help="Replace PDF files with the same names")
    args = parser.parse_args(argv)
    if not 25 <= args.scale <= 100:
        parser.error("--scale must be between 25 and 100")
    try:
        if args.list_parts:
            for part_id, name in _parts(_read_musicxml(args.input)):
                print(f"{part_id}\t{name}")
            return 0
        results = convert(args.input, args.output, title=args.title,
                          chosen_parts=args.part, scale=args.scale,
                          overwrite=args.overwrite)
    except (ValueError, FileExistsError, OSError, zipfile.BadZipFile, ET.ParseError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    for name, pages, target in results:
        print(f"{name}: {pages} page(s) -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
