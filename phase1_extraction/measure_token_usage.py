"""
TEMPORARY measurement script — not part of the pipeline.

Measures actual Claude API token usage/cost for the extraction call exactly
as phase1_extraction/extractor.py makes it (same model, same system prompt,
same max_tokens, no thinking/effort override — nothing about the real call
is changed here). Runs against the first 3 emails in test_emails.jsonl
because Postgres isn't reachable locally, so the real scanned-Gmail rows
in `emails` can't be read (see chat: DB connection refused, user chose to
proceed against the standalone test set instead of starting Postgres).

Also runs one supplementary, clearly-separate call with a simulated
thread_context (built from two other test emails) to isolate the marginal
cost THREAD_CONTEXT_DEPTH adds — this is NOT one of the "3 emails" and is
reported separately.

Safe to delete after use. Makes real, billed API calls.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from anthropic import Anthropic
from phase1_extraction.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, TEST_EMAILS_PATH
from phase1_extraction.extraction_prompt import EXTRACTION_SYSTEM_PROMPT, build_user_prompt

client = Anthropic(api_key=ANTHROPIC_API_KEY)

# Sonnet 5 pricing per Anthropic's current published rates (introductory
# pricing runs through 2026-08-31; standard rate shown alongside).
PRICE_PER_MTOK = {
    "intro": {"input": 2.00, "output": 10.00},
    "standard": {"input": 3.00, "output": 15.00},
}


def load_emails(n: int) -> list[dict]:
    emails = []
    with open(TEST_EMAILS_PATH, "r") as f:
        for line in f:
            emails.append(json.loads(line))
            if len(emails) >= n:
                break
    return emails


def call_and_measure(label: str, email_data: dict, thread_context: str = "") -> dict:
    user_prompt = build_user_prompt(email_data, thread_context)

    # Free pre-call sizing — what will actually be sent, counted before billing.
    pre_count = client.messages.count_tokens(
        model=ANTHROPIC_MODEL,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    # Identical call shape to phase1_extraction/extractor.py — model,
    # max_tokens, system, messages unchanged. No thinking/effort override.
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=500,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    block_types = [b.type for b in response.content]
    thinking_blocks = [b for b in response.content if b.type == "thinking"]
    text_block = next((b for b in response.content if b.type == "text"), None)

    usage = response.usage
    result = {
        "label": label,
        "model": response.model,
        "stop_reason": response.stop_reason,
        "chars": {
            "email_body": len(email_data.get("body", "")),
            "thread_context": len(thread_context),
            "system_prompt": len(EXTRACTION_SYSTEM_PROMPT),
            "user_prompt_total": len(user_prompt),
        },
        "pre_call_count_tokens": {
            "input_tokens": pre_count.input_tokens,
        },
        "usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
            "total_tokens": usage.input_tokens + usage.output_tokens,
        },
        "content_block_types": block_types,
        "thinking_block_present": len(thinking_blocks) > 0,
        "thinking_block_text_len": sum(len(b.thinking or "") for b in thinking_blocks),
        "response_text_preview": (text_block.text[:150] if text_block else None),
    }
    return result


def print_result(r: dict) -> None:
    print(f"\n--- {r['label']} ---")
    print(f"  model: {r['model']}   stop_reason: {r['stop_reason']}")
    print(f"  chars: email_body={r['chars']['email_body']}  thread_context={r['chars']['thread_context']}  "
          f"system_prompt={r['chars']['system_prompt']}  user_prompt_total={r['chars']['user_prompt_total']}")
    print(f"  pre-call count_tokens: input_tokens={r['pre_call_count_tokens']['input_tokens']}")
    u = r["usage"]
    print(f"  usage.input_tokens={u['input_tokens']}  usage.output_tokens={u['output_tokens']}  "
          f"cache_creation={u['cache_creation_input_tokens']}  cache_read={u['cache_read_input_tokens']}  "
          f"total={u['total_tokens']}")
    print(f"  content block types: {r['content_block_types']}")
    print(f"  thinking block present: {r['thinking_block_present']}  "
          f"(thinking text length: {r['thinking_block_text_len']} chars — 0 expected, display defaults to 'omitted')")
    print(f"  response preview: {r['response_text_preview']!r}")


def cost_row(input_tokens: int, output_tokens: int, tier: str) -> float:
    p = PRICE_PER_MTOK[tier]
    return (input_tokens / 1_000_000) * p["input"] + (output_tokens / 1_000_000) * p["output"]


def main():
    emails = load_emails(3)
    print(f"Loaded {len(emails)} emails from {TEST_EMAILS_PATH}")
    print(f"Model: {ANTHROPIC_MODEL}   max_tokens: 500 (same as extractor.py)   thinking param: not set (unchanged)")

    results = []
    for email in emails:
        r = call_and_measure(f"email #{email['id']} — {email['subject']!r}", email, thread_context="")
        print_result(r)
        results.append(r)

    # --- Supplementary, separate measurement: marginal cost of thread_context ---
    # Simulates THREAD_CONTEXT_DEPTH pulling in prior full emails, using two
    # other real test emails formatted exactly as app/routes_extract.py's
    # _build_thread_context() does. NOT counted in the 3-email average above.
    prior = load_emails(5)[3:5]
    thread_blocks = [
        f"[2026-08-10T09:00:00] From: {e['from']}\nSubject: {e['subject']}\n{e['body']}"
        for e in prior
    ]
    thread_context = "\n\n---\n\n".join(thread_blocks)
    target_email = emails[0]
    r_thread = call_and_measure(
        f"SUPPLEMENTARY (not one of the 3): email #{target_email['id']} WITH simulated 2-email thread_context",
        target_email,
        thread_context=thread_context,
    )
    print_result(r_thread)

    # --- Summary ---
    print("\n" + "=" * 70)
    print("SUMMARY (3 emails, no thread context — matches most real single emails)")
    print("=" * 70)
    total_input = sum(r["usage"]["input_tokens"] for r in results)
    total_output = sum(r["usage"]["output_tokens"] for r in results)
    total_cache_creation = sum((r["usage"]["cache_creation_input_tokens"] or 0) for r in results)
    total_cache_read = sum((r["usage"]["cache_read_input_tokens"] or 0) for r in results)
    n = len(results)

    print(f"Total input tokens (3 emails):  {total_input}")
    print(f"Total output tokens (3 emails): {total_output}  (includes any thinking tokens — not billed/reported separately by the API)")
    print(f"Total cache_creation_input_tokens: {total_cache_creation}")
    print(f"Total cache_read_input_tokens:     {total_cache_read}")
    print(f"Avg input/email:  {total_input / n:.1f}")
    print(f"Avg output/email: {total_output / n:.1f}")

    for tier in ("intro", "standard"):
        p = PRICE_PER_MTOK[tier]
        total_cost = cost_row(total_input, total_output, tier)
        per_email = total_cost / n
        per_100 = per_email * 100
        print(f"\n[{tier} pricing: ${p['input']}/MTok in, ${p['output']}/MTok out]")
        print(f"  Cost for these 3 emails: ${total_cost:.5f}")
        print(f"  Cost per email:          ${per_email:.5f}")
        print(f"  Extrapolated to 100 emails (no thread context): ${per_100:.4f}")

    print("\n" + "-" * 70)
    print("SUPPLEMENTARY: thread_context marginal cost (1 email, 2 prior emails as context)")
    print("-" * 70)
    u = r_thread["usage"]
    baseline = next(r for r in results if r["label"].startswith(f"email #{target_email['id']}"))
    delta_input = u["input_tokens"] - baseline["usage"]["input_tokens"]
    print(f"  input_tokens without thread_context: {baseline['usage']['input_tokens']}")
    print(f"  input_tokens WITH thread_context (2 prior emails): {u['input_tokens']}")
    print(f"  delta from thread_context alone: +{delta_input} input tokens")
    for tier in ("intro", "standard"):
        p = PRICE_PER_MTOK[tier]
        delta_cost = (delta_input / 1_000_000) * p["input"]
        print(f"  [{tier}] added cost from this one email's thread_context: ${delta_cost:.5f}")

    # Dump raw results for the record
    out_path = Path(__file__).parent / "measure_token_usage_results.json"
    with open(out_path, "w") as f:
        json.dump({"three_emails": results, "supplementary_thread_context": r_thread}, f, indent=2)
    print(f"\nRaw results written to {out_path}")


if __name__ == "__main__":
    main()
