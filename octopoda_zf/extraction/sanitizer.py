"""Pre-extraction secret + PII sanitizer.

Risk R14 (P0): API keys, passwords, PII in user transcripts must not be
extracted and stored. This runs BEFORE the transcript is sent to the extractor
LLM, so secrets never leave the user's process in a memory write.

Defense in depth: the extractor prompt is ALSO instructed to skip credentials,
and the importance filter drops facts that still look sensitive. This module is
the first and strongest line.

Design notes:
- Patterns are conservative (favor over-redaction over leaking).
- Each redaction records its category so we can audit what was stripped.
- We never log the matched secret itself, only its category + count.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Each entry: (category, compiled_pattern, replacement)
# Order matters: more specific patterns first.
_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    # Octopoda's own key format
    ("octopoda_key", re.compile(r"sk-octopoda-[A-Za-z0-9_\-]{16,}"), "[REDACTED_OCTOPODA_KEY]"),
    # OpenAI / generic sk- keys
    ("openai_key", re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "[REDACTED_API_KEY]"),
    # Anthropic keys
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "[REDACTED_API_KEY]"),
    # AWS access key id
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    # AWS secret access key (40 char base64-ish) — only when labelled, to avoid false positives
    (
        "aws_secret",
        re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+]{40}['\"]?"),
        "aws_secret_access_key=[REDACTED_AWS_SECRET]",
    ),
    # GitHub tokens
    ("github_token", re.compile(r"gh[posru]_[A-Za-z0-9]{36,}"), "[REDACTED_GITHUB_TOKEN]"),
    # Slack tokens
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"), "[REDACTED_SLACK_TOKEN]"),
    # Google API key
    ("google_key", re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "[REDACTED_GOOGLE_KEY]"),
    # JWT (three base64url segments)
    (
        "jwt",
        re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
        "[REDACTED_JWT]",
    ),
    # Private key blocks
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    # Credit card numbers (13-16 digits, optional separators) — validated by Luhn below
    (
        "credit_card",
        re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
        "[REDACTED_CARD]",
    ),
    # US SSN
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    # Passwords disclosed in text, including natural language:
    #   password = "..."  /  password: ...  /  "my password is ..."  /  "pwd was ..."
    (
        "password_assignment",
        re.compile(
            r"(?i)\b(password|passwd|pwd|passphrase)\b\s*"
            r"(?:[=:]|\bis\b|\bwas\b)\s*"
            r"['\"]?[^\s'\"]{6,}['\"]?"
        ),
        r"\1=[REDACTED_PASSWORD]",
    ),
    # Email addresses (PII)
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED_EMAIL]",
    ),
]


@dataclass
class SanitizeResult:
    text: str
    redactions: dict[str, int]  # category -> count

    @property
    def total_redactions(self) -> int:
        return sum(self.redactions.values())

    @property
    def found_secrets(self) -> bool:
        # Email is PII but not a "secret"; callers may treat differently.
        secret_categories = {k: v for k, v in self.redactions.items() if k != "email"}
        return sum(secret_categories.values()) > 0


def _luhn_valid(number: str) -> bool:
    """Luhn checksum, to avoid redacting random 13-16 digit strings that
    aren't actually card numbers (e.g. long IDs)."""
    digits = [int(c) for c in number if c.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def sanitize(text: str) -> SanitizeResult:
    """Strip secrets + PII from a transcript before extraction.

    Returns the cleaned text and a per-category redaction count. Never returns
    or logs the matched secret values themselves.
    """
    if not text:
        return SanitizeResult(text="", redactions={})

    redactions: dict[str, int] = {}
    out = text

    for category, pattern, replacement in _PATTERNS:
        if category == "credit_card":
            # Special handling: only redact Luhn-valid candidates.
            def _maybe_redact_card(m: re.Match[str]) -> str:
                candidate = m.group(0)
                if _luhn_valid(candidate):
                    redactions["credit_card"] = redactions.get("credit_card", 0) + 1
                    return "[REDACTED_CARD]"
                return candidate

            out = pattern.sub(_maybe_redact_card, out)
            continue

        # Count matches before substituting.
        matches = pattern.findall(out)
        if matches:
            redactions[category] = redactions.get(category, 0) + len(matches)
            out = pattern.sub(replacement, out)

    return SanitizeResult(text=out, redactions=redactions)
