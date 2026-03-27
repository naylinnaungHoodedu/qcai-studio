import re


CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
WHITESPACE_PATTERN = re.compile(r"[ \t]+")


def sanitize_user_text(value: str, *, preserve_newlines: bool = True) -> str:
    sanitized = CONTROL_CHARS_PATTERN.sub("", value.replace("\r\n", "\n").replace("\r", "\n"))
    sanitized = sanitized.replace("<", "").replace(">", "")
    lines = [WHITESPACE_PATTERN.sub(" ", line).strip() for line in sanitized.split("\n")]
    if preserve_newlines:
        return "\n".join(line for line in lines if line).strip()
    return " ".join(line for line in lines if line).strip()
