from datetime import datetime, timezone
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.adops_graph import (
    get_workflow_state,
    resume_adops_workflow,
    run_adops_workflow,
)
from app.db.postgres import get_agent_db
from app.models.agent import AgentAuditEvent, AgentWorkflowRun
from app.schemas.workflow import (
    AuditEventSchema,
    ResumeWorkflowRequest,
    RunWorkflowRequest,
    WorkflowDetailResponse,
    WorkflowRunResponse,
)

router = APIRouter()


@router.post(
    "/sellers/{seller_id}/run",
    response_model=WorkflowRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start an Autonomous LangGraph AdOps Workflow Run",
    description=(
        "Initiates an agentic optimization run for the given seller. "
        "Executes Tier 1 and Tier 2 actions autonomously. "
        "If Tier 3 actions require human approval, suspends execution at 'pending_approval'."
    ),
)
async def start_workflow_run(
    seller_id: int,
    req: RunWorkflowRequest = RunWorkflowRequest(),
) -> WorkflowRunResponse:
    thread_id = str(uuid.uuid4())
    result = await run_adops_workflow(
        thread_id=thread_id,
        seller_id=seller_id,
        objective=req.objective or "",
    )

    return WorkflowRunResponse(
        thread_id=result["thread_id"],
        seller_id=result["seller_id"],
        status=result["status"],
        objective=result.get("objective", ""),
        guardrails=result.get("guardrails"),
        proposed_plan=result.get("proposed_plan"),
        pending_hitl_actions=result.get("pending_hitl_actions") or [],
        auto_executed_actions=result.get("auto_executed_actions") or [],
        execution_summary=result.get("execution_summary"),
        hitl_decision=result.get("hitl_decision"),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@router.get(
    "/{thread_id}",
    response_model=WorkflowDetailResponse,
    summary="Inspect Workflow Run State & Audit Trail",
    description="Retrieves the full execution state and chronological audit event trail from PostgreSQL.",
)
async def get_workflow(
    thread_id: str,
    db: AsyncSession = Depends(get_agent_db),
) -> WorkflowDetailResponse:
    # 1. Query workflow run from PostgreSQL
    stmt = (
        select(AgentWorkflowRun)
        .where(AgentWorkflowRun.thread_id == thread_id)
        .options(selectinload(AgentWorkflowRun.audit_events))
    )
    res = await db.execute(stmt)
    run = res.scalar_one_or_none()

    # 2. Check in-memory checkpoint state as backup/supplement
    memory_state = await get_workflow_state(thread_id)

    if not run and not memory_state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow thread '{thread_id}' not found",
        )

    if run:
        workflow_res = WorkflowRunResponse(
            thread_id=run.thread_id,
            seller_id=run.seller_id,
            status=run.status,
            objective=run.objective or "",
            guardrails=memory_state.get("guardrails") if memory_state else None,
            proposed_plan=run.proposed_plan,
            pending_hitl_actions=run.pending_hitl_actions or [],
            auto_executed_actions=memory_state.get("auto_executed_actions", []) if memory_state else [],
            execution_summary=run.execution_summary,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

        audit_events = [
            AuditEventSchema(
                id=evt.id,
                thread_id=evt.thread_id,
                seller_id=evt.seller_id,
                node_name=evt.node_name,
                event_type=evt.event_type,
                tier=evt.tier,
                payload=evt.payload,
                created_at=evt.created_at,
            )
            for evt in (run.audit_events or [])
        ]
    else:
        workflow_res = WorkflowRunResponse(
            thread_id=memory_state["thread_id"],
            seller_id=memory_state["seller_id"],
            status=memory_state["status"],
            objective=memory_state["objective"],
            guardrails=memory_state.get("guardrails"),
            proposed_plan=memory_state.get("proposed_plan"),
            pending_hitl_actions=memory_state.get("pending_hitl_actions", []),
            auto_executed_actions=memory_state.get("auto_executed_actions", []),
            execution_summary=memory_state.get("execution_summary"),
        )
        audit_events = []

    return WorkflowDetailResponse(
        workflow=workflow_res,
        audit_trail=audit_events,
    )


@router.post(
    "/{thread_id}/resume",
    response_model=WorkflowRunResponse,
    summary="Resume a Paused Workflow with Human Decision",
    description=(
        "Enforces tenant ownership (seller_id) and resumes a thread suspended at 'pending_approval'. "
        "When approved=True, executes the Tier 3 budget scaling actions. "
        "When approved=False, skips budget mutations and marks workflow rejected."
    ),
)
async def resume_workflow(
    thread_id: str,
    req: ResumeWorkflowRequest,
    db: AsyncSession = Depends(get_agent_db),
) -> WorkflowRunResponse:
    # 1. Tenant ownership verification via PostgreSQL or memory state
    stmt = select(AgentWorkflowRun).where(AgentWorkflowRun.thread_id == thread_id)
    res = await db.execute(stmt)
    run = res.scalar_one_or_none()

    current_state = await get_workflow_state(thread_id)

    target_seller_id = run.seller_id if run else (current_state.get("seller_id") if current_state else None)

    if target_seller_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow thread '{thread_id}' not found",
        )

    # Multi-tenant isolation check: caller's seller_id must match workflow's seller_id
    if target_seller_id != req.seller_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Multi-tenant violation: Provided seller_id {req.seller_id} does not match "
                f"workflow tenant owner {target_seller_id}"
            ),
        )

    # Status check: only pending_approval workflows can be resumed
    current_status = run.status if run else current_state.get("status")
    if current_status != "pending_approval":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot resume workflow in '{current_status}' status. Only 'pending_approval' can be resumed.",
        )

    # 2. Resume LangGraph thread via Command(resume=...)
    result = await resume_adops_workflow(
        thread_id=thread_id,
        approved=req.approved,
        reviewer=req.reviewer,
        notes=req.notes or "",
    )

    return WorkflowRunResponse(
        thread_id=result["thread_id"],
        seller_id=result["seller_id"],
        status=result["status"],
        objective=result.get("objective", ""),
        guardrails=result.get("guardrails"),
        proposed_plan=result.get("proposed_plan"),
        pending_hitl_actions=result.get("pending_hitl_actions") or [],
        auto_executed_actions=result.get("auto_executed_actions") or [],
        execution_summary=result.get("execution_summary"),
        hitl_decision=result.get("hitl_decision"),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
