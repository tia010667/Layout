"""StateGraph assembly — the architectural spine of the FormatAI Agent.

Assembles 6 nodes + conditional routing into a compiled LangGraph graph.
Provides run_agent() as the entry point for the API layer.
"""

import asyncio
import logging
import sys
from typing import Literal

# Setup logging to stdout so it's visible in the uvicorn terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("formatai")

from langgraph.graph import StateGraph, START, END

from app.agent.state import AgentState
from app.agent.nodes.parse_template import parse_template
from app.agent.nodes.analyze_content import analyze_content
from app.agent.nodes.match_styles import match_styles
from app.agent.nodes.verify_formatting import verify_formatting
from app.agent.nodes.generate_docx import generate_docx
from app.agent.nodes.output import output_node
from app.api.job_manager import job_manager
from app.config import settings


def route_after_verify(state: AgentState) -> Literal["generate", "retry", "error"]:
    """Conditional edge function for the verify_formatting node.

    Reads the verification_result and retry_count to decide routing:
    - passed → "generate" (continue to generate_docx)
    - failed, retry_count < max → "retry" (back to match_styles)
    - failed, retry_count >= max → "error" (terminal)
    - no result / error → "error" (terminal)
    """
    verification = state.get("verification_result") or {}
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", settings.max_retries)
    error = state.get("error")

    if verification.get("passed", False):
        logger.info("Verification passed → routing to generate_docx")
        return "generate"

    # If there's a terminal error (missing data, not retryable), go to error
    if error and ("No template analysis" in str(error) or "No content structure" in str(error)):
        logger.warning(f"Terminal error (missing data) → error")
        return "error"

    if retry_count < max_retries:
        logger.info(f"Verification failed (attempt {retry_count}/{max_retries}) → retrying match_styles")
        return "retry"

    logger.warning(f"Verification failed after {max_retries} attempts → error")
    return "error"


def build_graph() -> StateGraph:
    """Build and compile the FormatAI Agent StateGraph.

    Graph topology:
      START → parse_template → analyze_content → match_styles → verify_formatting
                                                                    │
                                            ┌───────────────────────┼───────────────────┐
                                            ▼                       ▼                   ▼
                                        generate              match_styles          handle_error
                                            │                 (retry loop)              │
                                            ▼                       │                   ▼
                                        output ←───────────────────┘                 END
                                            │
                                            ▼
                                           END
    """
    workflow = StateGraph(AgentState)

    # Add all nodes
    workflow.add_node("parse_template", parse_template)
    workflow.add_node("analyze_content", analyze_content)
    workflow.add_node("match_styles", match_styles)
    workflow.add_node("verify_formatting", verify_formatting)
    workflow.add_node("generate_docx", generate_docx)
    workflow.add_node("output", output_node)
    workflow.add_node("handle_error", _handle_error)

    # Linear edges: parse → analyze → match → verify
    workflow.add_edge(START, "parse_template")
    workflow.add_edge("parse_template", "analyze_content")
    workflow.add_edge("analyze_content", "match_styles")
    workflow.add_edge("match_styles", "verify_formatting")

    # Conditional branching after verification
    workflow.add_conditional_edges(
        "verify_formatting",
        route_after_verify,
        {
            "generate": "generate_docx",
            "retry": "match_styles",
            "error": "handle_error",
        }
    )

    # Finalization edges
    workflow.add_edge("generate_docx", "output")
    workflow.add_edge("output", END)
    workflow.add_edge("handle_error", END)

    return workflow.compile()


async def _handle_error(state: AgentState) -> dict:
    """Terminal error node — captures error details for frontend display."""
    error_msg = state.get("error", "Unknown error")
    verification = state.get("verification_result", {})
    retry_count = state.get("retry_count", 0)

    # Consolidate error info
    if verification and not verification.get("passed"):
        error_detail = (
            f"Verification failed after {retry_count + 1} attempt(s). "
            f"Last feedback: {verification.get('retry_feedback', 'N/A')}"
        )
    else:
        error_detail = str(error_msg)

    return {
        "error": error_detail,
        "status": "failed",
    }


def run_agent(job_id: str) -> asyncio.Task:
    """Launch the Agent graph for a given job as an async background task.

    This is a synchronous function that creates and returns an asyncio.Task.
    The task runs in the background — the API layer stores the task handle
    for lifecycle management (cancellation on job delete).

    Args:
        job_id: The job identifier.

    Returns:
        An asyncio.Task that runs the agent in the background.
    """

    async def _run():
        job = job_manager.get_job(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return

        logger.info(f"Agent starting for job {job_id}")

        try:
            # Build initial state from job record
            initial_state: AgentState = {
                "job_id": job_id,
                "template_path": job.template_path,
                "content_path": job.content_path,
                "template_filename": job.template_filename,
                "content_filename": job.content_filename,
                "template_analysis": None,
                "content_structure": None,
                "style_mapping": None,
                "verification_result": None,
                "retry_count": 0,
                "verification_feedback": None,
                "max_retries": settings.max_retries,
                "docx_buffer": None,
                "preview_html": None,
                "error": None,
                "status": "parsing_template",
            }

            # Update job status before starting
            job_manager.update_job(job_id, status="parsing_template")

            # Compile and run the graph
            graph = build_graph()

            # Stream through nodes, updating job_manager on each state change
            # Track accumulated state since each event only has partial updates
            accumulated_state: dict = {}
            async for event in graph.astream(initial_state):
                # event is a dict like {"node_name": {"field": value, ...}}
                for node_name, node_output in event.items():
                    status = node_output.get("status", "") if isinstance(node_output, dict) else ""
                    err = node_output.get("error", "") if isinstance(node_output, dict) else ""
                    has_buffer = "docx_buffer" in node_output if isinstance(node_output, dict) else False
                    print(f"  [Agent] Node '{node_name}' done → status={status}", flush=True)
                    if err:
                        print(f"  [Agent]   error: {err}", flush=True)
                    if has_buffer:
                        print(f"  [Agent]   docx_buffer captured ({len(node_output['docx_buffer'])} bytes)", flush=True)
                    logger.info(f"Node '{node_name}' completed")

                    if isinstance(node_output, dict):
                        # Merge into accumulated state
                        accumulated_state.update(node_output)

                        # Update job manager with latest state
                        updates = {}
                        if "status" in node_output:
                            updates["status"] = node_output["status"]
                        if "error" in node_output:
                            updates["error"] = node_output["error"]
                        if "retry_count" in node_output:
                            updates["retry_count"] = node_output["retry_count"]
                        if "verification_result" in node_output:
                            vr = node_output["verification_result"]
                            updates["coverage_rate"] = vr.get("coverage_rate")
                            updates["error_count"] = vr.get("error_count")
                            updates["warning_count"] = vr.get("warning_count")
                        # Capture docx_buffer when generate_docx emits it
                        if "docx_buffer" in node_output:
                            job_manager.update_job(
                                job_id,
                                docx_buffer=node_output["docx_buffer"],
                            )
                        # Capture preview_html when output node emits it
                        if "preview_html" in node_output:
                            job_manager.update_job(
                                job_id,
                                preview_html=node_output["preview_html"],
                            )

                        if updates:
                            job_manager.update_job(job_id, **updates)

            # After graph completes, store final results from accumulated state
            if accumulated_state.get("docx_buffer"):
                job_manager.update_job(
                    job_id,
                    docx_buffer=accumulated_state["docx_buffer"],
                )
            if accumulated_state.get("preview_html"):
                job_manager.update_job(
                    job_id,
                    preview_html=accumulated_state["preview_html"],
                )

            # Ensure final status is set
            job = job_manager.get_job(job_id)
            if job and job.status not in ("completed", "failed"):
                job_manager.update_job(job_id, status="completed")

            logger.info(f"Agent run completed for job {job_id}")

        except Exception as e:
            logger.exception(f"Agent run failed for job {job_id}: {e}")
            job_manager.update_job(
                job_id,
                status="failed",
                error=f"Agent execution error: {type(e).__name__}: {str(e)}",
            )

    # Create and return the background task
    return asyncio.create_task(_run())
