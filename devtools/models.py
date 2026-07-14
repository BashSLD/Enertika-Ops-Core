"""Modelos compartidos por la suite de desarrollo."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Severity(str, Enum):
    """Nivel de un hallazgo del analizador."""

    ERROR = "error"
    WARNING = "warning"
    ACTION = "action"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class AddedLine:
    """Linea agregada en el diff, con su numero en el archivo nuevo."""

    path: str
    number: int
    text: str


@dataclass(frozen=True, slots=True)
class ChangedFile:
    """Archivo modificado y sus lineas agregadas."""

    path: str
    status: str
    added_lines: tuple[AddedLine, ...] = ()

    @property
    def suffix(self) -> str:
        return Path(self.path).suffix.lower()


@dataclass(frozen=True, slots=True)
class DiffSnapshot:
    """Estado del arbol de trabajo comparado con una referencia Git."""

    base: str
    files: tuple[ChangedFile, ...]


@dataclass(frozen=True, slots=True)
class Finding:
    """Resultado accionable producido por un control."""

    code: str
    severity: Severity
    message: str
    path: str | None = None
    line: int | None = None
    command: str | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
        }
        if self.path is not None:
            data["path"] = self.path
        if self.line is not None:
            data["line"] = self.line
        if self.command is not None:
            data["command"] = self.command
        return data


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Resultado de un comando determinista del pipeline de calidad."""

    name: str
    command: tuple[str, ...]
    returncode: int | None
    output: str = ""
    skipped_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 or self.returncode is None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "command": list(self.command),
            "returncode": self.returncode,
            "output": self.output,
            "skipped_reason": self.skipped_reason,
        }
