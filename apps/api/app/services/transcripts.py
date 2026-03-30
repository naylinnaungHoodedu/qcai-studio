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
    "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4": [
        VideoChapter(
            id="hcl-intro-problem",
            title="Why Hardware-Constrained Learning",
            timestamp_start=0,
            timestamp_end=96,
            summary="Frames the course around the failure of simulator-first intuition on near-term quantum hardware.",
            transcript_excerpt="The opening argues that realistic QC+AI work starts from hardware limits, not from idealized circuit abstractions.",
        ),
        VideoChapter(
            id="hcl-intro-constraints",
            title="Physical Constraints That Shape Learning",
            timestamp_start=96,
            timestamp_end=240,
            summary="Covers noise, shallow depth, topology, shot budgets, and queueing as first-order learning constraints.",
            transcript_excerpt="Noise, limited coherence, and finite shots are treated as design inputs rather than downstream annoyances.",
        ),
        VideoChapter(
            id="hcl-intro-goldilocks",
            title="Trainability and the Goldilocks Regime",
            timestamp_start=240,
            timestamp_end=372,
            summary="Explains why near-term QC+AI models must balance expressivity against trainability under real-device limits.",
            transcript_excerpt="The middle section emphasizes that useful models live in a narrow region between underpowered shallow circuits and untrainable deep ones.",
        ),
        VideoChapter(
            id="hcl-intro-workflow",
            title="Hardware-First Design Workflow",
            timestamp_start=372,
            timestamp_end=522,
            summary="Builds a practical workflow for choosing model families from hardware budgets, baseline pressure, and validation needs.",
            transcript_excerpt="The presenter turns hardware realism into a concrete design checklist spanning budgets, baselines, and mitigation cost.",
        ),
        VideoChapter(
            id="hcl-intro-risks",
            title="Failure Modes and Acceptance Gates",
            timestamp_start=522,
            timestamp_end=684,
            summary="Closes with diagnostic patterns, benchmark discipline, and the conditions required for a believable QC+AI claim.",
            transcript_excerpt="The ending shifts from optimism to evidence, stressing diagnostics, baselines, and explicit acceptance criteria.",
        ),
    ],
    "The Hardware-First Imperative in Quantum Machine LearningHardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.mp4": [
        VideoChapter(
            id="hcl-models-landscape",
            title="Constraint Landscape Across Model Families",
            timestamp_start=0,
            timestamp_end=84,
            summary="Introduces VQCs, kernels, and continuous-variable models through the lens of hardware-bounded feasibility.",
            transcript_excerpt="The lecture opens by comparing model families only after imposing realistic device limits on depth, connectivity, and measurement cost.",
        ),
        VideoChapter(
            id="hcl-models-vqc",
            title="VQCs and Barren Plateaus",
            timestamp_start=84,
            timestamp_end=182,
            summary="Explains why expressive variational circuits can become effectively untrainable under noise and depth growth.",
            transcript_excerpt="Variational expressivity is treated as dangerous when it pushes gradients into noise-dominated barren regimes.",
        ),
        VideoChapter(
            id="hcl-models-kernels",
            title="Kernel Concentration and Reachability",
            timestamp_start=182,
            timestamp_end=282,
            summary="Covers the twin risks of kernel concentration and shallow-model reachability deficits.",
            transcript_excerpt="The talk warns that both overly rich and overly weak models can fail, just in different statistical ways.",
        ),
        VideoChapter(
            id="hcl-models-validation",
            title="Acceptance Criteria and Test Strategy",
            timestamp_start=282,
            timestamp_end=380,
            summary="Turns validation into a design-time concern with benchmark gates, ablations, and baseline discipline.",
            transcript_excerpt="Selection is framed as inseparable from the tests that would later justify claiming quantum utility.",
        ),
        VideoChapter(
            id="hcl-models-decision",
            title="Choosing a Defensible QC+AI Model",
            timestamp_start=380,
            timestamp_end=467,
            summary="Closes with decision heuristics for picking model families under trainability, cost, and evidence constraints.",
            transcript_excerpt="The conclusion argues that credible QC+AI modeling is mostly about rejecting unjustified complexity early.",
        ),
    ],
    "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4": [
        VideoChapter(
            id="hcl-programming-device-first",
            title="Device-First Programming Mindset",
            timestamp_start=0,
            timestamp_end=92,
            summary="Reorients programming around the execution realities of cloud quantum hardware rather than simulator convenience.",
            transcript_excerpt="The lecture starts by replacing simulator habits with an execution model dominated by queueing, calibration, and sampling cost.",
        ),
        VideoChapter(
            id="hcl-programming-gradients",
            title="Parameter-Shift and Gradient Estimation",
            timestamp_start=92,
            timestamp_end=206,
            summary="Explains why parameter-shift methods are more stable than naive finite differences on shot-noisy devices.",
            transcript_excerpt="Gradient estimation is presented as a hardware problem because sampling variance directly shapes training viability.",
        ),
        VideoChapter(
            id="hcl-programming-measurements",
            title="Shot Allocation and Measurement Grouping",
            timestamp_start=206,
            timestamp_end=318,
            summary="Shows how commuting-term grouping and adaptive shot allocation reduce runtime and variance.",
            transcript_excerpt="Execution cost falls only when measurement planning is treated as part of the model design, not as post-processing.",
        ),
        VideoChapter(
            id="hcl-programming-mitigation",
            title="Mitigation, Logging, and Debugging",
            timestamp_start=318,
            timestamp_end=456,
            summary="Connects error mitigation, diagnostics, and experiment logging to reproducible NISQ learning workflows.",
            transcript_excerpt="The middle-to-late sections focus on telling hardware failure apart from model failure through instrumentation.",
        ),
        VideoChapter(
            id="hcl-programming-benchmarking",
            title="Benchmarking Real Runtime Behavior",
            timestamp_start=456,
            timestamp_end=582,
            summary="Ends on benchmark discipline that includes transpilation, latency, shot use, and mitigation overhead.",
            transcript_excerpt="The closing broadens evaluation beyond accuracy so programming choices can be judged against their operational cost.",
        ),
    ],
    "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4": [
        VideoChapter(
            id="hcl-software-architecture",
            title="Quantum Hardware as a Software-System Boundary",
            timestamp_start=0,
            timestamp_end=96,
            summary="Frames advanced QC+AI as a software-architecture problem shaped by queueing, calibration drift, and orchestration cost.",
            transcript_excerpt="The lecture opens by treating the quantum processor as a fragile asynchronous co-processor that software must manage carefully.",
        ),
        VideoChapter(
            id="hcl-software-mlir",
            title="MLIR, Compilation, and Backend Abstraction",
            timestamp_start=96,
            timestamp_end=214,
            summary="Explains why compiler dialects, intermediate representations, and backend abstraction matter for portable QC+AI systems.",
            transcript_excerpt="Compilation is presented as a first-class design surface because it governs reuse, routing visibility, and vendor portability.",
        ),
        VideoChapter(
            id="hcl-software-caching",
            title="Caching and Differentiable Execution Pipelines",
            timestamp_start=214,
            timestamp_end=332,
            summary="Shows how caching, invalidation policy, and differentiable orchestration shape iterative hybrid workloads.",
            transcript_excerpt="Repeated variational execution makes cache strategy and dependency tracking part of the performance story, not an implementation afterthought.",
        ),
        VideoChapter(
            id="hcl-software-pulse",
            title="Pulse-Level Control and Runtime Optimization",
            timestamp_start=332,
            timestamp_end=468,
            summary="Connects pulse-level control to decoherence exposure, latency reduction, and native-hardware optimization.",
            transcript_excerpt="The middle-to-late sections argue that lower-level control can matter more than preserving a clean logical-gate abstraction.",
        ),
        VideoChapter(
            id="hcl-software-reliability",
            title="Reliability Engineering and Acceptance Gates",
            timestamp_start=468,
            timestamp_end=589,
            summary="Closes with reproducibility, seed management, energy accounting, and the reliability standards needed for deployable QC+AI software.",
            transcript_excerpt="The conclusion reframes advanced quantum software engineering as operational discipline around calibration, reproducibility, and measurable acceptance gates.",
        ),
    ],
    "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4": [
        VideoChapter(
            id="hcl-finance-framing",
            title="Quantum Finance Under NISQ Limits",
            timestamp_start=0,
            timestamp_end=82,
            summary="Frames finance as a domain where hybrid optimization is more credible than broad quantum-speedup marketing.",
            transcript_excerpt="The opening emphasizes that finance adoption depends on hardware-aware workflows, not on abstract asymptotic claims.",
        ),
        VideoChapter(
            id="hcl-finance-workloads",
            title="Portfolio, Pricing, and Anomaly Targets",
            timestamp_start=82,
            timestamp_end=174,
            summary="Maps portfolio optimization, option pricing, anomaly detection, and credit tasks to realistic QC+AI methods.",
            transcript_excerpt="Different workloads are shown to favor different hybrid decompositions, encodings, and acceptance criteria.",
        ),
        VideoChapter(
            id="hcl-finance-implementation",
            title="Programming the Hybrid Finance Loop",
            timestamp_start=174,
            timestamp_end=266,
            summary="Explains how classical optimizers, QUBO formulations, and kernel or variational subroutines interact in practice.",
            transcript_excerpt="The implementation section repeatedly positions the quantum component as a bounded co-processor inside a larger financial stack.",
        ),
        VideoChapter(
            id="hcl-finance-risk",
            title="Model Risk and Benchmark Governance",
            timestamp_start=266,
            timestamp_end=360,
            summary="Covers baseline comparison, compilation overhead, explainability pressure, and model-risk controls.",
            transcript_excerpt="Operational finance demands stronger controls because a merely novel model is not enough to justify deployment cost.",
        ),
        VideoChapter(
            id="hcl-finance-acceptance",
            title="Acceptance Gates for Production Finance",
            timestamp_start=360,
            timestamp_end=450,
            summary="Closes with the acceptance thresholds needed before a QC+AI finance system should be treated as deployable.",
            transcript_excerpt="The final message is that financial usefulness depends on disciplined evidence, governance, and cost accounting.",
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
