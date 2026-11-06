# Inbox-to-Action V2.2: Triage Pre-Filter — Design Decisions for Approval

Review and approve each decision before V2.2 implementation begins.

**Scope of V2.2**: Introduce a deterministic Triage pre-filter ahead of the existing Extraction Agent, so obviously non-actionable email never reaches the (more expensive) extraction call. Extraction itself — `extraction_prompt.py` and `extractor.py` — is not touched in any way. Triage's only job is deciding *which emails are handed to* the existing, unmodified extraction pipeline. Nothing about Scheduling (agent, schema, or contract changes) is part of V2.2.

**Explicitly out of scope for V2.2** (later phases, per the V2 roadmap):
- **Scheduling Agent** — fully deferred, no implementation, no schema hook, no contract change of any kind in V2.2 (see Decision 5)
- **Calendar MCP** — deferred alongside Scheduling; when that phase is actually scheduled, it gets its own build-vs-adopt mini-doc, same shape as V2.1 Decisions 1–2
- Confidence + risk trust engine, auto-action (V2.3)
- Prompt-injection defense layer (V2.4)
- Learning loop from user corrections (V2.5)
- Any evaluation-harness work beyond what Decision 6 requires to prove Triage is safe (V2.6)
- Any change to `extraction_prompt.py` or `extractor.py` — see Decision 4

---

## V2.1 vs. V2.2 Workflow

V2.1 shipped the MCP transport migration; the pipeline shape itself was untouched. V2.2 inserts exactly one new step, entirely within the existing single-process request handling (no new services, no background workers — CLAUDE.md V1 constraints still bind).

**V2.1 (current, shipped):**
```
Gmail MCP fetch (list_recent_messages / get_message)
  → preprocess (clean_email_body)
  → save Email row
  → [/extract] every stored, not-yet-extracted email
      → Extraction Agent (extraction_prompt.py + extractor.py)
  → task_candidate created if actionable
  → review UI → user approves
  → Notion MCP create_notion_task
```

**V2.2 (this doc):**
```
Gmail MCP fetch                              ← unchanged from V2.1
  → preprocess                               ← unchanged from V2.1
  → save Email row                           ← unchanged from V2.1
  → [/extract] every stored, not-yet-extracted email
      → Triage (NEW — deterministic, no LLM call, no MCP call)
          obviously non-actionable? ──YES──▶ skip, log as triaged_out,
                                              email never reaches extraction
          uncertain / anything else ─────────▶ MUST proceed to extraction
      → Extraction Agent (extraction_prompt.py + extractor.py, byte-for-byte
                           unchanged from V2.1)
  → task_candidate created if actionable     ← unchanged from V2.1
  → review UI → user approves                ← unchanged from V2.1
  → Notion MCP create_notion_task             ← unchanged from V2.1
```

Triage is a pure, local, synchronous Python function operating on the already-fetched, already-cleaned email text. It calls neither Claude nor any MCP server, and it does not run inside `mcp_servers/` — it's an ordinary `app/` module, same as `preprocessing.py`.

---

## Decision 1: What "Triage" Means Here — Heuristic vs. Second LLM Call

### Question
The V2 roadmap describes Triage as a separate reasoning step ("is this actionable?"). But `extraction_prompt.py` already returns an `actionable` boolean as part of its single call. Do we add a *second Claude call* purely for triage, or handle triage without an extra LLM call?

### Current State
Every email that reaches extraction costs one Claude API call, regardless of whether it's obviously a newsletter or an obviously real request. There is no pre-filter today.

### Recommendation
Implement Triage as a **deterministic, cheap heuristic filter — no additional LLM call, in V2.2 or ever, without a separate future decision to revisit this.** Only emails Triage marks as obviously non-actionable are skipped; every other email — including anything uncertain — proceeds to the existing Extraction Agent, unmodified.

### Rationale
- The stated goal of Triage — "don't waste a full extraction call on obvious junk" — is fully achievable without a second LLM round-trip, at near-zero cost and near-zero new failure surface.
- A second LLM call doubles the number of Claude requests per email and introduces a new place for the pipeline to be wrong, for a case (junk detection) that heuristics already handle well.
- `extraction_prompt.py`'s own `actionable` field remains the sole authority for "is this a task." Triage's only job is to avoid calling that logic on obvious spam/newsletters — never to duplicate or override its judgment.

### Impact on V2.2
Keeps the architecture change small and cheap. Reduces Claude API calls on typical inboxes (most inboxes are majority newsletters/notifications).

---

## Decision 2: Triage Heuristics — What They Check, and Where They Live

### Question
What specifically does the heuristic filter check, and where is it configured?

### Recommendation

```
app/
└── triage.py    # New module, called from routes_scan.py or routes_extract.py
                  # (exact call site TBD at implementation time) before
                  # extraction — NOT inside phase1_extraction/, NOT inside
                  # mcp_servers/

def should_triage_out(email) -> bool:
    # Returns True only if the email should be SKIPPED (not sent to
    # extraction). Returns False for anything uncertain.
```

Checks, in order (any match → skip; anything that doesn't clearly match → do not skip):
- `List-Unsubscribe` header present (standard bulk-mail signal)
- Sender domain in a configurable `TRIAGE_BLOCKED_DOMAINS` list (e.g., known newsletter/notification senders — `config.py`, user-editable)
- Sender local-part matches a `no-reply@` / `noreply@` / `notifications@` pattern **AND** subject contains no keyword from a small `ACTION_KEYWORDS` allowlist (e.g., "please", "review", "due", "deadline", "assign") — the keyword check exists specifically so an automated system email that *does* contain a real request isn't blindly dropped just because of its sender pattern

### Rationale
- These are all cheap, deterministic, well-understood signals — no ambiguity about why an email was skipped.
- The keyword-allowlist exception on the `no-reply@` rule matters: some systems (ticketing tools, CI, calendar invites) send from no-reply addresses but contain genuine action items.
- Keeping the block/allow lists in `config.py` (same place as `THREAD_CONTEXT_DEPTH`, `CONFIDENCE_THRESHOLD` from V1) matches existing conventions instead of inventing a new config surface.

### Impact on V2.2
Deterministic, auditable, easy to tune without touching extraction logic.

---

## Decision 3: Triage Failure Mode — False Negatives Are the Primary Risk

### Question
If triage logic errors, or a case doesn't clearly match any heuristic, what happens?

### Recommendation
**Fail open, always.** Any error inside `should_triage_out()`, and any email that doesn't cleanly match a skip rule, MUST proceed to extraction. Triage only ever *removes* work from the pipeline — it must never be the reason a real task silently disappears before a human or the extraction step ever sees it.

### Rationale
- **This is a different risk profile than extraction's, and that's deliberate, not a contradiction of CLAUDE.md's "precision over recall."** Extraction's precision-over-recall bias governs what gets *surfaced to the user* — a missed task there is recoverable (the email is still in the inbox, still gets seen). Triage sits *before* that: a false negative here (an email wrongly marked "skip") never reaches extraction at all, is never stored as a candidate, and is invisible to the user by design. That failure is silent and effectively unrecoverable through the app. A false positive at the triage layer (an obvious newsletter that isn't skipped) just costs one avoidable Claude call — cheap and harmless.
- Given that asymmetry, Triage's error-handling bias is the mirror image of extraction's: when uncertain, extraction says "not actionable"; when uncertain, Triage says "don't skip."
- This mirrors the spirit of V1 Decision 5's "actionable first" principle applied one layer earlier: a cheap filtering step must never outrank the more careful downstream check it feeds.

### Impact on V2.2
Sets a hard rule Claude Code should not deviate from, regardless of how tempting a "smarter" triage rule might look. This is the single most important constraint in this document.

---

## Decision 4: Extraction Agent — Untouched, Not Formalized, Not Restructured

### Question
Does adding Triage require any change to `extraction_prompt.py` or `extractor.py`?

### Recommendation
**No.** Zero changes to `extraction_prompt.py` and zero changes to `extractor.py` — not a refactor, not a rename, not a "formalization" of extraction as a named agent. The only change anywhere in the pipeline is that extraction is now invoked on a filtered subset of emails instead of on every stored email, via the exact same `extractor.py` interface as today.

```
for email in fetched_emails:
    if triage.should_triage_out(email):
        log_triaged_out(email)
        continue
    candidate = extractor.extract(email)   # unchanged call, unchanged prompt
```

### Rationale
- `extraction_prompt.py` is explicitly locked per `PHASE1_README.md` ("will be reused in the backend unchanged") and per CLAUDE.md — V2.2 has no reason to reopen either file.
- Keeping this decision explicit prevents an implementing agent from restructuring, renaming, or "improving" extraction while working nearby. V2.2 is scoped to *what reaches* extraction, never to extraction itself.

### Impact on V2.2
Zero risk to extraction accuracy, since nothing about extraction's code, prompt, or call signature changes.

---

## Decision 5: Scheduling Agent & Calendar MCP — Fully Deferred, No Schema Changes

### Question
Should V2.2 add any groundwork (schema field, contract hook) for the future Scheduling Agent?

### Recommendation
**No. Nothing.** No new field on the extraction JSON contract, no schema change to `task_candidates`, no hook of any kind. Scheduling and Calendar MCP are deferred as a complete unit to a later phase, which will get its own design-decisions doc (same shape as V2.1 Decisions 1–2: a build-vs-adopt evaluation before any code is written).

### Rationale
- Any hook added now — even something as small as an optional field — touches `extraction_prompt.py`, which directly conflicts with Decision 4. There is no version of a Scheduling schema hook that doesn't reopen the one file V2.2 has committed not to touch.
- Speculative contract changes for a feature with no defined design yet (no MCP decision, no UX decision) are exactly the kind of premature groundwork CLAUDE.md warns against ("don't add tables/fields speculatively").
- Deferring cleanly now costs nothing; the Scheduling phase can design its own contract addition deliberately, informed by whatever Scheduling actually turns out to need.

### Impact on V2.2
Removes the one place the previous draft of this document was at risk of quietly expanding scope. V2.2 stays exactly Triage + existing Extraction.

---

## Decision 6: Regression & Evaluation Requirements

### Question
How do we prove Triage is safe, and that it hasn't changed anything about extraction itself?

### Recommendation
Three separate things must each be demonstrated — none may be assumed from the others:

**1. Existing extraction behavior is unchanged.**
`git diff` on `extraction_prompt.py` and `extractor.py` must be empty. `phase1_extraction/` remains a standalone script per its own README, untouched by and unaware of `app/triage.py` — Triage lives entirely in `app/`, never in `phase1_extraction/`.

**2. The existing 15-email Phase 1 evaluation still passes, at the same bar already established.**
Re-run `phase1_extraction/run_experiment.py` exactly as-is (no triage involved — it's a standalone script, per Decision 4/CLAUDE.md build order). Results must match the current committed baseline in `phase1_extraction/evaluation_results.json` (100% precision / 100% recall, as verified during V2.1's regression check) — not just "still runs," but the same numbers.

**3. Triage does not change extraction outputs for emails that reach extraction.**
For the subset of the 15 labeled test emails that Triage does *not* skip, diff their extraction JSON output with Triage wired in front (app-level `/extract` pipeline) against the V2.1 baseline output for the same emails (no triage). These must be byte-identical — Triage changes nothing about the email content or the extraction call, so any diff here is a bug, not an expected variation. This mirrors the old-vs-new diff pattern used for V2.1 Decision 6.

**4. Zero labeled-actionable emails may be triaged out.**
Run all 15 labeled test emails through `should_triage_out()` directly. This is a **hard requirement, not a tunable threshold** like `CONFIDENCE_THRESHOLD` — if any labeled-actionable email is skipped, the heuristic is a correctness bug and must be fixed before proceeding, not shipped with a caveat.

**5. Report the skip rate, and manually spot-check real inbox mail.**
Report % of emails filtered before reaching extraction — this is the efficiency number the whole decision is justified by. Because 15 emails is a small, already-labeled sample that likely underrepresents typical newsletter noise, supplement with a manual spot-check: pull the last ~50 real emails from the test inbox, run Triage, and manually confirm nothing genuinely actionable was skipped.

### Rationale
- Decision 3's "fail open" policy protects against triage *errors*, but a heuristic that's simply *wrong* (e.g., a legitimate sender domain accidentally in the blocklist) fails open correctly per-call while still being wrong by design — only measurement catches that.
- Splitting "extraction is unchanged," "the eval bar still holds," and "triage doesn't alter what reaches extraction" into three distinct checks matters because they can fail independently — e.g., extraction code could be untouched while the *pipeline wiring* around it introduces a subtle change (wrong field passed, wrong email object shape), which only check 3 would catch.

### Impact on V2.2
This is the gate for calling V2.2 done — same role Phase 1's precision/recall targets played for V1, and the same role the old-vs-new diff played for V2.1.

---

## Summary Table

| # | Decision | Recommendation | V2.2 Impact |
|---|---|---|---|
| 1 | Triage architecture | Deterministic heuristic pre-filter, no LLM call — ever, without a separate future decision | Cheap, low new risk |
| 2 | Triage heuristics | List-Unsubscribe / blocked domains / no-reply + keyword exception, in `config.py` | Deterministic, tunable |
| 3 | Triage failure mode | Fail open, always — false negatives are the primary safety concern | Prevents silent, unrecoverable task loss |
| 4 | Extraction Agent | Zero changes to `extraction_prompt.py` or `extractor.py` — only what reaches extraction changes | Zero accuracy risk |
| 5 | Scheduling Agent / Calendar MCP | Fully deferred — no schema hook, no contract change of any kind | Keeps V2.2 scope exactly Triage + Extraction |
| 6 | Regression & evaluation | Extraction unchanged + eval bar holds + triage-doesn't-alter-extraction-output diff + zero-skip hard rule + skip-rate + manual spot-check | Gate for calling V2.2 done |

---

## Approval Status

- [ ] Decision 1: Triage architecture (heuristic-only, no LLM call)
- [ ] Decision 2: Triage heuristics (as specified / edit list)
- [ ] Decision 3: Fail-open policy (false negatives = primary risk)
- [ ] Decision 4: Extraction Agent (zero changes, formalization removed)
- [ ] Decision 5: Scheduling Agent / Calendar MCP (fully deferred, no hook)
- [ ] Decision 6: Regression & evaluation requirements (all five checks)

---

## Status: DRAFT — AWAITING REVIEW

**Next step once approved**: Hand this doc, `app/routes_scan.py` or `app/routes_extract.py` (call site TBD), `app/config.py`, and `phase1_extraction/` to Claude Code with an instruction scoped to Decisions 1–4 — implement only the triage pre-filter and its wiring, leave `extraction_prompt.py` and `extractor.py` untouched, add no Scheduling-related field or hook (Decision 5), and verify all five checks in Decision 6 before considering it done.
