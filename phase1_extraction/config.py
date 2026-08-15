"""
Phase 1 Configuration
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Anthropic API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = "claude-sonnet-5"

# Extraction parameters
THREAD_CONTEXT_DEPTH = 5
CONFIDENCE_THRESHOLD = 0.7  # Initial experimental threshold, tuned based on evaluation

# Test dataset
TEST_EMAILS_PATH = "phase1_extraction/test_emails.jsonl"

# Results output
RESULTS_OUTPUT_PATH = "phase1_extraction/evaluation_results.json"

print(f"Configuration loaded: {ANTHROPIC_MODEL}")
