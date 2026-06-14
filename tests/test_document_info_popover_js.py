"""Regression guards for the compact document metadata and sharing popover."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC_JS = (ROOT / "static/js/document.js").read_text(encoding="utf-8")
STYLE = (ROOT / "static/style.css").read_text(encoding="utf-8")


def test_document_info_button_is_compact_and_wired():
    assert 'id="doc-info-btn"' in DOC_JS
    assert "addEventListener('click', toggleDocumentInfo)" in DOC_JS
    assert "if (_info)         _split.before(_info);" in DOC_JS


def test_document_info_surfaces_metadata_and_honest_sharing_state():
    assert "Download name" in DOC_JS
    assert "Document ID" in DOC_JS
    assert 'id="doc-info-project"' in DOC_JS
    assert 'id="doc-info-tags"' in DOC_JS
    assert "Save metadata" in DOC_JS
    assert "Logseq graph" in DOC_JS
    assert "Private to your account" in DOC_JS
    assert "Share links and live collaborative editing are not enabled yet." in DOC_JS


def test_document_info_popover_has_dedicated_styles():
    assert ".doc-info-popover {" in STYLE
    assert ".doc-info-sharing {" in STYLE
