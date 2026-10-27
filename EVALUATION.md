# Evaluation and Grounding Audit

Evaluation date: **2026-10-27**. Business reference date: **2026-10-20**, as required by the supplied dataset.

## Scope and evidence

This report evaluates the **ten preserved JSON artifacts in `outputs/`**, not hypothetical regenerated decisions. The source data contains customer-selected urgency, not adjudicated priority/routing/escalation/TAM labels. No hiring-team answer key or independent expert-labelled dataset was supplied. Consequently, **verified-label decision accuracy is unavailable**; all percentages below are explicitly **policy-based manual agreement**.

The implementation author assessed the source tickets, account/usage records and KB policies, with assumptions recorded in [`evaluation/policy_reference.json`](evaluation/policy_reference.json). This reference is an evaluation artifact, not an independent gold standard, and the production agent does not import it. [`scripts/evaluate_decisions.py`](scripts/evaluate_decisions.py) reproduces the comparison in [`evaluation/decision_report.json`](evaluation/decision_report.json). Identifier, read-citation and duplicate-window checks are additionally replayed by `scripts/audit_outputs.py` without LLM calls.

## Actual validation results

| Check | Observed result | Interpretation |
|---|---|---|
| `python scripts/validate_data.py` | All integrity rules passed | CSV foreign keys and KB links are valid |
| `python scripts/check_outputs.py` | **10/10 schema-valid** | Structural validity does not imply decision correctness |
| `pytest -q` | **42 passed, 0 failed** | Includes agent, policy, retry/quota, auth/RBAC, persistence and Streamlit tests |
| React production build | Passed | Vite build completed; route-level bundles are split |
| Browser tests excluding live Groq | **5 passed, 0 failed** | Startup/login, ticket/evidence display, reviews, role restrictions, admin, mobile and quota-error UI |
| Current grounding/policy audit | **2 findings; exit status 1** | The two preserved priority mismatches below are intentionally reported, not hidden |
| Preserved review files | SHA-256 manifest recorded | `evaluation/preserved_output_hashes.json` is checked against all ten files |

The Python suite prevents real Groq client construction. Controlled SDK/error doubles and isolated test databases exercise failures; they do not generate production review outputs. The browser quota test replays a previously recorded failure response with `result=null`; it creates no AI decision. Three upstream deprecation warnings were observed (Starlette/httpx and Streamlit/pandas), with no test failures.

## Accuracy methodology

Use **Accuracy = Correct Decisions / Total Evaluated Decisions x 100** only when the reference is clearly identified. Here it measures agreement with the documented manual policy reference, not independently verified prediction accuracy.

Four fields are assessed: `priority`, `route_to`, `escalate`, and `notify_tam`. That gives 40 possible decision cells. **One cell is excluded:** duplicate ticket TKT-192732 must retain the original adjudicated priority under KB-5930, but that value is not present in the CSV. Its saved P3 is a plausible inference, not a verifiable original label. The denominator is therefore **39**, not 40. Category labels, citations, confidence and duplicate detection are not silently added to improve this overall percentage.

| Decision dimension | Correct / evaluated | Policy-based agreement |
|---|---:|---:|
| Priority P1-P4 | **7/9** | **77.78%** |
| Routing | **10/10** | **100%** |
| Escalation | **10/10** | **100%** |
| TAM notification | **10/10** | **100%** |
| **Overall, decision-cell micro average** | **37/39** | **94.87%** |
| Strict whole-ticket agreement, all four fields scorable | **7/9** | **77.78%** |

Per-reference-priority breakdown (class recall/agreement, not one-vs-rest accuracy):

| Policy-reference priority | Correct / evaluated | Agreement |
|---|---:|---:|
| P1 | 2/2 | 100% |
| P2 | 1/2 | 50% |
| P3 | 3/3 | 100% |
| P4 | 1/2 | 50% |

One duplicate priority is excluded from this class breakdown. No independently verified category-classification score is claimed because the source provides an enum, not a labelled answer key.

## Per-ticket comparison

All expectations below are **policy-derived manual assessments**, not verified external labels. `Esc / TAM` contains the actual saved booleans; both agree with the reference for every ticket.

| Ticket | Saved priority | Policy reference | Saved route | Esc / TAM | Assessment |
|---|---|---|---|---|---|
| TKT-144939 | P1 | P1 | L2_engineering | true / true | All scored fields agree |
| TKT-119877 | P3 | P2 | L1_support | true / true | Priority mismatch |
| TKT-160477 | P3 | P3 | L1_support | false / false | All scored fields agree |
| TKT-192732 | P3 | Unscored (original absent) | L1_support | false / false | Priority excluded; other fields agree |
| TKT-169327 | P3 | P3 | L1_support | false / false | All scored fields agree |
| TKT-160067 | P2 | P4 | product | false / false | Priority mismatch |
| TKT-160094 | P2 | P2 | L2_engineering | false / false | All scored fields agree |
| TKT-128253 | P3 | P3 | L1_support | false / false | All scored fields agree |
| TKT-135081 | P1 | P1 | security | true / false | All scored fields agree |
| TKT-158764 | P4 | P4 | L1_support | false / false | All scored fields agree |

### Policy evidence and assumptions

- **TKT-144939:** All OCR processing blocked; active incident INC-26-0418 requires P1/L2; Premium account requires TAM notification.
- **TKT-119877:** Approval degradation has documented configuration remediation (base P3); renewal 61 days, 33.59% decline and two escalations trigger P2/risk/TAM. L1 configuration handling pending evidence of >2h delays.
- **TKT-160477:** Two blocked contracts with current credential-remediation procedure; no verified urgent deadline or risk override. Deprecated KB-2605 is not current guidance.
- **TKT-192732:** Same-account open TKT-122022, same module/error within seven days. P3 is a provisional policy inference from original scope/remediation; original adjudicated priority is unavailable. Do not re-escalate.
- **TKT-169327:** Exact requester domain resolves Europe entity ACC-4850. Scheduler remediation supports P3/L1. Renewal 320 days away means user decline alone does not trigger the risk override.
- **TKT-160067:** Documented by-design 200-document limit and batching workaround require Product/feature handling, base P4. Quarter-close wording provides no verified deadline within 72h; renewal is 200 days away.
- **TKT-160094:** Bid failure plus stated two-day closing deadline warrants P2/L2. SSO reconfiguration recorded October 14 corroborates trust issue; follow linked KB-7889. P2 alone does not require escalate=true.
- **TKT-128253:** Neither module nor actionable symptom identified: insufficient-information policy requires P3/L1 and specific clarification, not customer-selected P1.
- **TKT-135081:** Competing supplier bid exposure is Security/P1/escalate regardless of low urgency; pause affected event, avoid reproducing or speculating. No account-risk TAM trigger.
- **TKT-158764:** Pure delegation question: P4/L1. Embedded instructions cannot raise urgency, cause escalation, or disclose other customers.

The routing reference treats known account/configuration remediation as L1 unless a documented engineering escalation condition is established. In particular, the approval-delay ticket does not establish delays exceeding KB-6082's two-hour threshold. The account-risk override adds escalation/TAM handling; it does not itself establish a product defect. The Sourcing ticket has an explicit two-day business deadline and is routed to L2 under KB-2914.

## Two priority issues and offline fixes

1. **TKT-119877: saved P3; policy reference P2.** The saved note uses pure-how-to base P4 before raising to P3. The ticket instead reports functional degradation with troubleshooting remediation: base at least P3, then the verified account-risk override raises it to P2. Escalation and TAM flags are already correct.
2. **TKT-160067: saved P2; policy reference P4.** KB-4859 documents a by-design 200-document limit with a batching workaround. The saved note invents a business deadline within 72 hours from vague quarter-close wording and starts at an incorrect base P3. No such imminent deadline or account-risk trigger is evidenced. Product routing is already correct.

`tam_agent/agent.py` now rejects these general inconsistencies at submission: cited by-design limits need supported urgency before departing from P4, and observed degradation with a verified risk override cannot remain P3/P4. Relative-hour/day and ISO-date deadline checks distinguish explicit dates from vague calendar wording. Tests cover both failures, a genuinely explicit two-day deadline, risk-window boundaries, missing data, and preservation of routing/TAM behavior. Production checks contain no review-ticket ID branches.

**The saved artifacts are deliberately unchanged.** Passing offline regressions establishes that validation rejects these cases; it does not establish improved live-model accuracy. Regenerating and measuring post-fix outputs remains blocked by Groq quota.

## Citation, duplicate and grounding findings

- **16/16 citation occurrences** resolve to existing KB articles, are present in recorded read/policy observations and are non-deprecated. **16/16** are within the manually reviewed relevance reference. This is not an automatic guarantee that every sentence is entailed.
- **10/10 account IDs** match the unique requester-domain mapping. The Europe entity resolves to ACC-4850 rather than a similarly named parent.
- Duplicate agreement is **10/10 against the manual reference**: one true link, TKT-192732 -> TKT-122022, and nine non-duplicate outcomes. The positive case has matching account, canonical module/error, open status and a prior timestamp within seven days. No fabricated duplicate ID was found. Original adjudicated priority remains unknown.
- Clarification agreement is **10/10**: the vague ticket requests module/error/scope/time details instead of accepting P1. The injection-containing delegation question remains ordinary P4/L1 and does not disclose other-account data.
- **One definite unsupported factual claim:** the bulk-limit note asserts a deadline within 72 hours that is not stated in the ticket. This is also one of the two priority errors.
- **Two diagnostic-certainty risks:** TKT-169327 states that a tenant scheduler is paused; TKT-160094 presents the SSO trust cause as identified. The KB supports those diagnoses, and the SSO date corroborates the latter, but no live tenant/scheduler inspection verifies either cause. They should be presented as hypotheses for confirmation.
- The TKT-119877 reply includes grounded but internal renewal/adoption-risk details. Those details belong in the internal note rather than the customer draft.
- Security-team-engaged wording is a KB-prescribed draft. Actual engagement must occur before sending it: this platform does not send notifications or perform external ticket-system actions.

No invalid cited KB ID, incorrect resolved account ID or invented duplicate ID was detected. **A zero-hallucination claim would be unjustified**: the unsupported deadline and prose-certainty issues remain in preserved drafts, and identifier checks do not prove full semantic grounding.

## React/FastAPI integration evidence

Five local browser checks passed, covering manager search/evidence/review/analytics, support API/navigation restrictions, admin user/assignment/audit/settings workflow, mobile KB navigation, and a recorded quota failure with no completed recommendation. Saved investigations load without calling Groq.

**An earlier real live smoke passed before the quota stop:** login -> existing TKT-128253 -> Run AI Investigation -> FastAPI -> native Groq agent -> persisted validated result -> human approval. The isolated validation database records run `7d2b3e66-aad9-4b62-9d67-ee4916f0569c`, model `openai/gpt-oss-120b`, status `succeeded`, **57.632 seconds**, **14,032 reported input tokens**, **1,560 output tokens**, and review state `approved`. Browser execution was reported as one passed test in approximately 1.1 minutes. This is historical evidence, not a claim that live inference is currently available or that it validates post-fix priority behavior.

Costs remain unavailable without configured price snapshots; provider-reported token counts are not invented invoice totals. Isolated validation DB files and browser traces are ignored by Git.

## Groq quota limitation and preservation

Full-review regeneration was attempted and rejected by Groq's daily token quota. The last full batch recorded **0/10 newly generated results**; this must not be confused with the checker's **10/10 valid preserved files**. The saved ten artifacts survived those failures; no replacement results were synthesized. After the explicit quota-stop instruction, no further Groq calls were made, no waiting/retry loop was started, and all validation stayed offline.

Daily TPD/RPD errors now raise a specific non-transient error immediately, with **one request, no sleep and no automatic retry** verified by regression tests. FastAPI persists `failed`, clears the failed run's result, records the error and leaves usage/cost unknown when unreported. React displays failure/retry guidance without a completed recommendation. Retrying is an explicit user action creating a new run.

**Blocked:** fresh full-review generation, regenerated AI results for the two priority cases, post-fix live accuracy measurement and another live integration run. **Not blocked:** browsing saved results, offline audits/tests, account/KB views, human review, administration, and documentation.

## Reproduction without inference

```powershell
.\.venv\Scripts\python.exe scripts/validate_data.py
.\.venv\Scripts\python.exe scripts/check_outputs.py
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\python.exe scripts/evaluate_decisions.py
.\.venv\Scripts\python.exe scripts/audit_outputs.py
npm.cmd run build --prefix frontend
```

The final audit command intentionally exits nonzero while the two preserved priority findings remain. Browser verification uses an already-running development server and excludes the opt-in live test:

```powershell
$env:PLAYWRIGHT_BASE_URL="http://127.0.0.1:8000"
npm.cmd run test:e2e --prefix frontend -- --grep-invert "LIVE Groq"
```

Do not run `python run.py --set review` or enable `LIVE_AI=1` until inference is explicitly resumed with available quota. Do not rewrite preserved output files to make the report appear better.
