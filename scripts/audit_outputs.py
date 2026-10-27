"""Audit real outputs for schema, citations, identity, and temporal duplicate integrity.

This checks invariants; it does not claim to measure semantic correctness.
"""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tam_agent.data import load_accounts, load_tickets, load_review_set, load_usage
from tam_agent.agent import Context, decision_errors
from tam_agent.tools import TicketTools
from tam_agent.kb import load_kb
from tam_agent.schema import validate
from tam_agent.tools import date
from tam_agent.retrieval import canonical

def audit():
    account_frame, ticket_frame, usage_frame, articles = load_accounts(), load_tickets(), load_usage(), load_kb()
    ctx = Context(account_frame, ticket_frame, usage_frame, articles)
    accounts = {a["domain"]:a for a in account_frame.to_dict("records")}
    tickets = {t["ticket_id"]:t for t in ticket_frame.to_dict("records")}
    kb = {a["id"]:a for a in articles}
    errors, results = [], []
    for tid in load_review_set():
        p = ROOT / "outputs" / (tid+".json")
        if not p.exists():
            errors.append(tid+": missing output")
            continue
        out = json.loads(p.read_text(encoding="utf-8"))
        errors.extend(tid+": "+e for e in validate(out))
        ticket = tickets[tid]
        if out["account_id"] != accounts[ticket["requester_domain"]]["account_id"]:
            errors.append(tid+": wrong resolved account")
        read = set()
        for i,step in enumerate(out["reasoning_trace"],1):
            if step["step"] != i:
                errors.append(tid+": non-sequential trace")
            if step["action"] == "read_kb":
                obs = json.loads(step["observation"])
                if "id" in obs:
                    read.add(obs["id"])
            if step["action"] == "policies":
                read.update(a["id"] for a in json.loads(step["observation"]))
        for ref in out["kb_references"]:
            if ref not in kb or ref not in read or kb[ref]["meta"]["status"] == "deprecated":
                errors.append(tid+": ungrounded/deprecated citation "+ref)
        session = TicketTools(ctx,ticket)
        for step in out["reasoning_trace"]:
            name = step["action"]
            if name in ("resolve_account","account_insights","search_history","search_kb","read_kb","policies"):
                try:
                    getattr(session,name)(**json.loads(step.get("input","{}")))
                except (ValueError,TypeError,KeyError):
                    pass # Failed tool calls remain in the actual trace and contribute no evidence.
        candidate = {k:v for k,v in out.items() if k != "reasoning_trace"}
        errors.extend(tid+": "+e for e in decision_errors(candidate,session))
        original = out["duplicate_of"]
        if original:
            source = tickets.get(original)
            if not source:
                errors.append(tid+": fabricated duplicate ID")
            else:
                age = (date(ticket["created_at"])-date(source["created_at"])).total_seconds()/86400
                aid = source["account_id"] or accounts[source["requester_domain"]]["account_id"]
                if not (aid == out["account_id"] and 0 <= age <= 7 and source["status"] in ("open","pending_customer")
                        and canonical(source["module"]).lower() == canonical(ticket["module"]).lower()):
                    errors.append(tid+": ineligible duplicate")
        if out["category"] == "security" and (out["priority"],out["route_to"],out["escalate"]) != ("P1","security",True):
            errors.append(tid+": unsafe security decision")
        results.append({k:out[k] for k in ("ticket_id","category","priority","route_to","escalate","notify_tam","duplicate_of")})
    print(json.dumps({"audited":len(results),"errors":errors,"decisions":results},indent=2))
    return bool(errors)

if __name__ == "__main__":
    raise SystemExit(audit())
