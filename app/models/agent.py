from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    String,
    Integer,
    Text,
    DateTime,
    JSON,
    ForeignKey,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import AgentBase


class AgentWorkflowRun(AgentBase):
    """PostgreSQL entity storing LangGraph agentic workflow execution runs and HITL state."""

    __tablename__ = "agent_workflow_runs"

    thread_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    seller_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="running", index=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    proposed_plan: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    pending_hitl_actions: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    execution_summary: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    audit_events: Mapped[List["AgentAuditEvent"]] = relationship(
        "AgentAuditEvent",
        back_populates="workflow_run",
        cascade="all, delete-orphan",
        order_by="AgentAuditEvent.created_at.asc()",
        lazy="selectin",
    )


class AgentAuditEvent(AgentBase):
    """Immutable audit trail of node transitions, autonomous actions, and HITL decisions."""

    __tablename__ = "agent_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("agent_workflow_runs.thread_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seller_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    node_name: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    tier: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    workflow_run: Mapped["AgentWorkflowRun"] = relationship(
        "AgentWorkflowRun",
        back_populates="audit_events",
    )
