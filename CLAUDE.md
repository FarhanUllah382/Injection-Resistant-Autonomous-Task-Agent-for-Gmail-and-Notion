# CLAUDE.md — Inbox-to-Action

This file guides Claude Code when working in this repository. Read it before making changes.

## What this project is

**Inbox-to-Action**: Gmail → find things I need to do → show them to me → I approve → put them into Notion.

It is NOT a task manager. It is a bridge between where work arrives (email) and where work is tracked (Notion). The existing tools (Gmail, Notion) stay where they are — this app is the intelligence layer between them.

Full product spec lives at `docs/spec.md` (copy the original spec there). This file is about how to build it, not what it does — refer to the spec for product rationale.

## Core flow (do not deviate)

```
Gmail (manual scan trigger)
  → fetch new emails
  → preprocess (strip HTML/signatures/quoted text)
  → Claude API (actionability + extraction)
  → save as task candidate (status: pending)
  → show in review UI
  → user approves / edits / dismisses
  → on approve only → create Notion page → store notion_page_id
```

Nothing gets written to Notion without explicit human approval. This is non-negotiable — see spec section 9.

## V1 architectural constraints

These are **V1/MVP constraints, not permanent architectural laws**. The underlying principle: do not introduce complexity before the MVP requires it. If a later phase genuinely needs one of these, that's a deliberate decision to revisit — not a default. For now:

- **One FastAPI app, one process.** No microservices, no service-to-service calls, no internal message passing between "services." The pipeline steps (fetch → preprocess → extract → candidate → notion) are Python functions/modules called in sequence within a request handler, not deployables.
- **No Redis. No Celery. No background workers/queues.** Email scanning is triggered manually via an endpoint (e.g. `POST /scan`) that runs synchronously. This is intentional for v1.
- **No vector DB, no RAG, no LangGraph, no Kubernetes.** There is no retrieval problem yet — every email is processed independently.
- **No fine-tuned models.** Use the Claude API with a well-designed prompt + structured output. Improve the prompt before reaching for anything fancier.
- **No auto-task-creation.** Every task requires human approval before hitting Notion.
- **Precision over recall.** The extraction prompt should be conservative. Missing a real task is an acceptable failure; surfacing a false positive is not. If in doubt about a threshold or prompt change, bias toward fewer, higher-confidence suggestions.

If a task seems to need one of these, stop and flag it explicitly rather than adding it — e.g. "this would need a background worker, which is out of scope for v1; here's the manual-trigger alternative."

## Stack

- **Backend**: Python + FastAPI, single process
- **AI**: Anthropic Claude API (structured JSON output) — use the `anthropic` Python SDK
- **Email**: Gmail API + OAuth2, minimum scopes necessary (readonly is enough for v1)
- **DB**: PostgreSQL, plain SQL or a lightweight ORM (SQLModel/SQLAlchemy is fine — don't add a heavier data layer)
- **Frontend**: minimal Next.js — just enough for the review UI (list of candidates, approve/edit/dismiss buttons). Do not over-build this.
- **Notion**: Notion API, official Python or JS client

## Data model (do not expand without discussion)

Tables: `users`, `email_accounts`, `emails`, `task_candidates`, `user_decisions`, `notion_tasks`.

- `emails` stores the raw + cleaned text of every processed email, plus the Gmail `message_id` and `thread_id` (for the "link back to original email" requirement). These identifiers come from the Gmail API — they are application data, not something Claude generates. `task_candidates` reference `emails` by foreign key rather than duplicating these ids, and the backend builds the Gmail link from them. Claude must never be asked to produce a Gmail URL or id.
- `task_candidates` stores what Claude extracted: task, assignee, reason, confidence, status (`pending`/`approved`/`edited`/`dismissed`) — plus two distinct deadline fields (see "Deadline is a phrase, not a resolved date" below):
  - `deadline_phrase`: the exact natural-language phrase Claude extracted, e.g. `"Friday"` or `"tomorrow"`. Set by Claude, stored as-is.
  - `resolved_due_date`: the deterministic, application-computed calendar date derived from `deadline_phrase` using the email's received timestamp and the user's timezone. Set by the backend, never by Claude. May be null if `deadline_phrase` can't be safely resolved.
- `user_decisions` records what the user actually did, separately from the candidate's current status — this is deliberately kept as append-only history for future model improvement (see spec section 9, "Reason 2 — Learning"). Don't collapse this into `task_candidates.status` only.
- `notion_tasks` links an approved candidate to its Notion page id and sync status.

Don't add tables/fields speculatively for the long-term vision (multi-source ingestion, commitment engine, etc.) — that's explicitly out of scope. See "Long-term vision" in the spec; it is not being built now.

## Claude extraction contract

Every call to Claude for extraction must return strict JSON matching:

```json
{
  "actionable": true,
  "task": "string or null",
  "deadline": "string or null",
  "assignee": "string or null",
  "reason": "string",
  "confidence": 0.0
}
```

The contract stays as-is — the corrections below are about what each field means and who is responsible for it, not new fields.

**Deadline is a phrase, not a resolved date.** Claude extracts the deadline language exactly as it appears or is clearly implied ("Friday", "tomorrow", "next week", "end of month") — nothing more. This is what the JSON contract's `deadline` field maps to, and what's stored in `task_candidates.deadline_phrase`. Claude does not compute a calendar date. Resolving "Friday" into an actual date (`task_candidates.resolved_due_date`) is a deterministic, application-side step that uses the email's received timestamp and the user's timezone, done after extraction. Do not build a general natural-language date parser as part of the LLM prompt, and do not introduce a complex date-resolution system for V1 — a small, well-tested function (e.g. built on a standard date library) that handles common relative terms is enough. If a deadline phrase can't be confidently resolved, leave `resolved_due_date` null rather than guessing.

**Assignee is minimal for V1.** The MVP processes one person's inbox, so the real question is "is the logged-in user being asked to do something?" — not who a task should be assigned to in general. Claude must not invent or infer a person's identity from "you"; it should only populate `assignee` when the email explicitly names someone, and otherwise leave it null. Do not build entity/contact resolution in V1. Treat `assignee` as optional context for the review UI, not a field the pipeline depends on.

**Confidence is a ranking signal, not a probability.** Don't treat `confidence` as a calibrated probability — it's a model-generated signal used to rank and filter candidates. Use it to decide what clears the review-UI threshold, not as a statistic to report elsewhere. Start with a conservative threshold and tune it against the hand-labeled evaluation set (Phase 1) rather than picking a number arbitrarily. Precision over recall remains the priority when choosing where to set it.

**Thread context stays simple.** The prompt should be able to tell a new request apart from a follow-up on an existing one, an action the user (or someone else) already completed, and ordinary discussion with no request in it (spec section 7). For V1, do this by giving Claude the latest email plus a small amount of recent thread context (e.g. the last few messages) — not a full conversation-state engine, and not thread-level memory in the database beyond what's needed to assemble that context at call time.

Rules for the prompt:
- Never invent a deadline that isn't stated or clearly implied in the email (spec section 6, Example C).
- Never invent a person's name or identity — leave `assignee` null rather than guessing.
- Distinguish requests/commitments directed at the user from information, discussion, or things already done (spec section 7), using recent thread context where it's needed to avoid an obvious mistake.
- `actionable: false` should be the default unless there's clear evidence of a request. When in doubt, say no.
- Only show `task_candidates` to the user above a confidence threshold — start conservative and tune based on the labeled test set, not guesswork.

Before building the full pipeline, validate this contract against a small hand-labeled set of real emails (spec Phase 1). Do this as a standalone script, not inside the FastAPI app, so it's fast to iterate on.

## Build order (follow this, don't parallelize)

1. **Extraction experiment** — a standalone script: real emails in, JSON out, compare against a hand-labeled test set. This phase must not depend on FastAPI, PostgreSQL, Gmail OAuth, Notion, or Next.js — just the Claude API and a handful of example emails (can be pasted text or a small local file). No app code yet.
2. **Gmail integration** — OAuth, manual-trigger fetch, store raw emails.
3. **Review UI** — list candidates, approve/edit/dismiss. No Notion writes yet — just update `status` in the DB.
4. **Notion integration** — on approve, create the page, store the id, show success/failure.

Each phase should be independently testable before moving to the next. Don't build phase 3 UI polish before phase 1's extraction quality is validated — extraction quality is the actual risk in this project, not the UI.

## What "done" looks like for v1

Not a polished product. The milestone (spec section 15): a real Gmail email comes in, Claude correctly identifies the action, the user approves it, and the task appears in Notion with correct context and a link back to the original email. If that loop works reliably end to end, the MVP is done.

## When suggesting changes

- If a request would reintroduce something in the "do not build yet" list (Slack, multi-agent, semantic dedup, analytics, fine-tuning, etc. — spec section 10), say so explicitly and suggest the MVP-scoped alternative instead of quietly building it.
- Prefer boring, explicit code over clever abstractions. This is a small app; readability over extensibility.
- When adding a new dependency, state in one line why it's needed for the MVP specifically — not "because it's common practice."
