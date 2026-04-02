from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import Settings
from app.core.source_assets import source_asset_id
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
from app.services.text_utils import lead_sentence, truncate_display_excerpt
from app.services.transcripts import load_video_chapters


DOCUMENT_TITLE_MAP = {
    "Analyzing Quantum Computing and AI Paper 2025.docx": "Ali, Chicano, and Moraglio (Eds.), QC+AI 2025 Proceedings",
    "Quantum Computing AI Research Synthesis 2026.docx": "Ali, Chicano, and Moraglio (Eds.), QC+AI 2026 Proceedings",
    "Quantum Computing and Artificial Intelligence Industry Use Cases.docx": "Raj et al. (Eds.), Quantum Computing and Artificial Intelligence: The Industry Use Cases",
    "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx": "Routing, Graph Shrinking, and Logistics under Hardware Constraints",
    "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.docx": "Quantum Vision, GNN, and Few-Shot Hybrid Architectures",
    "Module4_Expressive Bottlenecks Compression, Language, and Explanation.docx": "Expressive Bottlenecks: Compression, Language, and Explanation",
    "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx": "Introduction to Hardware-Constrained QC+AI",
    "Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.docx": "Hardware-Constrained QC+AI Models",
    "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx": "Intermediate Quantum Programming for Hardware-Constrained QC+AI",
    "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx": "Advanced Quantum Software Development for Hardware-Constrained QC+AI",
    "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx": "Quantum Finance Programming and Optimization for Hardware-Constrained QC+AI",
}

ASSET_TITLE_MAP = {
    **DOCUMENT_TITLE_MAP,
    "Quantum Computing and Artificial Intelligence 2025.mp4": "Quantum Computing and Artificial Intelligence 2025",
    "Quantum Computing and Artificial Intelligence 2026.mp4": "Quantum Computing and Artificial Intelligence 2026",
    "Industry Use Cases.mp4": "Industry Use Cases",
    "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.mp4": "Routing, Graph Shrinking, and Logistics under Hardware Constraints",
    "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.mp4": "Quantum Vision, GNN, and Few-Shot Hybrid Architectures",
    "Module4_Expressive Bottlenecks Compression, Language, and Explanation.mp4": "Expressive Bottlenecks: Compression, Language, and Explanation",
    "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4": "Introduction to Hardware-Constrained QC+AI",
    "The Hardware-First Imperative in Quantum Machine LearningHardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.mp4": "Hardware-Constrained QC+AI Models",
    "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4": "Intermediate Quantum Programming for Hardware-Constrained QC+AI",
    "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4": "Advanced Quantum Software Development for Hardware-Constrained QC+AI",
    "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4": "Quantum Finance Programming and Optimization for Hardware-Constrained QC+AI",
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
    document_file: str | None = None,
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
        "document_file": document_file,
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
            "Dimensionality Reduction: Learning-Based Graph Shrinking",
            "Dynamic Penalty Tuning via Soft Actor-Critic (SAC)",
            "Overcoming Topological Constraints through Nested Qubit Routing",
        ],
        "lesson": _lesson_blueprint(
            slug="ai4qc-routing-and-optimization",
            title="Routing, Graph Shrinking, and Logistics under Hardware Constraints",
            summary="Connects logistics QUBO reformulation, learning-based graph shrinking, SAC-tuned augmented Lagrangian methods, and nested routing into a single hardware-aware quantum logistics pipeline.",
            key_ideas=[
                "Quantum logistics becomes tractable only after classical preprocessing compresses the instance while preserving feasibility.",
                "Graph shrinking is modeled as an MDP with a GNN policy so the reduced graph still respects combinatorial constraints.",
                "Routing remains a physical compilation bottleneck even after reformulation, so post-routing depth control still decides executable value.",
            ],
            key_notes=[
                "Q-ALM removes slack-variable blow-up, but poor penalty tuning can still produce infeasible routes or barren optimization landscapes.",
                "The lesson treats hybrid quantum logistics as a full systems stack spanning preprocessing, optimization, routing, colocation, and thermal management.",
            ],
            formulas=[
                "Quadratic Unconstrained Binary Optimization objective: x^T Q x.",
                "Augmented Lagrangian objective: L_rho(x, lambda) = f(x) + lambda^T c(x) + (rho / 2) ||c(x)||^2.",
            ],
            learner_questions=[
                "Why does learning-based graph shrinking matter before any quantum solve?",
                "What problem does SAC solve inside the augmented Lagrangian workflow?",
                "Why can nested qubit routing still dominate runtime after the optimization model is compressed?",
            ],
            section_refs=[
                "The Mathematical Complexity of Supply Chain Logistics",
                "Dimensionality Reduction: Learning-Based Graph Shrinking",
                "The Markov Decision Process Formulation",
                "Graph Neural Network Policy Encoding",
                "The Hybrid Optimization Framework: Augmented Lagrangian Methods",
                "Dynamic Penalty Tuning via Soft Actor-Critic (SAC)",
                "Overcoming Topological Constraints through Nested Qubit Routing",
                "The Nested Monte Carlo Search Architecture",
                "Performance Analytics and Post-Routing Transpilation",
            ],
            video_file="Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.mp4",
            document_file="Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx",
        ),
        "flashcards": [
            ("intro", "Why use graph shrinking before quantum optimization in logistics?", "It compresses the problem graph into a smaller constraint-preserving core that fits limited qubit resources."),
            ("intermediate", "What does the GNN policy learn in the graph-shrinking pipeline?", "It scores merge actions so the reduced graph preserves combinatorial structure and downstream feasibility."),
            ("advanced", "Why is SAC useful inside RL-Q-ALM?", "It adaptively tunes penalty parameters so constrained logistics subproblems stay feasible without flattening the optimization landscape."),
        ],
        "quiz": [
            {
                "type": "short-answer",
                "prompt": "Explain why quantum logistics needs both problem reduction before execution and routing control during compilation.",
                "answer": "Problem reduction keeps the logistics instance within limited qubit budgets while preserving constraints, and routing control limits the extra SWAPs and depth inflation introduced by sparse hardware connectivity.",
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
            "Quantum Vision Transformers: Overcoming Quadratic Attention Bottlenecks",
            "Quantum Graph Neural Networks: Relational Data in Hilbert Space",
            "The Generative Shift: Quantum Diffusion Models for Few-Shot Learning",
            "Ultra Parameter-Efficient Biomedical Image Analysis",
            "Hardware-Software Co-Design and Orchestration in the NISQ Era",
        ],
        "lessons": [
            _lesson_blueprint(
                slug="hybrid-applications-healthcare-vision",
                title="Quantum Vision, GNN, and Few-Shot Hybrid Architectures",
                summary="Grounds Module 3 in the authored source by tracing how QViTs, QGNNs, conditioned quantum diffusion, and NISQ orchestration keep the quantum stage narrow, data-efficient, and explicitly hardware-bounded.",
                key_ideas=[
                    "QViTs attack quadratic attention pressure by moving patch or latent interactions through a compact quantum bottleneck instead of replacing the entire perception stack.",
                    "QGNN and jet-tagging architectures stay credible when they preserve classical message passing, use the quantum layer selectively, and justify the parameter-efficiency tradeoff.",
                    "Few-shot quantum diffusion only becomes operationally meaningful when label conditioning, low-data gains, and orchestration overhead are evaluated together rather than as isolated novelty claims.",
                ],
                key_notes=[
                    "The Module 3 source repeatedly treats the quantum component as a bounded representational or decision stage embedded inside a larger classical pipeline.",
                    "Biomedical imaging, jet tagging, and few-shot generation all remain constrained by decoherence, bandwidth, and orchestration limits, so hardware-software co-design is part of the lesson rather than a deployment footnote.",
                ],
                formulas=[
                    "Hybrid attention, graph-message-passing, and diffusion-pipeline diagrams should make the quantum bottleneck explicit relative to classical preprocessing, conditioning, and decoding.",
                    "Conditioned diffusion should be framed as a forward corruption process plus a learned reverse denoising process with class guidance carried through ancilla or conditioning channels.",
                ],
                learner_questions=[
                    "Why does the authored Module 3 document keep returning to the quantum bottleneck instead of claiming end-to-end quantum perception?",
                    "What do QViT, QC-GCN jet tagging, and conditioned quantum diffusion gain from extreme parameter efficiency or low-data performance?",
                    "Why do orchestration latency, decoherence, and explainability constraints still limit how these hybrid vision and graph systems should be deployed?",
                ],
                section_refs=[
                    "Quantum Vision Transformers: Overcoming Quadratic Attention Bottlenecks",
                    "Ultra Parameter-Efficient Biomedical Image Analysis",
                    "Quantum Graph Neural Networks: Relational Data in Hilbert Space",
                    "Extreme Parameter Efficiency in Jet Tagging",
                    "QGShap: Exact Interpretability via Quantum Amplitude Amplification",
                    "The Generative Shift: Quantum Diffusion Models for Few-Shot Learning",
                    "The Architecture of Conditioned Quantum Diffusion Models (CQDDs)",
                    "Empirical Superiority in Low-Data Regimes",
                    "Hardware-Software Co-Design and Orchestration in the NISQ Era",
                    "High-Bandwidth Quantum-Classical Orchestration",
                ],
                video_file="Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.mp4",
                document_file="Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.docx",
                flashcards=[
                    ("intro", "What placement pattern dominates the authored Module 3 hybrid architectures?", "A narrow quantum bottleneck or conditioned subroutine inside a larger classical vision, graph, or diffusion pipeline."),
                    ("intermediate", "Why are the QViT and QC-GCN jet-tagging examples useful teaching cases?", "They show how a bounded quantum stage can trade off attention or relational expressivity against parameter count without pretending to replace the surrounding classical model."),
                    ("advanced", "Why does the Module 3 few-shot diffusion material emphasize conditioning and orchestration together?", "Because low-data gains alone are not enough; the hybrid system still has to manage class guidance, sampling overhead, decoherence, and classical-quantum coordination costs."),
                ],
                quiz=[
                    {
                        "type": "mcq",
                        "prompt": "Which architectural pattern best matches the authored Module 3 vision, graph, and few-shot cases?",
                        "choices": [
                            "Replace all classical layers with a quantum circuit",
                            "Use the quantum component as a targeted representational or decision bottleneck",
                            "Avoid any classical preprocessing",
                            "Assume hardware constraints are secondary once a kernel is used",
                        ],
                        "answer": "Use the quantum component as a targeted representational or decision bottleneck",
                        "difficulty": "intermediate",
                        "explanation": "The Module 3 applications preserve substantial classical structure around a focused quantum subroutine and keep hardware limits in view.",
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
        "summary": "Explores expressive bottlenecks across graph reasoning, generative modeling, language systems, and explainability before grounding quINR, quantum contrastive embeddings, and quantum-accelerated attribution in the authored Module 4 source.",
        "learning_goals": [
            "Understand why expressive bottlenecks are structural limits rather than mere parameter shortages.",
            "Explain how the authored Module 4 source connects compression, language adaptation, and retrieval to quantum representational capacity.",
            "Interpret quantum explainability claims as targeted accelerations that still depend on strong structural assumptions.",
        ],
        "source_highlights": [
            "The Theoretical Paradigm of Expressive Bottlenecks",
            "Quantum Implicit Neural Compression",
            "Quantum Contrastive Word Embeddings",
            "Overcoming the Explainability Bottleneck with Quantum Acceleration",
        ],
        "lesson": _lesson_blueprint(
            slug="representation-language-and-xai",
            title="Expressive Bottlenecks: Compression, Language, and Explanation",
            summary="Grounds Module 4 in the authored source by tracing how expressive bottlenecks emerge in graph, generative, and language systems before using quINR, quantum contrastive embeddings, and quantum-accelerated explainability as targeted responses.",
            key_ideas=[
                "Expressive bottlenecks are framed as structural limits in aggregation, dimensionality, adaptation, and retrieval that cannot be repaired reliably by naive parameter scaling alone.",
                "The authored document treats the quantum shift as a change in representational geometry, using Hilbert-space structure to argue for denser compression and richer semantic encoding.",
                "Explainability remains combinatorially hard even after better representations, so quantum amplitude amplification is presented as a narrow acceleration mechanism rather than a universal interpretability cure.",
            ],
            key_notes=[
                "Module 4 links compression, language, and explanation to the broader energy and hardware costs of classical scaling, so the quantum argument is partly architectural and partly thermodynamic.",
                "quINR, quantum contrastive embeddings, and explainability acceleration are all taught as bounded hybrid interventions with explicit assumptions about encoding, task structure, and execution cost.",
            ],
            formulas=[
                "Folded-angle embedding as a compact way to pack continuous coordinates into limited qubits for hybrid implicit neural compression.",
                "Logit-fidelity mapping to bridge bounded quantum fidelity with contrastive semantic objectives in quantum word embedding models.",
                "Amplitude amplification as the core quantum subroutine used to narrow the search cost of exact attribution over combinatorial explanation spaces.",
            ],
            learner_questions=[
                "Why does the authored Module 4 source define expressive bottlenecks as structural failures rather than simple under-parameterization?",
                "What do quINR and quantum contrastive word embeddings gain by changing the representational geometry instead of only scaling classical models?",
                "Why should quantum explainability methods still be taught with strong caveats about graph structure, attribution cost, and deployment assumptions?",
            ],
            section_refs=[
                "The Theoretical Paradigm of Expressive Bottlenecks",
                "Topological and Structural Bottlenecks in Graph Neural Networks",
                "Breaking Generative and Spatial Constraints",
                "Navigating Parameter, Adaptation, and Retrieval Bottlenecks in Language Models",
                "The Quantum Paradigm Shift: Redefining Computational Expressivity",
                "Quantum Implicit Neural Compression",
                "Quantum Contrastive Word Embeddings",
                "Overcoming the Explainability Bottleneck with Quantum Acceleration",
                "The Energetic Horizon and Future Outlook",
            ],
            video_file="Module4_Expressive Bottlenecks Compression, Language, and Explanation.mp4",
            document_file="Module4_Expressive Bottlenecks Compression, Language, and Explanation.docx",
        ),
        "flashcards": [
            ("intro", "What is an expressive bottleneck in the authored Module 4 source?", "A structural limit in a model's architecture, aggregation, or dimensionality that restricts the hypotheses it can represent or learn."),
            ("intermediate", "Why is quantum contrastive word embedding not just a quantum Word2Vec clone?", "Because the model has to translate classical contrastive objectives into bounded quantum fidelity scores through an additional logit-fidelity mapping."),
            ("advanced", "Why is the quantum explainability section taught cautiously?", "Because amplitude amplification only accelerates a narrowly structured attribution problem and does not remove the modeling assumptions or accountability burden around explanations."),
        ],
        "quiz": [
            {
                "type": "short-answer",
                "prompt": "Explain how the authored Module 4 document connects expressive bottlenecks across compression, language, and explanation.",
                "answer": "The document argues that all three areas face structural representational limits: compression loses high-frequency detail under tight parameter budgets, language models hit adaptation and retrieval bottlenecks, and explanation scales combinatorially. It then presents quantum methods as narrowly targeted ways to change the representational space or accelerate constrained search rather than as blanket replacements for classical systems.",
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
    {
        "slug": "hardware-constrained-introduction",
        "title": "Introduction to Hardware-Constrained Learning",
        "summary": "Introduces the hardware-first worldview for QC+AI, emphasizing noise, shot budgets, trainability, and the collapse of simulator-first intuition on real NISQ systems.",
        "learning_goals": [
            "Explain why hardware-constrained learning replaces simulator-first reasoning in near-term QC+AI.",
            "Identify the main physical limits that reshape learning design on NISQ hardware.",
            "Recognize the major failure modes that invalidate naive quantum-learning claims.",
        ],
        "source_highlights": [
            "Why Hardware-Constrained Learning",
            "Hardware Constraints That Shape Learning",
            "Practical Design Workflow",
            "Failure Modes & Diagnostics",
        ],
        "lesson": _lesson_blueprint(
            slug="introduction-to-hardware-constrained-learning",
            title="Why Hardware-Constrained Learning Replaces Simulator-First Thinking",
            summary="Uses the introduction document to frame QC+AI as a hardware-bounded systems discipline in which noise, depth, shot cost, and deployment realism set the design space.",
            key_ideas=[
                "The promise of QC+AI depends on hardware-aware design, not on importing idealized fault-tolerant assumptions into NISQ practice.",
                "Noise-induced barren plateaus, finite sampling, and cloud-execution costs are first-order design parameters rather than implementation details.",
                "Credible near-term models live in a narrow Goldilocks zone between expressivity and trainability.",
            ],
            key_notes=[
                "Benchmarking against strong classical baselines is mandatory because classical models still dominate most standard tasks.",
                "Quantum error mitigation can recover signal, but it shifts cost into sampling overhead rather than eliminating physical limits.",
            ],
            formulas=[
                "Use a hardware budget table covering coherence time, gate error, topology, and shot cost before choosing a learning architecture.",
            ],
            learner_questions=[
                "Why does simulator-first reasoning break down on deployed NISQ hardware?",
                "What makes noise and shot budgets architectural parameters instead of mere runtime annoyances?",
                "How should a practitioner recognize when a QC+AI claim is outside the near-term Goldilocks regime?",
            ],
            section_refs=[
                "Why Hardware-Constrained Learning",
                "Hardware Constraints That Shape Learning",
                "Practical Design Workflow",
                "Failure Modes & Diagnostics",
                "Risks & Mitigations",
            ],
            video_file="Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
        ),
        "flashcards": [
            ("intro", "What does hardware-constrained learning mean in this course?", "It means designing QC+AI models around the real limits of the target quantum hardware rather than assuming ideal qubits and unlimited depth."),
            ("intermediate", "Why are barren plateaus so damaging in the NISQ era?", "Because hardware noise and overly expressive circuits can flatten gradients until training becomes statistically impossible."),
            ("advanced", "Why is error mitigation not a free escape hatch?", "Because it often trades gate noise for an exponential or near-exponential growth in measurement cost and latency."),
        ],
        "quiz": [
            {
                "type": "mcq",
                "prompt": "Which statement best matches the introduction document?",
                "choices": [
                    "Hardware limits matter only after a theoretically optimal model is designed.",
                    "Near-term QC+AI should be built from the assumption of fault-tolerant logical qubits.",
                    "Noise, topology, and shot cost are architectural constraints that must shape the learning design from the start.",
                    "Classical baselines are less important once entanglement is present in a model.",
                ],
                "answer": "Noise, topology, and shot cost are architectural constraints that must shape the learning design from the start.",
                "difficulty": "intro",
                "explanation": "The introduction document treats hardware realism as the condition for any defensible near-term QC+AI claim.",
            }
        ],
    },
    {
        "slug": "hardware-constrained-models",
        "title": "Hardware-Constrained QC+AI Models",
        "summary": "Compares VQCs, quantum kernels, continuous-variable models, and validation criteria through the lens of trainability, concentration, reachability, and measurable acceptance gates.",
        "learning_goals": [
            "Compare the main near-term QC+AI model families under explicit hardware limits.",
            "Explain how trainability barriers differ across VQCs, kernels, and CV systems.",
            "Apply acceptance criteria and test strategy thinking before claiming model utility.",
        ],
        "source_highlights": [
            "Why Hardware-Constrained Learning Matters",
            "Constraint Landscape",
            "Methods Deep Dive",
            "Acceptance Criteria (Measurable)",
            "Test Strategy",
        ],
        "lesson": _lesson_blueprint(
            slug="hardware-constrained-qcai-models",
            title="Trainability, Kernels, and Validation in QC+AI Models",
            summary="Builds a model-selection lens for QC+AI by comparing VQCs, kernels, and CV-QNNs against real trainability limits, baseline pressure, and validation rigor.",
            key_ideas=[
                "VQCs fail when depth and noise drive gradients into barren plateaus, but shallow circuits can also fail through reachability deficits.",
                "Quantum kernels become useless when concentration collapses the Gram matrix into an identity-like object.",
                "Acceptance criteria and test strategy belong inside model design, not only in a later evaluation phase.",
            ],
            key_notes=[
                "The most viable near-term pattern remains asymmetric hybridization: heavy classical preprocessing feeding a small quantum head or kernel stage.",
                "Validation must separate genuine quantum contribution from classical surrogate effects and noisy benchmarking artifacts.",
            ],
            formulas=[
                "Compare candidate models with a trade-off table covering expressivity, trainability, shot cost, and baseline competitiveness.",
            ],
            learner_questions=[
                "Why can shallow circuits be too weak even when deep circuits are untrainable?",
                "What makes quantum kernel concentration such a serious failure mode?",
                "How do acceptance criteria change the way a practitioner chooses between model families?",
            ],
            section_refs=[
                "Why Hardware-Constrained Learning Matters",
                "Constraint Landscape",
                "Methods Deep Dive",
                "Acceptance Criteria",
                "Test Strategy",
            ],
            video_file="The Hardware-First Imperative in Quantum Machine LearningHardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.mp4",
        ),
        "flashcards": [
            ("intro", "What is the reachability deficit?", "It is the failure of a shallow quantum model to contain the true useful solution within the limited state space it can physically explore."),
            ("intermediate", "What happens when a quantum kernel concentrates exponentially?", "The off-diagonal similarity structure disappears and the resulting kernel matrix stops carrying useful relational information."),
            ("advanced", "Why are acceptance criteria part of model design?", "Because a model is not credible unless it can be benchmarked, stress-tested, and shown to outperform or justify itself against strong classical alternatives."),
        ],
        "quiz": [
            {
                "type": "short-answer",
                "prompt": "Explain why model-family selection in QC+AI must be driven by both trainability limits and measurable acceptance criteria.",
                "answer": "Different QC+AI model families fail in different ways under NISQ constraints, so selection must account for gradient behavior, kernel concentration, hardware cost, and explicit validation gates that compare performance against strong classical baselines.",
                "difficulty": "advanced",
            }
        ],
    },
    {
        "slug": "intermediate-quantum-programming",
        "title": "Intermediate Quantum Programming",
        "summary": "Covers the device-first programming patterns that make NISQ learning executable, including parameter-shift differentiation, shot allocation, measurement grouping, error-mitigation hooks, and benchmarking discipline.",
        "learning_goals": [
            "Use device-first programming patterns instead of simulator-only habits.",
            "Explain how gradient estimation, shot scheduling, and measurement grouping affect practical runtime.",
            "Build debugging and benchmarking habits that survive the jump from simulation to hardware.",
        ],
        "source_highlights": [
            "Hardware Constraints to Design Implications",
            "Intermediate Programming Patterns",
            "Hardware-Constrained Learning Approaches",
            "Diagnostics & Debugging Playbook",
            "Test Strategy",
        ],
        "lesson": _lesson_blueprint(
            slug="intermediate-quantum-programming-patterns",
            title="Device-First Programming Patterns for NISQ Learning",
            summary="Turns the intermediate programming brief into a practical programming lens for PSR-based gradients, shot-frugal scheduling, grouped measurements, and differentiable mitigation hooks.",
            key_ideas=[
                "Finite-difference habits from classical ML fail badly under shot noise; parameter-shift and shot-frugal methods are essential on real hardware.",
                "Measurement grouping and adaptive shot allocation are not optimizations at the margin; they are required to control execution cost and variance.",
                "Diagnostics and benchmarking must track transpilation overhead, mitigation cost, and real resource use alongside predictive performance.",
            ],
            key_notes=[
                "Data re-uploading is a practical way to grow expressivity without assuming more qubits than the device can support.",
                "Error mitigation must be wired into the training loop carefully so it improves usable signal without destroying the computational graph or cost budget.",
            ],
            formulas=[
                "Use a resource ledger that tracks shots, transpilation depth multiplier, mitigation passes, and queue latency per experiment.",
            ],
            learner_questions=[
                "Why is the parameter-shift rule more robust than finite differences on noisy hardware?",
                "How do measurement grouping and adaptive shot allocation change real execution budgets?",
                "What should a programmer log to distinguish model failure from hardware failure?",
            ],
            section_refs=[
                "Hardware Constraints",
                "Intermediate Programming Patterns",
                "Hardware-Constrained Learning Approaches",
                "Diagnostics & Debugging Playbook",
                "Acceptance Criteria",
                "Test Strategy",
            ],
            video_file="Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
        ),
        "flashcards": [
            ("intro", "Why is finite-difference differentiation a poor default on NISQ hardware?", "Because shot noise makes tiny perturbation-based gradient estimates unstable and expensive."),
            ("intermediate", "What does qubit-wise commutativity measurement grouping accomplish?", "It lets mutually commuting Pauli terms be measured together so the total number of circuit executions drops sharply."),
            ("advanced", "Why is benchmarking more than predictive accuracy in this programming layer?", "Because fair QC+AI evaluation must also include transpilation cost, mitigation overhead, shot count, and queue latency."),
        ],
        "quiz": [
            {
                "type": "mcq",
                "prompt": "Which pairing best reflects intermediate hardware-constrained programming practice?",
                "choices": [
                    "Deep all-to-all ansatz plus finite differences",
                    "Parameter-shift gradients plus measurement grouping and adaptive shot allocation",
                    "Unlimited shots plus no transpilation accounting",
                    "Simulator-only metrics plus hardware deployment claims",
                ],
                "answer": "Parameter-shift gradients plus measurement grouping and adaptive shot allocation",
                "difficulty": "intermediate",
                "explanation": "The intermediate programming document treats those techniques as core execution patterns rather than optional polish.",
            }
        ],
    },
    {
        "slug": "advanced-quantum-software",
        "title": "Advanced Quantum Software Development",
        "summary": "Moves from circuit programming to software architecture, compiler design, caching, pulse-level control, and reliability engineering for hardware-constrained QC+AI systems.",
        "learning_goals": [
            "Explain how software architecture changes when quantum hardware becomes an asynchronous, failure-prone co-processor.",
            "Connect differentiable programming, MLIR, and pulse-level control to hardware-aware QML execution.",
            "Recognize the reliability, reproducibility, and vendor-abstraction practices needed in advanced QC+AI software.",
        ],
        "source_highlights": [
            "Problem Framing: The Imperative of Hardware-Constrained Learning",
            "Advanced Programming and Software Development Practices",
            "Algorithm-to-Software Mapping",
            "Evaluation & Benchmarking",
            "Acceptance Criteria and Test Strategy",
        ],
        "lesson": _lesson_blueprint(
            slug="advanced-quantum-software-development",
            title="Compilation, MLIR, and Pulse-Level QC+AI Software Systems",
            summary="Reframes hardware-constrained QC+AI as a software-engineering problem that spans differentiable pipelines, compiler dialects, pulse-level control, caching, and reliability instrumentation.",
            key_ideas=[
                "The quantum processor behaves like a fragile asynchronous co-processor, so the software stack must minimize redundant compilation, data transfer, and idle latency.",
                "MLIR-style abstractions and virtualization reduce vendor lock-in while making routing, scheduling, and backend selection more explicit.",
                "Pulse-level control can create real performance gains because reducing interaction time often matters more than preserving a clean logical-gate abstraction.",
            ],
            key_notes=[
                "Caching and dependency-aware invalidation matter because variational loops execute the same circuit topology repeatedly with only parameter updates.",
                "Reliability engineering in QC+AI includes seed management, energy accounting, and calibration-aware execution, not only algorithm selection.",
            ],
            formulas=[
                "Treat wall-clock latency as a sum of compilation, queue, execution, mitigation, and host-side orchestration cost rather than only gate complexity.",
            ],
            learner_questions=[
                "Why does MLIR matter in advanced quantum software development?",
                "What is gained by optimizing at the pulse level instead of staying at the logical-gate level?",
                "How do caching and reproducibility policies affect real hybrid-system reliability?",
            ],
            section_refs=[
                "Problem Framing",
                "Advanced Programming and Software Development Practices",
                "Algorithm-to-Software Mapping",
                "Evaluation & Benchmarking",
                "Acceptance Criteria",
                "Practical Next Steps",
            ],
            video_file="Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
        ),
        "flashcards": [
            ("intro", "What does differentiable programming mean in this QC+AI context?", "It means treating the quantum routine as a differentiable layer inside a larger classical computation graph."),
            ("intermediate", "Why are MLIR dialects useful for QC+AI software?", "They help bridge high-level model code and low-level hardware-aware compilation while preserving optimization opportunities."),
            ("advanced", "Why is pulse-level control a major advanced-software topic?", "Because tuning native pulses can reduce latency and decoherence exposure more effectively than relying only on abstract gate decomposition."),
        ],
        "quiz": [
            {
                "type": "short-answer",
                "prompt": "Describe why advanced QC+AI software engineering must treat compilation, caching, and pulse-level execution as first-class design concerns.",
                "answer": "Real hybrid QC+AI systems repeatedly execute fragile circuits through queueing, transpilation, and calibration-sensitive hardware, so performance and reliability depend as much on software orchestration, reuse, and pulse-level optimization as on the model architecture itself.",
                "difficulty": "advanced",
            }
        ],
    },
    {
        "slug": "quantum-finance-programming",
        "title": "Quantum Finance Programming and Optimization",
        "summary": "Applies hardware-constrained QC+AI to portfolio optimization, option pricing, anomaly detection, and financial model-risk governance under strict NISQ limits.",
        "learning_goals": [
            "Map major quantum-finance workloads onto realistic NISQ-compatible methods.",
            "Explain why hybrid optimization and kernel methods dominate near-term finance use cases.",
            "Evaluate quantum-finance claims through benchmark rigor and model-risk management.",
        ],
        "source_highlights": [
            "Problem Framing: Quantum Finance + Hardware-Constrained Learning",
            "Core Methodological Toolbox",
            "Quantum Finance Targets Mapped to QML Methods",
            "Programming & Implementation Blueprint",
            "Quality Gates: Risks, Acceptance, and Testing",
        ],
        "lesson": _lesson_blueprint(
            slug="quantum-finance-programming-and-optimization",
            title="Risk-Aware Quantum Finance Under Hardware Constraints",
            summary="Uses the quantum-finance document to position portfolio, pricing, anomaly, and credit workflows as hardware-bounded hybrid systems governed by benchmark realism and model-risk controls.",
            key_ideas=[
                "Near-term finance utility comes from hardware-native hybrid workflows, not from fault-tolerant speedup narratives.",
                "Portfolio optimization, option pricing, anomaly detection, and credit tasks each map differently to kernels, VQCs, CV models, or hybrid optimizers.",
                "Production finance requires model-risk management, baseline comparison, and resource accounting at least as much as it requires algorithmic novelty.",
            ],
            key_notes=[
                "Compilation overhead can erase paper-level scaling claims when sparse topologies force large SWAP overheads.",
                "Financial deployment requires explicit acceptance gates because an expensive quantum model that merely matches a classical baseline is operationally unacceptable.",
            ],
            formulas=[
                "Quadratic Unconstrained Binary Optimization objective: x^T Q x.",
                "Compare finance workflows with a matrix covering objective class, encoding choice, constraint handling, and classical baseline.",
            ],
            learner_questions=[
                "Why are hybrid optimization loops so dominant in near-term quantum finance?",
                "How do portfolio optimization and option pricing differ in their hardware fit?",
                "What does model-risk management add to a quantum-finance deployment decision?",
            ],
            section_refs=[
                "Problem Framing",
                "Hardware Constraints That Dominate Outcomes",
                "Core Methodological Toolbox",
                "Quantum Finance Targets Mapped to QML Methods",
                "Programming & Implementation Blueprint",
                "Acceptance Criteria",
            ],
            video_file="Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
        ),
        "flashcards": [
            ("intro", "Why is quantum finance framed as hardware-first in this document?", "Because realistic near-term value depends on noise-aware, shot-frugal, topology-aware hybrid workflows rather than on fault-tolerant assumptions."),
            ("intermediate", "What makes quantum kernels attractive in some finance settings?", "They can express high-dimensional similarity structure while keeping the classical optimizer in control of the actual decision boundary."),
            ("advanced", "Why is model-risk management central to quantum finance adoption?", "Because hardware drift, sampling variance, opacity, and cost can all create deployment failures even if a prototype looks promising in simulation."),
        ],
        "quiz": [
            {
                "type": "mcq",
                "prompt": "Which statement best matches the quantum-finance document?",
                "choices": [
                    "Near-term finance advantage should be evaluated mainly through theoretical asymptotic speedup claims.",
                    "The quantum processor usually acts as a narrow co-processor inside a larger classical optimization and risk workflow.",
                    "Compilation overhead is largely irrelevant once a quantum model is expressive enough.",
                    "Model-risk management is less important in finance than in healthcare because finance tolerates more noise.",
                ],
                "answer": "The quantum processor usually acts as a narrow co-processor inside a larger classical optimization and risk workflow.",
                "difficulty": "intermediate",
                "explanation": "The finance document repeatedly frames the classical optimizer and risk workflow as the dominant system, with the quantum stage acting as a bounded specialist component.",
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
                matched_sections = self._match_sections(
                    sections,
                    lesson_blueprint["section_refs"],
                    lesson_blueprint.get("document_file"),
                )
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
                    source_assets=self._collect_source_assets(
                        assets,
                        matched_sections,
                        lesson_blueprint["video_file"],
                        lesson_blueprint.get("document_file"),
                    ),
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
            summary="An expanded interactive course grounded in the local QC+AI proceedings, hardware-constrained learning briefs, finance-focused methodology, and industry-use-case analysis, framed through NISQ realism, practical programming, and systems constraints.",
            modules=modules,
            source_assets=assets,
        )
        self.modules = {module.slug: module for module in modules}
        self._populate_related_lessons(lessons)
        self.lessons = lessons
        self.chunks = chunks

    def _build_source_asset(self, path: Path, kind: str) -> SourceAsset:
        asset_id = source_asset_id(path.name, kind)
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

    def _match_sections(
        self,
        sections: list[SectionRecord],
        refs: list[str],
        document_file: str | None = None,
    ) -> list[SectionRecord]:
        if not refs:
            return []
        document_source_id = None
        if document_file:
            document_source_id = Path(document_file).stem.lower().replace(" ", "-")
        matched: list[SectionRecord] = []
        used_keys: set[str] = set()
        for ref in refs:
            ref_l = ref.lower()
            for section in sections:
                if document_source_id and section.source_id != document_source_id:
                    continue
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
            excerpt = truncate_display_excerpt(section.body, 560)
            summary = lead_sentence(section.body, 220)
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

    def _collect_source_assets(
        self,
        assets: list[SourceAsset],
        sections: list[SectionRecord],
        video_file: str | None,
        document_file: str | None = None,
    ) -> list[SourceAsset]:
        source_titles = {section.source_title for section in sections}
        selected = [asset for asset in assets if asset.title in source_titles]
        if document_file:
            selected.extend(asset for asset in assets if asset.filename == document_file)
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
                    excerpt=truncate_display_excerpt(chunk.excerpt, 320),
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
