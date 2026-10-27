# Zycus AI Support Intelligence & Ticket Triage Platform

An internal decision-support workbench for investigating **existing support tickets**. The platform combines account context, usage trends, historical tickets and knowledge-base policies to recommend classification, priority, routing, escalation and TAM notification. Support managers review the recommendation before taking action.

**This is not a replacement for Zycus ticketing.** Source CSV/KB records are read-only. Customer responses and internal notes are drafts; the application does not send messages, notify TAMs or simulate an external Zycus integration.

## Project status and evaluation (2026-10-27)

| Area | Actual status |
|---|---|
| Saved assignment outputs | **10/10 schema-valid; preserved unchanged** |
| Offline Python tests | **43 passed** |
| Local browser checks without Groq | **6 passed** |
| React production build | Passed |
| KB citation audit | **16/16** exist, were read and are non-deprecated; all agree with the manual relevance reference |
| Priority policy agreement | **7/9 (77.78%)**; one duplicate priority cannot be scored |
| Routing / escalation / TAM agreement | **10/10 each** against the documented manual policy reference |
| Overall policy agreement | **37/39 decision cells (94.87%)**; this is not independently verified label accuracy |
| Live inference | Daily quota exhausted; no further API calls or quota waits are being made |

Two historical priority mismatches remain in the preserved artifacts: `TKT-119877` stores P3 where the policy reference is P2; `TKT-160067` stores P2 where the reference is P4. General validation guards and regression tests now reject these inconsistencies, but **post-fix live results have not been generated or measured**. No saved result was edited to improve the reported score.

An earlier real React -> FastAPI -> Groq investigation and human review passed before quota exhaustion. That historical success is not a claim that inference is currently available. Saved-result browsing, local authentication, reviews, KB/account views and offline tests remain usable.

Read [SOLUTION.md](SOLUTION.md) for the one-page submission summary and [EVALUATION.md](EVALUATION.md) for formulas, counts, per-ticket comparisons, grounding findings and quota limitations. The previous assignment README is retained in [ASSIGNMENT.md](ASSIGNMENT.md).

## Stack and responsibilities

| Layer | Implementation |
|---|---|
| Frontend | React JavaScript, Vite, Tailwind, shadcn/ui, React Router, TanStack Query, Recharts |
| Backend | FastAPI REST API with server-side authorization |
| Persistence | SQLite and SQLAlchemy for users, sessions, assignments, runs, reviews, settings and audits |
| AI | Existing Python agent with native Groq tool calling; model configured through environment variables |
| Retrieval | Existing keyword-based BM25 and sparse word/bigram TF-IDF retrieval |
| Source data | Existing ticket/account/usage CSV files and Markdown KB articles |
| Compatibility | Original `triage(ticket, ctx)`, CLI, fixed JSON schema and Streamlit dashboard |

No vector database, new embedding system, hosted RAG service or separate external ticketing infrastructure was introduced.

## Architecture

```mermaid
flowchart LR
    browser["React support workspace"] -->|"Authenticated REST and polling"| api["FastAPI: sessions, RBAC and endpoints"]
    api -->|"Persist application records"| appDb[("SQLite application database")]
    api -->|"Submit run ID"| worker["Single-process investigation worker"]
    worker --> agent["Existing Python tool-calling agent"]
    agent <-->|"Native tool calls and decisions"| groq["Groq API"]
    agent --> tools["Read-only evidence tools"]
    tools --> csvData[("Ticket, account and usage CSVs")]
    tools --> kbData["Markdown KB and support policies"]
    worker -->|"Status, events, result and metrics"| appDb
    cli["Original CLI and Streamlit"] --> agent
    cli -->|"CLI artifacts"| saved["Saved review JSON and execution logs"]
    saved -.->|"Import validated CLI artifacts"| appDb
```

The API is a thin adapter around `tam_agent/`: it handles access, execution lifecycle and persistence rather than duplicating the agent's business logic. The CSV/KB datasets remain the source of ticket facts; SQLite stores application state.

## End-to-end workflow

1. **Sign in.** The backend validates a salted password hash and issues an opaque HttpOnly session cookie. CSRF tokens protect authenticated writes.
2. **Find an existing ticket.** Search by ID, subject or company; filter source status, module and AI priority; sort and paginate. Support users see tickets only for assigned accounts.
3. **Inspect context.** Open ticket details and account intelligence, including renewal date, monthly usage, open escalations and policy-derived risk signals.
4. **Start an investigation when quota is available.** FastAPI stores a queued run and returns its ID immediately. An existing active investigation for the same ticket is reused to prevent duplicate launches.
5. **Investigate dynamically.** The agent chooses relevant tools, reads observations, follows KB links or supersession guidance as needed, and decides when to submit a recommendation.
6. **Validate and persist.** Schema, identity, citation, duplicate and policy checks gate completion. Events, reported token usage, latency and the final result are persisted. Failed jobs retain an error and no new result.
7. **Review evidence.** The frontend polls status and displays classification, P1-P4 priority, routing, escalation/TAM recommendations, duplicates, KB citations, actual tool traces, drafts and confidence.
8. **Apply human oversight.** A manager approves, rejects or amends priority/routing. The review is stored separately; the original AI result and source ticket remain unchanged.
9. **Monitor operations.** Managers inspect actual investigation statuses, latency, model/tool usage, reported tokens and review coverage. Admins manage access, account assignments, audit logs and pricing configuration.

```mermaid
sequenceDiagram
    participant browser as React workbench
    participant api as FastAPI
    participant db as SQLite
    participant worker as Worker
    participant agent as Python agent
    participant groq as Groq
    participant tools as Evidence tools
    browser->>api: Login
    api->>db: Verify user and store hashed session token
    api-->>browser: HttpOnly cookie and CSRF token
    browser->>api: Request investigation for existing ticket
    api->>api: Enforce role and account scope
    api->>db: Save queued run
    api->>worker: Submit run ID
    api-->>browser: Return run ID and status
    worker->>db: Mark running
    worker->>agent: Execute triage
    loop Agent-selected turns
        agent->>groq: Messages, evidence and tool schemas
        groq-->>agent: Selected tool or decision submission
        alt Evidence lookup selected
            agent->>tools: Execute selected read-only tool
            tools-->>agent: Return observation
        else Decision submitted
            agent->>agent: Validate schema and evidence consistency
        end
        agent->>db: Persist observations through audit callback
    end
    alt Validated result
        agent-->>worker: Return result
        worker->>db: Save succeeded result and measured metrics
    else Quota or execution failure
        agent-->>worker: Raise error without a result
        worker->>db: Save failed status and error
    end
    browser->>api: Poll investigation ID
    api->>db: Read authorized run
    api-->>browser: Actual status, evidence and available result
    opt Manager review
        browser->>api: Approve, reject or amend
        api->>db: Store separate review and audit event
    end
```

Execution status and human-review state are separate. A successful execution is not a guarantee of policy correctness or an approved decision. Retrying a failed investigation creates a new run; server-restart interruptions are marked failed rather than silently restarted.

## Agent tools and decision loop

| Tool | Evidence supplied |
|---|---|
| `resolve_account` | Exact requester-domain/account-ID matching; conflicts or unresolved identities |
| `account_insights` | Renewal window, active-user trend, open escalations, SSO date and account-risk override |
| `search_history` | Same-account historical tickets and complete duplicate-window eligibility information |
| `search_kb` | Ranked keyword-based KB candidates and metadata |
| `read_kb` | Full article body, status, related links and supersession target |
| `policies` | Current priority, routing, duplicate and security policies |
| `submit_decision` | Model-selected recommendation, accepted only after validation |

```mermaid
flowchart TD
    incoming["Incoming ticket and trusted system instructions"] --> choose["Groq chooses the next action"]
    choose --> action{"Selected action"}
    action -->|"Evidence needed"| lookup["Execute selected account, usage, history or KB tool"]
    lookup --> observation["Record actual observation"]
    observation --> choose
    action -->|"Ready to decide"| submit["Submit structured recommendation"]
    submit --> validate["Check schema, identity, citations, duplicates and policy consistency"]
    validate --> accepted{"Accepted?"}
    accepted -->|"No"| feedback["Return validation feedback"]
    feedback --> choose
    accepted -->|"Yes"| result["Persist validated result"]
    choose -->|"Daily quota or execution error"| failed["Persist failure without a fabricated result"]
```

The tool order is not fixed. Account calculations and safety checks are deterministic; tool selection, investigation depth and decision submission remain model-driven. Rejected attempts remain in the audit trace, while their full candidate payload is removed from subsequent prompts to limit repetition and prompt growth.

## Policy behavior

The authoritative documents include [KB-2914](kb/KB-2914.md), [KB-5930](kb/KB-5930.md) and [KB-6401](kb/KB-6401.md).

- Security/data exposure and production-wide outages require P1 handling. Security goes directly to Security; active incidents link to Engineering guidance.
- Major impairment without a workaround or a supported business deadline within 72 hours can justify P2.
- Limited impairment with remediation/workaround generally starts at P3; pure how-to and feature/limit cases start at P4.
- Renewal within 90 days plus a decline above 25% or at least two open escalations triggers a one-level priority uplift, capped at P2, with escalation/TAM handling. Existing P1 severity is not downgraded.
- By-design limits route to Product with the documented workaround. Vague month/quarter-end wording does not establish an imminent deadline.
- Duplicates require the same account, canonical module and symptom/error, an open/pending original, and a prior seven-day window. The original adjudicated priority is absent from this dataset and cannot be verified.
- Insufficient module/symptom information produces clarification rather than a guessed emergency.
- Ticket content and retrieved text are evidence, not trusted instructions. The embedded prompt-injection review ticket must not change policy or disclose other accounts.

**Business clock:** use `2026-10-20` for renewal, usage and policy calculations. Execution timestamps use real runtime time. October usage may be partial; missing values remain unknown rather than being invented as zero.

## Roles and pages

| Role | Backend-enforced access |
|---|---|
| Support engineer | Assigned-account tickets, investigations, account detail and KB |
| TAM/support manager | All tickets/accounts, reviews, escalations and analytics |
| Administrator | Manager access plus users, role/account assignments, audits and settings |

The UI includes Overview, Ticket Workbench, Investigation Detail, Account Intelligence, Knowledge Base, AI Analytics and Administration. Hiding navigation is only a usability measure: the backend checks permissions on every protected request and returns no unassigned ticket/account details to support users.

## Setup

Tested locally with Python 3.14.7 and Node.js 24.19.0. Create a Python virtual environment and use a current supported Node/npm installation. Commands below are PowerShell and start from the repository root.

### Install dependencies once

```powershell
cd C:\Users\zycus\Desktop\Arpit
# Create this only if .venv does not already exist:
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm.cmd ci
cd ..
```

If the Windows Store `python` alias is unreliable, use your installed Python interpreter to create the environment. After that, invoke `.venv\Scripts\python.exe` directly as shown.

Copy `.env.example` to `.env` **only if you do not already have `.env`**. Configure `GROQ_API_KEY` and a tool-capable `LLM_MODEL`; never commit credentials. A key is not needed just to browse saved data. Currently, inference quota is exhausted: do not repeatedly launch investigations or the CLI review run.

### Backend: terminal 1

```powershell
cd C:\Users\zycus\Desktop\Arpit
$env:APP_ENV="development"
$env:ENABLE_DEMO_ACCOUNTS="true"
.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Development demo users are seeded only when the application user table is empty and development seeding is enabled:

| Login | Password | Role |
|---|---|---|
| `support@demo.local` | `Demo@1234` | Assigned-account support |
| `manager@demo.local` | `Demo@1234` | TAM/support manager |
| `admin@demo.local` | `Demo@1234` | Administrator |

These are development credentials, not production accounts. Production rejects these seeded identities even if their rows or old development sessions remain in the database. The support demo user is assigned the accounts represented in the review set. If a database already has users, toggling the seed flag does not reset their passwords or recreate them.

### Frontend: terminal 2

```powershell
cd C:\Users\zycus\Desktop\Arpit\frontend
npm.cmd run dev
```

- React workspace: **http://127.0.0.1:5173**
- FastAPI docs: **http://127.0.0.1:8000/docs**
- Minimal health endpoint: **http://127.0.0.1:8000/api/health**

Vite proxies `/api` to port 8000. The IDE `@/*` alias is relative to `frontend/jsconfig.json`; the deprecated `baseUrl` option has been removed. Vite independently resolves the runtime alias to `frontend/src`.

### Serve the built frontend through FastAPI

```powershell
npm.cmd run build --prefix frontend
# Start or restart FastAPI after the build:
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

FastAPI serves `frontend/dist` when it exists at application startup, including SPA routes. The separate Vite development server is then optional.

### Retained Streamlit interface

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Streamlit and the CLI remain supported. Streamlit loads saved outputs without inference until its execution button is pressed. It is a local-only legacy interface and does not use the React/FastAPI session or RBAC layer.

## Configuration and storage

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | Server-only Groq credential |
| `LLM_PROVIDER` | `groq` |
| `LLM_MODEL` | Available tool-calling model; current file default is `openai/gpt-oss-20b` |
| `LLM_MAX_COMPLETION_TOKENS` | Response budget, default 2000 |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` | Timeout and bounded transient-error retry settings |
| `AGENT_MAX_TURNS` | Agent turn budget, default 24 |
| `APP_ENV` | Development or production; production enables Secure cookies |
| `ENABLE_DEMO_ACCOUNTS` | Explicit development seed flag, false by default |
| `DATABASE_URL` | Optional SQLite URL; default is repository `data/platform.db` |
| `APP_ORIGINS` | Comma-separated allowed frontend origins |
| `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` | First non-demo admin for an empty user database; bootstrap password must be at least 12 characters |

Use a fresh production database, real users, HTTPS and explicitly configured origins. Do not promote a demo-populated development database into production. Sessions use HttpOnly/SameSite cookies, stored token hashes, eight-hour expiry and CSRF protection; password/role updates revoke the affected user's sessions.

The application worker is **single-process/single-worker**, with a bounded pending queue and persistent history. Deploy with one API worker. Durable multi-process dispatch, distributed throttling, SSO/MFA and managed database migrations are future production work, not implemented external infrastructure.

`data/platform.db` and other local DB files are ignored by Git. Valid CLI artifacts are imported by content hash, with recorded CLI metrics where available. Older failed CLI attempts remain in JSONL logs; the importer is not a complete migration of all historical failures. API-run history is persisted independently and never overwrites the assignment outputs.

## APIs

Login and the minimal health endpoint are public. Other application API routes require an authenticated session; development API documentation is also accessible.

| Area | Main routes |
|---|---|
| Authentication | `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout` |
| Tickets | `GET /api/tickets`, `GET /api/tickets/{id}` |
| Accounts | `GET /api/accounts`, `GET /api/accounts/{id}` |
| Investigations | `POST /api/investigations`, `GET /api/investigations`, `GET /api/investigations/{id}` |
| Human review | `POST /api/investigations/{id}/reviews` |
| Knowledge | `GET /api/kb`, `GET /api/kb/{id}` |
| Reporting | `GET /api/overview`, `GET /api/analytics` |
| Administration | `GET/POST /api/users`, `PUT /api/users/{id}`, `GET /api/audit` |
| Configuration | `GET /api/settings`, `PUT /api/settings/pricing` |
| Health | `GET /api/health` |

After login or `auth/me`, the client retains the returned CSRF token in memory and supplies `X-CSRF-Token` on authenticated writes. Password hashes and Groq keys are never returned by the API.

## Metrics and cost honesty

Analytics derive from persisted runs and actual provider-reported usage. Latency includes tool execution and retry/rate-limit waits. Missing metrics are shown as unavailable, not fabricated zeros. Some failed generations do not return token usage, so reported totals may be incomplete.

Model prices are not guessed. An administrator may enter verified input/output USD rates per million tokens with a source reference. New investigations capture a pricing snapshot and calculate an **estimate** from reported usage. Existing unpriced runs are not silently given invented costs; estimates are not Groq invoices.

## Validation without Groq calls

```powershell
.\.venv\Scripts\python.exe scripts/validate_data.py
.\.venv\Scripts\python.exe scripts/check_outputs.py
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\python.exe scripts/evaluate_decisions.py
.\.venv\Scripts\python.exe scripts/audit_outputs.py
npm.cmd run build --prefix frontend
```

The automated audit intentionally exits nonzero while the two preserved priority mismatches remain. This is a known finding, not a claim that all decisions are correct.

With a development server running and Google Chrome installed:

```powershell
$env:PLAYWRIGHT_BASE_URL="http://127.0.0.1:8000"
npm.cmd run test:e2e --prefix frontend -- --grep-invert "LIVE Groq"
```

The browser tests use local HTTP, saved investigations and a recorded quota-error response contract. They do not launch Groq investigations. The pytest suite explicitly blocks a real Groq client and confines controlled test data to isolated databases.

### Live execution: only after quota is available and inference is resumed

The assignment interfaces are unchanged:

```powershell
.\.venv\Scripts\python.exe run.py --set review
.\.venv\Scripts\python.exe scripts/check_outputs.py
```

The normal CLI intentionally writes validated results into `outputs/`; **do not execute it while preserving the current submission artifacts**. Snapshot them first when a future authorized evaluation is ready. A failed request does not replace a previous valid JSON file. Daily quota errors stop immediately without waiting or repeated retries, and no fallback decision is synthesized.

## Troubleshooting

| Symptom | Check or action |
|---|---|
| Groq daily quota error | Keep the failed run for audit. Browse saved results; do not repeatedly retry or rewrite artifacts. Resume only after quota is available and inference is explicitly authorized. |
| Frontend cannot load API data | Start FastAPI on port 8000, verify `/api/health`, then check the Vite `/api` proxy. |
| Demo login fails | Seeding requires development mode, the explicit seed flag and an initially empty user table. Existing users are not reset; use the existing administrator to manage access. |
| CSRF or origin rejection | Refresh/sign in again and make sure the browser origin is in `APP_ORIGINS`. |
| Session expires after editing a user | User updates revoke affected sessions. Sign in again with the current credentials. |
| IDE still shows the old `baseUrl` warning | Confirm `frontend/jsconfig.json` has no `baseUrl`, then restart the IDE TypeScript server or reload the editor. |
| Built frontend route is unavailable | Build first, then restart FastAPI so it registers `frontend/dist` and SPA routes. |
| Grounding audit exits with status 1 | Read the two documented historical priority findings in `EVALUATION.md`; schema validity and decision correctness are separate checks. |

## Repository map

```text
api/                         FastAPI routes, auth, DB and background agent adapter
frontend/src/                React pages, API client and shared UI components
frontend/e2e/                Browser workflows and quota-error regression
tam_agent/                  Existing agent, tools, retrieval, loaders and schema
data/                       Source CSVs, review set and ignored local SQLite DBs
kb/                         Markdown articles and policies
outputs/                    Preserved review JSONs and real execution logs
evaluation/                 Manual policy reference, computed report and preservation hashes
scripts/                    Dataset, schema, grounding and policy evaluation scripts
tests/                      Offline Python tests; real Groq construction is forbidden
run.py                       Original CLI interface
app.py                       Retained Streamlit dashboard
SOLUTION.md                  One-page submission summary
EVALUATION.md                Actual results, mismatches, methodology and quota limits
ASSIGNMENT.md                Previous assignment README
```

## Known limitations and remaining blocked work

- Two saved priorities disagree with the manual policy reference. New code guards reject them, but quota prevents regeneration and post-fix live measurement.
- Original adjudicated duplicate priority is not supplied. No fabricated gold label or verified accuracy percentage is claimed.
- Confidence is model-reported, not calibrated. Identifier/citation validation does not prove every sentence; draft diagnoses still require tenant confirmation.
- Daily quota blocks new investigations and fresh review generation, not saved-result browsing or human review.
- Production deployment needs the hardening described above. The local prototype does not implement an external Zycus integration.

See [EVALUATION.md](EVALUATION.md) for the complete per-ticket assessment and the distinction between schema validity, manual agreement and verified accuracy.
