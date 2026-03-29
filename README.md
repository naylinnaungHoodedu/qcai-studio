# QC+AI Learning Monorepo

This repository now contains a working MVP implementation of the interactive QC+AI learning platform described in the local specifications.

## Challenge Submission

- Project name: `QC+AI Studio`
- Product owner: `Nay Linn Aung (na27@hood.edu)`
- License: `MIT` for repository code unless a file states otherwise
- Submission docs:
  - `SUBMISSION_ATTRIBUTION.md`
  - `PROJECT_SUMMARY.md`
  - `04_Completed_Activities_Log.md`

## Structure

- `apps/frontend`: Next.js learning interface deployed locally or via Vercel
- `apps/api`: FastAPI backend with source ingestion, notes, search, and grounded QA endpoints
- `infra/k8s`: Kubernetes manifests aligned with the implementation blueprint
- `docker-compose.yml`: root-level local orchestration for the API and frontend
- Expected local source assets:
  - `Quantum Computing AI Research Synthesis 2026.docx`
  - `Analyzing Quantum Computing and AI Paper 2025.docx`
  - `Quantum Computing and Artificial Intelligence Industry Use Cases.docx`
  - `Quantum Computing and Artificial Intelligence 2025.mp4`
  - `Quantum Computing and Artificial Intelligence 2026.mp4`
  - `Industry Use Cases.mp4`

The course is intentionally scoped to the three curated DOCX sources above and the three curated MP4 lesson assets. Stray working files in the repository root are not part of the served course corpus.

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

The three curated MP4 lesson assets are intended to be versioned with Git LFS for GitHub distribution.

```powershell
git lfs install
git lfs pull
```

If you are working from a fresh clone and the MP4 files have not been pulled yet, run the commands above before testing video playback.

Important LFS note:

- Install Git LFS before the first checkout whenever possible.
- ZIP downloads from GitHub do not hydrate LFS-managed MP4 payloads.
- If a clone was created before Git LFS was installed, run `git lfs install` and then `git lfs pull` from the repository root.
- Use `git lfs ls-files` to confirm the three curated MP4 assets were actually hydrated.

### Docker Compose

```powershell
docker compose up --build
```

This starts the API on `http://127.0.0.1:8000` and the frontend on `http://127.0.0.1:3000`.

## Docker build commands

Build from the repository root so the API image can include the local source corpus:

```powershell
docker build -f apps/api/Dockerfile -t qcai-api .
docker build -f apps/frontend/Dockerfile -t qcai-frontend .
```

## Key implementation notes

- `LICENSE` applies to the repository code. Third-party source documents, proceedings metadata, and curated media assets remain subject to their own upstream rights and are not relicensed by the repository code license.
- The backend assembles the course around the three curated local `.docx` sources listed above, including the industry-use-cases module grounded in the added DOCX.
- Background workers are real Python entrypoints and can be invoked directly with `python -m app.workers.ingestion`, `python -m app.workers.rag`, and `python -m app.workers.analytics`.
- Video chapters are currently driven by curated chapter metadata; transcript JSON files can be dropped into the repository-root `transcripts/` directory using the format documented in `transcripts/README.md`.
- QA uses grounded lexical retrieval by default and upgrades to Pinecone-backed hybrid retrieval only when `OPENAI_API_KEY`, `PINECONE_API_KEY`, and `PINECONE_INDEX` are all configured.
- The current public Cloud Run deployment is running in `production` with `ENABLE_DEMO_AUTH=false`; open-demo learner access is provided through guest cookies and CSRF-protected same-site mutations rather than demo-header auth.
- The frontend now proxies browser-side API requests and source-asset streaming through a same-origin Next.js route so deployed clients do not compile in a `localhost` API URL.
- Source assets now require authenticated or demo-authenticated access and video files support byte-range requests for reliable seeking.
- Quiz attempts and learner interactions are wired into the existing backend persistence and analytics endpoints.
- Learner progress is now aggregated through `/content/progress` and surfaced on the homepage and dashboard.
- Auth defaults to demo learner headers for local development, while the API surface is prepared for Auth0-backed JWT validation in deployed environments.

## Public operations still owned outside the repo

- Google Search Console submission and verification must be completed from the domain owner account.
- Exact-match redirect domains such as `quantumlearn.academy` require registrar and DNS changes outside the application repository.
- GitHub repository topics are set through repository settings or the GitHub CLI and are not stored in git history.
