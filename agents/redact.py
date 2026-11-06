"""Hides secrets in pull request text before it is sent to a model provider.

Only the text for the model is changed. The rules still read the real diff, so the risk label is not affected.
This finds known key formats and values assigned to names like password or api_key. It cannot recognise a secret
with no known format and no telling name, so it reduces the risk of a leak but does not remove it.
"""
import re

from .trace import SECRET_RE

HIDDEN = "[HIDDEN SECRET]"
_NAME = r"[\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credential)[\w.-]*[\"']?"

# Each pattern's value is its last group when it has one, so the name around the value stays readable for the model.
_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"),
    SECRET_RE,
    re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}"),                # a JSON web token
    re.compile(r"\bxox[abprs]-[\w-]{10,}"),                             # Slack
    re.compile(r"\b[sr]k_(?:live|test)_\w{8,}"),                        # Stripe
    re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@\"']+:([^\s/@\"']+)@"),   # the password in user:password@host
    re.compile(rf"(?i)\b{_NAME}\s*(?::|=|=>)\s*[\"'`]((?![$<{{])[^\"'`\s]{{6,}})[\"'`]"),  # password = "abc123", not "${{PASSWORD}}"
    re.compile(rf"(?i)\b{_NAME}\s*(?::|=)\s*((?=[A-Za-z0-9_+/=-]*\d)[A-Za-z0-9_+/=-]{{12,}})(?![\w(.])"),  # API_KEY=abc123, not token = getToken()
]


def hide_secrets(text: str | None) -> tuple[str, int]:
    """Returns the text with each secret replaced, and how many were found."""
    text, found = text or "", 0

    def hide(match: re.Match) -> str:
        nonlocal found
        found += 1
        if not match.re.groups:
            return HIDDEN
        whole, start = match.group(0), match.start(match.re.groups) - match.start(0)
        return whole[:start] + HIDDEN + whole[start + len(match.group(match.re.groups)):]

    for pattern in _PATTERNS:
        text = pattern.sub(hide, text)
    return text, found
