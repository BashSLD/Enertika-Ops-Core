import os
import re
import shutil
import subprocess
import json
from urllib import request, parse
from datetime import date, datetime, timedelta
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


def _semana_actual() -> tuple[datetime, datetime]:
    """Ventana de fetch: viernes anterior 18:00 MX → este viernes 18:00 MX (exclusivo)."""
    mx = ZoneInfo("America/Mexico_City")
    now = datetime.now(mx)
    today = now.date()
    dias_desde_viernes = (today.weekday() - 4) % 7
    viernes_actual = today - timedelta(days=dias_desde_viernes)
    viernes_anterior = viernes_actual - timedelta(days=7)
    since = datetime(viernes_anterior.year, viernes_anterior.month, viernes_anterior.day,
                     18, 0, 0, tzinfo=mx)
    until = datetime(viernes_actual.year, viernes_actual.month, viernes_actual.day,
                     18, 0, 0, tzinfo=mx)
    return since, until


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


def _read_commits_github(since, until) -> list[str]:
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

    utc = ZoneInfo("UTC")
    mx = ZoneInfo("America/Mexico_City")

    if isinstance(since, datetime):
        since_iso = since.astimezone(utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        since_iso = datetime(since.year, since.month, since.day, 0, 0, 0, tzinfo=mx).astimezone(utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if isinstance(until, datetime):
        until_iso = until.astimezone(utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        until_inclusive = until - timedelta(days=1)
        until_iso = datetime(until_inclusive.year, until_inclusive.month, until_inclusive.day, 23, 59, 59, tzinfo=mx).astimezone(utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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


def get_weekly_commits(since=None, until=None) -> dict:
    """
    Lee commits de la semana actual (o del rango dado) y los agrupa por módulo.

    Retorna:
        semana_inicio: date  — lunes de la semana (display)
        semana_fin: date     — viernes de la semana (display)
        total_commits: int
        feats: int
        fixes: int
        otros: int
        modulos: dict[str, list[dict]]  — solo feat/fix/perf/refactor
    """
    display_since: date
    display_until: date

    if not since:
        since, until = _semana_actual()
        # Display: lunes–viernes de la semana actual, independiente de la ventana de fetch
        mx = ZoneInfo("America/Mexico_City")
        today = datetime.now(mx).date()
        display_since = today - timedelta(days=today.weekday())      # lunes
        display_until = display_since + timedelta(days=4)            # viernes
    else:
        display_since = since.date() if isinstance(since, datetime) else since
        display_until = (until.date() - timedelta(days=1)) if isinstance(until, datetime) else until - timedelta(days=1)

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
        "semana_inicio": display_since,
        "semana_fin": display_until,
        "total_commits": len(raw_commits),
        "feats": feats,
        "fixes": fixes,
        "otros": otros,
        "modulos": modulos_sorted,
    }
