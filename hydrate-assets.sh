#!/usr/bin/env bash
set -euo pipefail

git lfs install
git lfs pull

mp4_count="$(git lfs ls-files | grep -c '\.mp4$' || true)"
hydrated_count="$(git lfs ls-files | grep '\.mp4$' | awk '$2 == "*" {count++} END {print count+0}')"

if [[ "${mp4_count}" -ne 12 ]]; then
  echo "Expected 12 Git LFS MP4 entries but found ${mp4_count}."
  exit 1
fi

if [[ "${hydrated_count}" -ne 12 ]]; then
  echo "Expected 12 hydrated MP4 payloads but found ${hydrated_count}."
  echo "Run 'git lfs ls-files' to inspect hydration state."
  exit 1
fi

echo "All 12 MP4 lesson assets are hydrated."
echo "Run 'git lfs ls-files | grep mp4' to verify the 12 curated entries."
