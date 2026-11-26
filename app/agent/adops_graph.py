import logging
from typing import Any, Dict, List, Optional, TypedDict
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import select

from app.agent.planner import plan_adops_actions
from app.db.postgres import agent_session_factory
from app.mcp.adace_server import (
    add_negative_keyword,
    adjust_keyword_bid,
    find_bleeding_search_terms,
    find_oob_scaling_candidates,
    get_campaign_performance,
    get_seller_guardrails,
    scale_campaign_budget,
)
from app.models.agent import AgentAuditEvent, AgentWorkflowRun

logger = logging.getLogger(__name__)


# =============================================================================
# 1. AGENT STATE DEFINITION
# =============================================================================


class AdOpsAgentState(TypedDict, total=False):
    """LangGraph AdOps Agent State schema."""

    thread_id: str
    seller_id: int
    objective: str
    guardrails: Dict[str, Any]
    analytics: Dict[str, Any]
    proposed_plan: Dict[str, Any]
    proposed_actions: List[Dict[str, Any]]
    auto_executed_actions: List[Dict[str, Any]]
    tier3_pending_actions: List[Dict[str, Any]]
    hitl_decision: Optional[Dict[str, Any]]
    final_summary: Dict[str, Any]
    status: str


# =============================================================================
# 2. POSTGRESQL PERSISTENCE HELPERS
# =============================================================================


async def record_audit_event(
    thread_id: str,
    seller_id: int,
    node_name: str,
    event_type: str,
    tier: Optional[int] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """Record an audit trail event in PostgreSQL."""
    try:
        async with agent_session_factory() as session:
            evt = AgentAuditEvent(
                thread_id=thread_id,
                seller_id=seller_id,
                node_name=node_name,
                event_type=event_type,
                tier=tier,
                payload=payload,
            )
            session.add(evt)
            await session.commit()
    except Exception as exc:
        logger.debug("AgentAuditEvent logging fallback/mocked: %s", exc)


async def record_workflow_run_update(
    thread_id: str,
    seller_id: int,
    status: str,
    objective: str = "",
    proposed_plan: Optional[Dict[str, Any]] = None,
    pending_hitl: Optional[List[Dict[str, Any]]] = None,
    summary: Optional[Dict[str, Any]] = None,
    approved_by: Optional[str] = None,
) -> None:
    """Upsert the workflow run status in PostgreSQL."""
    try:
        async with agent_session_factory() as session:
            stmt = select(AgentWorkflowRun).where(AgentWorkflowRun.thread_id == thread_id)
            res = await session.execute(stmt)
            run = res.scalar_one_or_none()

            if not run:
                run = AgentWorkflowRun(
                    thread_id=thread_id,
                    seller_id=seller_id,
                    status=status,
                    objective=objective,
                    proposed_plan=proposed_plan,
                    pending_hitl_actions=pending_hitl,
                    execution_summary=summary,
                    approved_by=approved_by,
                )
                session.add(run)
            else:
                run.status = status
                if objective:
                    run.objective = objective
                if proposed_plan is not None:
                    run.proposed_plan = proposed_plan
                if pending_hitl is not None:
                    run.pending_hitl_actions = pending_hitl
                if summary is not None:
                    run.execution_summary = summary
                if approved_by is not None:
                    run.approved_by = approved_by

            await session.commit()
    except Exception as exc:
        logger.debug("AgentWorkflowRun update fallback/mocked: %s", exc)


# =============================================================================
# 3. WORKFLOW GRAPH NODES
# =============================================================================


async def analyze_account(state: AdOpsAgentState) -> Dict[str, Any]:
    """Node 1: Call FastMCP analytics tools to inspect seller guardrails, metrics, and candidates."""
    seller_id = state["seller_id"]
    thread_id = state["thread_id"]

    # Call FastMCP read-only tools
    guardrails = await get_seller_guardrails(seller_id=seller_id)
    performance = await get_campaign_performance(seller_id=seller_id)
    bleeders = await find_bleeding_search_terms(seller_id=seller_id)
    oob_candidates = await find_oob_scaling_candidates(seller_id=seller_id)

    analytics = {
        "campaign_performance": performance,
        "bleeding_search_terms": bleeders,
        "oob_scaling_candidates": oob_candidates,
    }

    # Record audit event
    await record_audit_event(
        thread_id=thread_id,
        seller_id=seller_id,
        node_name="analyze_account",
        event_type="analysis",
        payload={
            "guardrails": guardrails,
            "campaigns_count": len(performance),
            "bleeders_count": len(bleeders),
            "oob_candidates_count": len(oob_candidates),
        },
    )

    await record_workflow_run_update(
        thread_id=thread_id,
        seller_id=seller_id,
        status="running",
        objective=state.get("objective", ""),
    )

    return {
        "guardrails": guardrails,
        "analytics": analytics,
        "status": "running",
    }


async def plan_actions(state: AdOpsAgentState) -> Dict[str, Any]:
    """Node 2: Plan Tier 1, Tier 2, and Tier 3 actions using Mock or Gemini planner."""
    seller_id = state["seller_id"]
    thread_id = state["thread_id"]
    guardrails = state.get("guardrails", {})
    analytics = state.get("analytics", {})
    objective = state.get("objective", "")

    # Execute dual-mode planner
    plan = await plan_adops_actions(
        seller_id=seller_id,
        guardrails=guardrails,
        analytics=analytics,
        objective=objective,
    )

    all_actions = plan.get("all_actions", [])
    tier3_actions = plan.get("tier3_actions", [])

    await record_audit_event(
        thread_id=thread_id,
        seller_id=seller_id,
        node_name="plan_actions",
        event_type="plan_created",
        payload=plan,
    )

    await record_workflow_run_update(
        thread_id=thread_id,
        seller_id=seller_id,
        status="running",
        proposed_plan=plan,
        pending_hitl=tier3_actions,
    )

    return {
        "proposed_plan": plan,
        "proposed_actions": all_actions,
        "tier3_pending_actions": tier3_actions,
        "auto_executed_actions": [],
    }


async def execute_autonomous_actions(state: AdOpsAgentState) -> Dict[str, Any]:
    """Node 3: Execute Tier 1 (negative keywords) & Tier 2 (bids), and pre-approved Tier 3 actions."""
    seller_id = state["seller_id"]
    thread_id = state["thread_id"]
    guardrails = state.get("guardrails", {})
    proposed = state.get("proposed_actions", [])
    tier3_pending = list(state.get("tier3_pending_actions", []))

    executed_results: List[Dict[str, Any]] = []

    # 1. Execute Tier 1 actions autonomously
    for action in proposed:
        if action.get("tier") == 1 and action.get("action_type") == "add_negative_keyword":
            res = await add_negative_keyword(
                seller_id=seller_id,
                campaign_str_id=action["campaign_str_id"],
                keyword_text=action["keyword_text"],
                match_type=action.get("match_type", "NEGATIVE_EXACT"),
                reason=action.get("reason", "Autonomous bleeder negation"),
            )
            executed_results.append(res)

    # 2. Execute Tier 2 actions autonomously
    for action in proposed:
        if action.get("tier") == 2 and action.get("action_type") == "adjust_keyword_bid":
            res = await adjust_keyword_bid(
                seller_id=seller_id,
                keyword_id=action["keyword_id"],
                new_bid=action["proposed_bid"],
                reason=action.get("reason", "Autonomous bounded bid optimization"),
            )
            executed_results.append(res)

    # 3. Handle Tier 3 actions:
    # If seller is pre-approved (increase_budget_option == 1) or all actions require no HITL, execute autonomously!
    # If seller requires approval (increase_budget_option != 1), leave in tier3_pending_actions!
    increase_budget_option = guardrails.get("increase_budget_option", 2)
    requires_hitl = guardrails.get("requires_hitl_approval", increase_budget_option != 1)

    if (increase_budget_option == 1 or not requires_hitl) and tier3_pending:
        for action in tier3_pending:
            res = await scale_campaign_budget(
                seller_id=seller_id,
                campaign_str_id=action["campaign_str_id"],
                proposed_budget=action["proposed_budget"],
                human_approved=False,  # Option 1 is pre-approved
                reason="Pre-approved autonomous Tier 3 budget scaling",
            )
            executed_results.append(res)
        tier3_pending = []  # All cleared

    await record_audit_event(
        thread_id=thread_id,
        seller_id=seller_id,
        node_name="execute_autonomous_actions",
        event_type="auto_executed",
        payload={
            "executed_count": len(executed_results),
            "executed_actions": executed_results,
            "tier3_pending_count": len(tier3_pending),
        },
    )

    await record_workflow_run_update(
        thread_id=thread_id,
        seller_id=seller_id,
        status="pending_approval" if tier3_pending else "running",
        pending_hitl=tier3_pending,
    )

    return {
        "auto_executed_actions": executed_results,
        "tier3_pending_actions": tier3_pending,
    }


def route_after_autonomous(state: AdOpsAgentState) -> str:
    """Conditional edge routing: pauses at HITL gate if Tier 3 actions need human review."""
    tier3_pending = state.get("tier3_pending_actions", [])
    guardrails = state.get("guardrails", {})
    increase_budget_option = guardrails.get("increase_budget_option", 2)
    requires_hitl = guardrails.get("requires_hitl_approval", increase_budget_option != 1)

    if tier3_pending and increase_budget_option != 1 and requires_hitl:
        return "human_approval_gate"
    return "finalize_report"


async def human_approval_gate(state: AdOpsAgentState) -> Dict[str, Any]:
    """Node 4: True LangGraph Interrupt Gate.

    Pauses execution when increase_budget_option != 1 and waits for external human decision.
    Upon resume via Command(resume=...), evaluates decision:
    - If approved: executes Tier 3 budget scaling with human_approved=True.
    - If rejected: skips mutation and marks workflow rejected.
    """
    seller_id = state["seller_id"]
    thread_id = state["thread_id"]
    tier3_pending = state.get("tier3_pending_actions", [])

    if not tier3_pending:
        return {"status": "completed"}

    # Update database status before pausing
    await record_audit_event(
        thread_id=thread_id,
        seller_id=seller_id,
        node_name="human_approval_gate",
        event_type="hitl_interrupted",
        tier=3,
        payload={"pending_actions": tier3_pending},
    )
    await record_workflow_run_update(
        thread_id=thread_id,
        seller_id=seller_id,
        status="pending_approval",
        pending_hitl=tier3_pending,
    )

    # -------------------------------------------------------------------------
    # LANGGRAPH TRUE INTERRUPT CALL
    # Execution pauses here until resumed via Command(resume={...})
    # -------------------------------------------------------------------------
    interrupt_payload = {
        "thread_id": thread_id,
        "seller_id": seller_id,
        "pending_actions": tier3_pending,
        "message": "Human approval required for Tier 3 budget scaling",
    }

    decision = interrupt(interrupt_payload)

    # -------------------------------------------------------------------------
    # RESUMED EXECUTION PATH
    # -------------------------------------------------------------------------
    approved = False
    reviewer = "AdAce Operator"
    notes = ""

    if isinstance(decision, dict):
        approved = bool(decision.get("approved", False))
        reviewer = str(decision.get("reviewer", "AdAce Operator"))
        notes = str(decision.get("notes", ""))

    hitl_executed: List[Dict[str, Any]] = []

    if approved:
        for action in tier3_pending:
            res = await scale_campaign_budget(
                seller_id=seller_id,
                campaign_str_id=action["campaign_str_id"],
                proposed_budget=action["proposed_budget"],
                human_approved=True,
                reason=f"Approved by {reviewer}: {notes}",
            )
            hitl_executed.append(res)

        await record_audit_event(
            thread_id=thread_id,
            seller_id=seller_id,
            node_name="human_approval_gate",
            event_type="hitl_resumed",
            tier=3,
            payload={
                "approved": True,
                "reviewer": reviewer,
                "notes": notes,
                "executed": hitl_executed,
            },
        )

        all_executed = list(state.get("auto_executed_actions", [])) + hitl_executed

        await record_workflow_run_update(
            thread_id=thread_id,
            seller_id=seller_id,
            status="completed",
            approved_by=reviewer,
            pending_hitl=[],
        )

        return {
            "hitl_decision": {"approved": True, "reviewer": reviewer, "notes": notes},
            "auto_executed_actions": all_executed,
            "tier3_pending_actions": [],
            "status": "completed",
        }
    else:
        # Rejected by human operator
        await record_audit_event(
            thread_id=thread_id,
            seller_id=seller_id,
            node_name="human_approval_gate",
            event_type="rejected",
            tier=3,
            payload={
                "approved": False,
                "reviewer": reviewer,
                "notes": notes,
                "reason": "Budget scaling rejected by human operator",
            },
        )

        await record_workflow_run_update(
            thread_id=thread_id,
            seller_id=seller_id,
            status="rejected",
            approved_by=reviewer,
            pending_hitl=[],
        )

        return {
            "hitl_decision": {"approved": False, "reviewer": reviewer, "notes": notes},
            "tier3_pending_actions": [],
            "status": "rejected",
        }


async def finalize_report(state: AdOpsAgentState) -> Dict[str, Any]:
    """Node 5: Compile execution summary, update PostgreSQL state, and complete run."""
    thread_id = state["thread_id"]
    seller_id = state["seller_id"]

    proposed = state.get("proposed_actions", [])
    executed = state.get("auto_executed_actions", [])
    hitl_decision = state.get("hitl_decision")

    current_status = state.get("status")
    if current_status != "rejected":
        final_status = "completed"
    else:
        final_status = "rejected"

    summary = {
        "thread_id": thread_id,
        "seller_id": seller_id,
        "status": final_status,
        "total_proposed_actions": len(proposed),
        "total_executed_actions": len(executed),
        "tier1_executed": sum(1 for a in executed if a.get("tier") == 1),
        "tier2_executed": sum(1 for a in executed if a.get("tier") == 2),
        "tier3_executed": sum(1 for a in executed if a.get("tier") == 3),
        "hitl_decision": hitl_decision,
    }

    event_type = "completed" if final_status == "completed" else "rejected"
    await record_audit_event(
        thread_id=thread_id,
        seller_id=seller_id,
        node_name="finalize_report",
        event_type=event_type,
        payload=summary,
    )

    await record_workflow_run_update(
        thread_id=thread_id,
        seller_id=seller_id,
        status=final_status,
        summary=summary,
    )

    return {
        "final_summary": summary,
        "status": final_status,
    }


# =============================================================================
# 4. GRAPH COMPILATION & SINGLETON RUNNER
# =============================================================================


def build_adops_workflow_graph(checkpointer: Optional[Any] = None):
    """Build and compile the 4-node LangGraph StateGraph with HITL interrupt capability."""
    builder = StateGraph(AdOpsAgentState)

    # Add workflow nodes
    builder.add_node("analyze_account", analyze_account)
    builder.add_node("plan_actions", plan_actions)
    builder.add_node("execute_autonomous_actions", execute_autonomous_actions)
    builder.add_node("human_approval_gate", human_approval_gate)
    builder.add_node("finalize_report", finalize_report)

    # Define execution edges
    builder.add_edge(START, "analyze_account")
    builder.add_edge("analyze_account", "plan_actions")
    builder.add_edge("plan_actions", "execute_autonomous_actions")

    # Conditional routing after autonomous actions
    builder.add_conditional_edges(
        "execute_autonomous_actions",
        route_after_autonomous,
        {
            "human_approval_gate": "human_approval_gate",
            "finalize_report": "finalize_report",
        },
    )

    builder.add_edge("human_approval_gate", "finalize_report")
    builder.add_edge("finalize_report", END)

    cp = checkpointer if checkpointer is not None else MemorySaver()
    return builder.compile(checkpointer=cp)


# Global checkpointer & workflow graph singleton
global_checkpointer = MemorySaver()
adops_graph = build_adops_workflow_graph(checkpointer=global_checkpointer)


def get_adops_workflow_graph():
    """Return the compiled AdOps workflow graph."""
    return adops_graph


async def run_adops_workflow(
    thread_id: str,
    seller_id: int,
    objective: str = "",
) -> Dict[str, Any]:
    """Execute the workflow until completion or until paused at the HITL approval gate."""
    config = {"configurable": {"thread_id": thread_id}}
    initial_state: AdOpsAgentState = {
        "thread_id": thread_id,
        "seller_id": seller_id,
        "objective": objective or "Autonomous AdOps campaign optimization with multi-tier guardrails",
    }

    # Run the graph
    await adops_graph.ainvoke(initial_state, config=config)

    # Inspect current state to determine if interrupted
    graph_state = await adops_graph.aget_state(config)
    values = graph_state.values

    # Determine status from graph tasks (if tasks has interrupt or next is human_approval_gate)
    is_interrupted = bool(graph_state.tasks and any(t.interrupts for t in graph_state.tasks))
    status = "pending_approval" if is_interrupted else values.get("status", "completed")

    plan_data = values.get("proposed_plan") or ({"all_actions": values.get("proposed_actions", [])} if values.get("proposed_actions") else None)

    return {
        "thread_id": thread_id,
        "seller_id": seller_id,
        "status": status,
        "objective": values.get("objective", objective),
        "guardrails": values.get("guardrails"),
        "proposed_plan": plan_data,
        "pending_hitl_actions": values.get("tier3_pending_actions", []),
        "auto_executed_actions": values.get("auto_executed_actions", []),
        "execution_summary": values.get("final_summary"),
        "hitl_decision": values.get("hitl_decision"),
    }


async def resume_adops_workflow(
    thread_id: str,
    approved: bool,
    reviewer: str = "AdAce Operator",
    notes: str = "",
) -> Dict[str, Any]:
    """Resume an interrupted workflow thread with a human operator approval or rejection."""
    config = {"configurable": {"thread_id": thread_id}}

    resume_payload = {
        "approved": approved,
        "reviewer": reviewer,
        "notes": notes,
    }

    # Resume graph via LangGraph Command
    await adops_graph.ainvoke(Command(resume=resume_payload), config=config)

    graph_state = await adops_graph.aget_state(config)
    values = graph_state.values

    plan_data = values.get("proposed_plan") or ({"all_actions": values.get("proposed_actions", [])} if values.get("proposed_actions") else None)

    return {
        "thread_id": thread_id,
        "seller_id": values.get("seller_id"),
        "status": values.get("status", "completed" if approved else "rejected"),
        "objective": values.get("objective", ""),
        "guardrails": values.get("guardrails"),
        "proposed_plan": plan_data,
        "pending_hitl_actions": values.get("tier3_pending_actions", []),
        "auto_executed_actions": values.get("auto_executed_actions", []),
        "execution_summary": values.get("final_summary"),
        "hitl_decision": values.get("hitl_decision"),
    }


async def get_workflow_state(thread_id: str) -> Optional[Dict[str, Any]]:
    """Inspect current in-memory checkpoint state for a thread."""
    config = {"configurable": {"thread_id": thread_id}}
    try:
        graph_state = await adops_graph.aget_state(config)
        if not graph_state or not graph_state.values:
            return None

        values = graph_state.values
        is_interrupted = bool(graph_state.tasks and any(t.interrupts for t in graph_state.tasks))
        status = "pending_approval" if is_interrupted else values.get("status", "completed")

        plan_data = values.get("proposed_plan") or ({"all_actions": values.get("proposed_actions", [])} if values.get("proposed_actions") else None)

        return {
            "thread_id": thread_id,
            "seller_id": values.get("seller_id"),
            "status": status,
            "objective": values.get("objective", ""),
            "guardrails": values.get("guardrails"),
            "proposed_plan": plan_data,
            "pending_hitl_actions": values.get("tier3_pending_actions", []),
            "auto_executed_actions": values.get("auto_executed_actions", []),
            "execution_summary": values.get("final_summary"),
            "hitl_decision": values.get("hitl_decision"),
        }
    except Exception:
        return None
