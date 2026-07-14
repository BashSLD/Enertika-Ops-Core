"""Ejecucion de verificaciones mecanicas sobre los archivos cambiados."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from devtools.models import ChangedFile, CommandResult, DiffSnapshot


def run_quality_commands(
    root: Path,
    snapshot: DiffSnapshot,
    *,
    run_tests: bool = True,
) -> tuple[CommandResult, ...]:
    """Ejecuta Ruff, compilacion y pruebas focalizadas."""

    python_files = _existing_python_files(root, snapshot.files)
    results = [
        _run_or_skip(
            root,
            "ruff",
            (sys.executable, "-m", "ruff", "check", *python_files),
            "No hay archivos Python modificados.",
            should_run=bool(python_files),
        ),
        _run_or_skip(
            root,
            "py_compile",
            (sys.executable, "-m", "py_compile", *python_files),
            "No hay archivos Python modificados.",
            should_run=bool(python_files),
        ),
    ]

    test_files = select_targeted_tests(root, snapshot.files)
    results.append(
        _run_or_skip(
            root,
            "pytest",
            (sys.executable, "-m", "pytest", *test_files, "-q"),
            (
                "Las pruebas fueron desactivadas con --no-tests."
                if not run_tests
                else "No se encontraron pruebas focalizadas para este diff."
            ),
            should_run=run_tests and bool(test_files),
        )
    )
    return tuple(results)


def select_targeted_tests(
    root: Path,
    changed_files: Iterable[ChangedFile],
) -> tuple[str, ...]:
    """Selecciona pruebas por archivos modificados con una heuristica explicable."""

    selected: set[str] = set()
    module_names: set[str] = set()
    core_stems: set[str] = set()

    for changed_file in changed_files:
        normalized = changed_file.path.replace("\\", "/")
        path = Path(normalized)
        if (
            normalized.startswith("tests/")
            and path.suffix == ".py"
            and path.name.startswith("test_")
        ):
            if (root / path).is_file():
                selected.add(normalized)
            continue
        parts = path.parts
        if len(parts) >= 2 and parts[0] == "modules":
            module_names.add(parts[1])
        elif len(parts) >= 2 and parts[0] == "core" and path.suffix == ".py":
            core_stems.add(path.stem.removesuffix("_service"))

    for module_name in module_names:
        selected.update(_matching_tests(root, f"test_{module_name}*.py"))
    for core_stem in core_stems:
        selected.update(_matching_tests(root, f"test_{core_stem}*.py"))

    return tuple(sorted(selected))


def _matching_tests(root: Path, pattern: str) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in (root / "tests").glob(pattern)
        if path.is_file()
    }


def _existing_python_files(
    root: Path,
    changed_files: Iterable[ChangedFile],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            changed_file.path
            for changed_file in changed_files
            if changed_file.suffix == ".py"
            and changed_file.status != "D"
            and (root / changed_file.path).is_file()
        )
    )


def _run_or_skip(
    root: Path,
    name: str,
    command: tuple[str, ...],
    skipped_reason: str,
    *,
    should_run: bool,
) -> CommandResult:
    if not should_run:
        return CommandResult(
            name=name,
            command=command,
            returncode=None,
            skipped_reason=skipped_reason,
        )

    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return CommandResult(
            name=name,
            command=command,
            returncode=2,
            output=str(exc),
        )

    output = "\n".join(
        part.strip() for part in (result.stdout, result.stderr) if part.strip()
    )
    return CommandResult(
        name=name,
        command=command,
        returncode=result.returncode,
        output=output,
    )
