# Inbox-to-Action V2.3: Trust / Risk Policy Engine — Design Decisions for Approval

Review and approve each decision before V2.3 implementation begins.

**Scope of V2.3**: Introduce a policy layer that decides, per candidate, whether the existing human-approval step can be skipped. This is the first V2 phase where the system can take a real action (create a Notion task) without a human looking at it first — treat it accordingly.

**Explicitly out of scope for V2.3**:
- Scheduling Agent and Calendar MCP (still deferred, per V2.2)
- Prompt-injection defense layer (V2.4) — see the sequencing note below, this is not a "do later, no rush" item for V2.3
- Learning loop / personalization from corrections (V2.5)
- Any change to `extraction_prompt.py`, `extractor.py`, or the V2.2 triage filter
- Multi-agent restructuring beyond what V2.2 already established

---

## ⚠️ Sequencing note — read before Decision 1

The original roadmap orders this as V2.3 (trust engine) and treats prompt-injection defense as a separate, later item (V2.4). That ordering is fine for *design*, but it is not safe for *rollout*.

Right now, every candidate — no matter how confidently or incorrectly extracted — gets caught by a human before anything happens. That review step is the system's only defense against a malicious or malformed email tricking extraction into a wrong-but-confident result. V2.3 proposes removing that backstop for some candidates. Until an injection-defense boundary exists (V2.4), a high-confidence extraction is not the same thing as a *trustworthy* extraction.

**Recommendation carried through every decision below**: V2.3 ships in **shadow mode only** — the policy engine computes and logs what it *would* do, but real auto-action stays off — until V2.4 exists. This is formalized in Decision 5 and isn't optional.

---

## Decision 1: What "Auto-Act" Actually Means Here

### Question
The roadmap describes a generic trust engine deciding between "auto" and "ask human" across arbitrary actions. What does that mean concretely in a codebase where the only action taken is creating one Notion page?

### Current State
There is exactly one write action in the whole system: `approve_candidate` creates a Notion task from a candidate's `final_*` fields (V1 Decision 6). There's no delete, no email sending, no data transfer — the generic "some actions are catastrophic, some are trivial" framing from the roadmap doesn't map onto real variation here.

### Recommendation
Scope V2.3 to a single question: **should this specific candidate skip the human review screen before its Notion page is created?** Do not build a general-purpose multi-action risk engine — there's only one action to gate.

### Rationale
- Building a generic engine for a single action type is speculative complexity with nothing to generalize over yet.
- Keeping the question narrow makes it possible to reason about correctness precisely (Decision 6), instead of hand-waving about hypothetical future actions.

### Impact on V2.3
Keeps the implementation small: one policy function, one decision point, one action it gates.

---

## Decision 2: What Feeds the Policy — Confidence + App-Specific Risk Signals

### Question
Confidence alone (V1's `confidence` field) is a ranking signal, not a correctness guarantee. What else should the policy consider before allowing auto-creation?

### Recommendation
Combine `confidence` with two cheap, already-available signals:

| Signal | Source | Why it matters |
|---|---|---|
| `confidence` | Existing extraction output | Primary ranking signal (V1 Decision 4) |
| `deadline_resolved` | Output of `deadline_resolver.py` | If the deadline phrase failed to resolve to a real date, the candidate is incomplete — never auto-act on it |
| `assignee_named` | Whether `assignee` is non-null | A named assignee raises the cost of being wrong (task attributed to the wrong person); an unassigned task is lower-stakes if wrong |

```python
def compute_policy(candidate) -> Literal["auto_eligible", "review_required"]:
    if not candidate.deadline_resolved:
        return "review_required"          # incomplete data, never auto-act
    if candidate.confidence >= AUTO_CONFIDENCE_THRESHOLD and candidate.assignee is None:
        return "auto_eligible"
    return "review_required"              # default: ask a human
```

`AUTO_CONFIDENCE_THRESHOLD` starts as a separate, higher constant than V1's `CONFIDENCE_THRESHOLD` (which only gates *visibility* in the review UI, not action) — recommend starting at 0.95, tunable only after shadow-mode evaluation (Decision 6).

### Rationale
- These three signals are already computed by the existing pipeline — no new extraction work, no new Claude calls.
- Requiring `assignee is None` for auto-eligibility is deliberately conservative: a wrongly-attributed task is a worse failure mode than a wrongly-created unassigned one, and it's cheap to just exclude that case entirely rather than model its risk.
- This is intentionally a narrow, easy-to-audit rule, not a scored/weighted model — appropriate for a first version of something that removes a safety net.

### Impact on V2.3
A candidate is only ever auto-eligible in the narrowest, lowest-stakes case: high confidence, resolvable deadline, no named person to misattribute.

---

## Decision 3: Auto-Act Is Not Silent

### Question
If a candidate is auto-eligible, does its Notion page get created with no further trace, or does the user still see it?

### Recommendation
Auto-created tasks are never silent. They:
1. Get created in Notion immediately (once shadow mode is lifted per Decision 5), and
2. Appear in a visible "Auto-created — review anytime" list in the existing review UI, with a one-click **undo** (deletes the Notion page, reverts candidate status to `pending`).

No candidate is ever created and then untraceable. "Skips the review gate" means "doesn't block on a human before acting," not "hides from the human."

### Rationale
- This is the practical form of "controlled autonomy" the roadmap gestures at — auto-action with a visible, reversible trail beats either full silence or full manual gating.
- Keeps trust-building incremental: users can watch the auto-create list for a while before trusting it, without the system ever doing something they can't see or reverse.

### Impact on V2.3
Adds one new UI list and one undo action; no new destructive capability introduced.

---

## Decision 4: Schema Changes

### Question
What needs to change in `task_candidates` / `user_decisions` (from V1 Decision 6) to support this?

### Recommendation

```sql
-- task_candidates: add policy outcome + inputs, and a new status value
ALTER TABLE task_candidates ADD COLUMN policy_decision VARCHAR;   -- 'auto_eligible' | 'review_required'
ALTER TABLE task_candidates ADD COLUMN deadline_resolved BOOLEAN;
-- status column (from V1) gets a new possible value: 'auto_approved'
--   pending → auto_approved (skips edited/approved) OR pending → approved (human path, unchanged)

-- user_decisions: log auto-actions the same way human ones are logged
-- action = 'auto_approved', changed_fields = null, decided_at = NOW()
-- this keeps the append-only audit trail (V1 Decision 6) as the single source
-- of truth for both human and automated decisions
```

### Rationale
- Reuses V1's existing audit design instead of inventing a parallel logging mechanism — an auto-action is just another row in `user_decisions`, distinguishable by its `action` value.
- Storing `policy_decision` on the candidate itself (not just in the log) makes shadow-mode reporting (Decision 6) a simple query, not a log-parsing exercise.

### Impact on V2.3
Small, additive schema change. No existing columns or constraints touched.

---

## Decision 5: Shadow Mode Before Real Mode — Non-Negotiable for First Rollout

### Question
How do we avoid shipping an auto-action policy that turns out to be wrong, given there's no way to "unsend" a bad first impression of an autonomous feature?

### Recommendation
V2.3 ships behind a single flag:

```python
# config.py
AUTO_ACT_ENABLED = False   # V2.3 initial default — do not flip without explicit approval
```

While `False`: `compute_policy()` still runs and its result is still logged to `task_candidates.policy_decision` and `user_decisions`, but every candidate — regardless of policy outcome — still goes through the normal human review screen exactly as it does today. Nothing about the user's current experience changes.

This flag stays `False` until **both**:
1. Decision 6's shadow-mode evaluation passes its bar, **and**
2. V2.4 (injection-defense boundary) exists — per the sequencing note above.

### Rationale
- This turns "trust the policy" from an assumption into something measured against real history before it ever acts for real.
- Ties the flag to an explicit, externally-visible condition (V2.4 existing) so "we'll add injection defense eventually" can't quietly become "we shipped auto-action without it."

### Impact on V2.3
V2.3 can be fully built, tested, and merged without ever changing user-visible behavior. Flipping the flag is a distinct, separately-approved decision — not a byproduct of merging this phase.

---

## Decision 6: Evaluation — What "The Policy Is Trustworthy" Actually Means

### Question
Confidence/recall numbers from Phase 1 measured extraction accuracy. What's the equivalent bar for the auto-act policy?

### Recommendation
Use the existing `user_decisions` audit history (V1 Decision 6) as ground truth. For every historical candidate a human already approved, edited, or dismissed, retroactively compute what `compute_policy()` would have said.

**Hard requirement — this is the actual gate, not a tunable target**: zero historically-**edited** or historically-**dismissed** candidates may be retroactively marked `auto_eligible`. A false auto-eligible on something a human corrected or rejected is exactly the failure mode this whole phase exists to prevent.

Secondary (informational, used to tune `AUTO_CONFIDENCE_THRESHOLD`, not a hard gate):
- % of historically-**approved-unchanged** candidates that would have been `auto_eligible` — this is the efficiency number; if it's very low (e.g., <5%), the threshold may be too conservative to be worth shipping at all, which is a legitimate outcome to report, not a failure to fix.

### Rationale
- Reuses data that already exists — no new labeled dataset needed, unlike Phase 1.
- The hard/soft split mirrors V1 Decision 4's structure (actionable-first, confidence as secondary signal): correctness is a gate, efficiency is a tuning dial.

### Impact on V2.3
This is the number that answers "is the policy good enough to flip Decision 5's flag" — not a vibe check.

---

## Decision 7: Regression Safety

### Question
How do we confirm V2.3 doesn't change anything about extraction or triage (V2.1/V2.2)?

### Recommendation
1. Re-run the Phase 1 15-email evaluation — results must be byte-identical to the current `evaluation_results.json`, confirming `extraction_prompt.py` and `extractor.py` are untouched.
2. Confirm `git diff --stat` shows zero changes to `phase1_extraction/`, `app/triage.py` (V2.2), `app/gmail_client.py`, `app/notion_client.py`, and the MCP server wrappers (V2.1).
3. With `AUTO_ACT_ENABLED = False`, run a full scan → review cycle and confirm the UI and approval flow are pixel-for-pixel the same as before V2.3, aside from the new (empty, until Decision 5's flag flips) auto-created list.

### Rationale
Same principle as V2.1 Decision 6 and V2.2's revised regression requirements: a phase that's supposed to be additive should be provably additive, not just "probably fine."

### Impact on V2.3
Gate for calling V2.3's *code* done — separate from Decision 6, which gates whether it's ever turned on for real.

---

## Summary Table

| # | Decision | Recommendation | V2.3 Impact |
|---|---|---|---|
| 1 | Scope | Single action gated (Notion creation), not a generic risk engine | Keeps implementation small |
| 2 | Policy inputs | confidence + deadline_resolved + assignee_named, simple rule not a scored model | Narrow, auditable auto-eligibility |
| 3 | Not silent | Auto-created tasks are visible + undoable, never hidden | Preserves user trust/visibility |
| 4 | Schema | Additive columns on `task_candidates`, reuse `user_decisions` audit log | No breaking changes |
| 5 | Shadow mode | `AUTO_ACT_ENABLED=False` until Decision 6 passes AND V2.4 exists | No real behavior change on merge |
| 6 | Evaluation | Hard zero-tolerance on false auto-eligible vs. historical edits/dismissals | The actual go/no-go gate |
| 7 | Regression | Byte-identical Phase 1 results, zero diff outside new files | Proves extraction/triage untouched |

---

## Approval Status

- [ ] Decision 1: Scope (single action, not generic engine)
- [ ] Decision 2: Policy inputs (confidence + deadline_resolved + assignee_named)
- [ ] Decision 3: Not silent (visible + undoable)
- [ ] Decision 4: Schema changes
- [ ] Decision 5: Shadow mode default, tied to V2.4 existing
- [ ] Decision 6: Evaluation hard requirement
- [ ] Decision 7: Regression safety

---

## Status: DRAFT — AWAITING REVIEW

**Next step once approved**: Hand this doc, `app/routes_candidates.py`, `app/deadline_resolver.py`, and the `user_decisions` schema to Claude Code with an instruction scoped to Decisions 1–4 and 7. Decision 5's flag stays `False` regardless of what Claude Code implements — flipping it is a separate, later approval, not part of this implementation task. Do not implement anything from V2.4 or V2.5 even if it seems like a natural next step while working on this.
