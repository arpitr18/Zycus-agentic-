"""Offline behavior tests: real data, synthetic edge cases, scripted native tool messages."""
import copy
import json
from datetime import timedelta
import pandas as pd
import pytest
from tam_agent.agent import Context, triage, decision_errors, DECISION_PROPERTIES
from tam_agent.data import load_accounts, load_tickets, load_usage
from tam_agent.kb import load_kb
from tam_agent.tools import TicketTools, date
from tam_agent.schema import EXAMPLE, validate

@pytest.fixture(scope="module")
def ctx():
    return Context(load_accounts(), load_tickets(), load_usage(), load_kb())

def ticket(ctx, **changes):
    return dict(ctx.ticket_records[0], **changes)

def test_domain_resolves_missing_id_and_similar_names(ctx):
    for account in ctx.account_records:
        session = TicketTools(ctx, ticket(ctx, account_id="", requester_domain=account["domain"], company_name_raw="misleading name"))
        assert session.resolve_account()["account"]["account_id"] == account["account_id"]

def test_conflicting_identity_and_unresolved(ctx):
    first, second = ctx.account_records[:2]
    session = TicketTools(ctx, ticket(ctx, account_id=first["account_id"], requester_domain=second["domain"]))
    assert session.resolve_account()["status"] == "conflict"
    assert session.account_id is None
    with pytest.raises(ValueError):
        session.account_insights()
    session = TicketTools(ctx, ticket(ctx, account_id="", requester_domain="unknown", company_name_raw=""))
    assert session.resolve_account()["status"] == "unresolved"

def test_risk_boundaries_missing_usage_and_future_exclusion(ctx):
    local = copy.copy(ctx)
    a = dict(ctx.account_records[0], renewal_date="2027-01-18", open_escalations="0") # 90 days
    local.accounts_by_id = {a["account_id"]: a}
    local.usage_records = [dict(account_id=a["account_id"], month=m, active_users=n) for m,n in
        [("2026-08",100),("2026-09",90),("2026-10",74),("2026-11",1)]]
    session = TicketTools(local, {})
    session.account_id = a["account_id"]
    assert session.account_insights()["risk_override"]
    local.usage_records[2]["active_users"] = 75
    assert not session.account_insights()["risk_override"] # strict >25 percent
    local.usage_records = []
    assert session.account_insights()["active_user_decline_pct"] is None
    a["open_escalations"] = "2"
    assert session.account_insights()["risk_override"]
    a["renewal_date"] = "2027-01-19"
    assert not session.account_insights()["risk_override"]

@pytest.mark.parametrize("query,expected", [
    ("E-4102 invoice OCR", "KB-3985"), ("E-2207 e-signature rejected", "KB-1786"),
    ("bulk approval 500 purchase orders limit", "KB-4859"),
    ("delegate approvals out of office", "KB-4449"), ("E-3310 bid submission", "KB-4795")])
def test_retrieval_recall(ctx, query, expected):
    assert expected in {r["id"] for r in TicketTools(ctx, {}).search_kb(query)}

def test_history_scoping_temporal_window_and_aliases(ctx):
    local = copy.copy(ctx)
    source = ticket(ctx, ticket_id="TKT-TEST", created_at="2026-10-20T12:00", module="CLM",
                    error_code="E-2207", subject="E-2207", description="signature rejected")
    records = []
    for name, days, status, account in [("valid",7,"open",source["account_id"]),
        ("old",8,"open",source["account_id"]), ("closed",1,"closed",source["account_id"]),
        ("future",-1,"open",source["account_id"]), ("other",1,"open","ACC-OTHER")]:
        records.append(dict(source, ticket_id=name, created_at=(date(source["created_at"])-timedelta(days=days)).isoformat(),
                            status=status, account_id=account, module="Contracts"))
    local.ticket_records = records
    session = TicketTools(local, source)
    session.account_id = source["account_id"]
    found = {t["ticket_id"]: t for t in session.search_history("E-2207 signature", limit=10)["tickets"]}
    assert set(found) == {"valid", "old", "closed"}
    assert found["valid"]["duplicate_window_eligible"]
    assert not found["old"]["duplicate_window_eligible"]
    assert not found["closed"]["duplicate_window_eligible"]

def test_reject_fabricated_and_deprecated_references(ctx):
    session = TicketTools(ctx, ticket(ctx))
    session.resolve_account()
    session.account_insights()
    session.policies()
    session.read_kb("KB-2605")
    out = copy.deepcopy(EXAMPLE)
    out.pop("reasoning_trace")
    out.update(ticket_id=session.ticket["ticket_id"], account_id=session.account_id,
               kb_references=["KB-FAKE", "KB-2605"], duplicate_of="TKT-FAKE")
    errors = decision_errors(out, session)
    assert any("Citations" in e for e in errors)
    assert any("deprecated" in e for e in errors)
    assert any("duplicate_of" in e for e in errors)

class ScriptedLLM:
    def __init__(self, calls):
        self.script = iter(calls)
        self.calls = 0
    def complete(self, messages, tools):
        name, args = next(self.script)
        self.calls += 1
        return {"role":"assistant", "tool_calls":[{"id":str(self.calls),"type":"function",
                "function":{"name":name,"arguments":json.dumps(args)}}]}

def test_agent_recovers_from_tool_and_submission_errors(ctx):
    local = copy.copy(ctx)
    t = ticket(ctx)
    out = {k: copy.deepcopy(EXAMPLE[k]) for k in DECISION_PROPERTIES}
    out.update(ticket_id=t["ticket_id"], account_id=t["account_id"], kb_references=["KB-2914"],
               priority="P1", escalate=True, notify_tam=True)
    local.llm = ScriptedLLM([("read_kb", {"article_id":"missing"}),
        ("submit_decision",out), ("resolve_account",{}), ("policies",{}),
        ("account_insights",{}), ("submit_decision",out)])
    result = triage(t, local)
    assert not validate(result)
    assert len(result["reasoning_trace"]) == 6
    assert "Unknown KB" in result["reasoning_trace"][0]["observation"]
    assert '"accepted": false' in result["reasoning_trace"][1]["observation"]
    assert '"accepted": true' in result["reasoning_trace"][-1]["observation"]

def test_bounded_loop_does_not_fabricate(ctx, monkeypatch):
    local = copy.copy(ctx)
    local.llm = ScriptedLLM([("policies",{})])
    monkeypatch.setenv("AGENT_MAX_TURNS", "1")
    with pytest.raises(RuntimeError, match="budget exhausted"):
        triage(ticket(ctx), local)


def test_unresolved_account_cannot_silently_finalize(ctx):
    session = TicketTools(ctx, ticket(ctx, account_id="", requester_domain="unknown", company_name_raw=""))
    session.resolve_account()
    session.policies()
    out = {k: copy.deepcopy(EXAMPLE[k]) for k in DECISION_PROPERTIES}
    out.update(ticket_id=session.ticket["ticket_id"], account_id=None, kb_references=["KB-2914"])
    assert any("Unresolved identity" in e for e in decision_errors(out, session))
    out.update(category="needs_info",needs_clarification=True,priority="P3")
    assert not decision_errors(out,session)


def test_security_and_nonfinite_confidence_are_rejected(ctx):
    session = TicketTools(ctx,ticket(ctx))
    session.resolve_account()
    session.account_insights()
    session.policies()
    out = {k: copy.deepcopy(EXAMPLE[k]) for k in DECISION_PROPERTIES}
    out.update(ticket_id=session.ticket["ticket_id"], account_id=session.account_id,
               category="security", priority="P4", confidence=float("nan"),kb_references=["KB-2914"])
    errors = decision_errors(out,session)
    assert any("Security requires" in e for e in errors)
    assert any("finite" in e for e in errors)


def test_malformed_json_records_real_tool_error(ctx,monkeypatch):
    local=copy.copy(ctx)
    class MalformedLLM:
        def complete(self,messages,tools):
            return {"role":"assistant","tool_calls":[{"id":"bad","type":"function",
                "function":{"name":"read_kb","arguments":"{not valid json"}}]}
    local.llm=MalformedLLM()
    monkeypatch.setenv("AGENT_MAX_TURNS","1")
    with pytest.raises(RuntimeError,match="budget exhausted"):
        triage(ticket(ctx),local)
    assert local.last_trace[0]["action"]=="read_kb"
    assert 'JSONDecodeError' in local.last_trace[0]["observation"]


def test_duplicate_reply_needs_current_status_not_only_creation_date(ctx):
    session = TicketTools(ctx,ticket(ctx))
    session.resolve_account()
    session.account_insights()
    session.policies()
    session.history["TKT-000001"] = {"status":"open","duplicate_window_eligible":True}
    out = {k:copy.deepcopy(EXAMPLE[k]) for k in DECISION_PROPERTIES}
    out.update(ticket_id=session.ticket["ticket_id"],account_id=session.account_id,category="duplicate",
        duplicate_of="TKT-000001",kb_references=["KB-2914"],customer_reply="TKT-000001 was opened yesterday.")
    assert any("status" in e for e in decision_errors(out,session))
    out["customer_reply"] = "TKT-000001 remains open. Updates will be posted there."
    out["internal_note"] = "Original adjudicated priority is unavailable; infer P3 from original scope and policy."
    assert not decision_errors(out,session)


def test_invalid_and_gapped_usage_remains_unknown(ctx):
    local = copy.copy(ctx)
    a = dict(ctx.account_records[0],renewal_date="2026-11-01",open_escalations="")
    local.accounts_by_id = {a["account_id"]:a}
    local.usage_records = [dict(account_id=a["account_id"],month=m,active_users=n) for m,n in
        [("2026-07",100),("2026-09",70),("2026-10",50)]]
    session = TicketTools(local,{})
    session.account_id = a["account_id"]
    insights = session.account_insights()
    assert insights["active_user_decline_pct"] is None
    assert insights["open_escalations"] is None
    assert insights["risk_override"] is None
    local.usage_records.insert(0,dict(account_id=a["account_id"],month="2026-08",active_users=float("nan")))
    insights = session.account_insights()
    assert insights["active_user_decline_pct"] is None
    assert insights["usage_months"][0]["active_users"] is None


def test_partial_execution_is_persisted_on_api_failure(ctx,tmp_path):
    from run import execute
    local=copy.copy(ctx)
    class FailingLLM:
        calls=0
        events=[]
        model="offline-test"
        def complete(self,messages,tools):
            self.calls+=1
            if self.calls==2:
                raise RuntimeError("simulated timeout")
            return {"role":"assistant","tool_calls":[{"id":"1","type":"function",
                "function":{"name":"policies","arguments":"{}"}}]}
    local.llm=FailingLLM()
    result,record=execute(ticket(ctx),local,tmp_path)
    assert result is None
    assert record["status"]=="exception"
    audit=json.loads((tmp_path/"tool_events.jsonl").read_text().splitlines()[0])
    assert audit["action"]=="policies"
    assert audit["ticket_id"]==ticket(ctx)["ticket_id"]
    assert record["trace"][0]["action"]=="policies"
    assert not list(tmp_path.glob("TKT-*.json"))


def test_read_only_tools_cannot_claim_external_actions(ctx):
    session=TicketTools(ctx,ticket(ctx))
    session.resolve_account()
    session.account_insights()
    session.policies()
    out={k:copy.deepcopy(EXAMPLE[k]) for k in DECISION_PROPERTIES}
    out.update(ticket_id=session.ticket["ticket_id"],account_id=session.account_id,kb_references=["KB-2914"],
               customer_reply="We've also logged a feature request with Product.")
    assert any("read-only" in e for e in decision_errors(out,session))
    out["customer_reply"]="I've added your ticket to the TAM watch list."
    assert any("read-only" in e for e in decision_errors(out,session))
    out["customer_reply"]="We will forward your request to Product for review."
    out["internal_note"]="TAM notified."
    assert any("read-only" in e for e in decision_errors(out,session))
    out["internal_note"]="Recommend notifying TAM if policy requires."
    assert not decision_errors(out,session)


def test_duplicate_window_candidates_survive_zero_lexical_overlap(ctx):
    local=copy.copy(ctx)
    source=ticket(ctx,ticket_id="TKT-CURRENT",created_at="2026-10-20T12:00",module="CLM",error_code="E-2207")
    prior=dict(source,ticket_id="TKT-PRIOR",created_at="2026-10-19T12:00",module="Contracts",status="open")
    local.ticket_records=[prior]
    session=TicketTools(local,source)
    session.account_id=source["account_id"]
    result=session.search_history("unrelatedvocabulary")
    assert result["duplicate_window_check"]["eligible_ticket_ids"]==["TKT-PRIOR"]
    assert result["tickets"][0]["retrieval_score"]==0
    assert result["tickets"][0]["exact_error_match"]


def test_cited_by_design_limit_enforces_product_policy(ctx):
    session=TicketTools(ctx,ticket(ctx))
    session.resolve_account()
    session.account_insights()
    session.policies()
    session.read_kb("KB-4859")
    out={k:copy.deepcopy(EXAMPLE[k]) for k in DECISION_PROPERTIES}
    out.update(ticket_id=session.ticket["ticket_id"],account_id=session.account_id,kb_references=["KB-4859"],
               category="how_to",route_to="L1_support",priority="P2")
    assert any("by-design limit" in e for e in decision_errors(out,session))
    out.update(category="feature_request",route_to="product",priority="P4")
    assert not decision_errors(out,session)


@pytest.mark.parametrize("description,priority,rejected", [
    ("Larger batches are needed before quarter end.","P2",True),
    ("Larger batches are needed before month end.","P3",True),
    ("Larger batches are needed before quarter end.","P4",False),
    ("The deadline is in 2 days.","P2",False),
])
def test_limit_priority_requires_verified_urgency(ctx,description,priority,rejected):
    t=ticket(ctx,subject="Documented batch limit",description=description)
    session=TicketTools(ctx,t);session.resolve_account();session.account_insights();session.policies();session.read_kb("KB-4859")
    out={k:copy.deepcopy(EXAMPLE[k]) for k in DECISION_PROPERTIES}
    out.update(ticket_id=t["ticket_id"],account_id=session.account_id,category="feature_request",route_to="product",
        priority=priority,kb_references=["KB-4859"])
    errors=decision_errors(out,session)
    assert bool([e for e in errors if "base P4" in e])==rejected


def test_degraded_function_risk_priority_is_not_pure_howto(ctx):
    local=copy.copy(ctx)
    account=dict(ctx.accounts_by_id[ticket(ctx)["account_id"]],renewal_date="2026-11-01",open_escalations="2")
    local.account_records=[account];local.accounts_by_id={account["account_id"]:account}
    t=ticket(ctx,subject="Approval inbox is slow",description="Orders arrive later than normal.")
    session=TicketTools(local,t);session.resolve_account();session.account_insights();session.policies();session.read_kb("KB-6082")
    out={k:copy.deepcopy(EXAMPLE[k]) for k in DECISION_PROPERTIES}
    out.update(ticket_id=t["ticket_id"],account_id=session.account_id,priority="P3",category="how_to",
        kb_references=["KB-6082"],escalate=True,notify_tam=True)
    assert any("functional degradation" in e for e in decision_errors(out,session))
    out["priority"]="P2"
    assert not decision_errors(out,session)
