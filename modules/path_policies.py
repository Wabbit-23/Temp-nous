"""Helpers for managing allowed and excluded filesystem roots."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple


def _clean(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except OSError:
        return path


def normalise_paths(values: Sequence[str | Path] | None) -> List[Path]:
    paths: List[Path] = []
    if not values:
        return paths
    seen = set()
    for entry in values:
        if entry is None:
            continue
        path = _clean(Path(entry))
        key = path.as_posix().lower()
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return paths


def _windows_exclusions(root: Path) -> List[Path]:
    system_dirs = [
        Path("C:/Windows"),
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
        Path("C:/ProgramData"),
    ]
    profile = Path(os.path.expandvars("%USERPROFILE%"))
    appdata = profile / "AppData"
    return normalise_paths(
        system_dirs
        + [
            appdata,
            Path("C:/pagefile.sys"),
            Path("C:/hiberfil.sys"),
            Path("C:/System Volume Information"),
            Path("C:/$Recycle.Bin"),
        ]
    )


def _posix_exclusions() -> List[Path]:
    linux = [
        Path("/bin"),
        Path("/boot"),
        Path("/dev"),
        Path("/etc"),
        Path("/lib"),
        Path("/proc"),
        Path("/root"),
        Path("/run"),
        Path("/sbin"),
        Path("/sys"),
        Path("/tmp"),
        Path("/usr"),
    ]
    mac = [
        Path("/System"),
        Path("/bin"),
        Path("/sbin"),
        Path("/usr"),
        Path("/private/var"),
        Path("/Library"),
        Path("/dev"),
    ]
    if sys.platform == "darwin":
        return normalise_paths(mac)
    return normalise_paths(linux)


def default_allowed_roots() -> List[Path]:
    home = Path.home()
    roots = [home]
    try:
        cwd = Path.cwd().resolve()
        if cwd not in roots:
            roots.append(cwd)
    except OSError:
        pass
    return normalise_paths(roots)


def default_excluded_paths() -> List[Path]:
    if os.name == "nt":
        return _windows_exclusions(Path.home())
    return _posix_exclusions()


def is_under(path: Path, parent: Path) -> bool:
    path = _clean(path)
    parent = _clean(parent)
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def is_allowed(path: Path, allowed_roots: Iterable[Path], excluded: Iterable[Path]) -> Tuple[bool, str | None]:
    path = _clean(path)
    for entry in excluded:
        if is_under(path, entry):
            return False, f"Excluded path: {entry}"
    for root in allowed_roots:
        if is_under(path, root) or path == root:
            return True, None
    return False, "Outside allowed roots"

