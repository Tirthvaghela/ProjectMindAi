"""Tests for the actual file-parsing path in nlp/resume.py — extract_text()
and its PDF/DOCX branches — which had zero coverage before this file
(test_resume.py only exercises the pure detect_skills()/
normalize_skill_variants() string functions downstream of it).

Builds real, valid PDF and DOCX bytes rather than mocking pypdf/python-docx,
so these genuinely exercise the real parsing libraries this app depends on,
not a stand-in for them. `werkzeug.datastructures.FileStorage` is the same
object Flask hands `extract_text()` in production (routes/search.py:
`request.files.get("resume")`), so these tests exercise the exact real
interface, not a hand-rolled duck-typed stub.

Preserves the existing privacy behaviour under test throughout: nothing here
persists a résumé anywhere — extract_text() only ever reads bytes handed to
it and returns a string, matching nlp/resume.py's own "processed in memory
and discarded" design (see routes/search.py:resume_suggest, which never
writes the file/text to MongoDB).
"""

from __future__ import annotations

import io

import pytest
from werkzeug.datastructures import FileStorage

from nlp.resume import MAX_RESUME_CHARS, UnreadableResume, extract_text


def _upload(filename: str, data: bytes) -> FileStorage:
    return FileStorage(stream=io.BytesIO(data), filename=filename)


# --- minimal, real, hand-built file bytes -----------------------------------
# No new dependency added just for tests: PDFs are built as a raw minimal
# PDF-1.4 document (a well-documented, compact format for a single text
# object), and DOCX files are built with python-docx itself (already a real
# dependency, and it can write as well as read).


def _minimal_pdf(content_stream: bytes) -> bytes:
    objects = [
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj",
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj",
        b"3 0 obj<</Type/Page/Parent 2 0 R/Resources<</Font<</F1 5 0 R>>>>"
        b"/MediaBox[0 0 612 792]/Contents 4 0 R>>endobj",
        b"4 0 obj<</Length " + str(len(content_stream)).encode() + b">>stream\n"
        + content_stream + b"\nendstream endobj",
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for obj in objects:
        offsets.append(out.tell())
        out.write(obj + b"\n")
    xref_offset = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{xref_offset}\n%%EOF".encode())
    return out.getvalue()


def _pdf_with_text(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    return _minimal_pdf(stream)


def _pdf_with_no_text() -> bytes:
    """A structurally valid PDF whose content stream draws nothing — the same
    shape pypdf sees from a scanned/image-only PDF (a real page, zero text
    objects), without needing an actual scanned image fixture."""
    return _minimal_pdf(b"")


def _docx_with_text(*paragraphs: str) -> bytes:
    from docx import Document

    doc = Document()
    for paragraph in paragraphs:
        doc.add_paragraph(paragraph)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# --- PDF ---------------------------------------------------------------------


def test_pdf_extraction_returns_the_real_text():
    text = extract_text(_upload("resume.pdf", _pdf_with_text("Python Flask MongoDB experience")))
    assert "Python Flask MongoDB experience" in text


def test_pdf_with_no_text_layer_raises_unreadable_resume():
    """The scanned/image-only PDF case — pypdf parses the file successfully
    but extracts "", which must not silently become an empty query."""
    with pytest.raises(UnreadableResume, match="scanned image"):
        extract_text(_upload("scan.pdf", _pdf_with_no_text()))


def test_corrupt_pdf_raises_unreadable_resume():
    with pytest.raises(UnreadableResume):
        extract_text(_upload("resume.pdf", b"this is not a pdf at all, just garbage bytes"))


def test_empty_pdf_raises_unreadable_resume():
    with pytest.raises(UnreadableResume):
        extract_text(_upload("resume.pdf", b""))


# --- DOCX ----------------------------------------------------------------


def test_docx_extraction_returns_the_real_text_joined_by_paragraph():
    text = extract_text(
        _upload("resume.docx", _docx_with_text("Experienced with Python, Flask, and MongoDB.", "Also knows React."))
    )
    assert text == "Experienced with Python, Flask, and MongoDB.\nAlso knows React."


def test_corrupt_docx_raises_unreadable_resume():
    """A .docx is a zip archive — garbage bytes fail at the archive level,
    well before any paragraph is ever read."""
    with pytest.raises(UnreadableResume):
        extract_text(_upload("resume.docx", b"not a real docx zip file"))


def test_empty_docx_raises_unreadable_resume():
    with pytest.raises(UnreadableResume):
        extract_text(_upload("resume.docx", b""))


def test_docx_with_no_paragraphs_returns_empty_text_without_raising():
    """Unlike the no-text-layer PDF case, an empty-but-valid DOCX (no
    paragraphs) is not treated as an error — there is no scanned-document
    failure mode to guard against here, just genuinely no content."""
    text = extract_text(_upload("resume.docx", _docx_with_text()))
    assert text == ""


# --- TXT / unsupported extensions (the fallback branch) ---------------------


def test_txt_extraction_decodes_utf8():
    text = extract_text(_upload("resume.txt", "Skills: Python, React, MongoDB".encode("utf-8")))
    assert text == "Skills: Python, React, MongoDB"


def test_empty_txt_returns_empty_string_without_raising():
    """Contrast the binary formats above: an empty plain-text file is valid
    empty content, not a parse failure — there's nothing to fail to parse."""
    assert extract_text(_upload("resume.txt", b"")) == ""


def test_a_file_with_no_extension_is_treated_as_plain_text():
    text = extract_text(_upload("resume", "Python developer".encode("utf-8")))
    assert text == "Python developer"


def test_an_unsupported_extension_falls_back_to_best_effort_plain_text():
    """extract_text() does no magic-byte/content-type sniffing — only the
    filename extension routes to the PDF/DOCX branches, so a mislabeled file
    (e.g. an image saved with a .jpg name) is simply decoded as text rather
    than rejected outright. Documents the real, current behaviour rather
    than an assumed one."""
    text = extract_text(_upload("resume.jpg", "Python Flask developer".encode("utf-8")))
    assert text == "Python Flask developer"


def test_undecodable_bytes_in_the_text_fallback_are_ignored_not_raised():
    """errors="ignore" on the plain-text decode path — genuinely
    non-UTF-8 bytes (e.g. a real binary image) must not crash the request,
    just extract whatever *is* decodable."""
    text = extract_text(_upload("resume.jpg", b"\xff\xd8\xff\xe0Python\xff\xffFlask"))
    assert "Python" in text and "Flask" in text


def test_text_extraction_is_truncated_to_max_resume_chars():
    text = extract_text(_upload("resume.txt", ("a" * (MAX_RESUME_CHARS + 500)).encode("utf-8")))
    assert len(text) == MAX_RESUME_CHARS


def test_pdf_extraction_is_truncated_to_max_resume_chars():
    long_text = "Python " * 4000  # comfortably over MAX_RESUME_CHARS once rendered
    text = extract_text(_upload("resume.pdf", _pdf_with_text(long_text)))
    assert len(text) <= MAX_RESUME_CHARS
