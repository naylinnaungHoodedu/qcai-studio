import json
from pathlib import Path

from app.schemas import VideoChapter


CURATED_VIDEO_CHAPTERS: dict[str, list[VideoChapter]] = {
    "Quantum Computing and Artificial Intelligence 2025.mp4": [
        VideoChapter(
            id="2025-intro",
            title="Why Quantum plus AI",
            timestamp_start=0,
            timestamp_end=71,
            summary="Introduces the QC+AI field and frames it through the practical limitations of NISQ hardware.",
            transcript_excerpt="The opening frames QC+AI as a hardware-constrained field in which every quantum step must earn its place inside a practical hybrid workflow.",
        ),
        VideoChapter(
            id="2025-nisq",
            title="NISQ Bottlenecks",
            timestamp_start=71,
            timestamp_end=143,
            summary="Explains that current systems are constrained by noise, routing overhead, and limited qubit budgets.",
            transcript_excerpt="The video emphasizes that current hardware cannot absorb raw problem formulations without strong classical assistance.",
        ),
        VideoChapter(
            id="2025-routing",
            title="Compilation and Routing",
            timestamp_start=143,
            timestamp_end=287,
            summary="Focuses on code compilation, qubit routing, and the physical cost of mapping logical circuits to sparse hardware graphs.",
            transcript_excerpt="Compilation overhead is presented as a decisive engineering constraint rather than a software afterthought.",
        ),
        VideoChapter(
            id="2025-optimization",
            title="Hybrid Optimization Patterns",
            timestamp_start=287,
            timestamp_end=431,
            summary="Covers hybrid optimization loops and the role of classical search and learning around quantum subroutines.",
            transcript_excerpt="The recurring message is that classical intelligence often protects fragile quantum steps from infeasible search spaces.",
        ),
        VideoChapter(
            id="2025-applications",
            title="Applications and System Design",
            timestamp_start=431,
            timestamp_end=575,
            summary="Closes with application examples and a general argument for hybridization as the practical path in the NISQ era.",
            transcript_excerpt="The ending connects routing, noise mitigation, and application design into a coherent hybrid systems view.",
        ),
    ],
    "Quantum Computing and Artificial Intelligence 2026.mp4": [
        VideoChapter(
            id="2026-intro",
            title="Hybrid QC+AI Framing",
            timestamp_start=0,
            timestamp_end=71,
            summary="Opens with the broad framing of quantum computing and AI as mutually enabling disciplines under hardware constraints.",
            transcript_excerpt="The introduction positions quantum computing and AI as mutually enabling disciplines, then narrows quickly to what present hardware can sustain operationally.",
        ),
        VideoChapter(
            id="2026-feature-bottlenecks",
            title="Feature Bottlenecks and Representations",
            timestamp_start=71,
            timestamp_end=215,
            summary="Emphasizes that the quantum role in practical models often sits at a compact, expressive bottleneck.",
            transcript_excerpt="The video visually reinforces that representation density matters more than speculative end-to-end replacement.",
        ),
        VideoChapter(
            id="2026-systems",
            title="Systems and Physical Constraints",
            timestamp_start=215,
            timestamp_end=359,
            summary="Returns to hardware and systems limitations, including resource bottlenecks and the need for disciplined orchestration.",
            transcript_excerpt="It ties model design back to what the hardware can sustain physically and operationally.",
        ),
        VideoChapter(
            id="2026-applications",
            title="Hybrid Applications",
            timestamp_start=359,
            timestamp_end=503,
            summary="Surveys application stories in optimization and hybrid learning with an emphasis on workable interfaces between classical and quantum components.",
            transcript_excerpt="The strongest message is that useful workflows are hybrid by construction.",
        ),
        VideoChapter(
            id="2026-roadmap",
            title="Roadmap and Future Direction",
            timestamp_start=503,
            timestamp_end=575,
            summary="Ends on a roadmap of sustainable hybrid systems, including the resource and thermodynamic framing of quantum agents.",
            transcript_excerpt="The closing emphasizes future systems design, not merely isolated algorithmic novelty.",
        ),
    ],
    "Industry Use Cases.mp4": [
        VideoChapter(
            id="industry-intro",
            title="Industry 5.0 Framing",
            timestamp_start=0,
            timestamp_end=76,
            summary="Opens by framing QC+AI as an Industry 5.0 transition shaped by resilience, sustainability, and workload-specific deployment choices.",
            transcript_excerpt="The video positions industry adoption as a portfolio question rather than a single universal disruption claim.",
            transcript_status="curated_chapter_summary",
        ),
        VideoChapter(
            id="industry-finance-logistics",
            title="Finance and Logistics",
            timestamp_start=76,
            timestamp_end=196,
            summary="Covers optimization-heavy sectors such as finance, cryptoeconomics, route planning, inventory management, and traffic flow.",
            transcript_excerpt="The strongest emphasis is on anomaly detection, portfolio optimization, and real-time orchestration around quantum optimization steps.",
            transcript_status="curated_chapter_summary",
        ),
        VideoChapter(
            id="industry-healthcare-climate",
            title="Healthcare, Pharma, and Climate",
            timestamp_start=196,
            timestamp_end=330,
            summary="Explains why healthcare, pharmaceuticals, chemistry, and climate modeling are attractive when simulation and high-dimensional inference are central.",
            transcript_excerpt="This section distinguishes native molecular simulation stories from broader predictive-analytics claims.",
            transcript_status="curated_chapter_summary",
        ),
        VideoChapter(
            id="industry-networks-security",
            title="Networks and Cybersecurity",
            timestamp_start=330,
            timestamp_end=470,
            summary="Moves into telecommunications, quantum networking, post-quantum migration, blockchain, and the urgency of security transition planning.",
            transcript_excerpt="Cybersecurity is framed as a migration problem with present consequences, not merely a distant speculative use case.",
            transcript_status="curated_chapter_summary",
        ),
        VideoChapter(
            id="industry-consumer-commercial",
            title="Consumer and Commercial Outlook",
            timestamp_start=470,
            timestamp_end=604,
            summary="Closes with consumer technology, entrepreneurial opportunity, commercialization limits, and the readiness differences across sectors.",
            transcript_excerpt="The conclusion stresses that adoption depends on regulation, infrastructure maturity, and hybrid support systems around the quantum component.",
            transcript_status="curated_chapter_summary",
        ),
    ],
}


def _mark_curated_transcript_status(chapters: list[VideoChapter]) -> list[VideoChapter]:
    return [
        chapter
        if chapter.transcript_status != "chapter_summary_only"
        else chapter.model_copy(update={"transcript_status": "curated_chapter_summary"})
        for chapter in chapters
    ]


def load_video_chapters(transcripts_dir: Path, filename: str) -> list[VideoChapter]:
    transcript_file = transcripts_dir / f"{Path(filename).stem}.json"
    if transcript_file.exists():
        try:
            data = json.loads(transcript_file.read_text(encoding="utf-8"))
            return [VideoChapter.model_validate(item) for item in data.get("chapters", [])]
        except Exception:
            pass
    return _mark_curated_transcript_status(CURATED_VIDEO_CHAPTERS.get(filename, []))
