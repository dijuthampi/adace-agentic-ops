from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RunWorkflowRequest(BaseModel):
    """Payload to initiate a new AdOps LangGraph workflow."""

    objective: Optional[str] = Field(
        "Autonomous AdOps campaign optimization with multi-tier guardrails",
        description="High-level goal for the agentic optimization run",
    )


class ResumeWorkflowRequest(BaseModel):
    """Payload to resume a paused LangGraph workflow with a human approval decision."""

    seller_id: int = Field(..., description="AdAce Seller ID for tenant verification")
    approved: bool = Field(..., description="Whether the human operator approved the pending actions")
    reviewer: str = Field("AdAce Operator", description="Name or identifier of the reviewer")
    notes: Optional[str] = Field("", description="Reviewer justifications or sign-off notes")


class AuditEventSchema(BaseModel):
    """Chronological event in the agent audit trail."""

    id: Optional[int] = None
    thread_id: str
    seller_id: int
    node_name: str
    event_type: str
    tier: Optional[int] = None
    payload: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None


class WorkflowRunResponse(BaseModel):
    """Current state and execution summary of a LangGraph AdOps workflow run."""

    thread_id: str
    seller_id: int
    status: str = Field(..., description="running, pending_approval, completed, rejected, failed")
    objective: str = ""
    guardrails: Optional[Dict[str, Any]] = None
    proposed_plan: Optional[Any] = None
    pending_hitl_actions: List[Dict[str, Any]] = Field(default_factory=list)
    auto_executed_actions: List[Dict[str, Any]] = Field(default_factory=list)
    execution_summary: Optional[Dict[str, Any]] = None
    hitl_decision: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class WorkflowDetailResponse(BaseModel):
    """Detailed view of workflow run including chronological audit trail."""

    workflow: WorkflowRunResponse
    audit_trail: List[AuditEventSchema] = Field(default_factory=list)
