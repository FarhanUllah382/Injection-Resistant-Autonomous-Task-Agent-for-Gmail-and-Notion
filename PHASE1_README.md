# Phase 1: Extraction Experiment

This is the Phase 1 extraction validation experiment. Goal: validate that Claude extraction works reliably before building the full backend.

## Project Structure

```
phase1_extraction/
├── __init__.py                  # Package init
├── config.py                    # Configuration (API key, model, constants)
├── extraction_prompt.py         # System prompt + user prompt builder (CORE IP)
├── extractor.py                 # Claude API wrapper
├── evaluate.py                  # Evaluation metrics + comparison logic
├── test_emails.jsonl            # Hand-labeled test set (15 emails)
└── run_experiment.py            # Main entry point
```

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create `.env` file with your API key:**
   ```bash
   cp .env.example .env
   # Edit .env and add your ANTHROPIC_API_KEY
   ```

3. **Verify test data:**
   ```bash
   python -c "import json; emails = [json.loads(line) for line in open('phase1_extraction/test_emails.jsonl')]; print(f'Loaded {len(emails)} emails')"
   ```

## Run Experiment

```bash
python phase1_extraction/run_experiment.py
```

This will:
1. Load 15 test emails with ground-truth labels
2. Call Claude API for each email
3. Extract structured JSON (actionable, task, deadline, assignee, confidence, reason)
4. Compare predictions vs. labels
5. Print metrics:
   - **Precision**: Of predictions marked actionable, % correct
   - **Recall**: Of truly actionable emails, % caught
   - **F1**: Harmonic mean
   - **False positives/negatives**: Count of errors
   - **Confidence distribution**: How confident was Claude?

6. Save detailed results to `phase1_extraction/evaluation_results.json`

## Evaluation Targets

| Metric | Target |
|---|---|
| Precision | >= 90% |
| Recall | >= 80% |
| False positives | < 5% |
| High-confidence (≥0.7) accuracy | >= 85% |

## Iteration Workflow

If evaluation falls short:

1. **Analyze failures** — review `evaluation_results.json` for misclassified emails
2. **Diagnose root cause**:
   - Is Claude confusing actionable vs. non-actionable?
   - Is deadline extraction wrong?
   - Is confidence miscalibrated?
3. **Revise `extraction_prompt.py`** — improve the system/user prompts
4. **Re-run** — `python phase1_extraction/run_experiment.py`
5. **Measure improvement** — repeat until metrics pass

## Key Files to Edit

- **`extraction_prompt.py`**: The extraction prompt (system + user template). This is the core IP that will be tuned.
  - Update `EXTRACTION_SYSTEM_PROMPT` to improve reasoning
  - Update `EXTRACTION_USER_PROMPT_TEMPLATE` to provide better instructions
  - Update `build_user_prompt()` to assemble context better

- **`config.py`**: Configuration constants
  - `ANTHROPIC_MODEL`: Change model if needed
  - `THREAD_CONTEXT_DEPTH`: Adjust thread context size
  - `CONFIDENCE_THRESHOLD`: Initial filter threshold

- **`test_emails.jsonl`**: Hand-labeled test set (don't edit; replace only if adding more data)

## Understanding the Contract

Every Claude response **must** return this JSON structure:

```json
{
  "actionable": boolean,           // true/false only
  "task": "string or null",        // What needs to be done
  "deadline": "string or null",    // Natural-language phrase (not resolved date)
  "assignee": "string or null",    // Who should do it (only if named)
  "reason": "string",              // Why you think it's actionable/not
  "confidence": number             // 0.0 to 1.0 ranking signal
}
```

**Important**: 
- Deadline is extracted as-is (e.g., "Friday", "by Sept 1st") — the application resolves it
- Assignee is null unless a specific person is explicitly named
- Confidence is a ranking signal, not a calibrated probability
- Actionable = there's a real request for the recipient

## Example Test Workflow

```bash
# Initial run
python phase1_extraction/run_experiment.py

# Results: Precision 75%, Recall 60% (below targets)

# Analyze results
cat phase1_extraction/evaluation_results.json | python -m json.tool

# See which emails failed, why

# Improve the prompt
vi phase1_extraction/extraction_prompt.py

# Re-run
python phase1_extraction/run_experiment.py

# Better: Precision 88%, Recall 83%

# Iterate until passing
```

## Next Phase

Once Phase 1 evaluation passes (Precision >= 90%, Recall >= 80%), lock the extraction prompt and move to Phase 2: Gmail integration + backend.

The `extraction_prompt.py` will be reused in the backend unchanged.
