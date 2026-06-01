import tempfile
import unittest
import zipfile
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
