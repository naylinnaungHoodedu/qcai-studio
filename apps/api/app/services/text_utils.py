import re


CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
WHITESPACE_PATTERN = re.compile(r"[ \t]+")
INLINE_REFERENCE_PATTERN = re.compile(r"(?<=[A-Za-z])\.(\d+)(?=\s)")
SENTENCE_BOUNDARY_PATTERN = re.compile(r"[.!?](?:['\")\]]*)\s")
MOJIBAKE_REPLACEMENTS = {
    "â\x80\x94": " - ",
    "â\x80\x93": "-",
    "â\x80\x99": "'",
    "â\x80\x98": "'",
    "â\x80\x9c": '"',
    "â\x80\x9d": '"',
    "â\x80\xa6": "...",
    "Â ": " ",
}


def sanitize_user_text(value: str, *, preserve_newlines: bool = True) -> str:
    sanitized = CONTROL_CHARS_PATTERN.sub("", value.replace("\r\n", "\n").replace("\r", "\n"))
    sanitized = sanitized.replace("<", "").replace(">", "")
    lines = [WHITESPACE_PATTERN.sub(" ", line).strip() for line in sanitized.split("\n")]
    if preserve_newlines:
        return "\n".join(line for line in lines if line).strip()
    return " ".join(line for line in lines if line).strip()


def normalize_display_text(value: str) -> str:
    sanitized = CONTROL_CHARS_PATTERN.sub("", value.replace("\r\n", "\n").replace("\r", "\n"))
    collapsed = re.sub(r"\s+", " ", sanitized).strip()
    for broken, replacement in MOJIBAKE_REPLACEMENTS.items():
        collapsed = collapsed.replace(broken, replacement)
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
