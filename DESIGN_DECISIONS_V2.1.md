# Inbox-to-Action V2.1: MCP Integration — Design Decisions for Approval

Review and approve each decision before V2.1 implementation begins.

**Scope of V2.1**: Replace the direct Gmail API and Notion API call sites in `app/` with equivalent calls made through MCP servers. Everything else stays identical to V1: `extraction_prompt.py` is unchanged, the human-approval workflow is unchanged, the DB schema is unchanged.

**Explicitly out of scope for V2.1** (later phases, per the V2 roadmap):
- Triage / Extraction / Scheduling agent split (V2.2)
- Confidence + risk trust engine, auto-action (V2.3)
- Prompt-injection defense layer around tool use (V2.4)
- Learning loop from user corrections (V2.5)
- Formal evaluation harness expansion (V2.6)
- Calendar MCP / scheduling

---

## Decision 1: Gmail MCP — Build vs. Adopt

### Question
Do we write a custom Gmail MCP server, or adopt an existing published one?

### Current State
V1 has custom Gmail API integration already built (fetch, thread context, dedup by `message_id`). There's no single de facto standard Gmail MCP server, and the existing OAuth scope/consent flow is already wired to our own backend.

### Recommendation
Build a thin custom Gmail MCP server that wraps our **existing** Gmail API code. Do not adopt a third-party Gmail MCP server for V2.1.

```
mcp_servers/
├── gmail_mcp/
│   ├── server.py        # Wraps existing gmail_client.py, exposes tools:
│   │                     #   list_recent_messages(thread_id?, since?)
│   │                     #   get_message(message_id)
│   └── __init__.py
```

### Rationale
- Our OAuth flow, token storage, and dedup logic already exist and are tested — re-wrapping them is far lower risk than adopting a third-party server with an unfamiliar auth model.
- A custom server can expose exactly the two tools we need (list, get) instead of a broad surface we'd have to audit.
- Keeps this phase mechanical: same underlying HTTP calls, new interface on top.

### Impact on V2.1
Low risk if scoped narrowly. Main new work is the MCP server shim, not new Gmail logic.

---

## Decision 2: Notion MCP — Build vs. Adopt

### Question
Same question, for Notion.

### Current State
Notion publishes an official MCP server. Our V1 Notion integration only does one thing: create a task page in a database from `final_*` candidate fields.

### Recommendation
Evaluate Notion's official MCP server first. If it supports creating a database page with our required properties (task, deadline, assignee), adopt it instead of building our own. If it doesn't cleanly map to our schema, fall back to a thin custom wrapper (same pattern as Decision 1).

**This evaluation should happen before implementation starts** — spend no more than a day confirming fit; don't build both in parallel.

### Rationale
- Notion's write surface is simple and well-suited to an official server — less reason to duplicate it ourselves.
- Gmail and Notion don't need to use the same build-vs-adopt answer; each is judged on its own auth/schema fit.

### Impact on V2.1
Could save implementation time if the official server fits. Adds a short evaluation step before coding begins.

---

## Decision 3: Transport & Deployment

### Question
How do the MCP servers run, and how does the backend reach them — local subprocess, or a networked service?

### Current State
V1's `docker-compose.yml` runs the backend and DB. No MCP infrastructure exists yet.

### Recommendation
Use **stdio transport**, with the backend spawning each MCP server as a local subprocess. Do **not** add new services to `docker-compose.yml` in V2.1.

```python
# backend spawns and talks to the MCP server over stdio,
# same process boundary as V1's api wrapper call — just a different protocol
```

### Rationale
- Fewer new failure modes: no new network ports, no new service to keep alive, no new item in `docker-compose.yml` to misconfigure.
- stdio is the simplest MCP transport and matches "V2.1 is plumbing, not infrastructure."
- If V2.2+ needs multiple agents sharing one MCP server (e.g., both extraction and scheduling agents hitting Calendar MCP), promoting to a networked service is a small, isolated follow-up decision — not a blocker now.

### Impact on V2.1
Minimizes new operational surface. Revisit transport choice only if a later phase needs shared/concurrent access.

---

## Decision 4: Credential Flow into MCP Servers

### Question
How do Gmail OAuth tokens and the Notion integration token reach the MCP server process without creating a second place secrets live?

### Current State
V1 stores tokens via the existing backend token store (referenced in `.env.example` / DB, not duplicated).

### Recommendation
Pass credentials to the MCP server **per-invocation**, via environment variables set by the backend at subprocess-spawn time, sourced from the existing token store. The MCP server itself stores nothing persistently.

```python
# backend, at spawn time:
env = {"GMAIL_ACCESS_TOKEN": token_store.get(user_id, "gmail"), ...}
subprocess = spawn_mcp_server("gmail_mcp", env=env)
```

### Rationale
- No new secret storage location to secure or audit.
- If a token is revoked/rotated, there's exactly one place that needs updating.
- Matches Decision 5 from V1 (no silent fallbacks, single source of truth) in spirit.

### Impact on V2.1
Prevents credential drift between two storage locations. No `.env.example` changes needed beyond what V1 already has.

---

## Decision 5: Replacement Scope — What Changes, What Doesn't

### Question
Exactly which call sites get replaced, and what must Claude Code leave untouched?

### Recommendation

**Replaced:**
- Gmail fetch calls in the scan/ingestion path → Gmail MCP tool calls
- Notion page-creation call in the approve path → Notion MCP tool call (or adopted official server, per Decision 2)

**Untouched:**
- `phase1_extraction/extraction_prompt.py` — reused unchanged, as stated in `PHASE1_README.md`
- Confidence threshold / `actionable` filter logic
- `task_candidates`, `user_decisions`, `emails` schema (Decisions 1, 2, 6 from V1)
- The human approval UI/workflow — Claude still only suggests, user still approves

### Rationale
Keeping the blast radius explicit prevents an implementing agent from "helpfully" touching extraction logic or the approval gate while it's in the neighborhood.

### Impact on V2.1
This section should be quoted directly in the instruction given to Claude Code.

---

## Decision 6: Regression Safety — Proving V2.1 Didn't Change Behavior

### Question
How do we confirm the MCP-backed pipeline produces the same results as the V1 direct-API pipeline?

### Recommendation
1. Before removing the old direct-call code, run the same 15-email Phase 1 test set through both paths (old direct calls vs. new MCP calls) and diff the extraction outputs — they should be identical, since only the transport changed, not the prompt or the email content.
2. Only delete the old direct-API code after that diff is clean. No dual-maintained code paths beyond this verification step — MCP becomes the sole path once verified.
3. If Notion's official server is adopted (Decision 2), separately verify the created page has the same properties as V1's output on at least one manual test task.

### Rationale
- V2.1 is supposed to be behavior-neutral. This step is the actual evidence of that, not just an assumption.
- Avoids the trap of maintaining two parallel implementations "just in case."

### Impact on V2.1
Adds one verification step before cleanup, but is the only thing that actually proves this phase is safe to ship.

---

## Summary Table

| # | Decision | Recommendation | V2.1 Impact |
|---|---|---|---|
| 1 | Gmail MCP | Build custom, wrap existing Gmail client | Low risk, mechanical |
| 2 | Notion MCP | Evaluate official server first; wrap custom only if it doesn't fit | Time-boxed evaluation before coding |
| 3 | Transport | stdio subprocess, no new docker-compose service | Minimal new infra |
| 4 | Credentials | Passed per-invocation via env vars from existing token store | No new secret storage |
| 5 | Replacement scope | Gmail fetch + Notion create only; extraction prompt and approval flow untouched | Prevents scope creep |
| 6 | Regression safety | Diff old vs. new outputs on Phase 1 test set before deleting old code | Behavior-neutral guarantee |

---

## Approval Status

- [ ] Decision 1: Gmail MCP (build custom)
- [ ] Decision 2: Notion MCP (evaluate official first)
- [ ] Decision 3: Transport (stdio subprocess)
- [ ] Decision 4: Credential flow (per-invocation env vars)
- [ ] Decision 5: Replacement scope (explicit allow/deny list)
- [ ] Decision 6: Regression safety (diff before delete)

---

## Status: DRAFT — AWAITING REVIEW

**Next step once approved**: Hand this doc, `app/` (current Gmail/Notion call sites), and `PHASE1_README.md` to Claude Code with an instruction scoped to Decision 5 — implement only what's listed as "Replaced," and leave everything under "Untouched" alone.
