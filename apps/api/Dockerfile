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
COPY --chown=qcai:qcai transcripts ./source-assets/transcripts
COPY --chown=qcai:qcai *.docx ./source-assets/
COPY --chown=qcai:qcai *.mp4 ./source-assets/
COPY --chown=qcai:qcai update_data/*.docx ./source-assets/update_data/
COPY --chown=qcai:qcai update_data/*.mp4 ./source-assets/update_data/

USER qcai

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
