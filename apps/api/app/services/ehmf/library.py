"""The misconception library v1 (plan Phase 7 D task 2, F "library v1", H; Phase 7 spec 3.5, 4.5; PD-43).

The library is a hashed file beside the configuration package (config_package/misconceptions/v1.json), whose canonical
sha256 the package pins (v1.v1_8.library) and whose .sha256 sidecar repeats it. It is "edited only by Content Owner or
V3" (task 2): an entry's editor is content_owner or v3:<the gold record hash it came from>; its paraphrase is a
public-corpus paraphrase, never licensed text (E-95), at most 280 characters, sharing no run of more than 8 words with a
cited span; its span ids resolve in the public corpus. Library v1 ships with no production entries: the Q-14 seed list
is unavailable (A-18) and the entries are the Content Owner's (DI-106). A V3 Type C gold label is exported as a proposal
(proposals_from_gold; python -m app.workers.ehmf export-library-proposals) and never applied: applying one is a library
edit under change control (docs/architecture/ehmf-change-control.md). A proposal and an applied entry hold no gold
label, rationale or reviewer data (gold labels never enter the public repository).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from app.services.ehmf.vocabulary import LIBRARY_SCHEMA

LIBRARY_NAME = "qcai-misconception-library"
EDITORS = ["content_owner", "v3"]
PARAPHRASE_MAX_CHARS = 280
PARAPHRASE_MAX_SHARED_WORDS = 8
_EDITOR = re.compile(r"^(content_owner|v3:[0-9a-f]{64})$")
_SPAN_ID = re.compile(r"^span-[0-9a-f]{64}$")
_ENTRY_ID = re.compile(r"^mc-[a-z0-9][a-z0-9-]*$")
_WORD = re.compile(r"[^\W_]+")
PROPOSAL_SCHEMA = "misconception-proposal-v1"


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _words(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def shares_long_run(paraphrase: str, span_text: str, *, max_shared: int = PARAPHRASE_MAX_SHARED_WORDS) -> bool:
    """True when the paraphrase and the span share a run of more than max_shared consecutive normalised words."""
    run = max_shared + 1
    words = _words(paraphrase)
    if len(words) < run:
        return False
    span_runs = {tuple(seq[i:i + run]) for seq in (_words(span_text),) for i in range(len(seq) - run + 1)}
    return any(tuple(words[i:i + run]) in span_runs for i in range(len(words) - run + 1))


def library_problems(raw: Any, *, store: Any = None, shipped: bool, max_chars: int = PARAPHRASE_MAX_CHARS,
                     max_shared_words: int = PARAPHRASE_MAX_SHARED_WORDS) -> list[str]:
    """Every rule of spec 4.5 that the library breaks (an empty list when it keeps them all)."""
    if not isinstance(raw, Mapping):
        return ["the misconception library must be a JSON object"]
    problems = []
    if raw.get("library") != LIBRARY_NAME:
        problems.append(f"library must be '{LIBRARY_NAME}'")
    if raw.get("schema") != LIBRARY_SCHEMA:
        problems.append(f"schema must be '{LIBRARY_SCHEMA}'")
    if raw.get("editors") != EDITORS:
        problems.append("editors must be [content_owner, v3] (plan task 2 \"edited only by Content Owner or V3\")")
    if not isinstance(raw.get("version"), str) or not raw.get("version"):
        problems.append("version must be a non-empty string")
    if not isinstance(raw.get("status"), str) or not raw.get("status"):
        problems.append("status must be a non-empty string")
    synthetic = raw.get("synthetic")
    if not isinstance(synthetic, bool):
        problems.append("synthetic must be a boolean")
    elif synthetic and shipped:
        problems.append("a synthetic library is refused at the shipped path")
    entries = raw.get("entries")
    if not isinstance(entries, list):
        return [*problems, "entries must be a list"]
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            problems.append("every entry is an object")
            continue
        entry_id = entry.get("id")
        name = entry_id if isinstance(entry_id, str) else "?"
        if not isinstance(entry_id, str) or not _ENTRY_ID.match(entry_id):
            problems.append(f"entry {name}: id must match mc-<lowercase slug>")
        elif entry_id in seen:
            problems.append(f"entry {name} is listed twice")
        else:
            seen.add(entry_id)
        editor = entry.get("editor")
        if not (isinstance(editor, str) and (_EDITOR.match(editor) or (editor == "synthetic-test" and synthetic is True))):
            problems.append(f"entry {name}: the editor must be content_owner or v3:<gold record hash> (plan task 2)")
        terms = entry.get("terms")
        if (not isinstance(terms, list) or len(terms) < 2 or not all(isinstance(term, str) and term and term == term.lower() for term in terms)
                or terms != sorted(set(terms))):
            problems.append(f"entry {name}: at least two terms, lowercase, sorted and unique")
        paraphrase = entry.get("paraphrase")
        if not isinstance(paraphrase, str) or not paraphrase.strip() or len(paraphrase) > max_chars:
            problems.append(f"entry {name}: the paraphrase is non-empty and at most {max_chars} characters")
            paraphrase = None
        span_ids = entry.get("span_ids")
        if not isinstance(span_ids, list) or not span_ids or not all(isinstance(span, str) and _SPAN_ID.match(span) for span in span_ids):
            problems.append(f"entry {name}: span_ids are span ids")
            span_ids = []
        edited = entry.get("edited")
        try:
            date.fromisoformat(edited) if isinstance(edited, str) else (_ for _ in ()).throw(ValueError())
        except ValueError:
            problems.append(f"entry {name}: edited is an ISO date")
        if store is not None:
            for span_id in span_ids:
                record = store.span_registry.get(span_id)
                if record is None or getattr(record, "plane", "public") != "public":
                    problems.append(f"entry {name}: span {span_id} does not resolve in the public corpus")
                elif paraphrase is not None and shares_long_run(paraphrase, record.text, max_shared=max_shared_words):
                    problems.append(f"entry {name}: the paraphrase copies more than {max_shared_words} consecutive words of a cited span "
                                    "(never licensed text, E-95)")
    return problems


@dataclass(frozen=True)
class LibraryFile:
    version: str
    sha256: str
    entries: tuple[tuple[str, tuple[str, ...]], ...]     # (entry id, terms)
    raw: Mapping[str, Any]


def read_library_file(path: Path, *, expected_sha256: str, shipped: bool, store: Any = None) -> tuple[LibraryFile | None, list[str]]:
    """The library at path, checked against the package pin, its sidecar and library_problems; (None, problems) on a fault."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, [f"the misconception library at {Path(path).name} could not be read: {exc}"]
    digest = canonical_sha256(raw)
    problems = []
    if digest != expected_sha256:
        problems.append(f"the misconception library's sha256 {digest} differs from the package pin {expected_sha256}")
    sidecar = Path(str(path) + ".sha256")
    try:
        recorded = sidecar.read_text(encoding="utf-8").strip()
    except OSError:
        recorded = None
    if recorded != digest:
        problems.append("the misconception library's .sha256 sidecar does not hold its canonical sha256")
    problems.extend(library_problems(raw, store=store, shipped=shipped))
    if problems:
        return None, problems
    entries = tuple((entry["id"], tuple(entry["terms"])) for entry in raw["entries"])
    return LibraryFile(version=raw["version"], sha256=digest, entries=entries, raw=raw), []


def proposals_from_gold(db: Any, *, store: Any = None) -> list[dict]:
    """One proposal per Type C claim label of an applied item's final gold row (spec 4.5): the claim id, its span ids and
    its text only when every span is public and quotable in the given store (else null; the gold row holds no claim text,
    only its hash, so the text is read from the corpus). A proposal is never applied here."""
    from sqlalchemy import select

    from app.db_models import V3GoldLabelRecord, V3QueueItem

    finals = select(V3QueueItem.final_gold_seq).where(V3QueueItem.state == "applied", V3QueueItem.final_gold_seq.is_not(None))
    rows = db.execute(select(V3GoldLabelRecord).where(V3GoldLabelRecord.seq.in_(finals)).order_by(V3GoldLabelRecord.seq)).scalars().all()
    proposals: list[dict] = []
    for row in rows:
        entry = json.loads(row.entry)
        spans_of = {claim["claim_id"]: sorted(claim["span_ids"]) for claim in entry.get("claims", ())}
        for label in entry.get("claim_labels", ()):
            if label.get("ehmf_type") != "C":
                continue
            span_ids = spans_of.get(label["claim_id"], [])
            proposals.append({"proposal_schema": PROPOSAL_SCHEMA, "source": f"v3:{row.record_hash}", "claim_id": label["claim_id"],
                              "span_ids": span_ids, "claim_text": None, "editor_required": "content_owner", "applied": False})
    return proposals
