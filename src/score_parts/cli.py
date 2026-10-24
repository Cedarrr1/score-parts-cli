"""Backward-compatible command-line interface."""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .engine import (  # Re-export helpers used by existing integrations.
    _parts, _read_musicxml, _safe_name, _single_part, _title, convert,
)


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
