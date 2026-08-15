# Inbox-to-Action V1 MVP — Design Decisions for Approval

Review and approve each decision before Phase 1 implementation begins.

---

## Decision 1: Store Raw + Cleaned Email Text

### Question
Should the `emails` table store the original HTML from Gmail AND the preprocessed version, or just the cleaned version?

### Current State
Both docs reference storing raw + cleaned, but don't specify the schema explicitly.

### Recommendation
```sql
CREATE TABLE emails (
  id SERIAL PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users(id),
  message_id VARCHAR NOT NULL,           -- Gmail API ID
  thread_id VARCHAR NOT NULL,
  raw_text TEXT NOT NULL,                -- Original from Gmail (HTML + signatures)
  cleaned_text TEXT NOT NULL,            -- After preprocessing (HTML stripped, etc.)
  received_at TIMESTAMP NOT NULL,
  UNIQUE(user_id, message_id),          -- Prevent re-extraction of same email
  ...
);
```

### Rationale
- **Debugging**: If extraction fails, you can compare raw vs. cleaned to diagnose whether the bug is preprocessing or the prompt.
- **Traceability**: You can re-extract with an improved prompt without re-fetching from Gmail.
- **Minimal cost**: Storage is negligible for Phase 1.
- **Foreign key**: `user_id` is required for the `UNIQUE(user_id, message_id)` constraint (see Decision 2).

### Impact on MVP
Enables debugging extraction failures. Critical for Phase 1 validation.

---

## Decision 2: Email Deduplication

### Question
How do you prevent the same email being re-extracted on a second scan?

### Current State
Spec mentions storing `message_id` and `thread_id` (from Gmail API), but neither doc specifies how to use them to prevent duplicates.

### Recommendation
```sql
-- Add unique constraint to emails table:
ALTER TABLE emails ADD CONSTRAINT unique_user_message 
  UNIQUE(user_id, message_id);

-- On scan, before extraction:
if email_exists(user_id, gmail_message_id):
  skip extraction
else:
  proceed with fetch → preprocess → extract
```

**Note**: The `user_id` foreign key is also defined in Decision 1 (emails table schema).

### Rationale
- **Data integrity**: Prevents duplicate candidates cluttering the review UI.
- **Cost control**: Avoids redundant Claude API calls.
- **User trust**: "5 new candidates" should actually be 5 new emails, not the same email extracted twice.
- **Multi-user safety**: `user_id` in the constraint ensures each user can have their own copy of a globally-replicated email (if needed in future); for MVP, it's a single user.

### Impact on MVP
Essential for multi-scan workflows. Required for Phase 1 validation to work reliably.

---

## Decision 3: Thread Context Depth

### Question
When building thread context for Claude, how many prior emails should you include?

### Current State
Spec says "recent thread context to avoid obvious mistakes"; CLAUDE.md says "e.g. the last few messages" — both are vague.

### Recommendation
```python
# Fetch the most recent 5 emails in the thread (including the latest)
# Pass to Claude as thread context
# EXPERIMENTAL: This value is tunable based on Phase 1 results
THREAD_CONTEXT_DEPTH = 5

emails_for_context = db.query(Email)\
  .filter(thread_id == thread_id)\
  .order_by(Email.received_at.desc())\
  .limit(THREAD_CONTEXT_DEPTH)\
  .all()

# Store in config.py as a configurable constant:
# THREAD_CONTEXT_DEPTH = 5  # Adjust based on Phase 1 evaluation results
```

### Rationale
- **Accuracy**: 5 emails usually captures enough context to distinguish "new request" from "already done" without being excessive.
- **Cost**: Smaller prompt = cheaper Claude API call.
- **Simplicity**: A fixed number is easier to test and tune than complex time windows.
- **Experimental**: This is an initial value. Phase 1 evaluation will determine whether 5 is sufficient or if a different depth is needed.

### Impact on MVP
Affects extraction accuracy. Must be validated in Phase 1. Conservative default (5) minimizes cost while providing safety.

---

## Decision 4: Confidence Threshold

### Question
Claude returns a confidence score (0.0–1.0). What score clears the review-UI threshold to show to users?

### Current State
CLAUDE.md emphasizes "precision over recall" and "start conservative and tune," but doesn't specify a number.

### Recommendation
```python
# In config.py:
# Initial experimental threshold (WILL BE TUNED based on Phase 1 evaluation)
CONFIDENCE_THRESHOLD = 0.7

# In routes:
candidates = db.query(TaskCandidate)\
  .filter(status == 'pending')\
  .filter(actionable == True)\  # Must be actionable first
  .filter(confidence >= CONFIDENCE_THRESHOLD)\
  .order_by(confidence.desc())\
  .all()
```

### Rationale
- **Actionability first**: The `actionable` flag is the primary filter (true/false). Confidence is a secondary ranking signal.
- **Signal-to-noise**: Confidence is not a probability, but a ranking signal. Higher confidence candidates surface first.
- **User trust**: If 20% of suggestions are wrong, users ignore the tool. If <5% are wrong, they'll engage.
- **Experimental threshold**: 0.7 is an initial starting point, NOT a validated value. Phase 1 evaluation on the labeled test set will determine the optimal threshold based on precision/recall tradeoff.

### Impact on MVP
Controls what the user sees. Initial threshold (0.7) is a starting point for Phase 1 evaluation. Tuning after Phase 1 evaluation is explicit feedback loop based on real false-positive rate.

---

## Decision 5: User Timezone (For Deadline Resolution)

### Question
Resolving "Friday" to a date requires the user's timezone. How do you store and retrieve it?

### Current State
Spec mentions "user's timezone" is needed (section 7). CLAUDE.md mentions it but doesn't specify storage.

### Recommendation
```sql
-- Add to users table (REQUIRED, not optional):
CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  email VARCHAR UNIQUE NOT NULL,
  timezone VARCHAR NOT NULL,  -- IANA timezone (e.g., 'America/New_York', 'Asia/Karachi')
  ...
);

-- In deadline_resolver.py, use zoneinfo (Python 3.9+):
from zoneinfo import ZoneInfo

def resolve_deadline_phrase(
  deadline_phrase: str, 
  email_received_at: datetime, 
  user_timezone: str
) -> Optional[date]:
  tz = ZoneInfo(user_timezone)  # Prefer zoneinfo over pytz
  # Convert email_received_at to user's local time
  # Then resolve "Friday" in that context
  ...
```

### Rationale
- **Correctness**: "Friday" means different days depending on timezone. If user is in PT and email arrived Thu 11pm PT, "Friday" resolves to Fri PT, not Fri UTC.
- **No silent fallback**: Do NOT default to UTC. The application must have the user's actual timezone before attempting deadline resolution.
- **For MVP testing**: The test user's timezone should be configured directly in the database (config, not UI). This ensures correct resolution from the start.
- **zoneinfo**: Use Python's built-in `zoneinfo` (available in Python 3.9+) rather than `pytz` for simplicity and accuracy.
- **User experience**: If due dates are wrong (off by a day), the Notion task is wrong.

### For Phase 1 Testing
The test user must have a valid IANA timezone configured (e.g., 'America/New_York'). Do not use UTC as a fallback for real users.

### Impact on MVP
Critical for date accuracy. Without a correct timezone, "Friday" resolves to the wrong day. Timezone must be configured for the test user before Phase 2 (Gmail integration).

---

## Decision 6: Edited Candidate Tracking

### Question
When a user edits a candidate (changes task, deadline, assignee) before approving, how do you record what was changed?

### Current State
Spec says "Edit → modify the candidate, then create the approved version" (section 9). CLAUDE.md mentions status `edited` but doesn't detail the schema.

### Recommendation

#### Schema
```sql
CREATE TABLE task_candidates (
  id SERIAL PRIMARY KEY,
  email_id INT NOT NULL REFERENCES emails(id),
  
  -- Claude's original extraction (immutable):
  claude_task TEXT,
  claude_deadline_phrase TEXT,
  claude_assignee TEXT,
  claude_reason TEXT,
  claude_confidence FLOAT,
  
  -- User's final version (may differ if edited):
  final_task TEXT,
  final_deadline_phrase TEXT,
  final_assignee TEXT,
  
  -- Status: pending, edited, approved, dismissed
  status VARCHAR DEFAULT 'pending',
  
  -- Resolved date + Notion link (only on approve):
  resolved_due_date DATE,
  notion_page_id VARCHAR,
  
  created_at TIMESTAMP DEFAULT NOW(),
  ...
);

-- Separate table for audit trail (append-only):
CREATE TABLE user_decisions (
  id SERIAL PRIMARY KEY,
  candidate_id INT REFERENCES task_candidates(id),
  user_id INT REFERENCES users(id),
  action VARCHAR,  -- 'approved', 'edited', 'dismissed'
  changed_fields JSONB,  -- e.g., {"task": "old → new", ...}
  decided_at TIMESTAMP DEFAULT NOW(),
  ...
);
```

#### Workflow
1. Claude generates candidate → status `pending`, all `claude_*` fields filled, all `final_*` fields null
2. User edits → PATCH `/candidates/:id` with new values → update `final_*` columns, set status `edited`, log to `user_decisions`
3. User approves → set status `approved`, resolve deadline, call Notion API with `final_*` values (fallback to `claude_*` if `final_*` is null)

### Rationale
- **User agency**: Fixes Claude's mistakes before Notion.
- **Future evaluation/improvement**: `user_decisions` is append-only history for future model/evaluation improvement. Note: Fine-tuning and training are explicitly out of scope for V1 (see spec section 11).
- **Clarity**: Keeps Claude's original extraction separate from user's final version. Aids debugging and traces user intent.

### Impact on MVP
Enables user control over approval. `user_decisions` table is foundation for future learning. Append-only design is critical (no overwrites).

---

## Summary Table

| # | Decision | Recommendation | MVP Impact |
|---|----------|---|---|
| 1 | Raw + Cleaned Text | Store both in `emails` table | Enables debugging Phase 1 extraction |
| 2 | Deduplication | `UNIQUE(user_id, message_id)` + skip re-scans | Prevents duplicates on multi-scan |
| 3 | Thread Depth | Last 5 emails in thread (experimental) | Balances accuracy vs. cost |
| 4 | Confidence Threshold | Start with 0.7, actionable first (experimental) | Controls signal-to-noise in review UI |
| 5 | User Timezone | IANA timezone required, no UTC fallback, zoneinfo | Ensures correct deadline resolution |
| 6 | Edited Candidates | Separate `claude_*` and `final_*` columns | User control + audit trail for learning |

---

## Approval Status

- [x] Decision 1: Raw + Cleaned Text — **APPROVED**
- [x] Decision 2: Email Deduplication — **APPROVED** (with user_id foreign key clarification)
- [x] Decision 3: Thread Depth (5) — **APPROVED** (experimental/configurable)
- [x] Decision 4: Confidence Threshold (0.7) — **APPROVED AS REVISED** (initial experimental value, actionable filter first)
- [x] Decision 5: User Timezone — **APPROVED AS REVISED** (IANA timezone required, no UTC fallback, zoneinfo preferred)
- [x] Decision 6: Edited Candidate Tracking — **APPROVED** (wording updated)

---

## Status: READY FOR PHASE 1

All 6 design decisions have been reviewed and approved with revisions incorporated.

**Next Step**: Phase 1 implementation begins — build the extraction experiment script with hand-labeled test set.
