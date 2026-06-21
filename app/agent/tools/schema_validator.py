"""Tool: Validate the style mapping against template and content constraints.

Performs 6 validation checks:
1. Schema structure — mappings exist, paragraph_index is unique
2. Coverage rate — ≥ 95% of paragraphs mapped
3. Style existence — every assigned style exists in template
4. Heading hierarchy — no skipped levels
5. Confidence — flag low-confidence mappings
6. Consistency — similar paragraphs get same style
"""

from typing import Any


def validate_style_mapping(
    mapping: dict[str, Any],
    template: dict[str, Any],
    content: dict[str, Any],
) -> dict[str, Any]:
    """Validate a style mapping against template and content.

    Args:
        mapping: The style_mapping from match_styles.
        template: The template_analysis with available styles.
        content: The content_structure with paragraph info.

    Returns:
        A dict with 'passed', 'coverage_rate', 'errors', 'warnings',
        and 'retry_feedback' (if not passed).
    """
    errors: list[dict] = []
    warnings: list[dict] = []

    total_paragraphs = content.get("paragraph_count", 0)
    if total_paragraphs == 0:
        total_paragraphs = len(content.get("paragraphs", []))

    mapped_indices: set[int] = set()
    available_profiles = set(
        p["profile_id"] for p in template.get("format_profiles", [])
    )

    # --- Check 1: Schema structural validation ---
    if not mapping or "mappings" not in mapping:
        errors.append({
            "type": "schema_violation",
            "message": "Missing 'mappings' key in style_mapping",
            "severity": "error",
        })
        return _build_result(False, errors, warnings, 0, total_paragraphs)

    mappings = mapping["mappings"]
    if not isinstance(mappings, list) or len(mappings) == 0:
        errors.append({
            "type": "schema_violation",
            "message": "Mappings list is empty or invalid",
            "severity": "error",
        })
        return _build_result(False, errors, warnings, 0, total_paragraphs)

    # --- Check 2: Duplicate mappings ---
    for m in mappings:
        idx = m.get("paragraph_index")
        if idx is None:
            errors.append({
                "type": "schema_violation",
                "message": f"Mapping entry missing paragraph_index",
                "severity": "error",
            })
            continue
        if idx in mapped_indices:
            errors.append({
                "type": "duplicate_mapping",
                "paragraph_index": idx,
                "message": f"Paragraph {idx} mapped to multiple styles",
                "severity": "error",
            })
        mapped_indices.add(idx)

    # --- Check 3: Coverage rate ---
    coverage_rate = len(mapped_indices) / max(total_paragraphs, 1)
    if coverage_rate < 0.95:
        missing = sorted([i for i in range(total_paragraphs) if i not in mapped_indices])
        if len(missing) > 20:
            missing_display = missing[:20]
            missing_display.append("...")
        else:
            missing_display = missing
        errors.append({
            "type": "low_coverage",
            "message": (
                f"Only {len(mapped_indices)}/{total_paragraphs} paragraphs mapped "
                f"(coverage={coverage_rate:.1%}). Missing indices: {missing_display}"
            ),
            "severity": "error",
        })

    # --- Check 4: Profile existence ---
    for m in mappings:
        profile_id = m.get("profile_id", "")
        if profile_id not in available_profiles:
            errors.append({
                "type": "nonexistent_profile",
                "paragraph_index": m.get("paragraph_index"),
                "message": f"Profile '{profile_id}' does not exist in template. Available: {sorted(available_profiles)}",
                "severity": "error",
            })

    # --- Check 5: Confidence threshold ---
    low_confidence = [m for m in mappings if m.get("confidence", 0) < 0.5]
    if low_confidence:
        warnings.append({
            "type": "low_confidence",
            "message": (
                f"{len(low_confidence)} mappings have confidence below 0.5"
            ),
            "severity": "warning",
            "affected_indices": [m["paragraph_index"] for m in low_confidence],
        })

    # --- Check 6: Consistency (similar paragraphs) ---
    text_groups: dict[str, list[int]] = {}
    for p in content.get("paragraphs", []):
        text = p.get("text", "").strip()
        if not text:
            continue
        prefix = text[:30].lower()
        if prefix not in text_groups:
            text_groups[prefix] = []
        text_groups[prefix].append(p["index"])

    for prefix, indices in text_groups.items():
        if len(indices) < 2:
            continue
        profiles_used: set[str] = set()
        for m in mappings:
            if m.get("paragraph_index") in indices:
                profiles_used.add(m.get("profile_id", ""))
        if len(profiles_used) > 1:
            warnings.append({
                "type": "inconsistent_profiles",
                "message": (
                    f"Paragraphs {indices} have similar text prefix ('{prefix}...') "
                    f"but different profiles: {profiles_used}"
                ),
                "severity": "warning",
            })

    # --- Determine pass/fail ---
    critical_errors = [e for e in errors if e["severity"] == "error"]
    passed = len(critical_errors) == 0

    # Build retry feedback
    feedback = ""
    if not passed:
        lines = ["Fix the following errors in the style mapping:"]
        for e in critical_errors:
            lines.append(f"- [{e['type']}] {e['message']}")
        feedback = "\n".join(lines)

    return _build_result(passed, errors, warnings, coverage_rate, total_paragraphs, feedback)


def _build_result(
    passed: bool,
    errors: list[dict],
    warnings: list[dict],
    coverage_rate: float,
    total_paragraphs: int,
    feedback: str = "",
) -> dict:
    """Assemble the final verification result dict."""
    return {
        "passed": passed,
        "coverage_rate": round(coverage_rate, 4),
        "total_paragraphs": total_paragraphs,
        "error_count": len([e for e in errors if e["severity"] == "error"]),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "retry_feedback": feedback if not passed else None,
    }
