"""
Email body preprocessing: strip HTML, quoted replies, and signatures.

This only produces cleaned_text for storage — it does not touch extraction.
"""

import re

from bs4 import BeautifulSoup

# Lines that mark the start of a quoted reply or signature block. Once one of
# these is found, everything from that line onward is discarded.
_CUTOFF_PATTERNS = [
    re.compile(r"^On .{0,120} wrote:\s*$"),
    re.compile(r"^-----Original Message-----\s*$", re.IGNORECASE),
    re.compile(r"^From:\s*.+$"),  # Outlook-style quoted header block
    re.compile(r"^>"),  # quoted reply line
    re.compile(r"^--\s*$"),  # RFC 3676 signature delimiter
    re.compile(r"^Sent from my (iPhone|iPad|Android|Galaxy).*$", re.IGNORECASE),
]


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n")


def strip_quoted_and_signature(text: str) -> str:
    lines = text.splitlines()
    kept = []
    for line in lines:
        if any(pattern.match(line.strip()) for pattern in _CUTOFF_PATTERNS):
            break
        kept.append(line)
    return "\n".join(kept)


def collapse_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_email_body(raw_text: str, is_html: bool) -> str:
    text = html_to_text(raw_text) if is_html else raw_text
    text = strip_quoted_and_signature(text)
    return collapse_whitespace(text)
