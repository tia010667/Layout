"""Tool: Generate a formatted .docx using format profiles.

Strategy:
1. Parse the template to extract format profiles (effective formatting
   from both style definitions AND direct paragraph formatting)
2. For each content paragraph, look up its assigned format profile
3. Apply the profile's direct formatting (pPr + rPr) to the paragraph
4. Strip any conflicting direct formatting from the content first
5. Copy the template's styles.xml, theme, fontTable, and sectPr

This approach works even when the template uses direct formatting
instead of style definitions (common in Chinese academic documents).
"""

import io
import zipfile
import copy
from pathlib import Path
from typing import Any

from lxml import etree

WPML = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _q(tag: str) -> str:
    return f"{{{WPML}}}{tag}"


def _strip_ns(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def copy_content_as_output(
    template_path: str,
    content_path: str,
) -> bytes:
    """Return the content file verbatim for the degenerate "copy" case.

    When content is the template with values filled in, it already carries
    the correct formatting everywhere (including inside tables). Restyling
    it would only degrade it — the safest output is the content itself.

    The template is opened only to confirm it is a valid .docx; its bytes
    are not used. Raises ValueError if the content file is not a valid .docx.
    """
    # Validate content is a readable docx before passing it through.
    with open(content_path, "rb") as f:
        content_bytes = f.read()
    with zipfile.ZipFile(io.BytesIO(content_bytes), "r") as z:
        if "word/document.xml" not in z.namelist():
            raise ValueError(f"Content file is not a valid .docx: {content_path}")

    return content_bytes


def generate_docx_from_mapping(
    template_path: str,
    style_mapping: dict[str, Any],
    content_structure: dict[str, Any],
    template_analysis: dict[str, Any] | None = None,
) -> bytes:
    """Generate a formatted .docx by applying format profiles to content."""

    content_path = content_structure.get("_content_path", "")

    # If we have a content .docx, use its body as the base (preserves inline
    # runs, tables, etc.). For .md (or any non-docx content), we have no docx
    # body to reuse, so rebuild paragraphs from the template directly.
    content_ext = Path(content_path).suffix.lower() if content_path else ""
    if content_ext == ".docx" and content_path != template_path:
        try:
            return _generate_from_content(
                template_path, content_path, style_mapping,
                content_structure, template_analysis
            )
        except Exception as e:
            print(f"  [generate] Content-based failed: {e}, falling back to template-based", flush=True)

    return _generate_from_template(
        template_path, style_mapping, content_structure, template_analysis
    )


def _build_profile_lookup(
    template_analysis: dict[str, Any] | None,
    style_mapping: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Build a lookup: profile_id → {pPr_xml, rPr_xml, role}.

    Falls back gracefully if template_analysis or format_profiles are missing.
    """
    profiles: dict[str, dict[str, Any]] = {}
    if template_analysis:
        for p in template_analysis.get("format_profiles", []):
            profiles[p["profile_id"]] = p

    # Determine default profile_id
    default_id = style_mapping.get("default_profile_id", "")
    if not default_id and profiles:
        # Pick first body profile, or just first profile
        for pid, p in profiles.items():
            if p.get("role") == "body":
                default_id = pid
                break
        if not default_id:
            default_id = next(iter(profiles))

    profiles["__default__"] = profiles.get(default_id, {})
    return profiles


def _build_index_to_profile(style_mapping: dict[str, Any]) -> dict[int, str]:
    """Build paragraph_index → profile_id lookup."""
    result: dict[int, str] = {}
    for m in style_mapping.get("mappings", []):
        idx = m.get("paragraph_index")
        if idx is not None:
            result[idx] = m.get("profile_id", "")
    return result


def _apply_profile_to_paragraph(
    p_elem,
    profile: dict[str, Any],
    keep_numPr: bool = False,
    strip_numPr: bool = True,
) -> None:
    """Apply a format profile's direct formatting to a paragraph element.

    - Replaces the paragraph's pPr with the profile's pPr
    - Applies the profile's rPr to all runs (preserving b/i/u inline formatting)
    - By default strips numPr (list/numbering) so no bullet points appear;
      set strip_numPr=False to keep the profile's numPr.
    """
    pPr_xml = profile.get("pPr_xml", "")
    rPr_xml = profile.get("rPr_xml", "")

    # --- Apply paragraph properties ---
    # Save existing numPr if we need to keep it
    existing_pPr = p_elem.find(_q("pPr"))
    saved_numPr = None
    if existing_pPr is not None and keep_numPr:
        numPr = existing_pPr.find(_q("numPr"))
        if numPr is not None:
            saved_numPr = copy.deepcopy(numPr)

    # Remove existing pPr
    if existing_pPr is not None:
        p_elem.remove(existing_pPr)

    # Create new pPr from profile
    new_pPr = None
    if pPr_xml:
        try:
            new_pPr = etree.fromstring(pPr_xml)
        except etree.XMLParseError:
            new_pPr = None

    if new_pPr is None:
        new_pPr = etree.Element(_q("pPr"))

    # Strip numPr from the profile's pPr to avoid unwanted bullet points
    if strip_numPr:
        for numPr in new_pPr.findall(_q("numPr")):
            new_pPr.remove(numPr)

    # If the profile has no numPr but the original paragraph did, restore it
    # (preserves list/numbering structure from content)
    if saved_numPr is not None and new_pPr.find(_q("numPr")) is None:
        new_pPr.append(saved_numPr)

    # Insert pPr as first child of paragraph
    p_elem.insert(0, new_pPr)

    # --- Apply run properties ---
    # Parse profile rPr
    profile_rPr = None
    if rPr_xml:
        try:
            profile_rPr = etree.fromstring(rPr_xml)
        except etree.XMLParseError:
            profile_rPr = None

    if profile_rPr is not None:
        for r_elem in p_elem.iter(_q("r")):
            # Save inline b/i/u from the run
            existing_rPr = r_elem.find(_q("rPr"))
            saved_bold = None
            saved_italic = None
            saved_underline = None
            if existing_rPr is not None:
                b = existing_rPr.find(_q("b"))
                if b is not None:
                    saved_bold = b.get(_q("val"), "true") != "false"
                i = existing_rPr.find(_q("i"))
                if i is not None:
                    saved_italic = i.get(_q("val"), "true") != "false"
                u = existing_rPr.find(_q("u"))
                if u is not None:
                    u_val = u.get(_q("val"), "single")
                    if u_val != "none":
                        saved_underline = u_val

            # Remove existing rPr
            if existing_rPr is not None:
                r_elem.remove(existing_rPr)

            # Clone profile rPr and apply
            new_rPr = copy.deepcopy(profile_rPr)

            # Restore inline b/i/u (these are semantic, not formatting)
            if saved_bold:
                b_elem = new_rPr.find(_q("b"))
                if b_elem is None:
                    b_elem = etree.SubElement(new_rPr, _q("b"))
                b_elem.set(_q("val"), "true")
            if saved_italic:
                i_elem = new_rPr.find(_q("i"))
                if i_elem is None:
                    i_elem = etree.SubElement(new_rPr, _q("i"))
                i_elem.set(_q("val"), "true")
            if saved_underline:
                u_elem = new_rPr.find(_q("u"))
                if u_elem is None:
                    u_elem = etree.SubElement(new_rPr, _q("u"))
                u_elem.set(_q("val"), saved_underline)

            # Insert rPr as first child of run
            r_elem.insert(0, new_rPr)


def _append_run(
    p_elem,
    text: str,
    bold: bool = False,
    italic: bool = False,
    underline: bool = False,
) -> None:
    """Append a <w:r> with optional inline b/i/u to a paragraph element."""
    r_elem = etree.SubElement(p_elem, _q("r"))

    if bold or italic or underline:
        rPr = etree.SubElement(r_elem, _q("rPr"))
        if bold:
            etree.SubElement(rPr, _q("b"))
        if italic:
            etree.SubElement(rPr, _q("i"))
        if underline:
            u = etree.SubElement(rPr, _q("u"))
            u.set(_q("val"), "single")

    if text:
        t_elem = etree.SubElement(r_elem, _q("t"))
        t_elem.text = text
        t_elem.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def _generate_from_content(
    template_path: str,
    content_path: str,
    style_mapping: dict[str, Any],
    content_structure: dict[str, Any],
    template_analysis: dict[str, Any] | None = None,
) -> bytes:
    """Use the content docx body, apply format profiles' direct formatting."""

    # Read both ZIPs
    with open(template_path, "rb") as f:
        tpl_zip = f.read()
    with open(content_path, "rb") as f:
        cnt_zip = f.read()

    tpl_z = zipfile.ZipFile(io.BytesIO(tpl_zip), "r")
    cnt_z = zipfile.ZipFile(io.BytesIO(cnt_zip), "r")

    # Parse template document.xml for section properties (page layout)
    tpl_doc_xml = tpl_z.read("word/document.xml")
    tpl_doc_tree = etree.fromstring(tpl_doc_xml)
    tpl_body = tpl_doc_tree.find(_q("body"))
    tpl_sectPr = None
    if tpl_body is not None:
        sp = tpl_body.find(_q("sectPr"))
        if sp is not None:
            tpl_sectPr = copy.deepcopy(sp)

    # Parse content document.xml
    cnt_doc_xml = cnt_z.read("word/document.xml")
    cnt_tree = etree.fromstring(cnt_doc_xml)
    cnt_body = cnt_tree.find(_q("body"))

    if cnt_body is None:
        raise ValueError("No body in content document")

    # Build profile lookup and index mapping
    profiles = _build_profile_lookup(template_analysis, style_mapping)
    index_to_profile = _build_index_to_profile(style_mapping)
    default_profile = profiles.get("__default__", {})

    # Apply format profiles to each paragraph
    paragraphs_modified = 0
    for para_idx, p_elem in enumerate(cnt_body.findall(_q("p"))):
        profile_id = index_to_profile.get(para_idx)
        if profile_id and profile_id in profiles:
            profile = profiles[profile_id]
        else:
            profile = default_profile

        if profile:
            _apply_profile_to_paragraph(p_elem, profile, keep_numPr=False)
        paragraphs_modified += 1

    print(f"  [generate] Applied format profiles to {paragraphs_modified} paragraphs", flush=True)

    # Replace body-level section properties with template's
    if tpl_sectPr is not None:
        existing_sectPr = cnt_body.find(_q("sectPr"))
        if existing_sectPr is not None:
            cnt_body.remove(existing_sectPr)
        cnt_body.append(copy.deepcopy(tpl_sectPr))

    # Serialize modified content document.xml
    new_doc_xml = etree.tostring(
        cnt_tree, xml_declaration=True, encoding="UTF-8", standalone=True
    )

    # Build output ZIP: use content as base but replace style/layout files
    output_buf = io.BytesIO()
    output_zip = zipfile.ZipFile(output_buf, "w", zipfile.ZIP_DEFLATED)

    template_files = {
        "word/styles.xml",
        "word/theme/theme1.xml",
        "word/fontTable.xml",
    }

    for item in cnt_z.infolist():
        if item.filename == "word/document.xml":
            output_zip.writestr(item, new_doc_xml)
        elif item.filename in template_files:
            try:
                output_zip.writestr(item, tpl_z.read(item.filename))
            except KeyError:
                output_zip.writestr(item, cnt_z.read(item.filename))
        else:
            output_zip.writestr(item, cnt_z.read(item.filename))

    tpl_z.close()
    cnt_z.close()
    output_zip.close()

    return output_buf.getvalue()


def _generate_from_template(
    template_path: str,
    style_mapping: dict[str, Any],
    content_structure: dict[str, Any],
    template_analysis: dict[str, Any] | None = None,
) -> bytes:
    """Fallback: use template body, add paragraphs with format profiles applied."""

    with open(template_path, "rb") as f:
        tpl_zip = f.read()

    tpl_z = zipfile.ZipFile(io.BytesIO(tpl_zip), "r")
    doc_xml = tpl_z.read("word/document.xml")
    doc_tree = etree.fromstring(doc_xml)

    body = doc_tree.find(_q("body"))
    if body is None:
        raise ValueError("No body element")

    sectPr = body.find(_q("sectPr"))
    for elem in [c for c in body if c.tag in (_q("p"), _q("tbl"))]:
        body.remove(elem)

    # Build profile lookup and index mapping
    profiles = _build_profile_lookup(template_analysis, style_mapping)
    index_to_profile = _build_index_to_profile(style_mapping)
    default_profile = profiles.get("__default__", {})

    paragraphs = content_structure.get("paragraphs", [])
    for p in paragraphs:
        idx = p["index"]
        text = p.get("text", "")

        profile_id = index_to_profile.get(idx)
        if profile_id and profile_id in profiles:
            profile = profiles[profile_id]
        else:
            profile = default_profile

        p_elem = etree.SubElement(body, _q("p"))

        # Create runs first (with inline bold/italic/underline) so that
        # _apply_profile_to_paragraph can apply the profile's run formatting
        # while preserving the inline semantic marks.
        runs = p.get("runs") or []
        if runs:
            for run in runs:
                _append_run(
                    p_elem,
                    run.get("text", ""),
                    run.get("bold", False),
                    run.get("italic", False),
                    run.get("underline", False),
                )
        elif text:
            _append_run(p_elem, text, False, False, False)

        # Apply format profile (paragraph + run properties)
        if profile:
            _apply_profile_to_paragraph(p_elem, profile, keep_numPr=False)

    if sectPr is not None:
        body.append(sectPr)

    new_doc_xml = etree.tostring(
        doc_tree, xml_declaration=True, encoding="UTF-8", standalone=True
    )

    output_buf = io.BytesIO()
    output_zip = zipfile.ZipFile(output_buf, "w", zipfile.ZIP_DEFLATED)
    for item in tpl_z.infolist():
        if item.filename == "word/document.xml":
            output_zip.writestr(item, new_doc_xml)
        else:
            output_zip.writestr(item, tpl_z.read(item.filename))

    tpl_z.close()
    output_zip.close()
    return output_buf.getvalue()
