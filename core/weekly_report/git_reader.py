import os
import re
import shutil
import subprocess
from datetime import date, timedelta
from zoneinfo import ZoneInfo

MODULE_NAMES = {
    "comercial": "Comercial",
    "simulacion": "Simulación",
    "simulacion-pdf": "Simulación",
    "levantamientos": "Levantamientos",
    "compras": "Compras",
    "proyectos": "Proyectos",
    "bom": "BOM",
    "finanzas": "Finanzas",
    "oym": "OyM",
    "admin": "Admin",
    "base": "Admin",
    "calculadora-polizas": "Calculadora de Pólizas",
    "calculadora": "Calculadora de Pólizas",
    "pdf": "Reportes PDF",
    "visita-obra": "Visita a Obra",
    "visita-obra-email": "Visita a Obra",
    "visita-obra-pdf": "Visita a Obra",
    "ingenieria": "Ingeniería",
    "construccion": "Construcción",
    "microsoft-graph": "Infraestructura",
    "ui": "Admin",
    "workflow": "Notificaciones",
    "emails": "Notificaciones",
    "notifications": "Notificaciones",
}

TYPE_LABELS = {
    "feat": "Nueva funcionalidad",
    "fix": "Corrección",
    "perf": "Optimización",
    "refactor": "Refactorización",
    "chore": "Mantenimiento",
    "docs": "Documentación",
    "style": "Estilo",
    "test": "Pruebas",
}

_SKIP_TYPES = {"chore", "docs", "style", "test"}

_COMMIT_RE = re.compile(r"^(\w+)\(([^)]+)\):\s*(.+)$")


def _semana_actual() -> tuple[date, date]:
    mx = ZoneInfo("America/Mexico_City")
    from datetime import datetime
    today = datetime.now(mx).date()
    lunes = today - timedelta(days=today.weekday())
    return lunes, today + timedelta(days=1)  # until es exclusivo en git


def get_weekly_commits(since: date = None, until: date = None) -> dict:
    """
    Lee commits de la semana actual (o del rango dado) y los agrupa por módulo.

    Retorna:
        semana_inicio: date
        semana_fin: date
        total_commits: int
        feats: int
        fixes: int
        otros: int
        modulos: dict[str, list[dict]]  — solo feat/fix/perf/refactor
    """
    if not since:
        since, until = _semana_actual()

    git_bin = shutil.which("git") or "/usr/bin/git"
    if not os.path.isfile(git_bin):
        raise RuntimeError(
            "git no está disponible en este entorno. "
            "Agrega 'git' al Dockerfile/nixpacks para usar el reporte de desarrollo."
        )

    if not os.path.isdir(".git"):
        raise RuntimeError(
            "El directorio .git no existe en este entorno. "
            "El reporte de desarrollo requiere acceso al historial de commits."
        )

    result = subprocess.run(
        [
            git_bin, "log",
            f"--after={since.isoformat()}",
            f"--before={until.isoformat()}",
            "--pretty=format:%s",
            "--no-merges",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    raw_commits = [l.strip() for l in result.stdout.splitlines() if l.strip()]

    modulos: dict[str, list] = {}
    feats = fixes = otros = 0

    for commit in raw_commits:
        m = _COMMIT_RE.match(commit)
        if not m:
            otros += 1
            continue

        tipo = m.group(1).lower()
        scope_raw = m.group(2).lower()
        desc = m.group(3).strip()

        if tipo == "feat":
            feats += 1
        elif tipo == "fix":
            fixes += 1
        else:
            otros += 1

        if tipo in _SKIP_TYPES:
            continue

        scopes = [s.strip() for s in re.split(r"[+,]", scope_raw)]
        module_names = {MODULE_NAMES.get(s, s.replace("-", " ").title()) for s in scopes}

        entry = {
            "tipo": tipo,
            "tipo_label": TYPE_LABELS.get(tipo, tipo.capitalize()),
            "descripcion": desc,
        }
        for name in module_names:
            modulos.setdefault(name, []).append(entry)

    # Módulos con más actividad primero
    modulos_sorted = dict(sorted(modulos.items(), key=lambda x: len(x[1]), reverse=True))

    return {
        "semana_inicio": since,
        "semana_fin": until - timedelta(days=1),
        "total_commits": len(raw_commits),
        "feats": feats,
        "fixes": fixes,
        "otros": otros,
        "modulos": modulos_sorted,
    }
