import re


ASCII_CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
WHITESPACE_PATTERN = re.compile(r"[ \t]+")
INLINE_REFERENCE_PATTERN = re.compile(r"(?<=[A-Za-z])\.(\d+)(?=\s)")
SENTENCE_BOUNDARY_PATTERN = re.compile(r"[.!?](?:['\")\]]*)\s")
MOJIBAKE_REPLACEMENTS = {
    "\u00e2\u0080\u0094": " - ",
    "\u00e2\u0080\u0093": "-",
    "\u00e2\u0080\u0099": "'",
    "\u00e2\u0080\u0098": "'",
    "\u00e2\u0080\u009c": '"',
    "\u00e2\u0080\u009d": '"',
    "\u00e2\u0080\u00a6": "...",
    "\u00c2 ": " ",
}
UTF8_MOJIBAKE_HINTS = (
    "\u00e2\u0080",
    "\u00c2",
    "\u00c3",
)


def _repair_utf8_mojibake(value: str) -> str:
    if not any(marker in value for marker in UTF8_MOJIBAKE_HINTS):
        return value

    try:
        repaired = value.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return value

    original_marker_count = sum(value.count(marker) for marker in UTF8_MOJIBAKE_HINTS)
    repaired_marker_count = sum(repaired.count(marker) for marker in UTF8_MOJIBAKE_HINTS)
    if repaired_marker_count > original_marker_count:
        return value
    return repaired


def sanitize_user_text(value: str, *, preserve_newlines: bool = True) -> str:
    sanitized = CONTROL_CHARS_PATTERN.sub("", value.replace("\r\n", "\n").replace("\r", "\n"))
    sanitized = sanitized.replace("<", "").replace(">", "")
    lines = [WHITESPACE_PATTERN.sub(" ", line).strip() for line in sanitized.split("\n")]
    if preserve_newlines:
        return "\n".join(line for line in lines if line).strip()
    return " ".join(line for line in lines if line).strip()


def normalize_display_text(value: str) -> str:
    sanitized = ASCII_CONTROL_CHARS_PATTERN.sub("", value.replace("\r\n", "\n").replace("\r", "\n"))
    sanitized = _repair_utf8_mojibake(sanitized)
    collapsed = re.sub(r"\s+", " ", sanitized).strip()
    for broken, replacement in MOJIBAKE_REPLACEMENTS.items():
        collapsed = collapsed.replace(broken, replacement)
    collapsed = CONTROL_CHARS_PATTERN.sub("", collapsed)
    collapsed = INLINE_REFERENCE_PATTERN.sub(".", collapsed)
    if collapsed and collapsed[0].islower():
        match = re.search(r"[.!?](?:['\")\]]*)\s+([A-Z])", collapsed)
        if match and match.start(1) <= 160:
            collapsed = collapsed[match.start(1) :].lstrip()
    return collapsed.strip()


def truncate_display_excerpt(value: str, max_chars: int, *, ellipsis: str = "...") -> str:
    text = normalize_display_text(value)
    if len(text) <= max_chars:
        return text

    candidate = text[: max_chars + 1]
    boundaries = [match.end() for match in SENTENCE_BOUNDARY_PATTERN.finditer(candidate)]
    for boundary in reversed(boundaries):
        if boundary >= max_chars // 2:
            return candidate[:boundary].rstrip()

    split_at = candidate.rfind(" ")
    if split_at >= max_chars // 2:
        return f"{candidate[:split_at].rstrip()}{ellipsis}"
    return f"{candidate[:max_chars].rstrip()}{ellipsis}"


def lead_sentence(value: str, max_chars: int = 220) -> str:
    text = normalize_display_text(value)
    match = SENTENCE_BOUNDARY_PATTERN.search(text)
    if match and match.end() <= max_chars:
        return text[: match.end()].rstrip()
    return truncate_display_excerpt(text, max_chars)
