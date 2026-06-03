import tempfile
import unittest
import zipfile
import subprocess
from pathlib import Path
from unittest import mock

from app.ai.document_summary import DocumentParseError, extract_text_from_file


class DocumentSummaryTest(unittest.TestCase):
    def test_extracts_text_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as handle:
            handle.write("This is a private document that should be summarized on the Raspberry Pi.")
            path = Path(handle.name)
        try:
            text = extract_text_from_file(path)
        finally:
            path.unlink(missing_ok=True)

        self.assertIn("private document", text)

    def test_rejects_unsupported_file_type(self):
        with tempfile.NamedTemporaryFile("w", suffix=".xlsx", encoding="utf-8", delete=False) as handle:
            handle.write("not supported")
            path = Path(handle.name)
        try:
            with self.assertRaises(DocumentParseError):
                extract_text_from_file(path)
        finally:
            path.unlink(missing_ok=True)

    def test_extracts_docx_with_standard_library(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Private Word document summary.</w:t></w:r></w:p></w:body>"
            "</w:document>"
        )
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as handle:
            path = Path(handle.name)
        try:
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", xml)
            text = extract_text_from_file(path)
        finally:
            path.unlink(missing_ok=True)

        self.assertIn("Private Word document", text)

    @mock.patch("app.ai.document_summary.shutil.which", return_value="/usr/bin/libreoffice")
    @mock.patch("app.ai.document_summary.subprocess.run")
    def test_extracts_legacy_doc_with_libreoffice(self, run_mock, _which_mock):
        with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as handle:
            handle.write(b"legacy doc placeholder")
            path = Path(handle.name)

        def fake_run(cmd, **_kwargs):
            outdir = Path(cmd[cmd.index("--outdir") + 1])
            source = Path(cmd[-1])
            (outdir / f"{source.stem}.txt").write_text(
                "Legacy Word document summary.",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(cmd, 0, stdout="converted", stderr="")

        run_mock.side_effect = fake_run
        try:
            text = extract_text_from_file(path)
        finally:
            path.unlink(missing_ok=True)

        self.assertIn("Legacy Word document", text)


if __name__ == "__main__":
    unittest.main()
