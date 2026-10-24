import json
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter

from score_parts.ai_client import review_page
from score_parts.batch import make_bundle, read_manifest, run_batch
from score_parts.engine import _measure_fingerprint, _read_musicxml, _single_part, convert
from score_parts.quality import check_pdf


MINIMAL = '''<?xml version="1.0" encoding="utf-8"?>
<score-partwise version="4.0">
 <work><work-title>测试曲</work-title></work>
 <part-list>
  <score-part id="P1"><part-name>Violin</part-name><part-abbreviation>Vln</part-abbreviation><score-instrument id="I1"><instrument-name>Violin</instrument-name></score-instrument><midi-instrument id="I1"><midi-channel>1</midi-channel><midi-program>41</midi-program></midi-instrument></score-part>
 </part-list>
 <part id="P1">
  <measure implicit="no" number="1"><attributes><divisions>1</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes><note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><type>whole</type></note></measure>
  <measure implicit="no" number="2"><note><rest/><duration>4</duration><type>whole</type></note><barline location="right"><bar-style>light-heavy</bar-style></barline></measure>
 </part>
</score-partwise>'''


class ProductTests(unittest.TestCase):
    def test_source_measure_content_survives_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "测试曲.musicxml"
            path.write_text(MINIMAL, encoding="utf-8")
            root = _read_musicxml(path)
            extracted = _read_musicxml_from_bytes(_single_part(root, "P1"))
            self.assertEqual(_measure_fingerprint(root, "P1"), _measure_fingerprint(extracted, "P1"))

    def test_batch_continues_after_invalid_score_and_bundles_report(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            valid = home / "测试曲.musicxml"
            valid.write_text(MINIMAL, encoding="utf-8")
            invalid = home / "broken.mxl"
            invalid.write_bytes(b"not a zip")
            batch = run_batch([invalid, valid], home / "deliveries")
            manifest = read_manifest(batch)
            self.assertEqual([item["status"] for item in manifest["scores"]], ["failed", "completed"])
            part = manifest["scores"][1]["outputs"][0]
            self.assertEqual(part["expected_measures"], 2)
            self.assertTrue((batch / part["file"]).is_file())
            self.assertTrue((batch / "report.html").is_file())
            with self.assertRaisesRegex(ValueError, "人工审阅"):
                make_bundle(batch, confirm_review=False)
            self.assertTrue(make_bundle(batch, confirm_review=True).is_file())
            self.assertTrue(read_manifest(batch)["reviewed"])

    def test_duplicate_instrument_names_get_distinct_files(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "duo.musicxml"
            duplicate = MINIMAL.replace('<score-part id="P1">', '<score-part id="P1">', 1)
            duplicate = duplicate.replace("</part-list>", '<score-part id="P2"><part-name>Violin</part-name></score-part></part-list>')
            duplicate = duplicate.replace("</score-partwise>", '<part id="P2"><measure number="1"><attributes><divisions>1</divisions><clef><sign>G</sign><line>2</line></clef></attributes><note><rest/><duration>4</duration><type>whole</type></note></measure></part></score-partwise>')
            path.write_text(duplicate, encoding="utf-8")
            outputs = convert(path, Path(temp) / "parts")
            self.assertEqual(len(outputs), 2)
            self.assertNotEqual(outputs[0][2].name, outputs[1][2].name)
            batch = run_batch([path], Path(temp) / "deliveries")
            parts = read_manifest(batch)["scores"][0]["outputs"]
            self.assertEqual([part["expected_measures"] for part in parts], [2, 1])
            self.assertNotEqual(parts[0]["file"], parts[1]["file"])

    def test_blank_page_and_explicit_ai_consent(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "blank.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=595.276, height=841.890)
            with pdf.open("wb") as file:
                writer.write(file)
            report = check_pdf(pdf, "Test", "Violin", 1)
            self.assertIn("blank_page", {item["code"] for item in report["findings"]})
            with patch("score_parts.ai_client.render_page_png", side_effect=AssertionError("must not render")):
                with self.assertRaisesRegex(ValueError, "同意"):
                    review_page(Path(temp), "blank.pdf", 1, endpoint="https://example.com", trial_token="token", consent=False)

    def test_ai_upload_contains_only_selected_page_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            batch = Path(temp)
            manifest = {"schema_version": 1, "created_at": "2026-10-24", "reviewed": False,
                        "ai_findings": [], "scores": [{"source": "source.mxl", "title": "Example",
                        "status": "completed", "parts": [], "error": None,
                        "outputs": [{"id": "P1", "name": "Violin", "file": "Violin.pdf", "pages": 1,
                                     "expected_measures": 1, "findings": []}]}]}
            (batch / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            captured = {}

            def urlopen(request, timeout):
                captured.update(json.loads(request.data))
                return io.BytesIO(b'{"findings":[{"code":"layout","severity":"review","message":"Check spacing","evidence":"Tight bar"}]}')

            with patch("score_parts.ai_client.render_page_png", return_value=b"selected-page"), \
                    patch("score_parts.ai_client.urllib.request.urlopen", side_effect=urlopen):
                findings = review_page(batch, "Violin.pdf", 1, endpoint="https://example.com",
                                       trial_token="secret", consent=True)
            self.assertEqual(set(captured), {"title", "part", "page", "image_base64"})
            self.assertEqual(findings[0]["source"], "ai")
            self.assertEqual(len(read_manifest(batch)["scores"][0]["outputs"][0]["findings"]), 1)


def _read_musicxml_from_bytes(value):
    from xml.etree import ElementTree as ET
    return ET.fromstring(value)


@unittest.skipUnless(__import__("importlib").util.find_spec("fastapi"), "Service dependencies not installed")
class TrialServiceTests(unittest.TestCase):
    def test_model_reply_is_parsed_without_network(self):
        from score_parts.ai_service import _ask_model
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only", "OPENAI_MODEL": "vision-test"}):
            with patch("openai.OpenAI") as client:
                client.return_value.responses.create.return_value.output_text = '{"findings":[]}'
                self.assertEqual(_ask_model("Example", "Violin", 1, "iVBORw0KGgo="), [])
                arguments = client.return_value.responses.create.call_args.kwargs
                self.assertEqual(arguments["model"], "vision-test")
                self.assertEqual(arguments["input"][0]["content"][1]["type"], "input_image")

    def test_quota_and_no_saved_page_image(self):
        from fastapi.testclient import TestClient
        from score_parts.ai_service import app
        with tempfile.TemporaryDirectory() as temp:
            database = str(Path(temp) / "usage.sqlite3")
            with patch.dict(os.environ, {"SCORE_PARTS_TRIAL_TOKENS": "secret-token", "SCORE_PARTS_TRIAL_LIMIT": "1",
                                      "SCORE_PARTS_USAGE_DB": database}):
                with patch("score_parts.ai_service._ask_model", return_value=[{
                    "code": "layout", "severity": "review", "message": "Check spacing", "evidence": "System is tight"
                }]):
                    client = TestClient(app)
                    payload = {"title": "Example", "part": "Violin", "page": 1,
                               "image_base64": "iVBORw0KGgo="}
                    headers = {"Authorization": "Bearer secret-token"}
                    first = client.post("/v1/check-page", json=payload, headers=headers)
                    self.assertEqual(first.status_code, 200)
                    self.assertEqual(first.json()["findings"][0]["severity"], "review")
                    second = client.post("/v1/check-page", json=payload, headers=headers)
                    self.assertEqual(second.status_code, 429)
                    self.assertEqual([path.name for path in Path(temp).iterdir()], ["usage.sqlite3"])

    def test_failed_model_call_does_not_use_trial_quota(self):
        from fastapi.testclient import TestClient
        from score_parts.ai_service import app
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"SCORE_PARTS_TRIAL_TOKENS": "secret-token", "SCORE_PARTS_TRIAL_LIMIT": "1",
                                      "SCORE_PARTS_USAGE_DB": str(Path(temp) / "usage.sqlite3")}):
                with patch("score_parts.ai_service._ask_model", side_effect=RuntimeError("offline")):
                    client = TestClient(app)
                    payload = {"title": "Example", "part": "Violin", "page": 1,
                               "image_base64": "iVBORw0KGgo="}
                    headers = {"Authorization": "Bearer secret-token"}
                    self.assertEqual(client.post("/v1/check-page", json=payload, headers=headers).status_code, 502)
                    self.assertEqual(client.post("/v1/check-page", json=payload, headers=headers).status_code, 502)


if __name__ == "__main__":
    unittest.main()
