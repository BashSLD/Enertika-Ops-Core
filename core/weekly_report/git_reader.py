import os
import re
import shutil
import subprocess
import json
from urllib import request, parse
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from core.config import settings

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


def _collect_stats(raw_commits: list[str]) -> tuple[dict, int, int, int]:
    """Agrupa commits por modulo y calcula contadores por tipo."""
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

    modulos_sorted = dict(sorted(modulos.items(), key=lambda x: len(x[1]), reverse=True))
    return modulos_sorted, feats, fixes, otros


def _read_commits_local(since: date, until: date) -> list[str]:
    """Lee commits del historial local de git."""
    git_bin = shutil.which("git") or "/usr/bin/git"
    if not os.path.isfile(git_bin):
        raise RuntimeError(
            "git no esta disponible en este entorno y no se pudo usar fallback GitHub API. "
            "Instala git o configura GITHUB_TOKEN + GITHUB_REPO."
        )

    result = subprocess.run(
        [
            git_bin,
            "log",
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

    return [l.strip() for l in result.stdout.splitlines() if l.strip()]


def _read_commits_github(since: date, until: date) -> list[str]:
    """Lee commits desde GitHub API (repos/{owner}/{repo}/commits)."""
    token = settings.GITHUB_TOKEN.strip()
    repo = settings.GITHUB_REPO.strip()
    branch = settings.GITHUB_BRANCH.strip() or "main"

    if not token or not repo:
        raise RuntimeError(
            "Falta configuracion de GitHub API. Define GITHUB_TOKEN y GITHUB_REPO "
            "para usar el reporte CEO en produccion sin .git."
        )

    if "/" not in repo:
        raise RuntimeError("GITHUB_REPO debe tener formato 'owner/repo'.")

    owner, repo_name = repo.split("/", 1)

    # GitHub usa timestamps UTC ISO8601; until en nuestra logica es exclusivo.
    since_iso = f"{since.isoformat()}T00:00:00Z"
    until_inclusive = until - timedelta(days=1)
    until_iso = f"{until_inclusive.isoformat()}T23:59:59Z"

    commits: list[str] = []
    page = 1

    while True:
        query = parse.urlencode(
            {
                "sha": branch,
                "since": since_iso,
                "until": until_iso,
                "per_page": 100,
                "page": page,
            }
        )
        url = f"https://api.github.com/repos/{owner}/{repo_name}/commits?{query}"

        req = request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

        try:
            with request.urlopen(req, timeout=20) as resp:
                payload = resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            raise RuntimeError(f"Error consultando GitHub API: {exc}")

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            raise RuntimeError("Respuesta invalida de GitHub API al consultar commits.")

        if isinstance(data, dict) and data.get("message"):
            raise RuntimeError(f"GitHub API devolvio error: {data.get('message')}")

        if not isinstance(data, list):
            raise RuntimeError("Formato inesperado de respuesta de GitHub API para commits.")

        if not data:
            break

        for item in data:
            raw_message = (item.get("commit", {}).get("message") or "").strip()
            if not raw_message:
                continue

            subject = raw_message.splitlines()[0].strip()
            if subject.startswith("Merge "):
                continue

            commits.append(subject)

        if len(data) < 100:
            break
        page += 1

    return commits


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

    raw_commits: list[str]
    github_configured = bool(settings.GITHUB_TOKEN.strip() and settings.GITHUB_REPO.strip())
    git_available = bool(os.path.isdir(".git"))

    if github_configured:
        raw_commits = _read_commits_github(since, until)
    elif git_available:
        raw_commits = _read_commits_local(since, until)
    else:
        raise RuntimeError(
            "El directorio .git no existe en este entorno y no hay fallback configurado. "
            "Define GITHUB_TOKEN y GITHUB_REPO para usar el reporte de desarrollo en produccion."
        )

    modulos_sorted, feats, fixes, otros = _collect_stats(raw_commits)

    return {
        "semana_inicio": since,
        "semana_fin": until - timedelta(days=1),
        "total_commits": len(raw_commits),
        "feats": feats,
        "fixes": fixes,
        "otros": otros,
        "modulos": modulos_sorted,
    }
