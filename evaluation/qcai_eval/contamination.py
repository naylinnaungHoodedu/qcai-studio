"""Contamination fingerprints and the research-log scanner (spec 3.14, 4.8; AC-10-4, AC-10-6; plan task 7; PD-71).

Plan task 7: "Contamination scanner runs in the research plane on salted fingerprints only; no ULQS or licensed text
enters public CI, production jobs or reports [Risk R-26]." Two fingerprint families: licensed passages as salted 12-word
shingles (`qcai-licensed-fingerprints/1`, the format `scripts/scan_boundary.py` reads), and ULQS texts as a salted HMAC of
every normalized whole text field of at least 3 words plus 6-word shingles (`qcai-ulqs-fingerprints/1`), so a short
question is still found. A fingerprint file holds its salt, so a real one is research-plane material. Reports hold paths
and counts only, never a text.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import unicodedata
from typing import Any, Callable, Iterable, Mapping, Sequence

LICENSED_FORMAT = "qcai-licensed-fingerprints/1"
ULQS_FORMAT = "qcai-ulqs-fingerprints/1"
HASH = "hmac-sha256-trunc32"
WORDS = re.compile(r"[^\W_]+")
TEXT_EXTENSIONS = frozenset({
    ".py", ".md", ".txt", ".json", ".jsonl", ".csv", ".ts", ".tsx", ".js", ".mjs", ".html", ".css", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".sql", ".xml", ".svg",
})
MAX_SCAN_BYTES = 20 * 1024 * 1024
MIN_WORDS_EXACT = 3
LICENSED_N = 12
ULQS_N = 6
MIN_SALT_BYTES = 32
RESEARCH_DATA_FILES = frozenset({"responses.jsonl"})
SYNTHETIC_FIXTURE_FORMAT = "contamination-synthetic-v1"
ULQS_TEXT_FIELDS = ("question", "gold_answer", "abstention_rationale", "reasoning_chain", "notes", "base_question", "topic")


def normalized_words(text: str) -> list[str]:
    return WORDS.findall(unicodedata.normalize("NFKC", text).casefold())


def _mac(salt: bytes, text: str) -> str:
    return hmac.new(salt, text.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def fingerprint_shingles(text: str, salt: bytes, n: int) -> set[str]:
    words = normalized_words(text)
    return {_mac(salt, " ".join(words[index:index + n])) for index in range(max(0, len(words) - n + 1))}


def exact_fingerprint(text: str, salt: bytes) -> str | None:
    words = normalized_words(text)
    if len(words) < MIN_WORDS_EXACT:
        return None
    return _mac(salt, " ".join(words))


def _texts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [entry for entry in value if isinstance(entry, str)]
    return []


def ulqs_texts(item: Mapping[str, Any]) -> list[str]:
    """Every free-text field of a ULQS item: question, answers, rationales, claims, replays, turns, negative evidence."""
    texts: list[str] = []
    for key in ULQS_TEXT_FIELDS:
        texts += _texts(item.get(key))
    texts += _texts(item.get("concepts"))
    for claim in item.get("atomic_claims", []) or []:
        if isinstance(claim, Mapping):
            texts += _texts(claim.get("text"))
    for replay in item.get("replays", []) or []:
        if isinstance(replay, Mapping):
            texts += _texts(replay.get("gold_answer")) + _texts(replay.get("presentation_notes"))
    for turn in item.get("conversation", []) or []:
        if isinstance(turn, Mapping):
            for key in ("user_utterance", "resolved_query", "gold_answer", "abstention_rationale"):
                texts += _texts(turn.get(key))
            for claim in turn.get("atomic_claims", []) or []:
                if isinstance(claim, Mapping):
                    texts += _texts(claim.get("text"))
            texts += _negative_texts(turn.get("negative_evidence"))
    texts += _negative_texts(item.get("negative_evidence"))
    return texts


def _negative_texts(block: Any) -> list[str]:
    if not isinstance(block, Mapping):
        return []
    return _texts(block.get("sections_searched")) + _texts(block.get("queries")) + _texts(block.get("limitations"))


def build_licensed(texts: Iterable[str], salt: bytes, *, set_id: str, n: int = LICENSED_N) -> dict[str, Any]:
    texts = list(texts)
    shingles: set[str] = set()
    for text in texts:
        shingles |= fingerprint_shingles(text, salt, n)
    return {"format": LICENSED_FORMAT, "hash": HASH, "fingerprint_set_id": set_id, "salt_hex": salt.hex(), "shingle_words": n,
            "fingerprints": sorted(shingles), "sources": {"documents": len(texts), "shingles": len(shingles)}}


def build_ulqs(items: Iterable[Mapping[str, Any]], salt: bytes, *, set_id: str, n: int = ULQS_N) -> dict[str, Any]:
    items = list(items)
    shingles: set[str] = set()
    exact: set[str] = set()
    count = 0
    for item in items:
        for text in ulqs_texts(item):
            count += 1
            shingles |= fingerprint_shingles(text, salt, n)
            fingerprint = exact_fingerprint(text, salt)
            if fingerprint:
                exact.add(fingerprint)
    return {"format": ULQS_FORMAT, "hash": HASH, "fingerprint_set_id": set_id, "salt_hex": salt.hex(), "shingle_words": n,
            "min_words_exact": MIN_WORDS_EXACT, "exact": sorted(exact), "fingerprints": sorted(shingles),
            "sources": {"items": len(items), "texts": count}}


@dataclass(frozen=True)
class FingerprintSet:
    id: str
    kind: str
    salt: bytes
    n: int
    shingles: frozenset[str]
    exact: frozenset[str]


def set_from_payload(payload: Mapping[str, Any]) -> FingerprintSet:
    if payload.get("hash") != HASH or payload.get("format") not in (LICENSED_FORMAT, ULQS_FORMAT):
        raise ValueError("not a qcai licensed or ULQS fingerprint file")
    kind = "licensed" if payload["format"] == LICENSED_FORMAT else "ulqs"
    default_n = LICENSED_N if kind == "licensed" else ULQS_N
    return FingerprintSet(id=str(payload.get("fingerprint_set_id", "unknown")), kind=kind, salt=bytes.fromhex(payload["salt_hex"]),
                          n=int(payload.get("shingle_words", default_n)), shingles=frozenset(payload["fingerprints"]),
                          exact=frozenset(payload.get("exact", [])))


def load_fingerprint_file(path: Path) -> FingerprintSet:
    return set_from_payload(json.loads(Path(path).read_text(encoding="utf-8")))


def synthetic_sets(fixture_path: Path) -> list[FingerprintSet]:
    """Fingerprints built in memory from the committed synthetic fixture with its published salt (public CI)."""
    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    if fixture.get("fixture") != SYNTHETIC_FIXTURE_FORMAT or fixture.get("synthetic") is not True:
        raise ValueError("not a synthetic contamination fixture")
    salt = bytes.fromhex(fixture["salt_hex"])
    licensed = build_licensed(fixture["licensed_passages"], salt, set_id="synthetic-licensed-v1")
    items = [{"question": text} for text in fixture["ulqs_texts"]]
    ulqs = build_ulqs(items, salt, set_id="synthetic-ulqs-v1")
    return [set_from_payload(licensed), set_from_payload(ulqs)]


def _segments(text: str) -> list[str]:
    segments = []
    for line in text.splitlines():
        segments.append(line)
        segments += re.split(r"(?<=[.!?])\s+|\"\s*[,:]\s*\"|\\n", line)
    return segments


def scan_text(text: str, sets: Sequence[FingerprintSet]) -> dict[str, int]:
    """Hits per set kind: shingles, plus for a ULQS set the exact fingerprint of every line, sentence or JSON string."""
    hits = {"licensed": 0, "ulqs": 0}
    segments = None
    for fingerprint_set in sets:
        count = len(fingerprint_shingles(text, fingerprint_set.salt, fingerprint_set.n) & fingerprint_set.shingles)
        if fingerprint_set.kind == "ulqs" and fingerprint_set.exact:
            if segments is None:
                segments = _segments(text) + _json_strings(text)
            exact = {exact_fingerprint(segment, fingerprint_set.salt) for segment in segments}
            count += len(exact & fingerprint_set.exact)
        hits[fingerprint_set.kind] += count
    return hits


def _json_strings(text: str) -> list[str]:
    """The decoded string literals of a JSON or JSONL text (a text logged as a JSON value is still found)."""
    found = []
    for match in re.findall(r'"((?:[^"\\]|\\.)*)"', text):
        try:
            found.append(json.loads(f'"{match}"'))
        except ValueError:
            found.append(match)
    return found


def _text_of(name: str, data: bytes) -> str | None:
    suffix = PurePosixPath(name).suffix.lower()
    if suffix == ".docx":
        try:
            from docx import Document

            return "\n".join(paragraph.text for paragraph in Document(io.BytesIO(data)).paragraphs)
        except Exception:
            return None
    if suffix in TEXT_EXTENSIONS:
        return data.decode("utf-8", errors="replace")
    return None


Entry = tuple[str, Callable[[], "bytes | None"]]


def _reader(path: Path) -> Callable[[], bytes | None]:
    def read() -> bytes | None:
        try:
            if path.stat().st_size > MAX_SCAN_BYTES:
                return None
            return path.read_bytes()
        except OSError:
            return None

    return read


def scan_files(entries: Iterable[Entry], sets: Sequence[FingerprintSet], *, excluded: Sequence[Mapping[str, str]] = ()) -> dict[str, Any]:
    """Scan (name, read) entries. Unknown extensions are not text; files over 20 MiB are excluded as too large."""
    files = scanned = 0
    out_excluded = [dict(entry) for entry in excluded]
    hit_files = []
    for name, read in entries:
        files += 1
        suffix = PurePosixPath(name).suffix.lower()
        if suffix not in TEXT_EXTENSIONS and suffix != ".docx":
            continue
        data = read()
        if data is None:
            out_excluded.append({"path": name, "reason": "too_large"})
            continue
        text = _text_of(name, data)
        if text is None:
            continue
        scanned += 1
        hits = scan_text(text, sets)
        if hits["licensed"] or hits["ulqs"]:
            hit_files.append({"path": name, "licensed_hits": hits["licensed"], "ulqs_hits": hits["ulqs"]})
    return {"files": files, "scanned": scanned, "excluded": out_excluded, "files_with_hits": hit_files}


def git_files(root: Path) -> list[str]:
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout.decode("utf-8")
    return sorted(name for name in listed.split("\0") if name)


def repository_target(root: Path, sets: Sequence[FingerprintSet], *, exclude: Sequence[str] = ()) -> dict[str, Any]:
    """The tracked tree (git ls-files only: untracked, ignored files on a workstation are never read)."""
    names = git_files(root)
    skipped = [{"path": name, "reason": "synthetic contamination fixture"} for name in names if name in exclude]
    entries = [(name, _reader(Path(root) / name)) for name in names if name not in exclude]
    return {"target": "repository", "root": ".", **scan_files(entries, sets, excluded=skipped), "files": len(names)}


def path_target(path: Path, sets: Sequence[FingerprintSet], *, label: str, exclude_paths: Sequence[Path] = ()) -> dict[str, Any]:
    path = Path(path)
    excluded_set = {Path(item).resolve() for item in exclude_paths}
    files = sorted(p for p in ([path] if path.is_file() else path.rglob("*")) if p.is_file())
    skipped = [{"path": _rel(p, path), "reason": "synthetic contamination fixture"} for p in files if p.resolve() in excluded_set]
    entries = [(_rel(p, path), _reader(p)) for p in files if p.resolve() not in excluded_set]
    return {"target": "path", "root": label, **scan_files(entries, sets, excluded=skipped), "files": len(files)}


def research_logs_target(directory: Path, sets: Sequence[FingerprintSet], *, label: str) -> dict[str, Any]:
    """Every file of a run directory except the fixed research-data file (responses.jsonl). The exclusion is a constant:
    nothing a run writes can widen it."""
    directory = Path(directory)
    files = sorted(p for p in directory.rglob("*") if p.is_file())
    skipped = [{"path": _rel(p, directory), "reason": "research data (model outputs)"} for p in files if p.name in RESEARCH_DATA_FILES]
    entries = [(_rel(p, directory), _reader(p)) for p in files if p.name not in RESEARCH_DATA_FILES]
    return {"target": "research-logs", "root": label, **scan_files(entries, sets, excluded=skipped), "files": len(files)}


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix() if root.is_dir() else path.name
    except ValueError:
        return path.name


def report(targets: Sequence[Mapping[str, Any]], sets: Sequence[FingerprintSet]) -> dict[str, Any]:
    total = sum(hit["licensed_hits"] + hit["ulqs_hits"] for target in targets for hit in target["files_with_hits"])
    return {"report": "qcai-research-log-scan", "format_version": 1, "fingerprint_sets": [s.id for s in sets], "targets": list(targets),
            "matches_total": total, "result": "pass" if total == 0 else "fail"}
