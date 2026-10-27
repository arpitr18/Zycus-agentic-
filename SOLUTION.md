# Solution: AI Support Intelligence & Ticket Triage

**Problem and scope.** Internal support teams need consistent recommendations grounded in customer context and support policy. This application investigates existing records; it does not replace Zycus ticketing, change source tickets, send replies, or notify customers/TAMs.

**Architecture.** React/Vite, Tailwind and shadcn/ui provide the workbench; React Router, TanStack Query and Recharts handle navigation, polling and charts. FastAPI authenticates users, enforces account/role permissions, queues investigations and exposes results. SQLAlchemy/SQLite persist sessions, runs, events, reviews and audits. The integration is **React -> FastAPI -> existing Python agent -> Groq + read-only tools**. CSV/Markdown remain authoritative source data. The original CLI, Streamlit app and output schema are preserved.

**Agent workflow.** A bounded native Groq tool-calling loop lets the model choose account resolution, account insights, history search, KB search, article reads and policy reads in any needed order, then call `submit_decision`. There is no fixed lookup sequence. Existing keyword-based BM25 and sparse TF-IDF retrieval select small candidate sets; the whole corpus is not sent to the model. No vector database or new embedding system was introduced. Identity comes from verified lookups; citations must have been read and cannot be deprecated. Duplicate candidates are scoped by account, module, status and prior seven-day window. Actual calls, observations, errors and usage are recorded.

**Policies and reliability.** KB rules govern P1-P4 priority, L1/L2/Product/Security routing, escalation, TAM notification, duplicates and clarification. Validation rejects conflicting recommendations and returns feedback to the model. New general guards reject invented urgency from vague calendar wording and enforce the account-risk uplift for observed degradation. Regressions cover both priority issues without ticket-specific production rules. API failures produce failed jobs with no result; daily quotas fail immediately without automatic waiting. Token costs remain unavailable unless verified prices are configured; calculated costs are estimates, not invoices.

**Access and review.** Salted scrypt passwords, hashed opaque session tokens, HttpOnly/SameSite cookies, CSRF checks and backend RBAC protect the application. Support sees assigned accounts; managers review all tickets and analytics; admins manage users, assignments and settings. Reviews and overrides remain separate from immutable AI recommendations. Demo seeding is opt-in for development; production rejects demo logins and sessions.

**Measured evaluation of preserved outputs.** No adjudicated labels were supplied: these are policy-based manual agreements, not verified-label accuracy.

- Saved schema validity: **10/10**; source-data integrity checks pass.
- Offline Python tests: **43/43**; local browser checks: **6/6**.
- Priority: **7/9 (77.78%)**; duplicate priority is unscorable without the original adjudicated value.
- Routing, escalation and TAM: **10/10 each**. Overall: **37/39 cells (94.87%)**, using correct/evaluated x 100.
- KB citations: **16/16** exist, were read, are non-deprecated and agree with the manual relevance reference.
- An earlier real React/FastAPI/Groq investigation and review passed; current live regeneration is blocked by exhausted quota.

**Assumptions, limitations and scale.** All business dates use 2026-10-20; the usage window contains August-October snapshots, and October may be partial. Confidence is uncalibrated. Two preserved priority mismatches and diagnostic wording risks remain documented in `EVALUATION.md`; no result was edited to imply a successful post-fix rerun. New guards are regression-tested, but post-fix live accuracy is unmeasured. The single-worker queue suits this assignment; multiple workers require a durable queue and coordinated throttling. At 10x, persist lexical indexes, index history by account/time and cache unchanged evidence to reduce latency and token cost. Production also needs deployment-specific HTTPS/access controls and real users. Setup and diagrams are in `README.md`.
