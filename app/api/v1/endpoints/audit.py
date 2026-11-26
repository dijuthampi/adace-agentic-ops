from datetime import datetime, timezone
from typing import List, Optional, Any
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.mysql import get_adace_db
from app.db.postgres import get_agent_db
from app.models.adace import AdAceStatusLog
from app.models.agent import AgentAuditEvent, AgentWorkflowRun
from app.schemas.audit import (
    AuditTrailItem,
    SellerWorkflowHistoryResponse,
    UnifiedAuditTrailResponse,
    WorkflowRunSummary,
)

router = APIRouter()


def _ensure_tz_aware(dt: Optional[datetime]) -> datetime:
    """Normalize datetime to timezone-aware UTC for accurate cross-database sorting."""
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@router.get(
    "/sellers/{seller_id}/trail",
    response_model=UnifiedAuditTrailResponse,
    summary="Get Unified Audit Trail (PostgreSQL Agent Events + MySQL Mutation Logs)",
    description=(
        "Queries both PostgreSQL (LangGraph agent node transitions & HITL approval events) "
        "and MySQL (AdAce status logs recording before/after budget and bid mutations), "
        "returning a unified, chronological compliance ledger strictly scoped to the seller."
    ),
)
async def get_unified_audit_trail(
    seller_id: int,
    pg_db: AsyncSession = Depends(get_agent_db),
    mysql_db: AsyncSession = Depends(get_adace_db),
) -> UnifiedAuditTrailResponse:
    # 1. Query PostgreSQL Agent Audit Events
    pg_stmt = (
        select(AgentAuditEvent)
        .where(AgentAuditEvent.seller_id == seller_id)
        .order_by(AgentAuditEvent.created_at.desc())
    )
    pg_res = await pg_db.execute(pg_stmt)
    pg_events = pg_res.scalars().all()

    # 2. Query MySQL AdAce Status Logs
    mysql_stmt = (
        select(AdAceStatusLog)
        .where(AdAceStatusLog.seller_id == seller_id)
        .order_by(AdAceStatusLog.run_date.desc())
    )
    mysql_res = await mysql_db.execute(mysql_stmt)
    mysql_logs = mysql_res.scalars().all()

    unified_items: List[AuditTrailItem] = []

    # Map PostgreSQL agent events
    for evt in pg_events:
        details = evt.payload or {}
        action_name = None
        if evt.event_type == "auto_executed":
            action_name = "AUTONOMOUS_EXECUTION"
        elif evt.event_type == "hitl_interrupted":
            action_name = "HITL_APPROVAL_SUSPENDED"
        elif evt.event_type == "hitl_resumed":
            action_name = "HITL_APPROVED_RESUMED"
        elif evt.event_type == "rejected":
            action_name = "HITL_ACTION_REJECTED"

        unified_items.append(
            AuditTrailItem(
                source="postgres_agent_audit",
                timestamp=evt.created_at,
                seller_id=evt.seller_id,
                thread_id=evt.thread_id,
                node_name=evt.node_name,
                event_type=evt.event_type,
                tier=evt.tier,
                action=action_name,
                campaign_str_id=details.get("campaign_str_id") or details.get("pending_actions", [{}])[0].get("campaign_str_id") if isinstance(details.get("pending_actions"), list) and details.get("pending_actions") else None,
                rule=details.get("rule"),
                status_text=f"Agent workflow node [{evt.node_name}] emitted {evt.event_type}",
                details=details,
            )
        )

    # Map MySQL status mutation logs
    for log in mysql_logs:
        prev_val = None
        cur_val = None
        action_label = f"MODULE_{log.module_id}_ACTION_{log.action_id}"

        if log.campaign_cur_budget is not None:
            prev_val = float(log.campaign_prv_budget) if log.campaign_prv_budget is not None else None
            cur_val = float(log.campaign_cur_budget)
            action_label = "CAMPAIGN_BUDGET_MUTATION"
        elif log.keywd_cur_bid is not None:
            prev_val = float(log.keywd_prev_bid) if log.keywd_prev_bid is not None else None
            cur_val = float(log.keywd_cur_bid)
            action_label = "KEYWORD_BID_MUTATION"
        elif log.neg_keywd_product is not None:
            action_label = "NEGATIVE_KEYWORD_ADDED"

        log_details: dict[str, Any] = {}
        if log.neg_keywd_product:
            log_details["neg_keywd_product"] = log.neg_keywd_product
        if log.cost is not None and float(log.cost) > 0:
            log_details["cost"] = float(log.cost)
        if log.clicks:
            log_details["clicks"] = log.clicks
        if log.orders:
            log_details["orders"] = log.orders

        unified_items.append(
            AuditTrailItem(
                source="mysql_status_log",
                timestamp=log.run_date,
                seller_id=log.seller_id,
                campaign_str_id=log.campaign_str_id,
                rule=log.rule,
                action=action_label,
                status_text=log.status_text,
                prev_value=prev_val,
                cur_value=cur_val,
                details=log_details or None,
            )
        )

    # Sort unified trail chronologically descending
    unified_items.sort(key=lambda item: _ensure_tz_aware(item.timestamp), reverse=True)

    return UnifiedAuditTrailResponse(
        seller_id=seller_id,
        total_events=len(unified_items),
        postgres_events_count=len(pg_events),
        mysql_logs_count=len(mysql_logs),
        events=unified_items,
    )


@router.get(
    "/sellers/{seller_id}/workflows",
    response_model=SellerWorkflowHistoryResponse,
    summary="List Workflow Execution History for a Seller",
    description="Returns all LangGraph workflow runs for the seller ordered by created_at descending.",
)
async def get_seller_workflows(
    seller_id: int,
    pg_db: AsyncSession = Depends(get_agent_db),
) -> SellerWorkflowHistoryResponse:
    stmt = (
        select(AgentWorkflowRun)
        .where(AgentWorkflowRun.seller_id == seller_id)
        .order_by(AgentWorkflowRun.created_at.desc())
    )
    res = await pg_db.execute(stmt)
    runs = res.scalars().all()

    workflow_summaries: List[WorkflowRunSummary] = []
    for r in runs:
        pending_count = len(r.pending_hitl_actions or [])
        executed_count = 0
        if isinstance(r.execution_summary, dict):
            executed_count = r.execution_summary.get("total_executed_actions", 0)

        workflow_summaries.append(
            WorkflowRunSummary(
                thread_id=r.thread_id,
                seller_id=r.seller_id,
                status=r.status,
                objective=r.objective,
                created_at=r.created_at,
                updated_at=r.updated_at,
                pending_hitl_count=pending_count,
                auto_executed_count=executed_count,
                approved_by=r.approved_by,
                summary=r.execution_summary,
            )
        )

    return SellerWorkflowHistoryResponse(
        seller_id=seller_id,
        total_workflows=len(workflow_summaries),
        workflows=workflow_summaries,
    )
