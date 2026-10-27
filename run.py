"""Run live triage and persist validated outputs, audit logs and metrics."""
import argparse
import json
import random
import time
import uuid
from pathlib import Path
from tam_agent.data import load_accounts, load_tickets, load_usage, load_review_set
from tam_agent.kb import load_kb
from tam_agent.agent import Context, triage
from tam_agent.schema import validate
OUT = Path(__file__).resolve().parent / "outputs"

def append_event(path, event):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")

def save_result(result, folder=OUT):
    errors = validate(result)
    if errors:
        raise ValueError("Invalid output: " + "; ".join(errors))
    folder.mkdir(exist_ok=True, parents=True)
    target = folder / (result["ticket_id"] + ".json")
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False), encoding="utf-8")
    temporary.replace(target)

def execute(ticket, ctx, folder=OUT):
    folder.mkdir(exist_ok=True, parents=True)
    started, calls0, events0 = time.perf_counter(), ctx.llm.calls, len(ctx.llm.events)
    ctx.last_events = []
    ctx.last_trace = []
    record = {"run_id": str(uuid.uuid4()), "ticket_id": ticket["ticket_id"], "model": ctx.llm.model,
              "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    identity = {"run_id":record["run_id"], "ticket_id":ticket["ticket_id"]}
    ctx.audit_sink = lambda step,event: append_event(folder / "tool_events.jsonl", {**identity, **event, **step})
    ctx.llm.event_sink = lambda event: append_event(folder / "api_events.jsonl", {**identity, **event})
    result = None
    try:
        result = triage(ticket, ctx)
        save_result(result, folder)
        record.update(status="ok", errors=[], decision={k: result[k] for k in
            ("category", "priority", "route_to", "escalate", "notify_tam", "confidence", "duplicate_of")})
    except Exception as exc:
        # SDK error bodies can contain prompts or sensitive details; client sanitizes API errors.
        record.update(status="exception", errors=[str(exc)], error_type=type(exc).__name__)
    record.update(seconds=round(time.perf_counter()-started, 3), llm_calls=ctx.llm.calls-calls0,
                  events=ctx.last_events, llm_events=ctx.llm.events[events0:],
                  trace=ctx.last_trace if result is None else [], output_file=ticket["ticket_id"]+".json" if result else None)
    with (folder / "run_log.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, allow_nan=False) + "\n")
    return result, record

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=["review", "sample"])
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--ids", nargs="*")
    args = parser.parse_args()
    tickets = load_tickets()
    ctx = Context(load_accounts(), tickets, load_usage(), load_kb())
    ids = args.ids or (random.Random(args.seed).sample(list(tickets.ticket_id), args.n) if args.set == "sample" else load_review_set())
    by_id, ok = tickets.set_index("ticket_id"), 0
    for tid in ids:
        if tid not in by_id.index:
            parser.error(f"Unknown ticket ID: {tid}")
        _, rec = execute(by_id.loc[tid].to_dict() | {"ticket_id": tid}, ctx)
        ok += rec["status"] == "ok"
        print(f"{tid}: {rec['status']} ({rec['seconds']}s, {rec['llm_calls']} calls)", flush=True)
        if rec["errors"]:
            print("; ".join(rec["errors"]), flush=True)
    print(f"{ok}/{len(ids)} valid outputs", flush=True)
    return 0 if ok == len(ids) else 1

if __name__ == "__main__":
    raise SystemExit(main())
