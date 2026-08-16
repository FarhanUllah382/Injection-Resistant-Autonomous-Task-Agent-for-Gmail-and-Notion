"""
Claude API Extractor

Calls Claude API with the extraction prompt and returns structured JSON.

Optionally accepts correction_notes (Design Decisions V2.5, Decision 4) —
a plain list of strings the *caller* fetches from the correction_notes
table (see app/correction_notes.py) and passes in. This module never
queries the database itself, so it stays exactly what it's always been: a
standalone, DB-independent module phase1_extraction/run_experiment.py can
run with nothing but the Claude API (PHASE1_README.md's Phase 1 isolation
requirement). When correction_notes is None or empty (the default), the
call is byte-identical to pre-V2.5 behavior — extraction_prompt.py itself
is never touched; notes are appended to the already-built user prompt.
"""

import json
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from anthropic import Anthropic
from phase1_extraction.extraction_prompt import EXTRACTION_SYSTEM_PROMPT, build_user_prompt
from phase1_extraction.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

NOTES_BLOCK_TEMPLATE = """

Notes from this user's past corrections:
{notes}

These notes describe how this user has corrected extraction judgment calls before — apply them as guidance where relevant. Return ONLY a valid JSON object with no additional text."""


def _append_correction_notes(user_prompt: str, correction_notes: Optional[List[str]]) -> str:
    """Appends a distinct, clearly-labeled notes block (Decision 4) — never
    edits extraction_prompt.py's locked base content. Restates the
    JSON-only instruction at the end so the model's last-seen instruction
    is still the output-format rule, regardless of prompt wording changes."""
    if not correction_notes:
        return user_prompt
    notes_text = "\n".join(f"- {note}" for note in correction_notes)
    return user_prompt + NOTES_BLOCK_TEMPLATE.format(notes=notes_text)


class ExtractionError(Exception):
    """Error during extraction."""
    pass


class Extractor:
    """Wrapper around Claude API for email extraction."""

    def __init__(self):
        self.client = Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = ANTHROPIC_MODEL

    def extract(
        self,
        email_data: Dict[str, str],
        thread_context: str = "",
        correction_notes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Extract structured task data from an email.

        Args:
            email_data: dict with 'from', 'subject', 'body'
            thread_context: optional recent thread context
            correction_notes: optional list of approved correction note
                strings, fetched by the caller (never by this module)

        Returns:
            dict with keys: actionable, task, deadline, assignee, reason, confidence
        
        Raises:
            ExtractionError: if extraction fails or JSON parsing fails
        """
        user_prompt = build_user_prompt(email_data, thread_context)
        user_prompt = _append_correction_notes(user_prompt, correction_notes)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                system=EXTRACTION_SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )
            
            # Extract response text. content[0] isn't always the text block —
            # the model can prepend a ThinkingBlock, which has no .text attr.
            text_block = next((b for b in response.content if b.type == "text"), None)
            if text_block is None:
                raise ExtractionError(
                    f"No text block in Claude response. Block types: "
                    f"{[b.type for b in response.content]}"
                )
            response_text = text_block.text.strip()
            
            # Remove markdown code fence if present
            if response_text.startswith("```json"):
                response_text = response_text[7:]  # Remove ```json
            if response_text.startswith("```"):
                response_text = response_text[3:]  # Remove ```
            if response_text.endswith("```"):
                response_text = response_text[:-3]  # Remove trailing ```
            
            response_text = response_text.strip()
            
            # Parse JSON
            try:
                result = json.loads(response_text)
            except json.JSONDecodeError as e:
                raise ExtractionError(
                    f"Failed to parse Claude response as JSON. "
                    f"Response: {response_text[:200]}\nError: {e}"
                )
            
            # Validate required fields
            required_fields = ["actionable", "task", "deadline", "assignee", "reason", "confidence"]
            for field in required_fields:
                if field not in result:
                    raise ExtractionError(
                        f"Missing required field '{field}' in Claude response. "
                        f"Response: {result}"
                    )
            
            # Validate types
            if not isinstance(result["actionable"], bool):
                raise ExtractionError(f"Field 'actionable' must be boolean, got {type(result['actionable'])}")
            if not isinstance(result["confidence"], (int, float)):
                raise ExtractionError(f"Field 'confidence' must be number, got {type(result['confidence'])}")
            if not isinstance(result["reason"], str):
                raise ExtractionError(f"Field 'reason' must be string, got {type(result['reason'])}")
            
            # task, deadline, assignee can be null or string
            for field in ["task", "deadline", "assignee"]:
                if result[field] is not None and not isinstance(result[field], str):
                    raise ExtractionError(
                        f"Field '{field}' must be null or string, got {type(result[field])}"
                    )
            
            return result
            
        except ExtractionError:
            raise
        except Exception as e:
            raise ExtractionError(f"Unexpected error during extraction: {e}")


def extract_email(
    email_data: Dict[str, str],
    thread_context: str = "",
    correction_notes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Convenience function to extract an email.

    Args:
        email_data: dict with 'from', 'subject', 'body'
        thread_context: optional recent thread context
        correction_notes: optional list of approved correction note strings

    Returns:
        dict with extraction result
    """
    extractor = Extractor()
    return extractor.extract(email_data, thread_context, correction_notes)
