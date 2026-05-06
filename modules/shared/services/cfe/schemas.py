from dataclasses import dataclass
from enum import Enum
from typing import Any


class CfeExcelModo(str, Enum):
    CALCULADO = "calculado"
    FORMULAS = "formulas"


@dataclass(frozen=True)
class CfeXmlInput:
    filename: str
    content: bytes


@dataclass(frozen=True)
class CfeExcelColumn:
    key: str
    header: str


@dataclass(frozen=True)
class CfeExcelProfile:
    slug: str
    nombre: str
    columns: tuple[CfeExcelColumn, ...]


CfeReceipt = dict[str, Any]
