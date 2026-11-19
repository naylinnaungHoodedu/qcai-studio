"""Near-duplicate gate rules (plan Phase 2 task 2.9; spec 3.10)."""

from __future__ import annotations

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.core.near_duplicates import Candidate, containment, jaccard, near_duplicate_pairs, word_shingles

PARAMS = get_config_package(Settings()).near_duplicate


def test_word_shingles_normalise_case_and_width():
    assert word_shingles("Ａ b C d E f", 5) == {"a b c d e", "b c d e f"}
    assert word_shingles("too short", 5) == {"too short"}
    a, b = {"x", "y", "z"}, {"y", "z"}
    assert jaccard(a, b) == 2 / 3 and containment(a, b) == 1.0


def test_document_jaccard_and_containment_thresholds():
    text = " ".join(f"word{index}" for index in range(400))
    excerpt = " ".join(f"word{index}" for index in range(100, 200))
    distinct = " ".join(f"other{index}" for index in range(400))
    pairs = near_duplicate_pairs(
        [Candidate("full", "document", text=text), Candidate("excerpt", "document", text=excerpt), Candidate("distinct", "document", text=distinct)],
        PARAMS,
    )
    assert [(pair.a, pair.b) for pair in pairs] == [("full", "excerpt")]
    assert pairs[0].containment == 1.0 and "containment" in pairs[0].reasons[0]


def test_video_rules():
    base = dict(kind="video", sha256="a" * 64, size_bytes=286_348_553, duration_s=575.176)
    reencode = Candidate("v2026", kind="video", sha256="b" * 64, size_bytes=286_549_020, duration_s=575.176)
    pairs = near_duplicate_pairs([Candidate("v2025", **base), reencode], PARAMS)
    assert len(pairs) == 1 and "mp4-mvhd-v1" in pairs[0].reasons[0]
    far = Candidate("other", kind="video", sha256="c" * 64, size_bytes=286_549_020 * 2, duration_s=581.0)
    assert near_duplicate_pairs([Candidate("v2025", **base), far], PARAMS) == []
    same_hash = Candidate("copy", kind="video", sha256="a" * 64, size_bytes=1, duration_s=None)
    assert near_duplicate_pairs([Candidate("v2025", **base), same_hash], PARAMS)[0].reasons == ("equal sha256",)
    chapters = "Routing chapter on qubit connectivity and swap overhead in depth " * 5
    by_chapter = near_duplicate_pairs(
        [Candidate("a", kind="video", sha256="1" * 64, size_bytes=10, chapter_text=chapters),
         Candidate("b", kind="video", sha256="2" * 64, size_bytes=99, chapter_text=chapters)],
        PARAMS,
    )
    assert by_chapter and "curated chapter Jaccard" in by_chapter[0].reasons[0]
