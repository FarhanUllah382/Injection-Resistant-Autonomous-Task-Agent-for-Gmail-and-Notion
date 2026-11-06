# Inbox-to-Action V2.6: Calendar MCP + Scheduling Agent — Design Decisions for Approval

Review and approve each decision before V2.6 implementation begins.

**Scope of V2.6**: Build the Scheduling Agent that every prior phase deferred. Given an email that proposes a meeting time, check the user's calendar and surface either a confirmation or alternative times — as a suggestion the user approves, never as an automatic booking.

**This phase reopens two things every prior doc deliberately left closed:**
1. Calendar MCP — deferred since V2.1 (no calendar integration existed to build against).
2. A meeting-detection field in the extraction contract — proposed in the original V2.2 draft as `mentions_meeting_time`, then explicitly **removed** at your instruction because nothing consumed it yet. That's no longer true — the Scheduling Agent is the consumer. Decision 3 reopens this, deliberately and narrowly, same pattern V2.4 used to justify its own prompt change.

**Explicitly out of scope for V2.6**:
- Auto-booking without human approval — no extension of `AUTO_ACT_ENABLED` to calendar actions (Decision 5)
- Multi-attendee availability aggregation (only the user's own calendar is checked)
- Recurring meetings, video-call link generation, timezone conversion across attendees
- Any change to `app/policy.py`'s existing Notion-creation logic (V2.3) — scheduling is a parallel action, not folded into that policy
- Learning-loop involvement (V2.5's correction notes stay scoped to task extraction, not scheduling — consistent with V2.5 Decision 2's boundary)

---

## Decision 1: Calendar MCP — Build vs. Adopt

### Question
Same question V2.1 asked for Gmail and Notion: custom server, or adopt an existing one?

### Current State
Gmail already uses Google OAuth (V1). Google Calendar is the same provider family — the existing OAuth client can very likely be extended with an additional scope rather than standing up a second auth flow.

### Recommendation
Build a thin custom Calendar MCP server, following the exact pattern of Gmail's (V2.1 Decision 1): wrap calendar API calls, expose two tools only —

```
mcp_servers/calendar_mcp/server.py
  list_events(start, end)      # free/busy check for a window
  create_event(...)            # only ever called after explicit human approval — see Decision 5
```

Do not adopt a third-party Calendar MCP server. Same reasoning as Gmail: our OAuth/token handling already exists and is trusted; a third-party server would mean a second, unfamiliar auth path for no real benefit.

### Rationale
- Reuses V2.1's already-approved build-vs-adopt logic instead of re-litigating it from scratch.
- Two tools, both narrow (`list_events` for checking, `create_event` for booking) — easy to audit, matches the "expose exactly what's needed" principle from V2.1 Decision 1.

### Impact on V2.6
Low new risk on the MCP-plumbing side — this is the same shape of work as V2.1, just a third server.

---

## Decision 2: OAuth Scope Expansion

### Question
Adding Calendar access means requesting a new consent scope. How does this affect existing users who already granted Gmail-only access?

### Recommendation
- Extend the existing Google OAuth consent request to include the Calendar read/write scope.
- Existing users must explicitly re-consent (Google requires this for new scopes — there's no way to silently expand access).
- The system must degrade gracefully if a user hasn't granted Calendar scope: extraction, triage, and Notion task creation continue working exactly as before; only the Scheduling Agent's suggestion step is skipped (logged as `calendar_unavailable`, not treated as an error).

### Rationale
- Re-consent is a hard requirement from Google, not a design choice — but building the graceful-degradation path is a choice, and an important one: a user who never grants Calendar access shouldn't see V2.6 as a regression in what already worked.
- Matches V1 Decision 5's insistence on explicit configuration (IANA timezone) over silent fallbacks — this is the same principle applied to a new scope instead of a new field.

### Impact on V2.6
No forced re-auth flow breaks existing functionality; Calendar becomes additive, not a new dependency for the whole pipeline.

---

## Decision 3: Reopening the Extraction Contract — Meeting Detection

### Question
The original `mentions_meeting_time` proposal was removed from V2.2 because nothing consumed it. Is this the right time to add it back?

### Recommendation
Yes — this is exactly the situation that removal was waiting for. Add one field back to the JSON contract, narrowly scoped, following V2.4's precedent for how a prompt change gets justified and regression-tested (accuracy bar, not byte-diff, since the prompt is genuinely changing):

```json
{
  "actionable": true,
  "task": "...",
  "deadline": "...",
  "assignee": "...",
  "reason": "...",
  "confidence": 0.85,
  "injection_suspected": false,
  "proposed_meeting_time": null   // NEW — natural-language time phrase if the
                                    // email proposes meeting at a specific time,
                                    // else null. Resolved to a real datetime by
                                    // the existing deadline_resolver.py pattern.
}
```

### Rationale
- The earlier removal was correct *at the time* — an unused field is speculative complexity, exactly what that decision was right to cut.
- Reusing `deadline_resolver.py`'s existing resolution logic (rather than inventing a second resolver) keeps this consistent with how "Friday" already gets turned into a real date elsewhere in the pipeline.

### Impact on V2.6
Second (and last, for now) deliberate exception to the "prompt is locked" default — held to the same regression bar V2.4 established: Phase 1 accuracy must still meet target after the change (Decision 8).

---

## Decision 4: Scheduling Agent Workflow

### Question
Given a candidate with a resolved `proposed_meeting_time`, what does the agent actually do?

### Recommendation

```
Candidate has proposed_meeting_time
        ↓
Calendar MCP: list_events(window around proposed time)
        ↓
   time free?
    /      \
  YES        NO
   │          │
   ▼          ▼
"Confirmed   Suggest up to 3 alternative slots:
 free"       next available business-hour windows
             in the same week, from list_events
             results — simple nearest-free-slot
             search, no optimization across
             multiple constraints
        ↓
Surfaced to user in the review UI alongside
the existing task candidate — never booked yet
```

### Rationale
- "Nearest free slot" is a simple, explainable heuristic — matches the project's consistent preference (triage heuristics, policy rules) for simple-and-auditable over sophisticated-and-opaque.
- Capping at 3 suggestions avoids dumping a wall of options on the user; if none work, they can check their own calendar — this tool augments, it doesn't need to solve scheduling perfectly.

### Impact on V2.6
New, self-contained module (`app/scheduling.py`) — doesn't need to touch extraction, triage, or policy logic to do its job.

---

## Decision 5: Human Approval Boundary — No Auto-Booking

### Question
Does approving a task candidate also book the calendar event, or is that a separate step?

### Recommendation
**Separate, explicit step.** Approving a task (existing `approve_candidate` flow) only creates the Notion page, exactly as it does today. Booking a calendar event requires a distinct action — a second explicit confirmation in the review UI (e.g., "Also add to calendar" as its own button, not a checkbox bundled into task approval).

`create_event` is never called by anything except that explicit, separate human action. There is no policy path, confidence threshold, or `AUTO_ACT_ENABLED` branch that can trigger it. This isn't a shadow-mode-then-flip situation like V2.3 — auto-booking a calendar event isn't proposed at all in this phase.

### Rationale
- A task and a calendar event are genuinely different commitments (one's a to-do, one blocks time on a calendar other people might see) — collapsing them into one approval click hides that difference from the user.
- Keeping this fully outside the policy engine avoids ever having to answer "should calendar events be auto-bookable" under time pressure later — that's a future decision to make deliberately, not an accidental side effect of this phase's design.

### Impact on V2.6
Zero interaction with V2.3's policy engine. Calendar booking is unconditionally human-gated, with no flag to ever bypass that in this phase.

---

## Decision 6: Security Boundary Reuse — No New Logic Needed

### Question
Should the Scheduling Agent have its own injection/spoofing defenses, given it's a new surface touching email content?

### Recommendation
No new security logic. The Scheduling Agent only ever runs on candidates that have already passed triage (V2.2) and whose `injection_suspected` / `sender_trust_signal` (V2.4) don't disqualify them from normal processing. If a candidate is already flagged `review_required` for security reasons, it still goes to standard human review — the Scheduling Agent's suggestion is just additional information alongside it, not a bypass of anything.

### Rationale
- V2.4's defenses are about trusting extracted content generally — a proposed meeting time is just another extracted field, not a new category of risk requiring its own defense mechanism.
- Reuse over reinvention: this project's V2.4 doc already established the relevant boundary; V2.6 just needs to not accidentally create a second, unguarded path around it.

### Impact on V2.6
No new security code. One line of care in implementation: don't let the Scheduling Agent read from a candidate before V2.4's checks have run on it.

---

## Decision 7: Timezone Handling — Reuse, Don't Reinvent

### Question
Calendar free/busy checks need a timezone, same as deadline resolution already does. Reuse or rebuild?

### Recommendation
Reuse the mandatory explicit IANA timezone from V1 Decision 5. `proposed_meeting_time` resolution and the Calendar MCP's `list_events` window both use the same per-user timezone value already required for `deadline_resolver.py` — no new timezone field, no new fallback logic, no UTC default.

### Rationale
- V1 Decision 5 already settled this question generally ("no UTC fallback, explicit IANA timezone required") — V2.6 has no reason to introduce a second, parallel timezone mechanism for calendar checks specifically.

### Impact on V2.6
Zero new configuration surface for timezone handling.

---

## Decision 8: Evaluation

### Question
How do we know the Scheduling Agent's detection and suggestions are actually correct?

### Recommendation
1. **New scheduling test set**: 8–10 emails, hand-labeled — some clearly proposing a specific meeting time, some ambiguous ("let's connect sometime"), some with no scheduling content at all. Confirm `proposed_meeting_time` is populated only for the clear cases, and null for ambiguous/absent ones (mirrors the `actionable` field's existing precision-first philosophy from Phase 1).
2. **Calendar-check correctness**: against a test calendar fixture with known busy/free windows, confirm the agent correctly identifies conflicts and proposes only genuinely free alternative slots.
3. **Phase 1 regression**: re-run the original 15-email set — must still meet original precision/recall targets after the prompt change (Decision 3), same bar V2.4 established.
4. **V2.4 adversarial set regression**: re-run V2.4's 8–10 adversarial emails — confirm `injection_suspected`/`sender_trust_signal` behavior is unaffected by the new field.

### Rationale
- Reuses the exact evaluation patterns already established (Phase 1 bar, V2.4's accuracy-not-diff bar, hard-requirement-style correctness checks) rather than inventing new evaluation philosophy for this phase.

### Impact on V2.6
Concrete gate before this phase is considered done — consistent with every prior phase requiring measured evidence, not just design confidence.

---

## Decision 9: Regression Safety

### Question
How do we confirm V2.6 doesn't destabilize anything built in V2.1–V2.5?

### Recommendation
`git diff --stat` must show changes scoped only to:
- `extraction_prompt.py` (Decision 3's single field)
- `mcp_servers/calendar_mcp/` (new)
- `app/scheduling.py` (new)
- `app/mcp_clients.py` (extended to spawn the calendar server, per V2.1's existing pattern)
- Review UI additions for the separate "Also add to calendar" action (Decision 5)

Zero changes to `app/policy.py`, `app/sender_trust.py`, `app/triage.py`, `app/extractor.py`'s correction-notes logic (V2.5), `gmail_client.py`, `notion_client.py`.

### Rationale
- Same scoped-diff discipline every prior phase used as its final check — the list of "should be empty" files is itself a statement of exactly what this phase is and isn't allowed to touch.

### Impact on V2.6
Final gate. If the diff includes anything outside this list, that's a signal the phase drifted beyond what was approved.

---

## Summary Table

| # | Decision | Recommendation | V2.6 Impact |
|---|---|---|---|
| 1 | Calendar MCP | Build custom, reuse Gmail's build-vs-adopt logic and OAuth pattern | Low new risk, familiar shape |
| 2 | OAuth scope | Extend existing consent; graceful degradation if not granted | No forced re-auth break |
| 3 | Extraction contract | Reopen `proposed_meeting_time` field, now justified by a real consumer | Prompt change #2, accuracy-bar tested |
| 4 | Agent workflow | Check availability, suggest up to 3 alternatives, simple nearest-slot heuristic | Self-contained, no optimization complexity |
| 5 | Approval boundary | Calendar booking is a separate explicit human action, never auto | Zero interaction with V2.3's policy engine |
| 6 | Security | Reuse V2.4's existing gates, no new logic | No new security surface |
| 7 | Timezone | Reuse V1's mandatory IANA timezone | No new config |
| 8 | Evaluation | New scheduling test set + calendar-fixture check + Phase 1 + V2.4 regression | Concrete correctness gate |
| 9 | Regression safety | Scoped diff — policy/sender-trust/triage/extractor untouched | Confirms boundaries held |

---

## Approval Status

- [ ] Decision 1: Calendar MCP (build custom)
- [ ] Decision 2: OAuth scope expansion + graceful degradation
- [ ] Decision 3: Reopen `proposed_meeting_time` field
- [ ] Decision 4: Scheduling Agent workflow (nearest-slot heuristic)
- [ ] Decision 5: Separate human approval for calendar booking (no auto)
- [ ] Decision 6: Security boundary reuse (no new logic)
- [ ] Decision 7: Timezone reuse (V1 Decision 5)
- [ ] Decision 8: Evaluation requirements
- [ ] Decision 9: Regression safety (scoped diff)

---

## Status: DRAFT — AWAITING REVIEW

**Next step once approved**: Hand this doc, `app/deadline_resolver.py`, `mcp_servers/gmail_mcp/` (as the pattern to follow for Decision 1), and the current review UI to Claude Code, scoped to Decisions 1–9. `create_event` must never be reachable from anywhere except the explicit human action in Decision 5 — that's the one thing worth checking by hand in the diff, not just trusting the report.
