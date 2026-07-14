"""Lectura segura y portable del diff de Git."""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from pathlib import Path

from devtools.models import AddedLine, ChangedFile, DiffSnapshot

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_SCANNABLE_SUFFIXES = {".css", ".html", ".js", ".py", ".sql"}


class GitError(RuntimeError):
    """Error controlado al consultar el repositorio."""


def find_repository_root(start: Path) -> Path:
    """Obtiene la raiz Git que contiene ``start``."""

    result = _run_git(start, "rev-parse", "--show-toplevel")
    return Path(result.strip()).resolve()


def collect_snapshot(root: Path, base: str = "HEAD") -> DiffSnapshot:
    """Construye una instantanea de cambios, incluidos archivos no rastreados."""

    statuses = _read_statuses(root, base)
    added_by_path = parse_unified_diff(_read_diff(root, base))

    for path in _read_untracked_paths(root):
        statuses.setdefault(path, "?")
        added_by_path[path] = _read_untracked_lines(root, path)

    files = tuple(
        ChangedFile(
            path=path,
            status=status,
            added_lines=tuple(added_by_path.get(path, ())),
        )
        for path, status in sorted(statuses.items())
    )
    return DiffSnapshot(base=base, files=files)


def parse_unified_diff(diff_text: str) -> dict[str, list[AddedLine]]:
    """Extrae solamente las lineas agregadas de un diff unificado."""

    added_by_path: dict[str, list[AddedLine]] = defaultdict(list)
    current_path: str | None = None
    new_line_number: int | None = None

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            current_path = None
            new_line_number = None
            continue

        if raw_line.startswith("+++ ") and new_line_number is None:
            current_path = _parse_new_path(raw_line[4:])
            new_line_number = None
            continue

        hunk = _HUNK_RE.match(raw_line)
        if hunk:
            new_line_number = int(hunk.group(1))
            continue

        if current_path is None or new_line_number is None:
            continue

        if raw_line.startswith("+"):
            added_by_path[current_path].append(
                AddedLine(current_path, new_line_number, raw_line[1:])
            )
            new_line_number += 1
        elif raw_line.startswith(" "):
            new_line_number += 1
        elif raw_line.startswith("-") or raw_line.startswith("\\"):
            continue

    return dict(added_by_path)


def _parse_new_path(raw_path: str) -> str | None:
    if raw_path == "/dev/null":
        return None
    if raw_path.startswith("b/"):
        return raw_path[2:]
    return raw_path


def _read_statuses(root: Path, base: str) -> dict[str, str]:
    output = _run_git(
        root,
        "diff",
        "--name-status",
        "--find-renames",
        base,
        "--",
    )
    statuses: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        statuses[parts[-1]] = parts[0][0]
    return statuses


def _read_diff(root: Path, base: str) -> str:
    return _run_git(
        root,
        "-c",
        "core.quotepath=false",
        "diff",
        "--unified=0",
        "--no-color",
        "--no-ext-diff",
        base,
        "--",
    )


def _read_untracked_paths(root: Path) -> tuple[str, ...]:
    output = _run_git(root, "ls-files", "--others", "--exclude-standard", "-z")
    return tuple(path for path in output.split("\0") if path)


def _read_untracked_lines(root: Path, relative_path: str) -> list[AddedLine]:
    path = root / relative_path
    if path.suffix.lower() not in _SCANNABLE_SUFFIXES or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [
        AddedLine(relative_path, number, line)
        for number, line in enumerate(text.splitlines(), start=1)
    ]


def _run_git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ("git", *args),
            cwd=root,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise GitError(f"No fue posible ejecutar Git: {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise GitError(detail or "Git termino con un error desconocido")
    return result.stdout
