from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = REPO_ROOT / "dist" / "release"
RELEASE_TAG = "v1.0.0"

CURATED_DOCX = [
    Path("Quantum Computing AI Research Synthesis 2026.docx"),
    Path("Analyzing Quantum Computing and AI Paper 2025.docx"),
    Path("Quantum Computing and Artificial Intelligence Industry Use Cases.docx"),
    Path("update_data/Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx"),
    Path("update_data/Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.docx"),
    Path("update_data/Module4_Expressive Bottlenecks Compression, Language, and Explanation.docx"),
    Path("update_data/Module6_From Algorithmic Novelty to Sustainable Hybrid Systems.docx"),
    Path("Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx"),
    Path("Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.docx"),
    Path("Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx"),
    Path("Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx"),
    Path("Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx"),
]

CURATED_VIDEOS = [
    Path("Quantum Computing and Artificial Intelligence 2025.mp4"),
    Path("Quantum Computing and Artificial Intelligence 2026.mp4"),
    Path("Industry Use Cases.mp4"),
    Path("update_data/Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.mp4"),
    Path("update_data/Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.mp4"),
    Path("update_data/Module4_Expressive Bottlenecks Compression, Language, and Explanation.mp4"),
    Path("update_data/Module6_From Algorithmic Novelty to Sustainable Hybrid Systems.mp4"),
    Path("Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4"),
    Path("The Hardware-First Imperative in Quantum Machine LearningHardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.mp4"),
    Path("Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4"),
    Path("Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4"),
    Path("Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4"),
]

CORE_REPO_PATHS = [
    Path(".dockerignore"),
    Path(".gcloudignore"),
    Path(".gitattributes"),
    Path(".gitignore"),
    Path("04_Completed_Activities_Log.md"),
    Path("08_Fictional_User_Accounts_and_User_Commands.md"),
    Path("LICENSE"),
    Path("PROJECT_SUMMARY.md"),
    Path("README.md"),
    Path("SUBMISSION_ATTRIBUTION.md"),
    Path("docker-compose.yml"),
    Path("sitemap-live.xml"),
    Path("apps"),
    Path("infra"),
    Path("transcripts"),
    Path("seeds"),
    Path("tools"),
    Path("hydrate-assets.sh"),
]

PART1_ZIP_NAME = f"qcai-studio-{RELEASE_TAG}-part1-app-docs-media.zip"
PART2_ZIP_NAME = f"qcai-studio-{RELEASE_TAG}-part2-hydrated-media.zip"
RELEASE_NOTES_NAME = f"RELEASE_NOTES_{RELEASE_TAG}.md"


def _assert_curated_assets_exist() -> None:
    missing = [path for path in CURATED_DOCX + CURATED_VIDEOS if not (REPO_ROOT / path).exists()]
    if missing:
        raise FileNotFoundError(f"Missing curated assets: {', '.join(str(path) for path in missing)}")


def _assert_videos_are_hydrated() -> None:
    completed = subprocess.run(
        ["git", "lfs", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    mp4_lines = [line for line in completed.stdout.splitlines() if line.strip().endswith(".mp4")]
    hydrated_lines = [line for line in mp4_lines if " * " in line]
    if len(mp4_lines) != 12 or len(hydrated_lines) != 12:
        raise RuntimeError(
            "Expected 12 hydrated MP4 assets in git lfs ls-files before packaging the release bundles."
        )
    for relative_path in CURATED_VIDEOS:
        asset_path = REPO_ROOT / relative_path
        with asset_path.open("rb") as handle:
            prefix = handle.read(64)
        if prefix.startswith(b"version https://git-lfs.github.com/spec/v1"):
            raise RuntimeError(f"{relative_path} is still a Git LFS pointer, not a hydrated MP4 payload.")


def _iter_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {"node_modules", ".next", "__pycache__", ".pytest_cache", "dist"} for part in path.parts):
            continue
        if path.name.startswith("qcai_dev.db"):
            continue
        files.append(path)
    return files


def _collect_core_repo_files() -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for relative_root in CORE_REPO_PATHS:
        absolute_root = REPO_ROOT / relative_root
        for file_path in _iter_files(absolute_root):
            relative_path = file_path.relative_to(REPO_ROOT)
            if relative_path in seen:
                continue
            seen.add(relative_path)
            files.append(relative_path)
    return sorted(files)


def _write_zip(archive_path: Path, files: list[Path]) -> None:
    with zipfile.ZipFile(archive_path, "w", allowZip64=True) as archive:
        for relative_path in files:
            absolute_path = REPO_ROOT / relative_path
            compress_type = zipfile.ZIP_STORED if absolute_path.suffix.lower() == ".mp4" else zipfile.ZIP_DEFLATED
            archive.write(absolute_path, arcname=relative_path.as_posix(), compress_type=compress_type)


def _build_release_notes(part1_name: str, part2_name: str) -> str:
    return f"""# QC+AI Studio Release {RELEASE_TAG}

## Assets

- `{part1_name}`: runnable repository, release tooling, transcript scaffolding, audit artifacts, all 12 curated DOCX files, and the first 6 curated MP4 lesson assets in README order
- `{part2_name}`: the remaining 6 curated MP4 lesson assets in repo-relative paths
- `SHA256SUMS.txt`: SHA-256 checksums for every generated release asset

## Extraction order

1. Extract `{part1_name}` into an empty folder.
2. Extract `{part2_name}` into the same folder and allow it to merge into the existing tree.
3. Verify checksums with `SHA256SUMS.txt`.
4. If you cloned the repo instead of using the release ZIPs, run `./hydrate-assets.sh` to hydrate and verify the Git LFS MP4 payloads.

## Trust and transparency

- Seeded demo activity in project, builder, and arena surfaces is explicitly labeled and derived from fictional audit personas documented on `/audit-fixtures`.
- The release bundles preserve repo-relative paths so hydration, playback, and source discovery behave the same way they do in a hydrated git clone.
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    _assert_curated_assets_exist()
    _assert_videos_are_hydrated()

    shutil.rmtree(DIST_DIR, ignore_errors=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    core_files = _collect_core_repo_files()
    part1_files = sorted(set(core_files + CURATED_DOCX + CURATED_VIDEOS[:6]))
    part2_files = CURATED_VIDEOS[6:]

    part1_zip = DIST_DIR / PART1_ZIP_NAME
    part2_zip = DIST_DIR / PART2_ZIP_NAME
    release_notes = DIST_DIR / RELEASE_NOTES_NAME
    checksums = DIST_DIR / "SHA256SUMS.txt"

    _write_zip(part1_zip, part1_files)
    _write_zip(part2_zip, part2_files)
    release_notes.write_text(_build_release_notes(part1_zip.name, part2_zip.name), encoding="utf-8")

    checksum_targets = [part1_zip, part2_zip, release_notes]
    checksum_lines = [f"{_sha256(path)}  {path.name}" for path in checksum_targets]
    checksums.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    print(f"Created {part1_zip}")
    print(f"Created {part2_zip}")
    print(f"Created {release_notes}")
    print(f"Created {checksums}")


if __name__ == "__main__":
    main()
