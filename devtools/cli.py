"""Interfaz de linea de comandos de la suite."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from devtools.checks import run_checks
from devtools.git_diff import GitError, collect_snapshot, find_repository_root
from devtools.models import CommandResult, DiffSnapshot, Finding, Severity
from devtools.quality import run_quality_commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m devtools",
        description="Suite de calidad para Enertika Ops Core.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help=argparse.SUPPRESS,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    diff_parser = subparsers.add_parser(
        "diff",
        help="Analiza las lineas agregadas del arbol de trabajo.",
    )
    _add_common_options(diff_parser)

    quality_parser = subparsers.add_parser(
        "quality",
        help="Analiza el diff y ejecuta controles mecanicos.",
    )
    _add_common_options(quality_parser)
    quality_parser.add_argument(
        "--no-tests",
        action="store_true",
        help="Omite pytest; mantiene Ruff y py_compile.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = find_repository_root(args.root.resolve())
        snapshot = collect_snapshot(root, args.base)
    except GitError as exc:
        return _render_fatal(str(exc), args.format)

    findings = run_checks(snapshot)
    command_results: tuple[CommandResult, ...] = ()
    if args.command == "quality":
        command_results = run_quality_commands(
            root,
            snapshot,
            run_tests=not args.no_tests,
        )

    if args.format == "json":
        _render_json(snapshot, findings, command_results)
    else:
        _render_text(snapshot, findings, command_results)

    has_errors = any(item.severity is Severity.ERROR for item in findings)
    commands_failed = any(not item.succeeded for item in command_results)
    return 1 if has_errors or commands_failed else 0


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--base",
        default="HEAD",
        help="Referencia Git de comparacion (predeterminado: HEAD).",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Formato de salida.",
    )


def _render_text(
    snapshot: DiffSnapshot,
    findings: tuple[Finding, ...],
    command_results: tuple[CommandResult, ...],
) -> None:
    print(f"DEVTOOLS - revision contra {snapshot.base}")
    print(f"Archivos cambiados: {len(snapshot.files)}")

    if not findings:
        print("[OK] No se encontraron hallazgos en las lineas agregadas.")
    else:
        for finding in findings:
            location = ""
            if finding.path:
                location = f" {finding.path}"
                if finding.line is not None:
                    location += f":{finding.line}"
            print(f"[{finding.severity.value.upper()}] {finding.code}{location}")
            print(f"  {finding.message}")
            if finding.command:
                print(f"  Comando: {finding.command}")

    for result in command_results:
        if result.skipped_reason:
            print(f"[SKIP] {result.name}: {result.skipped_reason}")
            continue
        status = "OK" if result.succeeded else "ERROR"
        print(f"[{status}] {result.name} (codigo {result.returncode})")
        if result.output:
            print(result.output)

    counts = Counter(item.severity.value for item in findings)
    print(
        "Resumen: "
        f"{counts[Severity.ERROR.value]} errores, "
        f"{counts[Severity.WARNING.value]} advertencias, "
        f"{counts[Severity.ACTION.value]} acciones."
    )


def _render_json(
    snapshot: DiffSnapshot,
    findings: tuple[Finding, ...],
    command_results: tuple[CommandResult, ...],
) -> None:
    payload = {
        "base": snapshot.base,
        "changed_files": [
            {
                "path": item.path,
                "status": item.status,
                "added_lines": len(item.added_lines),
            }
            for item in snapshot.files
        ],
        "findings": [item.to_dict() for item in findings],
        "commands": [item.to_dict() for item in command_results],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _render_fatal(message: str, output_format: str) -> int:
    if output_format == "json":
        print(json.dumps({"error": message}, ensure_ascii=False, indent=2))
    else:
        print(f"[ERROR] {message}")
    return 2
