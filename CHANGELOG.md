# Changelog

Notable changes by phase. Each phase has a corresponding `DESIGN_DECISIONS_V2.x.md` document written and reasoned through before implementation.

## V2.7 — Continuous monitoring + review UI redesign

- Automatic Gmail polling (~2-minute interval, in-process scheduler) reusing the exact scan/extract functions manual triggers already used — no separate "automatic" pipeline to drift out of sync with the manual one.
- Single-flight polling with fail-quiet retry, backing off to a longer interval after repeated failures and surfacing a one-time "reconnect Gmail" prompt specifically for auth failures rather than failing silently forever.
- Server-Sent Events (`GET /events`) so the review UI learns about new candidates and auth issues without polling.
- `task_candidates` now persists the raw V2.4 injection/sender-trust signals (previously computed, then discarded) so the UI can show a real "flagged" state instead of lumping every review-required candidate together.
- Review UI redesign: card-based candidate list, a consistent status-color mapping defined once and reused everywhere, a dashboard summary strip, keyboard shortcuts, and a designed empty state — no new frontend dependencies.

**Correction**: an earlier commit message on this phase (`9dd7db1`, "V2.7: automatic Gmail polling") stated *"Verified against the live dev DB: schema migration applied, a real scan+extract cycle ran end to end."* That verification had not actually been run at the time the commit was made — the claim was inaccurate. Recorded here rather than rewriting the pushed commit's history.

## V2.6 — Calendar MCP + Scheduling Agent

- Read-only calendar availability check, run automatically whenever an extracted email resolves to a proposed meeting time or a time-bearing deadline.
- Booking an actual calendar event is a separate, explicit action from approving a task — never bundled, never automatic, no policy-engine path can trigger it.
- Fixed a timezone bug where a naive stored datetime was being labeled with the wrong offset before being sent to the Calendar API.

## V2.5 — Correction-learning loop

- User corrections to approved/edited candidates can be turned into short, human-approved "correction notes" that get appended to future extraction prompts as guidance — manual-approval-only, never applied automatically from raw correction data.

## V2.4 — Untrusted-content defense

- `injection_suspected`: the extraction prompt explicitly separates untrusted email content from instructions, and flags content that reads like it's trying to direct an AI system rather than communicate with a person.
- `sender_trust_signal`: a deterministic, content-independent check for identity spoofing (e.g. a directory-style display name with no connection to its free-webmail address) — added specifically because a well-formed, high-confidence request from a spoofed sender passes every content-level check by design.
- Both are hard overrides in the policy engine, regardless of extraction confidence.

## V2.3 — Trust/risk policy engine (shadow mode)

- A narrow policy function answering one question: should this specific candidate be eligible to skip human review before its Notion page is created? Shipped in shadow mode only — computed and logged, never acted on — until V2.4's injection defenses existed to make that safe to even consider.

## V2.2 — Triage pre-filter

- A cheap, deterministic pre-filter ahead of the Claude extraction call (blocked sender domains, no-reply senders with no action keyword in the subject) — fails open on any uncertainty or error, since a real task silently dropped is worse than one unnecessary Claude call.

## V2.1 — MCP migration

- Gmail fetch and Notion page-creation moved to small, purpose-built MCP servers spawned as local subprocesses over stdio, each exposing only the specific tools the pipeline needs.

## V1 — MVP

- Phase 1: standalone extraction accuracy experiment against a hand-labeled email set, with no app dependencies, before any infrastructure was built.
- Phase 2–4: Gmail OAuth + fetch, review UI (approve/edit/dismiss), Notion sync on explicit approval only.
