# Deploying by digest, with a committed deployment record (plan task 1.9, AC-1-7)

AC-1-7: "A committed deployment record names digest and commit; /health returns that commit."

**Not run yet.** A rollout is a production change. It needs the Platform Owner's approval and a D-05 release approval, and it is currently blocked by DL-2 (D-02/D-31). Images are built by Cloud Build, never on a workstation. Deploy the API and the frontend together: they share `GUEST_TOKEN_SECRET`.

## 1. Build one commit, in Cloud Build
Build from a clean checkout of the exact commit on `main`, so that what is uploaded is that commit:

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/naylinnaungHoodedu/qcai-studio.git build-src
cd build-src
git checkout <commit>
git status --porcelain   # must print nothing
gcloud builds submit --project naylinnaung --config infra/cloudbuild/api-image.yaml --substitutions _GIT_SHA=$(git rev-parse HEAD) .
gcloud builds submit --project naylinnaung --config infra/cloudbuild/frontend-image.yaml --substitutions _GIT_SHA=$(git rev-parse HEAD) .
```

Source assets are not part of the build: `.gcloudignore` and `.dockerignore` keep them out of the upload and the image (AC-1-5; P1-D-07). Each image is tagged with the commit (never `:latest`) and stamped with it, so `/health` reports it. Cloud Build records each pushed digest. A missing or short `_GIT_SHA` stops the build.

## 2. Deploy by digest, check, then move traffic
```bash
python scripts/deploy_by_digest.py --service qcai-api --commit <commit>             # the plan only
python scripts/deploy_by_digest.py --service qcai-api --commit <commit> --execute --no-pin --update-secret GUEST_TOKEN_SECRET=qcai-guest-token-secret:1
python scripts/deploy_by_digest.py --service qcai-frontend --commit <commit> --execute --no-pin --update-secret GUEST_TOKEN_SECRET=qcai-guest-token-secret:1
```

`--update-secret` binds a secret by name and version, never by value. `--no-pin` stops before traffic moves, so the tagged URLs can be checked first; the script then prints the `update-traffic` command. Without it, the script moves traffic as soon as `/health` reports the commit.

With `--execute`, the script:
1. resolves the image digest;
2. deploys it with no traffic and a `c-<commit[:12]>` tag;
3. checks that the tagged URL's `/health` reports the commit. If it does not, it stops with no traffic moved;
4. pins 100% of traffic to that named revision, so traffic no longer follows "latest".

## 3. Record, and commit the record
```bash
python scripts/deployment_record.py --commit <commit> --write deploy/records
```

The record names, for each service:
- the serving revision and its image digest;
- the public `/health` response.

It exits 1 if traffic follows "latest", a digest is missing, or `/health` does not report the commit. Commit a passing record by pull request. That record, plus the `/health` it shows, is the AC-1-7 evidence.

## Rollback
Route traffic back to the previous revision by name, then record again:

```bash
gcloud run services update-traffic qcai-api --project naylinnaung --region us-central1 --to-revisions <previous revision>=100
```

Before the first digest-pinned rollout, the previous revisions are `qcai-api-00036-lzg` (`sha256:e94cadd0…4775a5`) and `qcai-frontend-00051-sw7` (BEP-0, AC-0-2).
