"""Utility helpers for discovering locally available AI models."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable, List, Sequence


MODEL_FILE_SUFFIXES = {".gguf", ".bin", ".onnx", ".pt", ".json"}
DEFAULT_SEARCH_DIRS = [
    Path(__file__).parent.parent / "models",
    Path(__file__).parent.parent / "data" / "models",
    Path.home() / ".nous" / "models",
    Path.home() / ".cache" / "nous-ai" / "models",
]


def _parse_ollama_list(output: str) -> List[str]:
    models = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("NAME"):
            continue
        parts = line.split()
        if parts:
            models.append(parts[0])
    return models


def _as_paths(values: Sequence[str] | None) -> List[Path]:
    paths: List[Path] = []
    if not values:
        return paths
    for entry in values:
        if not entry:
            continue
        try:
            paths.append(Path(entry).expanduser().resolve())
        except OSError:
            continue
    return paths


def _discover_from_paths(paths: Iterable[Path]) -> List[str]:
    names: List[str] = []
    for base in paths:
        if not base or not base.exists() or not base.is_dir():
            continue
        try:
            children = list(base.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                try:
                    modelfile = next(
                        (child / candidate for candidate in ("Modelfile", "modelfile") if (child / candidate).exists()),
                        None,
                    )
                except OSError:
                    modelfile = None
                has_known_assets = False
                try:
                    has_known_assets = any(
                        asset.suffix.lower() in MODEL_FILE_SUFFIXES for asset in child.iterdir()
                    )
                except OSError:
                    has_known_assets = False
                if modelfile or has_known_assets:
                    names.append(child.name)
                continue
            if child.suffix.lower() in MODEL_FILE_SUFFIXES:
                names.append(child.stem)
    return names


def detect_local_models(
    extra_models: Sequence[str] | None = None,
    search_paths: Sequence[str] | None = None,
) -> List[str]:
    """Return a unique, case-insensitive list of discovered local model names."""

    discovered: List[str] = []
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            discovered.extend(_parse_ollama_list(result.stdout))
    except FileNotFoundError:
        # Ollama is optional; ignore if not installed.
        pass

    search_dirs = list(DEFAULT_SEARCH_DIRS)
    search_dirs.extend(_as_paths(search_paths))
    discovered.extend(_discover_from_paths(search_dirs))

    if extra_models:
        for model in extra_models:
            model = (model or "").strip()
            if model:
                discovered.append(model)

    seen = set()
    unique = []
    for model in discovered:
        norm = model.lower()
        if norm not in seen:
            seen.add(norm)
            unique.append(model)
    return unique
