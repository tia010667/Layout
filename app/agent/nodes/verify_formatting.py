"""Node 4: Verify the style mapping and route conditionally.

Performs schema validation, coverage check, style existence check,
heading hierarchy validation, confidence check, and consistency check.

On failure: routes back to match_styles (retry) or to error (max retries).
On success: routes to generate_docx.
"""

from app.agent.state import AgentState
from app.agent.tools.schema_validator import validate_style_mapping
from app.config import settings


async def verify_formatting(state: AgentState) -> dict:
    """Validate the style mapping produced by match_styles.

    Runs all verification checks and emits a verification_result.
    The graph's conditional edge function reads this result to route.
    """
    mapping = state.get("style_mapping")
    template = state.get("template_analysis")
    content = state.get("content_structure")
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", settings.max_retries)

    _failed_verification = {
        "passed": False,
        "coverage_rate": 0,
        "total_paragraphs": 0,
        "error_count": 1,
        "warning_count": 0,
        "errors": [],
        "warnings": [],
        "retry_feedback": "",
    }

    if not mapping:
        _failed_verification["errors"] = [{"type": "missing_data", "message": "No style mapping to verify", "severity": "error"}]
        _failed_verification["retry_feedback"] = "No style mapping was produced"
        # Allow retry — the LLM call may have failed transiently
        new_retry_count = retry_count + 1
        if new_retry_count >= max_retries:
            return {
                "verification_result": _failed_verification,
                "retry_count": new_retry_count,
                "error": (
                    f"Verification failed after {new_retry_count} attempts. "
                    f"Last feedback: No style mapping was produced"
                ),
                "status": "failed",
            }
        else:
            return {
                "verification_result": _failed_verification,
                "verification_feedback": "No style mapping was produced — the LLM call may have failed. Please try again.",
                "retry_count": new_retry_count,
                "status": "matching_styles",
            }
    if not template:
        _failed_verification["errors"] = [{"type": "missing_data", "message": "No template analysis available", "severity": "error"}]
        return {
            "verification_result": _failed_verification,
            "error": "No template analysis available for verification",
            "status": "failed",
        }
    if not content:
        _failed_verification["errors"] = [{"type": "missing_data", "message": "No content structure available", "severity": "error"}]
        return {
            "verification_result": _failed_verification,
            "error": "No content structure available for verification",
            "status": "failed",
        }

    try:
        result = validate_style_mapping(mapping, template, content)

        if result["passed"]:
            return {
                "verification_result": result,
                "verification_feedback": None,
                "status": "generating_docx",
            }
        else:
            new_retry_count = retry_count + 1
            if new_retry_count >= max_retries:
                return {
                    "verification_result": result,
                    "retry_count": new_retry_count,
                    "error": (
                        f"Verification failed after {new_retry_count} attempts. "
                        f"Last feedback: {result.get('retry_feedback', 'Unknown error')}"
                    ),
                    "status": "failed",
                }
            else:
                return {
                    "verification_result": result,
                    "verification_feedback": result.get("retry_feedback", ""),
                    "retry_count": new_retry_count,
                    "status": "matching_styles",
                }

    except Exception as e:
        return {
            "error": f"[verify_formatting] {type(e).__name__}: {str(e)}",
            "status": "failed",
        }
