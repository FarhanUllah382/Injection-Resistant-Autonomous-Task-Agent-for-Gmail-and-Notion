# Inbox-to-Action V2.5: Correction Learning Loop — Design Decisions for Approval

Review and approve each decision before V2.5 implementation begins.

**Scope of V2.5**: Use the existing `user_decisions` audit log (V1 Decision 6) to make extraction *judgment calls* — what counts as a task, how to interpret ambiguous phrasing — better reflect how this specific user actually corrects the system, without retraining or fine-tuning Claude.

**Explicitly out of scope for V2.5**:
- Fine-tuning or retraining any model. V1 Decision 6 already ruled this out for the audit log; V2.5 doesn't revisit that.
- Any change to V2.3's policy thresholds or V2.4's hard security overrides based on "learned" patterns — see Decision 2, this is a hard boundary, not an oversight.
- Automatic, unreviewed rule promotion — every learned correction is human-approved before it affects anything (Decision 3).
- Scheduling Agent / Calendar MCP (still deferred)
- Flipping `AUTO_ACT_ENABLED` (still V2.3 Decision 5's call, untouched by this phase)
- A broader Phase-1-style dataset expansion (that's V2.6 territory if you pursue it later, not part of this doc)

---

## Decision 1: What "Learning" Means — Context Injection, Not Fine-Tuning

### Question
The roadmap's "learning loop" could mean anything from full fine-tuning to a hardcoded if-statement. What's actually being built?

### Current State
V1 Decision 6 already established the audit log (`claude_*` vs `final_*` fields, append-only `user_decisions`) explicitly **not** for fine-tuning in V1. Every prior phase has kept `extractor.py`'s Claude call simple and stateless per-request.

### Recommendation
V2.5 adds a short block of natural-language correction notes to the extraction call's context — not a model change, not a fine-tune, not a vector store or embedding-based retrieval system. Just: a handful of human-approved sentences describing this user's actual preferences, included in the prompt at call time.

```
[appended to the extraction call, not to the locked base prompt — see Decision 4]

Notes from this user's past corrections:
- "FYI" or "heads up" emails are usually not tasks, even if phrased politely.
- When an email says "review" without specifying who, assume it's for the user.
```

### Rationale
- Matches the roadmap's own framing of this as "a practical first version of a learning loop," not a research project in personalization.
- Keeps this phase cheap and auditable — every "thing the system learned" is a literal sentence a human can read, not a weight update no one can inspect.
- Consistent with every prior phase's bias toward deterministic, inspectable mechanisms over opaque ones.

### Impact on V2.5
Sets expectations correctly: this is a lightweight nudge to extraction judgment, not a system that gets smarter on its own.

---

## Decision 2: Hard Boundary — Corrections Never Touch Security Logic

### Question
V2.4 was built specifically because a single historical dismissal (candidate id=9) revealed a real gap. Should the learning loop be able to generalize from cases like that?

### Recommendation
**No — this is a hard boundary, not a judgment call.** Correction notes may only ever influence extraction-level output (`actionable`, `task`, `deadline`, `assignee` interpretation). They are never passed to `compute_policy()` (V2.3) and never influence `injection_suspected` or `sender_trust_signal` (V2.4). Those stay owned entirely by V2.3/V2.4's deterministic, hard-override logic.

Architecturally: correction notes are assembled and injected only inside `extractor.py`'s call construction. `policy.py` and `sender_trust.py` have no code path that reads them, by design.

This guarantee is about outcomes, not just code. A note must never change `policy_decision` for any candidate, even indirectly — e.g. by shifting the `confidence` or `assignee` values extraction produces, which `compute_policy()` (V2.3) consumes without knowing whether a note influenced them. "No code path reads them" is necessary but not sufficient on its own; Decision 7 check 5 is what actually verifies the outcome-level guarantee, not just the code-level one.

### Rationale
- Id=9 is exactly the kind of single data point that a naive learning loop would over-generalize from — "dismissed" isn't a stable signal for "extraction was wrong," it can just as easily mean "extraction was right but the sender was untrustworthy," which is a security judgment, not a preference.
- V2.4 already solved that specific problem with a deterministic, evaluated, hard-override rule. Letting a soft, natural-language "learned note" duplicate or (worse) soften that would undo the exact thing V2.4 was built to guarantee.
- This mirrors V2.4 Decision 4's own principle: some things are hard overrides, not scoring inputs. That principle extends here by keeping learning entirely out of the override path.

### Impact on V2.5
This is the single most important constraint in this document. Everything else below operates inside it.

---

## Decision 3: Human Curation Gate — No Automatic Rule Promotion

### Question
How do raw corrections in `user_decisions` become the notes described in Decision 1?

### Recommendation
A **manual-only** batch step — run on demand by the user (e.g. a standalone script, same pattern as `phase1_extraction/run_experiment.py`), never live in the request path and never on a schedule. V2.5 does not introduce background workers, schedulers, or cron of any kind; that would reopen CLAUDE.md's V1 constraint against background infrastructure, and this phase has no standing reason to revisit that constraint. If scheduled execution is ever genuinely needed, that is a distinct, explicitly-flagged decision for a later doc, not a byproduct of this one. The step:
1. Reviews recent edits/dismissals from `user_decisions`.
2. Proposes candidate correction notes as short natural-language sentences, using Claude since it's off the hot path and its output is a *proposal*, not something that acts on its own. This call reads historical email content (via the `emails`/`task_candidates` rows behind the relevant `user_decisions`) — the same untrusted external data extraction already processes, from the same inbox, potentially including the same kind of adversarial content V2.4 was built to defend against. It must use the same containment principle: historical email content is wrapped in delimiters (e.g. `<email_content>` tags, consistent with `extraction_prompt.py`) with an explicit instruction that it is data to summarize into a proposal, never instructions to act on. Skipping this would reopen, one step removed, exactly the injection surface V2.4 closed for the main extraction call — a subtly-injected historical email could otherwise get itself proposed as a plausible-looking "learned rule" that a human might approve without noticing.
3. Presents proposals to the user for explicit approval — accept, edit the wording, or reject — before anything is stored as active.

No note ever becomes active without this approval step. This mirrors every other phase's pattern: nothing changes behavior silently.

### Rationale
- A fully automatic summarizer risks encoding noise as if it were signal — one inconsistent human decision (maybe the user was just busy that day) shouldn't become a permanent "rule."
- Keeping this off the hot path means it never adds latency or a new Claude call to the actual scan/extract cycle users experience.
- The proposal step's own Claude call touches the same class of untrusted input (raw historical email content) V2.4 was built to defend against — containment there isn't a new concern, it's the same guarantee extended to a second call site.
- Manual-only keeps this phase from silently reopening CLAUDE.md's V1 no-background-worker constraint.

### Impact on V2.5
Adds one new reviewable step to the workflow, not a new automated behavior in the live pipeline.

---

## Decision 4: Storage & Injection — Extraction Prompt Stays Locked

### Question
Where do approved notes live, and how do they reach the extraction call, given `extraction_prompt.py`'s base content should stay stable?

### Recommendation

```sql
CREATE TABLE correction_notes (
    id INTEGER PRIMARY KEY,
    rule_text VARCHAR,
    source_decision_ids JSON,   -- which user_decisions rows this was derived from; JSON column, consistent with UserDecision.changed_fields — not a delimited VARCHAR
    approved_at TIMESTAMP,
    active BOOLEAN DEFAULT true
);
```

`extraction_prompt.py`'s locked base content is **not** edited. `phase1_extraction/extractor.py` is changed to accept the active notes as a new argument and append them as a distinct, clearly-labeled block when constructing the call — same pattern V2.4 used for the untrusted-content delimiter, kept separate here as a second, independent block.

`extractor.py` does not query `correction_notes` itself and gains no database dependency — it stays exactly what it is today: a standalone, DB-independent module that `phase1_extraction/run_experiment.py` can run with nothing but the Claude API and a handful of example emails (`PHASE1_README.md`, CLAUDE.md's Phase 1 isolation requirement). The caller is responsible for fetching active notes from `correction_notes` (a plain list of strings) and passing them into `extract()` / `extract_email()` as a parameter:
- In the live app, that caller is `app/routes_extract.py`.
- In evaluation contexts (Decision 6, Decision 7 check 5), the evaluation script fetches and passes them the same way.

When the caller passes no notes (or an empty list — the default when the parameter is omitted), the notes block is omitted entirely and the call is byte-identical to pre-V2.5 behavior.

### Rationale
- Keeps the base prompt (already regression-tested twice, in Phase 1 and again after V2.4) stable and diffable in isolation from the dynamic, per-user corrections layer.
- A dedicated table (rather than a config file) makes the approve/reject/deactivate flow in Decision 3 straightforward to build against.
- A JSON column for `source_decision_ids` matches the existing `UserDecision.changed_fields` convention instead of inventing a new delimited-string format for the same kind of data.
- Passing notes in as an argument, rather than having `extractor.py` query the database itself, preserves Phase 1's standalone-script constraint — `run_experiment.py` must keep working with no Postgres dependency, which a DB-querying `extractor.py` would break.

### Impact on V2.5
`extraction_prompt.py` diff stays empty. Changes are scoped to `phase1_extraction/extractor.py`'s call-assembly logic (a new parameter, not a new dependency), `app/routes_extract.py` (fetches and passes active notes), and one new table.

---

## Decision 5: Caps and Conflict Handling

### Question
What stops the notes block from growing indefinitely or containing contradictory guidance?

### Recommendation
- The 5-note cap is **read-time only**: `SELECT ... FROM correction_notes WHERE active = true ORDER BY approved_at DESC LIMIT 5`. This is a pure query-time selection — it never writes to any row. A 6th (or 60th) active note stays `active = true` in the database indefinitely; it simply isn't among the 5 most-recently-approved, so it isn't selected for injection this call. The system never automatically flips another note's `active` column because of the cap — the only way `active` changes is a direct, explicit user action (Decision 3's approval flow, or a manual deactivate). The user can manually deactivate any note at any time regardless of count.
- No automatic expiry or decay logic in V2.5 — that's added complexity for a problem that hasn't been observed yet. A manual on/off toggle per note is sufficient for a first version.
- No automatic conflict detection between notes. The human-approval gate (Decision 3) is the conflict check — a person reading 5 short sentences before approving a 6th is a reasonable review burden; building automated contradiction-detection for this is over-engineering at this scale.

### Rationale
- Keeps prompt bloat bounded without inventing a ranking/relevance system that has nothing real to be tuned against yet.
- Consistent with the project's general pattern of choosing the simplest mechanism that closes the actual gap, and deferring sophistication until evidence calls for it (same instinct that kept V2.2's triage heuristic-only, and V2.3's risk factors to three simple signals).

### Impact on V2.5
Bounded, predictable prompt size. Easy to reason about what's actually influencing any given extraction call.

---

## Decision 6: Evaluation

### Question
How do we know a correction note actually helps, rather than just feeling plausible?

### Recommendation
Two checks, both required before a note is treated as validated (not just approved):
1. **No regression**: re-run the Phase 1 15-email set with the active notes included. Precision/recall must not drop below the original targets — a note that fixes one pattern but breaks unrelated extraction is a net loss.
2. **Retroactive correction check**: for each newly proposed note, find the historical `user_decisions` rows it was derived from and confirm that re-running extraction with the note included would have produced output matching the `final_*` (human-corrected) fields instead of the original `claude_*` (wrong) fields, for that specific case — without changing the output on other, unrelated historical candidates.
   - **Field-level / semantic equivalence, not exact string equality.** Compare on the fields the correction actually targets (e.g. `actionable`, `assignee`, deadline interpretation) — LLM output isn't byte-stable across calls, and a human's edited wording in `final_task` isn't itself what a note is trying to reproduce. A note passes if it changes the underlying *judgment* to match the human's correction, not if it reproduces their exact phrasing.
   - **Evaluate against the actual active-note set, not each note in isolation.** Run the check with the up-to-5 notes that would really be active together in production once this note is approved (the proposed note plus whichever currently-approved notes would still fall in the top-5 by recency) — that's what real extraction calls will actually see. A note that passes in isolation but interacts badly with another active note would be missed by isolated testing. Single-note evaluation may still be used *in addition*, to diagnose which specific note caused a given result — but the pass/fail gate is the combined-set behavior.

### Rationale
- Mirrors V2.3 Decision 6 and V2.4 Decision 6's pattern: don't trust a mechanism because the design looks reasonable, measure it against real history first.
- The "doesn't change unrelated candidates" half of check 2 matters as much as the "fixes the target case" half — a note that's too broad is its own kind of failure.
- Testing against the combined active-note set (not each note alone) matters because Decision 5 explicitly declines automatic conflict detection between notes — the retroactive check is the only place interaction effects would actually surface before a note goes live.

### Impact on V2.5
Gives a concrete pass/fail per note, not just a vibe that "this seems like a reasonable rule."

---

## Decision 7: Regression Safety

### Question
How do we confirm V2.5 doesn't quietly widen scope into V2.3/V2.4's territory, or destabilize the locked base prompt?

### Recommendation
1. `git diff --stat` on `extraction_prompt.py` — must be empty (base prompt untouched, per Decision 4).
2. `git diff --stat` on `app/policy.py` and `app/sender_trust.py` — must be empty. This confirms the code boundary (no import, no read of `correction_notes`) held — but code-untouched is not the same as outcome-unaffected. Check 5 is what verifies the guarantee that actually matters.
3. Phase 1 15-email set with zero active correction notes — results identical to the current baseline, confirming the new code path is fully inert when no notes are approved yet.
4. Phase 1 15-email set with any approved notes active — must still meet original precision/recall targets (Decision 6, check 1).
5. **Behavioral policy-equivalence check (required, not diff-based)**: take the selected historical/test candidate set — the real candidates behind Decision 6's retroactive check, plus the Phase 1 15-email set — and for each one, run the full extraction → policy pipeline twice: once with the currently-active correction notes included, once with none. Confirm `compute_policy()` produces the **identical `policy_decision`** both times, for every candidate. Notes are permitted to change `task` / `deadline` / `assignee` interpretation; they must never change whether a candidate ends up `auto_eligible` vs. `review_required`. This is the check that actually proves Decision 2's boundary holds — a note that leaves `policy.py` completely untouched can still shift a policy outcome by changing the `confidence` or `assignee` values extraction feeds into it, and only this check catches that.

### Rationale
- Point 2 confirms the code-level boundary; point 5 confirms the outcome-level boundary, which is the one that actually matters. Neither is sufficient alone — point 2 without point 5 would give false confidence that a purely data-flow-driven influence (notes shifting `confidence`/`assignee`, which then shift `compute_policy()`'s output) can't happen, when it can.
- Point 3 confirms this phase is safe to merge even before any notes exist, same "ships inert, gets activated deliberately" pattern V2.3 used for `AUTO_ACT_ENABLED`.

### Impact on V2.5
Final gate before this phase is considered complete.

---

## Summary Table

| # | Decision | Recommendation | V2.5 Impact |
|---|---|---|---|
| 1 | What "learning" means | Context injection (short approved sentences), not fine-tuning | Keeps mechanism cheap and auditable |
| 2 | Security boundary | Corrections never reach `policy.py` or `sender_trust.py` — hard boundary, verified as an outcome, not just a code diff (Decision 7 check 5) | Prevents undoing V2.3/V2.4's guarantees |
| 3 | Curation gate | Manual-only batch step (no scheduler/cron), human-approved before any note is active; proposal call applies V2.4-style containment to historical email content | No silent behavior change, no new injection surface |
| 4 | Storage/injection | New `correction_notes` table (JSON `source_decision_ids`); `extraction_prompt.py` base stays locked; `extractor.py` stays DB-independent, notes passed in by the caller | Isolable, diffable change surface; Phase 1 standalone execution preserved |
| 5 | Caps/conflicts | Max 5 active notes selected read-time only (`ORDER BY approved_at DESC LIMIT 5`); cap never auto-modifies `active`; no auto-expiry, manual toggle only | Bounded, simple, no over-engineering |
| 6 | Evaluation | No-regression check + retroactive correction check, field-level/semantic equivalence, evaluated against the full active-note set | Concrete pass/fail per note, tested as production would actually run it |
| 7 | Regression safety | Zero diff on prompt/policy/sender-trust files + inert-by-default behavior + behavioral policy-equivalence check (notes on vs. off) | Confirms boundary held in practice, not just in code |

---

## Approval Status

- [ ] Decision 1: Learning = context injection, not fine-tuning
- [ ] Decision 2: Hard boundary — never touches policy/security logic
- [ ] Decision 3: Human curation gate, no automatic promotion
- [ ] Decision 4: Storage (`correction_notes` table), prompt stays locked
- [ ] Decision 5: Caps and conflict handling (5-note max, manual toggle)
- [ ] Decision 6: Evaluation requirements (no-regression + retroactive check)
- [ ] Decision 7: Regression safety (scoped diff + inert-by-default)

---

## Status: DRAFT — AWAITING REVIEW

**Next step once approved**: Hand this doc, `phase1_extraction/extractor.py`, `app/routes_extract.py`, the `user_decisions` schema, and `app/policy.py`/`app/sender_trust.py` (so Claude Code can see exactly what it must not touch) to Claude Code, scoped to Decisions 1–7. No correction notes should exist or be active by default when this phase merges — Decision 7's inert-by-default check (point 3) and the behavioral policy-equivalence check (point 5) are what confirm that.
