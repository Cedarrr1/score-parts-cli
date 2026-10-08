import tempfile
import unittest
import zipfile
from pathlib import Path

from score_parts.cli import _parts, _read_musicxml, _safe_name, _single_part, _title


SCORE = b'''<?xml version="1.0" encoding="utf-8"?>
<score-partwise version="4.0">
  <work><work-title>Example</work-title></work>
  <part-list>
    <score-part id="P1"><part-name>Violin I</part-name></score-part>
    <score-part id="P2"><part-name>Viola</part-name></score-part>
  </part-list>
  <part id="P1"><measure number="1"><print new-page="yes"/><note><rest/><duration>4</duration><type>whole</type></note></measure></part>
  <part id="P2"><measure number="1"><note><rest/><duration>4</duration><type>whole</type></note></measure></part>
</score-partwise>'''


class MusicXmlTests(unittest.TestCase):
    def test_mxl_container_selects_score_and_extracts_one_part(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.mxl"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("META-INF/container.xml", '''<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="music/score.musicxml"/></rootfiles></container>''')
                archive.writestr("music/score.musicxml", SCORE)
                archive.writestr("unrelated.xml", "<root/>")
            root = _read_musicxml(path)
        self.assertEqual(_parts(root), [("P1", "Violin I"), ("P2", "Viola")])
        self.assertEqual(_title(root, "fallback"), "Example")
        extracted = _single_part(root, "P1").decode("utf-8")
        self.assertIn('id="P1"', extracted)
        self.assertNotIn('id="P2"', extracted)
        self.assertNotIn("new-page", extracted)

    def test_invalid_input_and_safe_output_name(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "score.mid"
            path.write_bytes(b"MThd")
            with self.assertRaisesRegex(ValueError, "Input must be"):
                _read_musicxml(path)
        self.assertEqual(_safe_name('CON'), '_CON')
        self.assertEqual(_safe_name('Violin: I / solo'), 'Violin_ I _ solo')


if __name__ == "__main__":
    unittest.main()
