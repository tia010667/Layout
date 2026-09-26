"""Tool: Classify the document type before formatting.

Reads the structural fingerprint of template and content (from raw
document.xml) and decides which formatting strategy to use:

- copy      : content is the template with values filled in (degenerate
              case) — output the content as-is.
- text_flow : both documents are linear paragraph flows (no tables) —
              use the existing restyle pipeline.
- table_form: content/template is table-driven — needs table-aware
              restyle (recognized here, handled later).

Only reads word/document.xml — cheap and sufficient for classification.
"""

import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

WPML = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _q(tag: str) -> str:
    return f"{{{WPML}}}{tag}"


def _docx_fingerprint(path: str) -> dict[str, Any]:
    """Extract a structural fingerprint from a .docx's document.xml.

    Deliberately captures column layout (not row counts) and the set of
    top-level pStyle ids — these stay stable when a form is filled in,
    whereas row counts / in-table paragraph counts change as users add
    or remove rows.
    """
    with open(path, "rb") as f:
        doc_tree = etree.fromstring(zipfile.ZipFile(f).read("word/document.xml"))

    body = doc_tree.find(_q("body"))
    if body is None:
        return {
            "top_count": 0,
            "tbl_count": 0,
            "tbl_cols": [],
            "top_style_ids": set(),
            "in_tbl_count": 0,
        }

    top_ps = body.findall(_q("p"))
    tables = body.findall(_q("tbl"))

    tbl_cols = []
    for tbl in tables:
        first_row = tbl.find(_q("tr"))
        tbl_cols.append(
            len(first_row.findall(_q("tc"))) if first_row is not None else 0
        )

    top_style_ids = set()
    for p in top_ps:
        pPr = p.find(_q("pPr"))
        if pPr is not None:
            pStyle = pPr.find(_q("pStyle"))
            if pStyle is not None:
                top_style_ids.add(pStyle.get(_q("val")))

    in_tbl_count = sum(len(tbl.findall(".//" + _q("p"))) for tbl in tables)

    return {
        "top_count": len(top_ps),
        "tbl_count": len(tables),
        "tbl_cols": tbl_cols,
        "top_style_ids": top_style_ids,
        "in_tbl_count": in_tbl_count,
    }


def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity of two sets (1.0 when both empty)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def classify_document(
    template_path: str,
    content_path: str,
) -> dict[str, Any]:
    """Classify a template+content pair into copy / text_flow / table_form."""
    content_ext = Path(content_path).suffix.lower() if content_path else ""

    # Non-docx content can never be a "copy" of the template.
    if content_ext != ".docx":
        tpl_fp = _docx_fingerprint(template_path)
        mode = (
            "table_form"
            if tpl_fp["in_tbl_count"] > tpl_fp["top_count"]
            else "text_flow"
        )
        return {
            "mode": mode,
            "reason": f"content is {content_ext or 'unknown'}, not a docx copy",
            "tpl_fp": tpl_fp,
            "cnt_fp": None,
        }

    tpl_fp = _docx_fingerprint(template_path)
    cnt_fp = _docx_fingerprint(content_path)

    # copy: a table-form template whose content is the same form filled in.
    # Required signals: identical table count (and at least one table),
    # identical column layout, (≈) identical top-level paragraph count, and
    # highly-overlapping top-level styles. Row counts are ignored on purpose —
    # filling the form adds/removes rows without changing structural identity.
    # Style comparison is fuzzy (Jaccard ≥ 0.5) because editing tools often
    # renumber a style here or there (e.g. "14" → "15") during a save cycle.
    is_copy = (
        tpl_fp["tbl_count"] == cnt_fp["tbl_count"]
        and tpl_fp["tbl_count"] > 0
        and tpl_fp["tbl_cols"] == cnt_fp["tbl_cols"]
        and abs(tpl_fp["top_count"] - cnt_fp["top_count"]) <= 2
        and _jaccard(tpl_fp["top_style_ids"], cnt_fp["top_style_ids"]) >= 0.5
    )
    if is_copy:
        return {
            "mode": "copy",
            "reason": "content structurally matches template (filled-in copy)",
            "tpl_fp": tpl_fp,
            "cnt_fp": cnt_fp,
        }

    tpl_table_heavy = tpl_fp["in_tbl_count"] > tpl_fp["top_count"]
    cnt_table_heavy = cnt_fp["in_tbl_count"] > cnt_fp["top_count"]
    if tpl_table_heavy or cnt_table_heavy:
        mode, reason = "table_form", "table-driven document (in-table paragraphs dominate)"
    else:
        mode, reason = "text_flow", "linear paragraph flow"

    return {
        "mode": mode,
        "reason": reason,
        "tpl_fp": tpl_fp,
        "cnt_fp": cnt_fp,
    }
