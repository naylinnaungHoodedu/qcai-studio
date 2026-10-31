FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system qcai && useradd --system --gid qcai --home-dir /app --no-create-home qcai
RUN mkdir -p /app/source-assets/update_data && chown -R qcai:qcai /app

COPY apps/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=qcai:qcai apps/api/app ./app
COPY --chown=qcai:qcai corpus/public ./corpus/public
COPY --chown=qcai:qcai transcripts ./source-assets/transcripts
# No source asset goes in the image: a governed build serves only what the manifest approves, and none is
# approved (Decision P1-D-07, D-31; AC-1-5: "neither served nor packaged"). An approved asset gets a delivery
# path when D-02 approves it (D-10).

# The commit this image was built from, reported by /health and /ready (AC-1-7). Last, so a new commit
# rebuilds only this layer. Cloud Build passes it (infra/cloudbuild/api-image.yaml).
ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA

USER qcai

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
