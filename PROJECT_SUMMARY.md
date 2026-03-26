# QC+AI Studio

## One-Page Project Summary

**Product owner:** Nay Linn Aung (`na27@hood.edu`)

`QC+AI Studio` is a full-stack learning platform for quantum computing and artificial intelligence that teaches the field through real hardware constraints, hybrid system design, and source-grounded evidence. Instead of treating QC+AI as abstract hype, the platform organizes curated workshop proceedings, industry-use-case analysis, and lecture media into a structured study path that emphasizes routing overhead, qubit scarcity, hybrid orchestration, application-specific evidence, and commercialization context.

The platform solves a specific problem: most quantum-computing learning experiences are either static documents or generic chat interfaces, and they rarely connect theory to what current hardware can actually support. `QC+AI Studio` turns that gap into an interactive product. Learners move through structured modules, ask grounded questions, review flashcards, take quizzes, save lesson notes, track study progress, and inspect the underlying references used in each lesson.

The application is implemented as a FastAPI backend plus a Next.js frontend. The backend assembles the course from curated local source documents and lecture assets, exposes lesson, search, notes, analytics, quiz, and progress endpoints, and serves authenticated source assets with byte-range support for reliable media streaming. The frontend provides the learner-facing experience: module navigation, lesson pages, video playback, grounded Q&A, flashcards, quizzes, notes, search, and progress views.

AI is used in two layers. First, the product itself is AI-powered: it supports grounded retrieval and can upgrade to OpenAI-backed RAG when an API key is configured, allowing learners to ask source-aware questions instead of browsing raw files manually. Second, the project has been significantly enhanced and submission-prepared with OpenAI Codex. Codex-assisted work in the current submission package includes implementation refinements, bug fixing, verification improvements, repository cleanup, source-label normalization, challenge packaging, and technical documentation.

Key capabilities in the current build include:

- 6 structured training modules grounded in curated QC+AI source materials
- lesson-level grounded search and Q&A with citation context
- learner notes, quizzes, analytics, and aggregated course progress
- clean reference presentation instead of raw file-name leakage in the UI
- authenticated source-asset delivery and byte-range video streaming
- local Docker and Kubernetes deployment scaffolding

Technically, the project is designed as a serious MVP rather than a one-page demo. It includes typed API schemas, persistence via SQLAlchemy and SQLite, automated backend verification, frontend lint/build validation, and deployment-oriented configuration. The current local verified runtime is a production-style frontend and backend pair served on separate ports with proxied browser access through the frontend.

`QC+AI Studio` is intended as both a learning tool and a demonstration of AI-assisted product engineering. It shows how OpenAI Codex can be used not just to generate code fragments, but to support iterative improvement across backend services, frontend UX, testing, cleanup, and submission preparation for a real project with clear educational value.
