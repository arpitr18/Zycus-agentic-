"""Support workbench: live execution, evidence, traces and evaluation."""
import json
from pathlib import Path
import pandas as pd
import streamlit as st
from tam_agent.data import load_accounts, load_tickets, load_usage, load_review_set, AS_OF_DATE
from tam_agent.kb import load_kb
from tam_agent.agent import Context
from tam_agent.schema import validate
from run import execute, OUT

st.set_page_config(page_title="Triage | Support Operations", page_icon="?", layout="wide")
st.markdown("""<style>
.block-container {padding-top:2rem; max-width:1400px}
[data-testid="stMetric"] {border:1px solid #e2e8f0; border-radius:10px; padding:14px}
</style>""", unsafe_allow_html=True)

@st.cache_data
def resources():
    return load_accounts(), load_tickets(), load_usage(), load_kb()

accounts, tickets, usage, kb = resources()
review = load_review_set()
by_id = {t["ticket_id"]:t for t in tickets.to_dict("records")}
with st.sidebar:
    st.title("? Triage")
    st.caption("SUPPORT OPERATIONS")
    scope = st.radio("Ticket queue", ["Review set", "All tickets"])
    ids = review if scope == "Review set" else list(by_id)
    tid = st.selectbox("Select ticket", ids, format_func=lambda x: x+" ? "+by_id[x]["subject"][:45])
    st.divider()
    st.caption("Dataset reference date: " + AS_OF_DATE)
    st.caption("Draft recommendations for support review. No messages or notifications are sent.")

ticket = by_id[tid]
st.title("Ticket triage workbench")
st.caption(tid+"  /  "+ticket["company_name_raw"]+"  /  "+ticket["created_at"])
st.subheader(ticket["subject"])
with st.expander("Incoming ticket", expanded=True):
    st.text(ticket["description"])
    st.caption("Module: "+(ticket["module"] or "Not provided")+" ? Customer priority: "+(ticket["customer_priority"] or "Not provided"))
if st.button("Run agent", type="primary"):
    with st.spinner("Agent is gathering evidence and deciding next steps?"):
        if "agent_context" not in st.session_state:
            st.session_state.agent_context = Context(accounts, tickets, usage, kb)
        result, record = execute(ticket, st.session_state.agent_context)
        st.session_state["run_"+tid] = record
    if record["status"] != "ok":
        st.error("Execution failed: "+"; ".join(record["errors"]))
    else:
        st.success(f"Decision saved ? {record['llm_calls']} model calls ? {record['seconds']:.1f}s")

path = OUT / (tid+".json")
result = None
if path.exists():
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        st.error("The saved output could not be read.")
if result:
    current_run = st.session_state.get("run_"+tid)
    if current_run and current_run["status"] != "ok":
        st.warning("Showing the previous saved decision. The latest execution failed.")
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Classification", result["category"].replace("_"," ").title())
    c2.metric("Priority", result["priority"])
    c3.metric("Route", result["route_to"].replace("_"," "))
    c4.metric("Model confidence", f"{result['confidence']:.0%}")
    st.caption("Escalate: "+str(result["escalate"])+" ? Notify TAM: "+str(result["notify_tam"])+
               " ? Clarification: "+str(result["needs_clarification"])+" ? Duplicate of: "+str(result["duplicate_of"]))
    decision, evidence, timeline, raw = st.tabs(["Response & notes", "Account & knowledge", "Execution timeline", "JSON"])
    with decision:
        left,right = st.columns(2)
        with left:
            st.subheader("Customer response")
            st.text(result["customer_reply"])
        with right:
            st.subheader("Internal support note")
            st.text(result["internal_note"])
    with evidence:
        st.subheader("Account insights")
        for signal in result["account_signals"]:
            st.write("? "+signal)
        aid = result["account_id"]
        history = usage[usage.account_id == aid].sort_values("month")
        if not history.empty:
            st.line_chart(history.set_index("month")[["active_users"]], height=220)
        kb_by_id = {a["id"]:a for a in kb}
        for ref in result["kb_references"]:
            article = kb_by_id.get(ref)
            if article:
                with st.expander(ref+" ? "+article["meta"]["title"]):
                    st.caption("Status: "+article["meta"]["status"]+" ? Updated: "+article["meta"]["last_updated"])
                    st.text(article["body"])
    with timeline:
        st.caption("Recorded tool calls and observations; decision summaries are in the internal note.")
        for entry in result["reasoning_trace"]:
            with st.expander(f"{entry['step']:02d} ? {entry['action']}"):
                st.code(entry.get("input", "{}"), language="json")
                try:
                    st.json(json.loads(entry["observation"]))
                except (ValueError, TypeError):
                    st.text(entry["observation"])
    with raw:
        errors = validate(result)
        st.caption("Schema valid" if not errors else "; ".join(errors))
        st.json(result)
        st.download_button("Download JSON", json.dumps(result,indent=2), file_name=tid+".json", mime="application/json")
else:
    st.info("Run the agent to generate a decision, or select a ticket with a saved result.")

st.divider()
st.subheader("Evaluation & execution metrics")
valid = 0
for review_id in review:
    p = OUT / (review_id+".json")
    if p.exists():
        try:
            valid += not validate(json.loads(p.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            pass
logs = []
log_path = OUT / "run_log.jsonl"
if log_path.exists():
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            logs.append(json.loads(line))
        except ValueError:
            continue
latest = {r["ticket_id"]:r for r in logs}
success = [r for r in latest.values() if r["status"] == "ok"]
a,b,c = st.columns(3)
a.metric("Schema-valid review outputs", f"{valid}/{len(review)}")
b.metric("Mean successful latency", f"{sum(r['seconds'] for r in success)/len(success):.1f}s" if success else "?")
c.metric("Mean model calls", f"{sum(r['llm_calls'] for r in success)/len(success):.1f}" if success else "?")
st.caption("Schema validity measures structure. Decision correctness requires a human review; confidence is not calibrated accuracy.")
if latest:
    st.dataframe(pd.DataFrame([{k:r.get(k) for k in ("ticket_id","status","seconds","llm_calls","model")} for r in latest.values()]), hide_index=True, width="stretch")
