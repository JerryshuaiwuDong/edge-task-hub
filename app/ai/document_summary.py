from __future__ import annotations

import hashlib
import re
import time
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

class DocumentParseError(RuntimeError):
    pass


@dataclass(frozen=True)
class DocumentSummaryResult:
    ok: bool
    text: str
    model: str
    elapsed_seconds: float
    sha256: str
    file_size: int
    error: str = ""


def extract_text_from_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return _clean_text(path.read_text(encoding="utf-8", errors="replace"))
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix == ".pdf":
        return _extract_pdf(path)
    raise DocumentParseError(f"Unsupported file type: {suffix or 'unknown'}")


def summarize_document_file(path: Path, *, file_name: str = "") -> DocumentSummaryResult:
    from app.ai.model_runtime import generate_ollama
    settings = _settings()

    started = time.monotonic()
    file_size = path.stat().st_size
    sha256 = _sha256(path)
    if file_size > settings.document_summary_max_file_bytes:
        return DocumentSummaryResult(
            ok=False,
            text="",
            model=settings.document_summary_model,
            elapsed_seconds=round(time.monotonic() - started, 3),
            sha256=sha256,
            file_size=file_size,
            error=f"File is too large. Limit: {settings.document_summary_max_file_bytes} bytes.",
        )

    try:
        text = extract_text_from_file(path)
    except DocumentParseError as exc:
        return DocumentSummaryResult(
            ok=False,
            text="",
            model=settings.document_summary_model,
            elapsed_seconds=round(time.monotonic() - started, 3),
            sha256=sha256,
            file_size=file_size,
            error=str(exc),
        )

    if not text:
        return DocumentSummaryResult(
            ok=False,
            text="",
            model=settings.document_summary_model,
            elapsed_seconds=round(time.monotonic() - started, 3),
            sha256=sha256,
            file_size=file_size,
            error="No readable text was found in the file.",
        )

    prompt = build_document_prompt(text, file_name=file_name or path.name)
    result = generate_ollama(
        prompt,
        model=settings.document_summary_model,
        max_tokens=settings.document_summary_max_tokens,
        timeout=settings.document_summary_timeout_seconds,
    )
    if not result.ok or not result.text:
        return DocumentSummaryResult(
            ok=False,
            text="",
            model=result.model or settings.document_summary_model,
            elapsed_seconds=result.elapsed_seconds,
            sha256=sha256,
            file_size=file_size,
            error=result.error or "The local model returned an empty summary.",
        )

    return DocumentSummaryResult(
        ok=True,
        text=result.text,
        model=result.model or settings.document_summary_model,
        elapsed_seconds=result.elapsed_seconds,
        sha256=sha256,
        file_size=file_size,
    )


def build_document_prompt(text: str, *, file_name: str) -> str:
    settings = _settings()
    clipped = text[: settings.document_summary_max_chars]
    return "\n".join(
        [
            "You are a private edge AI document assistant running on a Raspberry Pi.",
            "Summarize only the provided document text. Do not invent facts.",
            "Return English output with: 1) a short title, 2) 3-5 bullet points, 3) action items if any.",
            f"File name: {file_name}",
            "Document text:",
            clipped,
        ]
    )


def _extract_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise DocumentParseError("Invalid .docx file.") from exc

    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise DocumentParseError("Invalid .docx XML content.") from exc

    paragraphs = []
    for para in root.iter():
        if not para.tag.endswith("}p"):
            continue
        parts = []
        for node in para.iter():
            if node.tag.endswith("}t") and node.text:
                parts.append(node.text)
            elif node.tag.endswith("}tab"):
                parts.append("\t")
            elif node.tag.endswith("}br"):
                parts.append("\n")
        if parts:
            paragraphs.append("".join(parts))
    return _clean_text("\n".join(paragraphs))


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return _extract_pdf_basic(path)
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text)
    return _clean_text("\n".join(parts))


def _extract_pdf_basic(path: Path) -> str:
    raw = path.read_bytes()
    chunks = [raw]
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        stream = match.group(1)
        try:
            chunks.append(zlib.decompress(stream))
        except zlib.error:
            chunks.append(stream)

    texts = []
    for chunk in chunks:
        text = chunk.decode("latin-1", errors="ignore")
        for value in re.findall(r"\(((?:\\.|[^\\)])*)\)\s*Tj", text):
            texts.append(_unescape_pdf_string(value))
        for array in re.findall(r"\[(.*?)\]\s*TJ", text, re.S):
            for value in re.findall(r"\((?:\\.|[^\\)])*\)", array):
                texts.append(_unescape_pdf_string(value[1:-1]))
        for hex_value in re.findall(r"<([0-9A-Fa-f\s]+)>\s*Tj", text):
            cleaned = re.sub(r"\s+", "", hex_value)
            try:
                decoded = bytes.fromhex(cleaned).decode("utf-16-be", errors="ignore")
            except ValueError:
                decoded = ""
            if decoded:
                texts.append(decoded)
    cleaned = _clean_text(" ".join(texts))
    if not cleaned:
        raise DocumentParseError("No readable text was found in this PDF. Install pypdf for stronger PDF extraction.")
    return cleaned


def _unescape_pdf_string(value: str) -> str:
    return (
        value.replace(r"\(", "(")
        .replace(r"\)", ")")
        .replace(r"\\", "\\")
        .replace(r"\n", "\n")
        .replace(r"\r", "\r")
        .replace(r"\t", "\t")
    )


def _clean_text(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip()).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _settings():
    from app.config import settings

    return settings
