# QC+AI Learning Monorepo

This repository now contains a working MVP implementation of the interactive QC+AI learning platform described in the local specifications.

## Challenge Submission

- Project name: `QC+AI Studio`
- Product owner: `Nay Linn Aung (na27@hood.edu)`
- License: `MIT` for repository code unless a file states otherwise
- Submission docs:
  - `04_Completed_Activities_Log.md`
  - `SUBMISSION_ATTRIBUTION.md`
  - `PROJECT_SUMMARY.md`

### Ethical Transparency Addendum (2026-04-09)

- All seeded demo activity shown on public project, builder, or arena surfaces is explicitly labeled and derived from fictional audit personas documented in `08_Fictional_User_Accounts_and_User_Commands.md`.
- No real learner data is fabricated as public evidence. First-visit activity can be seeded from `seeds/demo/` strictly to make immediate evaluation possible without implying live-user traffic.
- Human review remains the final gate on curated source assets, public claims, partner-facing copy, and release packaging.
- Automation and AI assistance are limited to implementation, refinement, testing, infrastructure, packaging, and documentation acceleration rather than unsupervised publication.

### Demo Seeding for Immediate Evaluation

Canonical demo fixtures now live under `seeds/demo/` and can be loaded idempotently with:

```powershell
cd apps/api
python -m app.workers.seed_demo
```

This creates one labeled seeded project submission plus peer review, one labeled seeded builder share, and one labeled seeded arena ladder entry using the stable `fixture-ac-xx` identity convention.

## Structure

- `apps/frontend`: Next.js learning interface deployed locally or via Vercel
- `apps/api`: FastAPI backend with source ingestion, notes, search, and grounded QA endpoints
- `infra/k8s`: Kubernetes manifests aligned with the implementation blueprint
- `docker-compose.yml`: root-level local orchestration for the API and frontend
- Active source-asset discovery roots:
  - repository root
  - `update_data/`
- Expected active local source assets:
  - `Quantum Computing AI Research Synthesis 2026.docx`
  - `Analyzing Quantum Computing and AI Paper 2025.docx`
  - `Quantum Computing and Artificial Intelligence Industry Use Cases.docx`
  - `update_data/Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx`
  - `update_data/Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.docx`
  - `update_data/Module4_Expressive Bottlenecks Compression, Language, and Explanation.docx`
  - `update_data/Module6_From Algorithmic Novelty to Sustainable Hybrid Systems.docx`
  - `Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx`
  - `Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.docx`
  - `Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx`
  - `Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx`
  - `Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx`
  - `Quantum Computing and Artificial Intelligence 2025.mp4`
  - `Quantum Computing and Artificial Intelligence 2026.mp4`
  - `Industry Use Cases.mp4`
  - `update_data/Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.mp4`
  - `update_data/Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.mp4`
  - `update_data/Module4_Expressive Bottlenecks Compression, Language, and Explanation.mp4`
  - `update_data/Module6_From Algorithmic Novelty to Sustainable Hybrid Systems.mp4`
  - `Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4`
  - `The Hardware-First Imperative in Quantum Machine LearningHardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.mp4`
  - `Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4`
  - `Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4`
  - `Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4`

The current public curriculum is intentionally scoped to twelve curated DOCX sources and twelve curated MP4 lesson assets, with the routing-and-optimization, hybrid-applications, representation-language, and thermodynamics lessons now grounded in the dedicated Module 2, Module 3, Module 4, and Module 6 source pairs under `update_data/`.

## Roadmap to Full Academy (v2-Q3 2026)

- `Phase 1 (live)`: 11 modules, 12 lessons, 34 simulations, grounded search/Q&A, portfolio-style projects, peer review, labeled seeded demo activity, and audit-fixture transparency surfaces.
- `Phase 2`: full 15-course transcript coverage, transcript-linked chapter panels, richer completion evidence, and exportable portfolio/certificate-style signals.
- `Phase 3`: community contributions through pull-requested modules, deeper specialization tracks, expanded partner review workflows, and broader human-reviewed curriculum operations.

## Local development

### Backend

```powershell
cd apps/api
copy .env.example .env
uvicorn app.main:app --reload
```

`ALLOWED_ORIGINS` in `apps/api/.env` can be provided either as a JSON array or as a comma-separated list.

### Frontend

```powershell
cd apps/frontend
copy .env.example .env.local
npm install
npm run dev
```

If the backend is not running on `http://127.0.0.1:8000`, update `API_BASE_URL` in `apps/frontend/.env.local` before starting the frontend.

### Git LFS media setup

The curated MP4 lesson assets are intended to be versioned with Git LFS for GitHub distribution.

```powershell
git lfs install
git lfs pull
```

If you are working from a fresh clone and the MP4 files have not been pulled yet, run the commands above before testing video playback. For a one-command hydration and verification pass from Git Bash or WSL, run `./hydrate-assets.sh`.

Important LFS note:

- Install Git LFS before the first checkout whenever possible.
- ZIP downloads from GitHub do not hydrate LFS-managed MP4 payloads.
- If a clone was created before Git LFS was installed, run `git lfs install` and then `git lfs pull` from the repository root.
- Use `git lfs ls-files` to confirm the curated MP4 assets were actually hydrated.
- Release `v1.0.0` publishes split hydrated bundles because the curated source set is about `3.10 GB`: `qcai-studio-v1.0.0-part1-app-docs-media.zip` and `qcai-studio-v1.0.0-part2-hydrated-media.zip`.
- Extract part 1 first, then extract part 2 into the same folder so the six remaining MP4 payloads merge into the runnable tree.
- Verify the release assets with `SHA256SUMS.txt` before distributing or mirroring them.
- Release notes and split-bundle assets are intended to live at `https://github.com/naylinnaungHoodedu/qcai-studio/releases/tag/v1.0.0`.

### Docker Compose

```powershell
docker compose up --build
```

This starts the API on `http://127.0.0.1:8000` and the frontend on `http://127.0.0.1:3000`.

## Docker build commands

Build from the repository root so the API image can include the local source corpus:

```powershell
docker build -f apps/api/Dockerfile -t qcai-api .
docker build -t qcai-frontend apps/frontend
```

## Key implementation notes

- `LICENSE` applies to the repository code. Third-party source documents, proceedings metadata, and curated media assets remain subject to their own upstream rights and are not relicensed by the repository code license.
- The backend now assembles the course around a twelve-document active local corpus and twelve curated MP4 lesson assets, producing an eleven-module, twelve-lesson curriculum.
- The `ai4qc-routing-and-optimization` lesson now uses the dedicated Module 2 routing/logistics DOCX and MP4 assets from `update_data/`, with lesson sections and curated chapters aligned to that source pair.
- The `hybrid-applications-healthcare-vision` lesson now uses the dedicated Module 3 vision/GNN/few-shot DOCX and MP4 assets from `update_data/`, with lesson sections and curated chapters aligned to that source pair.
- The `representation-language-and-xai` lesson now uses the dedicated Module 4 expressive-bottlenecks DOCX and MP4 assets from `update_data/`, with lesson sections and curated chapters aligned to that source pair.
- The `thermodynamics-and-roadmap` lesson now uses the dedicated Module 6 sustainable-systems DOCX and MP4 assets from `update_data/`, with lesson sections and curated chapters aligned to that source pair.
- Background workers are real Python entrypoints and can be invoked directly with `python -m app.workers.ingestion`, `python -m app.workers.rag`, `python -m app.workers.analytics`, and `python -m app.workers.seed_demo`.
- Video chapters are currently driven by curated chapter metadata; transcript JSON files can be dropped into the repository-root `transcripts/` directory using the format documented in `transcripts/README.md`.
- Seeded demo activity is deterministic, traceable, and opt-in. The `seed_demo` worker loads the canonical JSON fixtures under `seeds/demo/` and only upserts records for the stable `fixture-ac-xx` audit personas.
- QA uses grounded lexical retrieval by default and upgrades to Pinecone-backed hybrid retrieval only when `OPENAI_API_KEY`, `PINECONE_API_KEY`, and `PINECONE_INDEX` are all configured.
- The current public Cloud Run deployment is running in `production` with `ENABLE_DEMO_AUTH=false`; open-demo learner access is provided through guest cookies and CSRF-protected same-site mutations rather than demo-header auth.
- The frontend now proxies browser-side API requests and source-asset streaming through a same-origin Next.js route so deployed clients do not compile in a `localhost` API URL.
- The frontend now exposes lightweight `/health` and `/ready` probe routes, while the API readiness route verifies both database reachability and assembled lesson availability.
- Source assets now require authenticated or demo-authenticated access and video files support byte-range requests for reliable seeking.
- Quiz attempts and learner interactions are wired into the existing backend persistence and analytics endpoints.
- Learner progress is now aggregated through `/content/progress` and surfaced on the homepage and dashboard.
- Auth defaults to demo learner headers for local development, while the API surface is prepared for Auth0-backed JWT validation in deployed environments.
- The current production-oriented container and infrastructure scaffolding now includes non-root runtime containers, SHA-tagged Cloud Build outputs, Kubernetes startup/readiness/liveness probes, resource requests and limits, and PodDisruptionBudgets for the API and frontend.
- `python tools/package_release.py` validates hydrated media, creates the split `v1.0.0` ZIP bundles under `dist/release/`, emits `SHA256SUMS.txt`, and writes release notes that describe extraction order and seeded-demo labeling.

## Public operations still owned outside the repo

- Google Search Console submission and verification must be completed from the domain owner account.
- Exact-match redirect domains such as `quantumlearn.academy` require registrar and DNS changes outside the application repository.
- GitHub repository topics are set through repository settings or the GitHub CLI and are not stored in git history.
