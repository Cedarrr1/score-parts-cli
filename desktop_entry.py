"""PyInstaller entry point for the Windows desktop app."""

import sys


if "--self-test" in sys.argv:
    import tempfile
    from pathlib import Path
    from PySide6.QtWidgets import QApplication
    from score_parts.desktop import MainWindow
    from score_parts.engine import _verovio_resources
    from score_parts.quality import check_pdf
    from score_parts.engine import convert
    import svglib  # noqa: F401
    import pypdfium2  # noqa: F401
    import verovio

    app = QApplication([])
    window = MainWindow()
    with _verovio_resources() as path:
        toolkit = verovio.toolkit(False)
        if not toolkit.setResourcePath(path):
            raise RuntimeError("Packaged Verovio font resources are unavailable")
    sample = '''<score-partwise version="4.0"><work><work-title>Package test</work-title></work>
    <part-list><score-part id="P1"><part-name>Violin</part-name></score-part></part-list>
    <part id="P1"><measure number="1"><attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>
    <note><rest/><duration>4</duration><type>whole</type></note></measure></part></score-partwise>'''
    with tempfile.TemporaryDirectory(prefix="score-parts-self-test-") as temp:
        source = Path(temp) / "test.musicxml"
        source.write_text(sample, encoding="utf-8")
        part = convert(source, Path(temp) / "out")[0][2]
        report = check_pdf(part, "Package test", "Violin", 1)
        if report["pages"] < 1 or any(item["severity"] == "error" for item in report["findings"]):
            raise RuntimeError("Packaged conversion self-test failed")
    window.close()
else:
    from score_parts.desktop import main
    raise SystemExit(main())
