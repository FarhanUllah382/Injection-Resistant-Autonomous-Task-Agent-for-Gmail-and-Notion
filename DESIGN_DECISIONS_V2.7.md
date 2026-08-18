# Inbox-to-Action V2.7: Continuous Monitoring + UI Redesign — Design Decisions for Approval

Review and approve each decision before V2.7 implementation begins.

**Scope of V2.7**: Two things, kept deliberately separate even though they ship together:
1. Replace on-demand scanning with automatic polling (Option A, ~2 min interval) — changes *when* the pipeline runs, not what it does.
2. Redesign the review UI to feel professional and to surface new candidates as they arrive, without hiding or weakening any existing safety-relevant control.

**Explicitly out of scope for V2.7**:
- True push notifications via Gmail Pub/Sub webhooks (Option B) — documented as a future upgrade, not built now
- Any change to `app/policy.py`, `app/sender_trust.py`, `app/triage.py`, or `extraction_prompt.py` — this phase touches *when* candidates are discovered and *how* they're displayed, never the logic that decides what happens to them
- Auto-approving, auto-booking, or auto-dismissing anything — every guarantee from V2.3–V2.6 carries forward unchanged
- Mobile native apps — "responsive" web UI only

---

## Decision 1: Polling Mechanism and Interval

### Question
Where does the ~2-minute timer live, and how does it trigger a scan?

### Recommendation
An in-process background scheduler inside the existing backend (e.g. APScheduler running an async job) — **not** a new service in `docker-compose.yml`. Every ~2 minutes, it calls the exact same scan entry point that manual triggers already use today.

```python
# app/scheduler.py (new)
@scheduler.scheduled_job("interval", minutes=2)
async def poll_gmail():
    await run_scan(user_id)   # the same function manual/on-demand scans already call
```

### Rationale
- Matches V2.1 Decision 3's reasoning exactly: fewer new failure modes, no new container to keep alive, no new port. Continuous monitoring is a scheduling change, not an infrastructure change.
- Reusing `run_scan()` directly (rather than reimplementing scan logic for the scheduled path) guarantees the automatic and manual paths can never silently drift apart.

### Impact on V2.7
Smallest possible new surface for "the system now checks by itself."

---

## Decision 2: Concurrency and Failure Safety

### Question
What happens if a poll takes longer than 2 minutes, or Gmail's API errors out repeatedly?

### Recommendation
- **Single-flight lock**: if a poll is still running when the next one is scheduled, skip that tick rather than running two scans concurrently.
- **Fail quiet, retry next interval**: a failed poll (network error, expired token, API error) is logged, not surfaced to the user as an error — it simply tries again in 2 minutes. No retry storm: back off to a longer interval (e.g. 10 min) after 3 consecutive failures, and resume the normal 2-minute cadence once a poll succeeds.
- If the failure is an expired/revoked OAuth token specifically, surface a **single, clear** "reconnect Gmail" prompt in the UI rather than silently failing forever — this is the one failure mode that genuinely needs the user's attention.

### Rationale
- Extends the "fail open" principle from V2.2 Decision 3 into infrastructure reliability: a scheduling hiccup should never be the reason a real task goes undetected, and it should never spam the user with transient noise either.
- Distinguishing "will fix itself" (network blip) from "needs you" (revoked auth) keeps notification meaningful instead of noisy.

### Impact on V2.7
Prevents the two realistic failure modes — overlapping runs and silent permanent breakage — without adding much code.

---

## Decision 3: Pipeline Reuse and Dedup Guarantee

### Question
Does polling risk creating duplicate candidates if the same email gets fetched across multiple poll cycles?

### Current State
V1 Decision 2 already established `UNIQUE(user_id, message_id)` specifically to make re-scanning safe.

### Recommendation
No new dedup logic needed. Polling is just `run_scan()` called more often — the existing constraint already guarantees a second fetch of the same email is a no-op.

### Rationale
- This is a case where an earlier decision, made for a different reason (manual re-scans), turns out to fully cover a new use case for free. Worth confirming explicitly rather than assuming.

### Impact on V2.7
Zero new work; one thing to verify in testing (Decision 9), not build.

---

## Decision 4: Security — No New Attack Surface

### Question
Does continuous monitoring change the system's security posture at all?

### Recommendation
No. Polling reuses the exact same Gmail OAuth token and MCP call (`list_recent_messages`) as manual scanning. Every downstream guarantee applies identically and unconditionally to automatically-discovered candidates:
- V2.2 triage still filters obvious junk before extraction.
- V2.4's `injection_suspected` / `sender_trust_signal` checks still run on every candidate, still hard-override the policy engine.
- V2.3's human-approval gate still blocks Notion creation.
- V2.6's calendar booking is still a separate, explicit, human-only action.

The only thing that changes is *how soon* a candidate reaches you, not what checks it passes through first.

### Rationale
- This is worth stating explicitly and verifying (Decision 9), not just assumed — "the system now runs itself more often" is exactly the kind of framing that invites scope-creep into "so maybe it should act on its own more too," which is not what's being approved here.
- Option B (webhooks) would introduce a real new surface — a public endpoint. That's precisely why it's deferred, not because Option A needed a workaround.

### Impact on V2.7
Confirms this phase is additive to discovery speed only, with zero effect on the trust boundaries every prior phase built.

---

## Decision 5: In-App Notification Delivery

### Question
How does the frontend learn a new candidate arrived, and how is it surfaced?

### Recommendation
Server-Sent Events (SSE) from the existing backend to the open review-UI tab — lighter weight than a full WebSocket connection, sufficient for one-directional "something changed, refresh" signals. When a new pending candidate is created, the backend pushes an event; the UI shows a toast ("New email: 'Project deadline moved to Friday' — 1 new task to review") and updates a badge count, without forcing navigation or interrupting whatever the user is doing.

If the UI tab isn't open, the next time it's opened, a lightweight "since you were away" summary badge shows the count waiting — no separate notification channel (email/push) is added in this phase.

### Rationale
- SSE is simpler to build and reason about than WebSockets for a use case that only ever needs server→client, one-way updates.
- Non-interruptive by design — matches V2.3 Decision 3's "visible but never disruptive/hidden" principle, now applied to notifications instead of auto-created tasks.

### Impact on V2.7
One new lightweight endpoint (`/events`) and one new frontend component (toast + badge).

---

## Decision 6: UI Design System

### Question
What does "professional and engaging" actually mean concretely, so this isn't just a vibe?

### Recommendation
A small, deliberate design system rather than a generic redesign:

- **Color**: neutral base (off-white/near-black text, soft gray surfaces) with one accent color for primary actions, and a **consistent, small semantic palette for candidate status** — this matters more than aesthetics here, since status color is doing real communication work: e.g. amber = pending review, green = approved, red = flagged (injection/spoofing — V2.4), slate = dismissed, blue = scheduled. Colors should be the *same* ones used consistently across the candidate list, the dashboard summary, and toasts — never redefined per-component.
- **Typography**: one clean sans-serif, a clear size/weight hierarchy (candidate task title > sender/deadline metadata > body snippet), generous line height for scan-ability — this is a review queue, users will skim it daily.
- **Layout**: card-based candidate list (not a dense table) — each card shows task, deadline, sender, status badge, and the approve/edit/dismiss actions without a click-through, so triage-by-eye is fast.
- **Dashboard summary strip** at the top: counts for "new today," "pending review," "auto-eligible awaiting your click" (V2.3), "meetings to confirm" (V2.6) — gives an at-a-glance sense of backlog without opening anything.
- **Empty/loading states**: designed, not default — an empty inbox-review state should feel like "you're caught up," not a blank page.
- **Keyboard shortcuts** for the review flow (e.g. `a` approve, `d` dismiss, `e` edit, `j`/`k` to move between candidates) — meaningful for a daily-use tool, not just decoration.

### Rationale
- Grounding "professional" in specific, testable choices (consistent status color mapping, card layout, real empty states) avoids the trap of redesign work that looks nicer but doesn't actually make daily review faster — which is the actual point of a review queue.
- Keyboard shortcuts specifically reward daily use, which is exactly what continuous monitoring is optimizing for — more candidates arriving faster means the review experience needs to scale with volume, not just look good in a screenshot.

### Impact on V2.7
Gives Claude Code (and you, reviewing the result) a concrete checklist instead of "make it look professional," which is unimplementable as stated.

---

## Decision 7: Safety-Relevant Controls Must Stay Equally Prominent

### Question
A redesign easily risks visually de-emphasizing controls that exist for safety reasons, purely by accident of "cleaning things up." How do we prevent that?

### Recommendation
Three specific controls are **not allowed to shrink, hide behind a menu, or lose visual weight** relative to the primary approve action, regardless of how the redesign otherwise looks:
1. The **undo** button on auto-created candidates (V2.3 Decision 3) — must be exactly as easy to find as approve/dismiss, not a small "..." menu item.
2. The **separate, distinct** "Also add to calendar" action (V2.6 Decision 5) — must remain visually distinguishable from task approval, never merged into a single button or a pre-checked default.
3. Any candidate flagged by V2.4 (`injection_suspected` / `sender_trust_signal: suspicious`) must be visually distinct in the card list (e.g. the red status badge from Decision 6) — a redesign that makes flagged and normal candidates look the same defeats the entire point of V2.4.

### Rationale
- This is the actual risk in "let's make the UI nicer" — not that it breaks functionality, but that visual hierarchy quietly re-prioritizes what the user notices, which can undo a safety design decision without a single line of backend code changing.
- Naming these three explicitly means Claude Code (and your own review) has a concrete checklist to verify, not a vague "don't break anything."

### Impact on V2.7
The actual gate for whether this redesign is safe to ship, separate from whether it looks good.

---

## Decision 8: Confirm the Existing Frontend Stack Before Implementing

### Question
This doc's UI recommendations are framework-agnostic. What needs to happen before Claude Code starts building them?

### Recommendation
Claude Code should inspect the current `web/` directory first (framework, component structure, existing styling approach) and adapt Decision 6/7's principles to whatever already exists, rather than this doc prescribing specific component code. If `web/` is a from-scratch/minimal frontend, this is a good time to establish the design system properly; if it's already a mature setup, the redesign should extend it, not replace it wholesale.

### Rationale
- I don't have visibility into `web/`'s current implementation from here — prescribing specific framework code without knowing the actual stack risks a redesign task that doesn't fit the codebase.

### Impact on V2.7
Adds a short discovery step before implementation, same as V2.1 Decision 2's "evaluate before building" pattern.

---

## Decision 9: Evaluation and Regression Safety

### Question
How do we confirm V2.7 doesn't change any decision logic, and that polling behaves as intended in practice?

### Recommendation
1. Run the system for a trial period (e.g. a real day of inbox traffic) with polling active — confirm no duplicate candidates appear (Decision 3), confirm Gmail API usage stays comfortably within quota at the 2-minute cadence.
2. Manually trigger a Gmail API failure (e.g. temporarily revoke token in a test account) — confirm the fail-quiet + backoff + "reconnect" prompt behavior from Decision 2 works as designed, not just in theory.
3. `git diff --stat` — zero changes to `app/policy.py`, `app/sender_trust.py`, `app/triage.py`, `extraction_prompt.py`, `app/scheduling.py`'s decision logic. Changes scoped to `app/scheduler.py` (new), a new `/events` endpoint, and `web/`.
4. Manual UI review against Decision 7's three-item checklist specifically — this can't be fully automated, it needs an actual look.

### Rationale
- Splits "does the backend behave correctly" (points 1–3, testable) from "does the redesign preserve safety-relevant visual hierarchy" (point 4, needs a human eye) — treating both as required, not optional.

### Impact on V2.7
Final gate — consistent with every prior phase's insistence on evidence over confidence.

---

## Summary Table

| # | Decision | Recommendation | V2.7 Impact |
|---|---|---|---|
| 1 | Polling mechanism | In-process scheduler, 2-min interval, reuses `run_scan()` | No new infra |
| 2 | Failure safety | Single-flight lock, fail-quiet + backoff, surface only auth failures | Robust without noise |
| 3 | Dedup | Existing `UNIQUE(user_id, message_id)` already covers it | Zero new code |
| 4 | Security | No new attack surface — same OAuth, same downstream checks unconditionally | Confirms trust boundaries hold |
| 5 | Notifications | SSE + non-interruptive toast/badge | Lightweight, one new endpoint |
| 6 | Design system | Semantic status colors, card layout, dashboard strip, real empty states, keyboard shortcuts | Concrete, checkable "professional" |
| 7 | Safety-relevant UI | Undo, calendar-add, and flagged-candidate styling can't shrink or hide | Prevents redesign from eroding safety |
| 8 | Stack discovery | Inspect `web/` before implementing | Fits existing codebase |
| 9 | Evaluation | Live trial + failure injection test + scoped diff + manual UI checklist | Evidence-based gate |

---

## Approval Status

- [ ] Decision 1: Polling mechanism (in-process, 2 min)
- [ ] Decision 2: Failure safety (fail-quiet, backoff, auth-failure prompt)
- [ ] Decision 3: Dedup (confirmed covered by existing constraint)
- [ ] Decision 4: Security posture (no new surface)
- [ ] Decision 5: Notifications (SSE + toast/badge)
- [ ] Decision 6: UI design system (as specified / edit)
- [ ] Decision 7: Safety-relevant controls stay prominent (non-negotiable checklist)
- [ ] Decision 8: Stack discovery before implementation
- [ ] Decision 9: Evaluation requirements

---

## Status: DRAFT — AWAITING REVIEW

**Next step once approved**: Hand this doc, `app/routes_scan.py`, and `web/` (for Claude Code to inspect per Decision 8) to Claude Code, scoped to Decisions 1–9. Decision 7's checklist should be verified by you personally once implementation is done — it's the one item in this doc that a written report can't fully substitute for.
