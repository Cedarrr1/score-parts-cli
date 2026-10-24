"""Copy bundled runtime dependency license files into the portable package."""

from __future__ import annotations

import importlib.metadata as metadata
import shutil
import sys
from pathlib import Path


RUNTIME_PACKAGES = [
    "verovio", "svglib", "reportlab", "pypdf", "pypdfium2", "PySide6_Essentials",
    "shiboken6", "lxml", "pillow", "cssselect2", "tinycss2", "webencodings",
    "charset-normalizer",
]


def main(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    rows = ["Bundled runtime dependency notices", "", "Review each included license before external distribution.", ""]
    for name in RUNTIME_PACKAGES:
        package = metadata.distribution(name)
        rows.append(f"- {package.metadata['Name']} {package.version}: "
                    f"{package.metadata.get('License-Expression') or package.metadata.get('License') or 'see package files'}")
        for file in package.files or []:
            parts = Path(str(file)).parts
            lower = [part.lower() for part in parts]
            filename = Path(str(file)).name.lower()
            if "licenses" not in lower and "license" not in filename and filename not in {"copying", "copying.lesser"}:
                continue
            source = Path(package.locate_file(file))
            if not source.is_file():
                continue
            target = destination / package.metadata["Name"] / Path(*parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    (destination / "README.txt").write_text("\n".join(rows), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
