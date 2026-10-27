"""Read-only evidence tools, scoped to the resolved account and dataset clock."""
from datetime import datetime
import re
import math
from .data import AS_OF_DATE
from .retrieval import HybridIndex, canonical
NOW = datetime.fromisoformat(AS_OF_DATE)

def date(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)

def codes(ticket):
    return set(re.findall(r"E-\d+", " ".join(str(ticket.get(k, "")) for k in ("error_code", "subject", "description"))))

class TicketTools:
    def __init__(self, ctx, ticket):
        self.ctx, self.ticket = ctx, ticket
        self.account_id, self.risk = None, None
        self.resolution_attempted = False
        self.read_ids, self.history = set(), {}

    def resolve_account(self):
        """Resolve exact domain/ID; conflicts and ambiguous identities require clarification."""
        self.resolution_attempted = True
        t = self.ticket
        by_domain = [a for a in self.ctx.account_records if a["domain"].lower() == t.get("requester_domain", "").strip().lower()]
        by_id = self.ctx.accounts_by_id.get(t.get("account_id"))
        if by_id and by_domain and by_id["account_id"] != by_domain[0]["account_id"]:
            return {"status": "conflict", "message": "ID and domain disagree; request verified identity."}
        matches = by_domain or ([by_id] if by_id else [])
        if not matches:
            name = t.get("company_name_raw", "").lower().strip()
            matches = [a for a in self.ctx.account_records if name and name == a["company_name"].lower()]
        if len(matches) != 1:
            return {"status": "unresolved", "candidate_count": len(matches), "message": "Request account ID and verified domain."}
        account = matches[0]
        self.account_id = account["account_id"]
        return {"status": "resolved", "matched_by": "domain" if by_domain else "account_id_or_exact_name", "account": account}

    def account_insights(self):
        """Read renewal, last three monthly usage observations, SSO changes and account-risk override."""
        if not self.account_id:
            raise ValueError("Resolve account first")
        a = self.ctx.accounts_by_id[self.account_id]
        first_month_index = NOW.year * 12 + NOW.month - 3
        first_month = f"{first_month_index // 12:04d}-{first_month_index % 12 + 1:02d}"
        rows = [r for r in self.ctx.usage_records if r["account_id"] == self.account_id
                and first_month <= r["month"] <= AS_OF_DATE[:7]]
        recent = sorted(rows, key=lambda r: r["month"])[-3:]
        decline = None
        try:
            users = [float(r["active_users"]) for r in recent]
            if len(users) == 3 and users[0] > 0 and all(math.isfinite(v) and v >= 0 for v in users):
                decline = 100 * (users[0] - users[-1]) / users[0]
        except (ValueError, TypeError, KeyError):
            pass
        try:
            renewal = (date(a["renewal_date"]) - NOW).days if a.get("renewal_date") else None
        except (ValueError, TypeError):
            renewal = None
        try:
            escalations = int(a["open_escalations"])
        except (ValueError, TypeError, KeyError):
            escalations = None
        if renewal is not None and not 0 <= renewal <= 90:
            override = False
        elif renewal is None:
            override = None
        elif (decline is not None and decline > 25) or (escalations is not None and escalations >= 2):
            override = True
        else:
            override = False if decline is not None and escalations is not None else None
        self.risk = {"renewal_days": renewal, "active_user_decline_pct": round(decline, 2) if decline is not None else None,
            "risk_override": override, "open_escalations": escalations, "usage_months": [{k:None if isinstance(v,float) and not math.isfinite(v) else v for k,v in r.items()} for r in recent],
            "sso_enabled_date": a.get("sso_enabled_date"), "tier": a["tier"], "as_of": AS_OF_DATE,
            "trend_definition": "first versus last of the three calendar-month observations ending at as_of; October may be partial; null risk means insufficient data"}
        return self.risk

    def search_history(self, query, limit=5):
        """Search prior same-account tickets; expose duplicate-window checks. Source priority is customer-selected only."""
        if not self.account_id:
            raise ValueError("Resolve account first")
        target = date(self.ticket["created_at"])
        rows = [t for t in self.ctx.ticket_records if t["ticket_id"] != self.ticket["ticket_id"]
            and self.ctx.ticket_account(t) == self.account_id and date(t["created_at"]) <= target]
        if not rows:
            return {"tickets": [], "note": "No prior same-account tickets", "duplicate_window_check":{"complete":True,"eligible_ticket_ids":[]}}
        ranked = HybridIndex([t["subject"]+" "+t["description"]+" "+t.get("error_code", "") for t in rows]).search(query, len(rows))
        candidates = []
        score_by_index = dict(ranked)
        for i, t in enumerate(rows):
            score = score_by_index.get(i,0)
            age = (target - date(t["created_at"])).total_seconds() / 86400
            same_module = canonical(t["module"]).lower() == canonical(self.ticket["module"]).lower()
            eligible = 0 <= age <= 7 and t["status"] in ("open", "pending_customer") and same_module
            if not eligible and score <= 0:
                continue
            candidates.append(dict(t, retrieval_score=score, age_days=round(age, 3), duplicate_window_eligible=eligible,
                exact_error_match=bool(codes(t) & codes(self.ticket)), priority_note="customer_priority is not adjudicated priority"))
        candidates.sort(key=lambda t: (t["duplicate_window_eligible"], t["exact_error_match"], t["retrieval_score"]), reverse=True)
        found = candidates[:max(1, min(int(limit), 10))]
        self.history.update({t["ticket_id"]: t for t in found})
        return {"tickets": found,
            "duplicate_window_check":{"complete":True,
                "eligible_ticket_ids":[t["ticket_id"] for t in candidates if t["duplicate_window_eligible"]],
                "note":"All same-module open/pending tickets in the prior 7 days for this account. If empty, further queries cannot find an eligible duplicate."},
            "policy": "Need same symptom/error as well as window/module; similarity alone is not proof."}

    def search_kb(self, query, limit=5):
        """Search KB metadata/body; read candidates before citing, follow superseded_by and relevant related links."""
        return [{"score": score, **self.ctx.kb[i]["meta"]} for i, score in
            self.ctx.kb_index.search(query, max(1, min(int(limit), 8)))]

    def read_kb(self, article_id):
        """Read full KB body, status, superseded_by and related links."""
        if article_id not in self.ctx.kb_by_id:
            raise ValueError("Unknown KB article ID")
        self.read_ids.add(article_id)
        return self.ctx.kb_by_id[article_id]

    def policies(self):
        """Read current support policies: priority, routing, risk, duplicates and security."""
        articles = [a for a in self.ctx.kb if a["meta"].get("type") == "policy" and a["meta"].get("status") == "current"]
        self.read_ids.update(a["id"] for a in articles)
        return articles
