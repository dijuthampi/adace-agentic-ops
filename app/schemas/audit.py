from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AuditTrailItem(BaseModel):
    """Unified audit event from either PostgreSQL agent state or MySQL mutation status log."""

    source: str = Field(..., description="'postgres_agent_audit' or 'mysql_status_log'")
    timestamp: datetime = Field(..., description="Timestamp of the event or mutation")
    seller_id: int
    thread_id: Optional[str] = None
    node_name: Optional[str] = None
    event_type: Optional[str] = None
    tier: Optional[int] = None
    action: Optional[str] = None
    campaign_str_id: Optional[str] = None
    rule: Optional[str] = None
    status_text: Optional[str] = None
    prev_value: Optional[float] = None
    cur_value: Optional[float] = None
    details: Optional[Dict[str, Any]] = None


class UnifiedAuditTrailResponse(BaseModel):
    """Unified chronological audit ledger combining agent node transitions and database mutations."""

    seller_id: int
    total_events: int
    postgres_events_count: int
    mysql_logs_count: int
    events: List[AuditTrailItem] = Field(default_factory=list)


class WorkflowRunSummary(BaseModel):
    """Summary of a past or in-progress LangGraph workflow run for a seller."""

    thread_id: str
    seller_id: int
    status: str
    objective: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    pending_hitl_count: int = 0
    auto_executed_count: int = 0
    approved_by: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None


class SellerWorkflowHistoryResponse(BaseModel):
    """Chronological history of all agentic workflow runs scoped to a specific seller."""

    seller_id: int
    total_workflows: int
    workflows: List[WorkflowRunSummary] = Field(default_factory=list)
