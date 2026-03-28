from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import Settings
from app.schemas import (
    CourseOverview,
    Flashcard,
    LessonDetail,
    LessonSection,
    ModuleSummary,
    QuizQuestion,
    RelatedLessonSummary,
    SearchResult,
    SourceAsset,
)
from app.services.docx_parser import SectionRecord, parse_docx_sections
from app.services.transcripts import load_video_chapters


DOCUMENT_TITLE_MAP = {
    "Analyzing Quantum Computing and AI Paper 2025.docx": "Ali, Chicano, and Moraglio (Eds.), QC+AI 2025 Proceedings",
    "Quantum Computing AI Research Synthesis 2026.docx": "Ali, Chicano, and Moraglio (Eds.), QC+AI 2026 Proceedings",
    "Quantum Computing and Artificial Intelligence Industry Use Cases.docx": "Raj et al. (Eds.), Quantum Computing and Artificial Intelligence: The Industry Use Cases",
}

ASSET_TITLE_MAP = {
    **DOCUMENT_TITLE_MAP,
    "Quantum Computing and Artificial Intelligence 2025.mp4": "Quantum Computing and Artificial Intelligence 2025",
    "Quantum Computing and Artificial Intelligence 2026.mp4": "Quantum Computing and Artificial Intelligence 2026",
    "Industry Use Cases.mp4": "Industry Use Cases",
}


@dataclass
class IndexedChunk:
    chunk_id: str
    title: str
    source_kind: str
    source_title: str
    excerpt: str
    lesson_slug: str | None
    score_boost: float
    timestamp_label: str | None = None


def _lesson_blueprint(
    slug: str,
    title: str,
    summary: str,
    key_ideas: list[str],
    key_notes: list[str],
    formulas: list[str],
    learner_questions: list[str],
    section_refs: list[str],
    video_file: str | None,
    flashcards: list[tuple[str, str, str]] | None = None,
    quiz: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "slug": slug,
        "title": title,
        "summary": summary,
        "key_ideas": key_ideas,
        "key_notes": key_notes,
        "formulas": formulas,
        "learner_questions": learner_questions,
        "section_refs": section_refs,
        "video_file": video_file,
        "flashcards": flashcards or [],
        "quiz": quiz or [],
    }


def _module_lessons(blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    lessons = blueprint.get("lessons")
    if lessons:
        return lessons

    lesson = dict(blueprint["lesson"])
    if not lesson.get("flashcards"):
        lesson["flashcards"] = blueprint.get("flashcards", [])
    if not lesson.get("quiz"):
        lesson["quiz"] = blueprint.get("quiz", [])
    return [lesson]


MODULE_BLUEPRINTS: list[dict[str, Any]] = [
    {
        "slug": "nisq-hybrid-workflows",
        "title": "QC+AI Overview and the NISQ Reality",
        "summary": "Introduces QAI versus AI4QC and the central claim of the corpus: useful near-term progress comes from disciplined hybridization under NISQ constraints.",
        "learning_goals": [
            "Distinguish QAI from AI4QC.",
            "Identify the major NISQ constraints that shape algorithm design.",
            "Understand why hybrid workflows dominate the source corpus.",
        ],
        "source_highlights": [
            "Introduction and Contextual Overview (2026)",
            "The Convergence of Quantum Mechanics and Computational Intelligence (2025)",
        ],
        "lesson": _lesson_blueprint(
            slug="nisq-reality-overview",
            title="Hybrid Quantum-Classical Design in the NISQ Era",
            summary="Frames the course around NISQ-era limits and the distinction between using quantum methods for AI versus using AI to make quantum computing operationally useful.",
            key_ideas=[
                "NISQ hardware forces algorithmic modesty and systems discipline.",
                "Hybrid designs split labor: classical systems absorb orchestration, quantum components contribute targeted representational or optimization steps.",
                "The strongest theme across the sources is credible hybridization, not blanket quantum replacement.",
            ],
            key_notes=[
                "Treat routing, noise, and qubit scarcity as primary design parameters.",
                "Ask in every method: what is quantum, what stays classical, and where does the physical bottleneck move?",
            ],
            formulas=[
                "Present a workflow diagram separating classical preprocessing, quantum subroutine, and classical post-processing.",
            ],
            learner_questions=[
                "What is the difference between QAI and AI4QC?",
                "Why do the sources repeatedly emphasize hybrid loops instead of end-to-end quantum models?",
                "What makes a QC+AI claim plausible in the NISQ era?",
            ],
            section_refs=[
                "Introduction and Contextual Overview",
                "The Convergence of Quantum Mechanics and Computational Intelligence",
            ],
            video_file="Quantum Computing and Artificial Intelligence 2025.mp4",
        ),
        "flashcards": [
            ("intro", "What does AI4QC mean in the course corpus?", "Using classical AI methods to make quantum hardware and quantum workflows more usable."),
            ("intermediate", "What does QAI mean in the course corpus?", "Using quantum mechanisms or quantum circuits to enhance AI models or representations."),
            ("advanced", "Why is hybridization the dominant near-term pattern?", "Because classical systems still handle the scale, memory, and orchestration that current quantum hardware cannot absorb alone."),
        ],
        "quiz": [
            {
                "type": "mcq",
                "prompt": "Which statement best matches the source corpus?",
                "choices": [
                    "Near-term value comes mostly from fully quantum end-to-end models.",
                    "Near-term value comes from hybrid workflows shaped by hardware constraints.",
                    "Classical AI is largely irrelevant once quantum hardware is available.",
                    "Routing and compilation are secondary implementation details.",
                ],
                "answer": "Near-term value comes from hybrid workflows shaped by hardware constraints.",
                "difficulty": "intro",
                "explanation": "Both the 2025 and 2026 materials repeatedly position hybridization as the realistic path in the NISQ era.",
            }
        ],
    },
    {
        "slug": "ai-for-quantum-hardware",
        "title": "AI for Quantum Hardware and Optimization",
        "summary": "Explains how classical AI supports quantum routing, constrained optimization, graph shrinking, and realistic problem reformulation.",
        "learning_goals": [
            "Understand why classical AI often enables rather than replaces quantum computation.",
            "Explain routing, graph shrinking, and augmented Lagrangian methods in hardware-aware terms.",
            "Connect combinatorial reformulation to qubit scarcity.",
        ],
        "source_highlights": [
            "Classical Artificial Intelligence for Quantum Circuit Routing (2025)",
            "Hybrid Reinforcement Learning and Quantum Optimization for Logistics (2026)",
            "Learning-Based Graph Shrinking for Constrained Combinatorial Quantum Optimization (2026)",
        ],
        "lesson": _lesson_blueprint(
            slug="ai4qc-routing-and-optimization",
            title="Routing, Graph Shrinking, and Logistics under Hardware Constraints",
            summary="Uses routing, RL-tuned augmented Lagrangian methods, and graph shrinking to show how classical intelligence creates viable interfaces to limited quantum hardware.",
            key_ideas=[
                "Routing overhead can erase theoretical algorithmic gains if ignored.",
                "Classical learning can reshape the optimization landscape before quantum execution.",
                "Graph shrinking and reformulation are practical compression strategies for limited qubit budgets.",
            ],
            key_notes=[
                "The sources treat AI as a compiler, controller, and search heuristic around fragile quantum subroutines.",
                "Sparse connectivity and QUBO blow-up are physical constraints, not merely theoretical nuisances.",
            ],
            formulas=[
                "Quadratic Unconstrained Binary Optimization objective: x^T Q x.",
                "Augmented Lagrangian objective blending primary cost with penalty and multiplier terms.",
            ],
            learner_questions=[
                "Why can routing overhead dominate practical performance?",
                "What does RL add to an augmented Lagrangian approach for logistics?",
                "Why is graph shrinking so valuable in NISQ settings?",
            ],
            section_refs=[
                "Classical Artificial Intelligence for Quantum Circuit Routing",
                "The NMCS Methodology and State Formulation",
                "Scalability, Benchmarks, and Topological Generalization",
                "Hybrid Reinforcement Learning and Quantum Optimization for Logistics",
                "Learning-Based Graph Shrinking for Constrained Combinatorial Quantum Optimization",
            ],
            video_file="Quantum Computing and Artificial Intelligence 2025.mp4",
        ),
        "flashcards": [
            ("intro", "What problem does qubit routing solve?", "It maps logical multi-qubit interactions onto sparse physical hardware connectivity."),
            ("intermediate", "Why use graph shrinking before quantum optimization?", "It compresses large constrained instances into smaller forms that fit limited qubit resources."),
            ("advanced", "What is the practical role of RL-Q-ALM in the source corpus?", "It lets classical learning adapt penalty behavior so quantum subproblems become more tractable and stable."),
        ],
        "quiz": [
            {
                "type": "short-answer",
                "prompt": "Explain why routing is a physical systems problem rather than only a compiler nicety.",
                "answer": "Routing determines how many extra SWAP operations and depth penalties are introduced by sparse connectivity, directly affecting decoherence exposure and executable fidelity.",
                "difficulty": "intermediate",
            }
        ],
    },
    {
        "slug": "quantum-enhanced-applications",
        "title": "Quantum-Enhanced AI in Vision, Healthcare, and Few-Shot Learning",
        "summary": "Focuses on hybrid architectures where quantum layers act as compact feature bottlenecks, kernels, or classifiers inside larger classical systems.",
        "learning_goals": [
            "Compare several application patterns for hybrid QC+AI systems.",
            "Identify where the quantum component actually sits in each architecture.",
            "Distinguish educational promise from operational maturity.",
        ],
        "source_highlights": [
            "Quantum Vision Transformers in High-Energy Physics (2025)",
            "Quantum-Classical Graph Neural Networks for Particle Jet Tagging (2025)",
            "Quantum Diffusion Models for Few-Shot Learning (2025)",
            "Quantum-Enhanced Reinforcement Learning in Safety-Critical Clinical Control (2026)",
            "Quantum Kernel Methods for High-Dimensional Biomedical Imaging (2026)",
        ],
        "lessons": [
            _lesson_blueprint(
                slug="hybrid-applications-healthcare-vision",
                title="Quantum Vision, GNN, and Few-Shot Hybrid Architectures",
                summary="Surveys vision-transformer, graph-neural, and diffusion examples in which the quantum component is a narrow representational bottleneck rather than a total model replacement.",
                key_ideas=[
                    "The most credible pattern is to place the quantum circuit at a narrow, expressive bottleneck.",
                    "Vision, jet-tagging, and few-shot examples preserve substantial classical structure around the quantum component.",
                    "Operational realism comes from identifying exactly what the bounded quantum stage is supposed to improve.",
                ],
                key_notes=[
                    "QViT, quantum-classical GNNs, and quantum diffusion all use the quantum stage selectively rather than universally.",
                    "The strongest educational takeaway is architectural placement, not blanket quantum superiority.",
                ],
                formulas=[
                    "Hybrid attention or latent-pipeline sketches should show where the quantum stage sits relative to classical preprocessing and decoding.",
                ],
                learner_questions=[
                    "Why do these application papers keep the quantum circuit at the feature bottleneck?",
                    "What does the quantum component contribute in the jet-tagging and few-shot-learning examples?",
                    "How should a practitioner assess whether these vision and graph applications are mature enough for deployment?",
                ],
                section_refs=[
                    "Quantum Vision Transformers in High-Energy Physics",
                    "Quantum-Classical Graph Neural Networks for Particle Jet Tagging",
                    "Quantum Diffusion Models for Few-Shot Learning",
                ],
                video_file="Quantum Computing and Artificial Intelligence 2026.mp4",
                flashcards=[
                    ("intro", "What is a common placement for the quantum component in practical hybrid models?", "At a compact feature bottleneck, kernel layer, or classifier head."),
                    ("intermediate", "Why are the QViT and quantum-classical GNN examples pedagogically useful?", "They show how a bounded quantum stage can sit inside a larger classical perception pipeline without replacing the full model."),
                    ("advanced", "Why is the few-shot diffusion example notable?", "It treats the quantum component as a compact latent or representational aid rather than a full generative stack replacement."),
                ],
                quiz=[
                    {
                        "type": "mcq",
                        "prompt": "Which architectural pattern best matches the vision, graph, and few-shot application cases in the sources?",
                        "choices": [
                            "Replace all classical layers with a quantum circuit",
                            "Use the quantum component as a targeted representational or decision bottleneck",
                            "Avoid any classical preprocessing",
                            "Assume hardware constraints are secondary once a kernel is used",
                        ],
                        "answer": "Use the quantum component as a targeted representational or decision bottleneck",
                        "difficulty": "intermediate",
                        "explanation": "The application cases preserve substantial classical structure around a focused quantum subroutine.",
                    }
                ],
            ),
            _lesson_blueprint(
                slug="clinical-and-kernel-qcai-systems",
                title="Clinical Control and Kernelized Biomedical Hybrids",
                summary="Focuses on safety-critical clinical control and biomedical-kernel examples where quantum models are embedded inside tightly scoped classical decision systems.",
                key_ideas=[
                    "Healthcare examples succeed only when the quantum role remains narrow, explicit, and auditable.",
                    "QC-DQN is best interpreted as a hybrid control architecture in a constrained safety setting, not as a broad replacement for classical RL.",
                    "Quantum kernels are framed as compact similarity mechanisms inside otherwise classical biomedical workflows.",
                ],
                key_notes=[
                    "QUEN ties a quantum-kernel bottleneck to a concrete aneurysm classification task with explicit regularization ideas.",
                    "Clinical-control examples should always be read with deployment maturity and validation requirements in mind.",
                ],
                formulas=[
                    "Bellman-style value updates for reinforcement learning, interpreted in a hybrid QC-DQN setting.",
                    "Kernel similarity as a fidelity-style overlap between encoded quantum states.",
                ],
                learner_questions=[
                    "What does a quantum kernel add in the aneurysm classification example?",
                    "Why should QC-DQN be taught carefully in a clinical context?",
                    "What makes these healthcare-flavored examples more operationally constrained than the perception examples?",
                ],
                section_refs=[
                    "Quantum-Enhanced Reinforcement Learning in Safety-Critical Clinical Control",
                    "Quantum Kernel Methods for High-Dimensional Biomedical Imaging",
                ],
                video_file="Quantum Computing and Artificial Intelligence 2026.mp4",
                flashcards=[
                    ("intro", "Why is QUEN interesting pedagogically?", "It ties a quantum kernel-style bottleneck to a concrete biomedical imaging task with explicit physical regularization ideas."),
                    ("intermediate", "Why should QC-DQN be taught carefully?", "Because it is an instructive hybrid design in a safety-critical setting, but not evidence that quantum RL broadly replaces classical control methods."),
                    ("advanced", "What makes healthcare QC+AI architectures operationally demanding?", "They require bounded quantum roles, validation discipline, and auditable fallback behavior around the clinical decision path."),
                ],
                quiz=[
                    {
                        "type": "short-answer",
                        "prompt": "Explain why QC-DQN and biomedical quantum-kernel methods should be evaluated as narrow hybrid architectures rather than end-to-end quantum replacements.",
                        "answer": "Both examples embed a bounded quantum stage inside a larger classical decision or imaging pipeline, so the technical question is whether that narrow insertion improves representation or control without undermining validation, safety, or fallback behavior.",
                        "difficulty": "advanced",
                    }
                ],
            ),
        ],
    },
    {
        "slug": "representation-explainability",
        "title": "Representation, Language, Compression, and Explainability",
        "summary": "Explores quINR, QuCoWE, and QGSHAP as examples of expressive hybrid representations and more faithful explanation under combinatorial complexity.",
        "learning_goals": [
            "Understand why representation density is a recurring theme in hybrid QC+AI.",
            "Explain how quantum semantics and compression claims are framed in the source corpus.",
            "Interpret QGSHAP as a targeted explainability acceleration story.",
        ],
        "source_highlights": [
            "Quantum Implicit Neural Compression (2025)",
            "Distributional Semantics and Quantum Contrastive Word Embeddings (2026)",
            "Quantum Amplitude Amplification for Exact GNN Explainability (2026)",
        ],
        "lesson": _lesson_blueprint(
            slug="representation-language-and-xai",
            title="Expressive Bottlenecks: Compression, Language, and Explanation",
            summary="Uses quINR, QuCoWE, and QGSHAP to show how hybrid quantum components are often justified by representational density or combinatorial structure rather than generic speedup claims.",
            key_ideas=[
                "Quantum representations are often pitched as compact, expressive bottlenecks.",
                "Language and semantic models require careful adaptation because quantum fidelity does not directly mirror classical contrastive objectives.",
                "Explainability remains combinatorially hard; targeted quantum subroutines can be presented as accelerants under strict assumptions.",
            ],
            key_notes=[
                "quINR is best taught as a compression story, not as a universal neural network replacement.",
                "QuCoWE explicitly repairs a mismatch between fidelity-based similarity and classical distributional objectives.",
                "QGSHAP should be framed as a specialized explainability method with strong structural assumptions.",
            ],
            formulas=[
                "Folded-angle embedding as a compact way to pack classical coordinates into limited qubits.",
                "Logit-fidelity mapping to bridge bounded quantum fidelity with contrastive learning objectives.",
            ],
            learner_questions=[
                "Why is quINR framed as a compression and representation method?",
                "What problem does the logit-fidelity head solve in QuCoWE?",
                "How should QGSHAP be explained to a student who already knows Shapley values?",
            ],
            section_refs=[
                "Quantum Implicit Neural Compression",
                "Distributional Semantics and Quantum Contrastive Word Embeddings",
                "Quantum Amplitude Amplification for Exact GNN Explainability",
            ],
            video_file="Quantum Computing and Artificial Intelligence 2026.mp4",
        ),
        "flashcards": [
            ("intro", "What is the central promise of quINR in the course corpus?", "High representational expressivity for compression using a hybrid quantum implicit neural representation."),
            ("intermediate", "Why is QuCoWE not a simple quantum version of Word2Vec?", "Because classical contrastive objectives and bounded quantum fidelity are not directly compatible."),
            ("advanced", "What makes QGSHAP pedagogically interesting?", "It connects quantum amplitude amplification to a well-known explainability bottleneck in graph models."),
        ],
        "quiz": [
            {
                "type": "short-answer",
                "prompt": "Explain the role of representation density across quINR and QuCoWE.",
                "answer": "Both methods treat the quantum component as a compact expressive space: quINR for signal representation and QuCoWE for semantic structure, but each requires careful mapping from classical objectives into a physically realizable quantum form.",
                "difficulty": "advanced",
            }
        ],
    },
    {
        "slug": "industry-use-cases",
        "title": "Industry Use Cases",
        "summary": "Maps the local industry-use-case corpus onto finance, healthcare, logistics, climate, telecommunications, cybersecurity, consumer technology, and commercialization.",
        "learning_goals": [
            "Map the dominant QC+AI opportunity patterns across major industry verticals.",
            "Distinguish optimization, simulation, and security migration use cases from one another.",
            "Explain how Industry 5.0, commercialization pressure, and regulation shape adoption.",
        ],
        "source_highlights": [
            "The Macro-Industrial Shift: Industry 4.0 to Industry 5.0",
            "Revolutionary Use Cases in Financial Modeling and Cryptoeconomics",
            "Transforming Healthcare, Pharmaceuticals, and Computational Chemistry",
            "Cybersecurity, Post-Quantum Cryptography, and Blockchain",
            "The Entrepreneurial Ecosystem and Commercial Opportunities",
        ],
        "lesson": _lesson_blueprint(
            slug="industry-use-cases",
            title="Where QC+AI Creates Industry Value",
            summary="Surveys the industry-use-case document as a cross-sector map of where QC+AI is positioned as an optimization, simulation, security, and personalization tool.",
            key_ideas=[
                "The document frames QC+AI as a portfolio of workload-specific industry plays rather than a single universal disruption story.",
                "Finance and logistics emphasize optimization and anomaly detection, while pharma and materials work is anchored in native molecular simulation.",
                "Cybersecurity and post-quantum migration are presented as urgent transition problems, not optional future enhancements.",
            ],
            key_notes=[
                "Industry 5.0 is used as a strategic frame for resilient, sustainable, and human-centered deployment rather than automation for its own sake.",
                "Commercial readiness varies sharply by vertical: some claims depend on near-term hybrid workflows, while others assume more mature quantum infrastructure.",
            ],
            formulas=[
                "Use a workload map that pairs each vertical with its dominant QC+AI task class: optimization, simulation, secure communication, or personalization.",
                "Compare sectors with a readiness matrix covering hardware dependence, regulatory pressure, and expected hybrid-classical support.",
            ],
            learner_questions=[
                "Which sectors in the document primarily depend on combinatorial optimization rather than quantum-native simulation?",
                "Why does cybersecurity have a more urgent migration profile than consumer recommendation or gaming use cases?",
                "How does the Industry 5.0 framing change the way the document justifies adoption?",
            ],
            section_refs=[
                "The Macro-Industrial Shift: Industry 4.0 to Industry 5.0",
                "Revolutionary Use Cases in Financial Modeling and Cryptoeconomics",
                "Transforming Healthcare, Pharmaceuticals, and Computational Chemistry",
                "Global Logistics, Supply Chain, and Traffic Flow Management",
                "Environmental Sciences: Weather Forecasting and Climate Modeling",
                "Advanced Communications: Quantum Networks and Mobile Coverage",
                "Cybersecurity, Post-Quantum Cryptography, and Blockchain",
                "Consumer Technology: Voice-Controlled Devices, Advertising, and Gaming",
                "The Entrepreneurial Ecosystem and Commercial Opportunities",
                "Strategic Outlook and Future Trajectories",
            ],
            video_file="Industry Use Cases.mp4",
        ),
        "flashcards": [
            ("intro", "Which industry group in the document is most tightly tied to native molecular simulation?", "Healthcare, pharmaceuticals, and computational chemistry."),
            ("intermediate", "Why is post-quantum cryptography treated as urgent rather than speculative?", "Because the document treats quantum attacks on current public-key systems and store-now-decrypt-later risks as active migration drivers."),
            ("advanced", "Why are logistics and telecom use cases still hybrid even when the document is optimistic?", "Because they depend on large classical data pipelines, orchestration systems, and real-time constraints around the quantum optimization step."),
        ],
        "quiz": [
            {
                "type": "mcq",
                "prompt": "Which pairing best matches the industry-use-case document?",
                "choices": [
                    "Pharma is framed mainly as ad targeting, while cybersecurity is framed mainly as loot generation.",
                    "Finance and logistics are framed around optimization and anomaly detection, while cybersecurity centers on post-quantum migration.",
                    "Consumer gaming is framed as the most urgent national security migration priority.",
                    "The document argues that every vertical requires the same quantum workload pattern.",
                ],
                "answer": "Finance and logistics are framed around optimization and anomaly detection, while cybersecurity centers on post-quantum migration.",
                "difficulty": "intermediate",
                "explanation": "The source distinguishes optimization-heavy sectors from the security transition problem and does not present the verticals as interchangeable.",
            }
        ],
    },
    {
        "slug": "thermodynamics-roadmap",
        "title": "Thermodynamic Quantum Agents and Future Directions",
        "summary": "Closes the course by treating QC+AI as a systems discipline concerned with energy, memory, and sustainable hybrid orchestration.",
        "learning_goals": [
            "Explain the thermodynamic framing of quantum agents.",
            "Separate near-term credible pathways from more speculative long-range claims.",
            "Summarize the roadmap implied by the 2026 synthesis.",
        ],
        "source_highlights": [
            "The Thermodynamic Imperative: Quantum Agents and Resource Efficiency (2026)",
            "Synthesis and Future Trajectories in Hybrid Quantum-Classical Computing (2026)",
            "Synthesis and Forward Outlook (2025)",
        ],
        "lesson": _lesson_blueprint(
            slug="thermodynamics-and-roadmap",
            title="From Algorithmic Novelty to Sustainable Hybrid Systems",
            summary="Synthesizes the source corpus around resource efficiency, memory cost, and the broader systems view of hybrid QC+AI.",
            key_ideas=[
                "The most interesting future claims may be about resource efficiency rather than only runtime speedup.",
                "Thermodynamic perspectives force a more serious conversation about sustainable AI scaling.",
                "Future QC+AI roadmaps depend on hardware maturity, orchestration quality, and careful application selection.",
            ],
            key_notes=[
                "The 2026 synthesis broadens the argument from individual methods to system-level design.",
                "Use this lesson to help learners separate strategic direction from premature operational claims.",
            ],
            formulas=[
                "Present a conceptual energy-per-inference comparison rather than a single canonical formula.",
            ],
            learner_questions=[
                "What does it mean for a quantum-agent advantage to be thermodynamic?",
                "Which source claims seem near-term credible, and which are still exploratory?",
            ],
            section_refs=[
                "The Thermodynamic Imperative: Quantum Agents and Resource Efficiency",
                "Synthesis and Future Trajectories in Hybrid Quantum-Classical Computing",
                "Synthesis and Forward Outlook",
            ],
            video_file="Quantum Computing and Artificial Intelligence 2026.mp4",
        ),
        "flashcards": [
            ("intro", "What is the thermodynamic framing of a quantum agent?", "It treats the advantage partly in terms of memory and energetic cost under uncertainty, not only raw runtime."),
            ("intermediate", "Why is sustainable AI scaling part of the QC+AI conversation?", "Because the corpus argues that future AI systems may hit energy and memory constraints that motivate new computational substrates."),
            ("advanced", "Why should roadmap discussions remain cautious?", "Because credible progress depends on hardware maturity, orchestration, error behavior, and workload-specific evidence, not broad slogans."),
        ],
        "quiz": [
            {
                "type": "short-answer",
                "prompt": "Describe how the 2026 synthesis reframes quantum advantage in AI.",
                "answer": "It expands the notion of advantage beyond speed to include thermodynamic and memory efficiency, embedding QC+AI inside a larger systems and sustainability perspective.",
                "difficulty": "advanced",
            }
        ],
    },
]


class CourseStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=120)
        self.overview: CourseOverview | None = None
        self.modules: dict[str, ModuleSummary] = {}
        self.lessons: dict[str, LessonDetail] = {}
        self.chunks: list[IndexedChunk] = []
        self.build()

    def build(self) -> None:
        sections = self._load_sections()
        doc_assets = [self._build_source_asset(path, "document") for path in self.settings.source_documents]
        video_assets = [self._build_source_asset(path, "video") for path in self.settings.source_videos]
        assets = doc_assets + video_assets

        modules: list[ModuleSummary] = []
        lessons: dict[str, LessonDetail] = {}
        chunks: list[IndexedChunk] = []

        for module_index, blueprint in enumerate(MODULE_BLUEPRINTS, start=1):
            lesson_slugs: list[str] = []
            for lesson_blueprint in _module_lessons(blueprint):
                lesson_slug = lesson_blueprint["slug"]
                matched_sections = self._match_sections(sections, lesson_blueprint["section_refs"])
                lesson_sections = self._build_lesson_sections(matched_sections)
                video_asset = next((asset for asset in video_assets if asset.filename == lesson_blueprint["video_file"]), None)
                chapters = load_video_chapters(self.settings.transcripts_dir, video_asset.filename) if video_asset else []

                lesson = LessonDetail(
                    slug=lesson_slug,
                    module_slug=blueprint["slug"],
                    title=lesson_blueprint["title"],
                    summary=lesson_blueprint["summary"],
                    key_ideas=lesson_blueprint["key_ideas"],
                    key_notes=lesson_blueprint["key_notes"],
                    formulas=lesson_blueprint["formulas"],
                    learner_questions=lesson_blueprint["learner_questions"],
                    sections=lesson_sections,
                    source_assets=self._collect_source_assets(assets, matched_sections, lesson_blueprint["video_file"]),
                    video_asset=video_asset,
                    chapters=chapters,
                    flashcards=self._build_flashcards(lesson_slug, lesson_blueprint.get("flashcards", [])),
                    quiz_questions=self._build_quiz(lesson_slug, lesson_blueprint.get("quiz", [])),
                )
                lessons[lesson_slug] = lesson
                lesson_slugs.append(lesson_slug)
                chunks.extend(self._build_chunks(module_index, lesson, matched_sections))

            modules.append(
                ModuleSummary(
                    slug=blueprint["slug"],
                    title=blueprint["title"],
                    summary=blueprint["summary"],
                    learning_goals=blueprint["learning_goals"],
                    lesson_slugs=lesson_slugs,
                    source_highlights=blueprint["source_highlights"],
                )
            )

        self.overview = CourseOverview(
            id="qcai-hardware-aware-course",
            title="Quantum Computing and AI: Hardware-Constrained Hybrid Learning",
            summary="An interactive course grounded in the local QC+AI research syntheses and industry-use-case analysis, framed through NISQ realism, practical applications, and systems constraints.",
            modules=modules,
            source_assets=assets,
        )
        self.modules = {module.slug: module for module in modules}
        self._populate_related_lessons(lessons)
        self.lessons = lessons
        self.chunks = chunks

    def _build_source_asset(self, path: Path, kind: str) -> SourceAsset:
        asset_id = path.stem.lower().replace(" ", "-")
        return SourceAsset(
            id=asset_id,
            title=ASSET_TITLE_MAP.get(path.name, path.name),
            kind=kind,
            filename=path.name,
            size_bytes=path.stat().st_size if path.exists() else None,
            download_url=f"/source-assets/by-id/{asset_id}",
            description="Local project source asset",
        )

    def _load_sections(self) -> list[SectionRecord]:
        all_sections: list[SectionRecord] = []
        for path in self.settings.source_documents:
            if path.exists():
                document_title = DOCUMENT_TITLE_MAP.get(path.name, path.stem)
                sections = parse_docx_sections(path)
                for section in sections:
                    section.source_title = document_title
                all_sections.extend(sections)
        return all_sections

    def _match_sections(self, sections: list[SectionRecord], refs: list[str]) -> list[SectionRecord]:
        if not refs:
            return []
        matched: list[SectionRecord] = []
        used_keys: set[str] = set()
        for ref in refs:
            ref_l = ref.lower()
            for section in sections:
                key = f"{section.source_title}:{section.heading}"
                if key in used_keys:
                    continue
                if ref_l in section.heading.lower():
                    matched.append(section)
                    used_keys.add(key)
        return matched

    def _build_lesson_sections(self, sections: list[SectionRecord]) -> list[LessonSection]:
        built: list[LessonSection] = []
        for index, section in enumerate(sections, start=1):
            excerpt = section.body[:500].strip()
            summary = excerpt.split(". ")[0].strip()
            built.append(
                LessonSection(
                    id=f"{section.source_id}-section-{index}",
                    source_title=section.source_title,
                    heading=section.heading,
                    summary=summary,
                    excerpt=excerpt,
                    topics=self._derive_topics(section.heading, section.body),
                )
            )
        return built

    def _derive_topics(self, heading: str, body: str) -> list[str]:
        haystack = f"{heading} {body}".lower()
        topic_map = {
            "routing": "routing",
            "qubo": "qubo",
            "finance": "finance",
            "portfolio": "finance",
            "health": "healthcare",
            "drug": "drug discovery",
            "pharma": "drug discovery",
            "genomic": "genomics",
            "aneurysm": "healthcare",
            "vision": "vision",
            "graph": "graph methods",
            "language": "language",
            "embedding": "representation",
            "supply chain": "logistics",
            "traffic": "logistics",
            "weather": "climate",
            "climate": "climate",
            "network": "telecommunications",
            "mobile": "telecommunications",
            "cryptography": "cybersecurity",
            "blockchain": "cybersecurity",
            "advertising": "consumer technology",
            "gaming": "consumer technology",
            "thermodynamic": "thermodynamics",
            "kernel": "kernel methods",
            "reinforcement": "reinforcement learning",
            "optimization": "optimization",
        }
        return sorted({label for token, label in topic_map.items() if token in haystack})

    def _collect_source_assets(self, assets: list[SourceAsset], sections: list[SectionRecord], video_file: str | None) -> list[SourceAsset]:
        source_titles = {section.source_title for section in sections}
        selected = [asset for asset in assets if asset.title in source_titles]
        if video_file:
            selected.extend(asset for asset in assets if asset.filename == video_file)
        deduped: list[SourceAsset] = []
        seen: set[str] = set()
        for asset in selected:
            if asset.id not in seen:
                deduped.append(asset)
                seen.add(asset.id)
        return deduped

    def _build_flashcards(self, lesson_slug: str, cards: list[tuple[str, str, str]]) -> list[Flashcard]:
        return [
            Flashcard(
                id=f"{lesson_slug}-flashcard-{index}",
                difficulty=difficulty,
                prompt=prompt,
                answer=answer,
                card_type="concept" if difficulty == "intro" else "application",
            )
            for index, (difficulty, prompt, answer) in enumerate(cards, start=1)
        ]

    def _build_quiz(self, lesson_slug: str, quiz_items: list[dict[str, Any]]) -> list[QuizQuestion]:
        return [
            QuizQuestion(
                id=f"{lesson_slug}-quiz-{index}",
                question_type=item["type"],
                prompt=item["prompt"],
                choices=item.get("choices", []),
                answer=item["answer"],
                explanation=item.get("explanation", item["answer"]),
                difficulty=item["difficulty"],
            )
            for index, item in enumerate(quiz_items, start=1)
        ]

    def _build_chunks(self, module_index: int, lesson: LessonDetail, sections: list[SectionRecord]) -> list[IndexedChunk]:
        chunks: list[IndexedChunk] = []
        for section in sections:
            text_chunks = self._splitter.split_text(section.body)
            for index, excerpt in enumerate(text_chunks, start=1):
                chunks.append(
                    IndexedChunk(
                        chunk_id=f"{lesson.slug}:{section.source_id}:{index}",
                        title=section.heading,
                        source_kind="document",
                        source_title=section.source_title,
                        excerpt=excerpt,
                        lesson_slug=lesson.slug,
                        score_boost=float(module_index),
                    )
                )
        if lesson.video_asset:
            for chapter in lesson.chapters:
                chunks.append(
                    IndexedChunk(
                        chunk_id=f"{lesson.slug}:{lesson.video_asset.id}:{chapter.id}",
                        title=chapter.title,
                        source_kind="video",
                        source_title=lesson.video_asset.title,
                        excerpt=chapter.summary,
                        lesson_slug=lesson.slug,
                        score_boost=float(module_index) + 0.2,
                        timestamp_label=_format_timestamp(chapter.timestamp_start),
                    )
                )
        if not chunks:
            chunks.extend(self._build_authored_lesson_chunks(module_index, lesson))
        return chunks

    def _build_authored_lesson_chunks(self, module_index: int, lesson: LessonDetail) -> list[IndexedChunk]:
        authored_parts = [
            lesson.summary,
            "\n".join(f"Key idea: {idea}" for idea in lesson.key_ideas),
            "\n".join(f"Key note: {note}" for note in lesson.key_notes),
            "\n".join(f"Formula or diagram prompt: {formula}" for formula in lesson.formulas),
            "\n".join(f"Learner question: {question}" for question in lesson.learner_questions),
        ]
        authored_text = "\n\n".join(part for part in authored_parts if part)
        if not authored_text:
            return []
        return [
            IndexedChunk(
                chunk_id=f"{lesson.slug}:lesson-authored:{index}",
                title=lesson.title,
                source_kind="lesson",
                source_title=lesson.title,
                excerpt=excerpt,
                lesson_slug=lesson.slug,
                score_boost=float(module_index) + 0.1,
            )
            for index, excerpt in enumerate(self._splitter.split_text(authored_text), start=1)
        ]

    def search(self, query: str, lesson_slug: str | None = None, top_k: int = 8) -> list[SearchResult]:
        query_terms = {token for token in _tokenize(query) if token}
        raw_query = query.strip().lower()
        if not raw_query:
            return []
        results: list[SearchResult] = []
        for chunk in self.chunks:
            if lesson_slug and chunk.lesson_slug != lesson_slug:
                continue
            title_text = chunk.title.lower()
            excerpt_text = chunk.excerpt.lower()
            title_overlap = sum(1 for term in query_terms if term in title_text)
            excerpt_overlap = sum(1 for term in query_terms if term in excerpt_text)
            phrase_bonus = 0
            if len(raw_query) >= 3:
                phrase_bonus = 4 if raw_query in title_text else 2 if raw_query in excerpt_text else 0
            if title_overlap == 0 and excerpt_overlap == 0 and phrase_bonus == 0:
                continue
            score = title_overlap * 3 + excerpt_overlap * 2 + phrase_bonus + chunk.score_boost
            results.append(
                SearchResult(
                    chunk_id=chunk.chunk_id,
                    title=chunk.title,
                    source_kind=chunk.source_kind,
                    source_title=chunk.source_title,
                    excerpt=chunk.excerpt,
                    lesson_slug=chunk.lesson_slug,
                    score=round(score, 3),
                    timestamp_label=chunk.timestamp_label,
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]

    def _populate_related_lessons(self, lessons: dict[str, LessonDetail]) -> None:
        lesson_topics = {slug: self._lesson_topics(lesson) for slug, lesson in lessons.items()}
        lesson_asset_ids = {slug: {asset.id for asset in lesson.source_assets} for slug, lesson in lessons.items()}
        for lesson_slug, lesson in lessons.items():
            ranked: list[tuple[int, RelatedLessonSummary]] = []
            for candidate_slug, candidate in lessons.items():
                if candidate_slug == lesson_slug:
                    continue
                shared_topics = sorted(lesson_topics[lesson_slug] & lesson_topics[candidate_slug])
                shared_assets = sorted(lesson_asset_ids[lesson_slug] & lesson_asset_ids[candidate_slug])
                score = (len(shared_topics) * 3) + (len(shared_assets) * 2)
                if score <= 0:
                    continue
                ranked.append(
                    (
                        score,
                        RelatedLessonSummary(
                            slug=candidate.slug,
                            title=candidate.title,
                            summary=candidate.summary,
                            module_slug=candidate.module_slug,
                            reason=self._related_reason(shared_topics, shared_assets),
                        ),
                    )
                )
            ranked.sort(key=lambda item: (item[0], item[1].title), reverse=True)
            lesson.related_lessons = [item for _, item in ranked[:3]]

    def _lesson_topics(self, lesson: LessonDetail) -> set[str]:
        topics: set[str] = set()
        for section in lesson.sections:
            topics.update(section.topics)
        derived = self._derive_topics(
            lesson.title,
            " ".join([lesson.summary, *lesson.key_ideas, *lesson.key_notes, *lesson.learner_questions]),
        )
        topics.update(derived)
        return topics

    def _related_reason(self, shared_topics: list[str], shared_assets: list[str]) -> str:
        if shared_topics:
            return f"Shares core themes in {', '.join(shared_topics[:3])}."
        if shared_assets:
            return "Draws on overlapping source material from the local QC+AI corpus."
        return "Connects through adjacent QC+AI systems concepts."


def _tokenize(text: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return [token for token in cleaned.split() if len(token) > 2]


def _format_timestamp(seconds: int) -> str:
    minutes, secs = divmod(seconds, 60)
    return f"{minutes:02d}:{secs:02d}"
