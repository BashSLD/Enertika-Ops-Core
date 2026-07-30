"""Validacion criptografica de releases del lanzador local CFE."""
from __future__ import annotations

import base64
import binascii
import json
import re
import secrets
from datetime import date

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PublicKey,
)

LAUNCHER_MANIFEST_SCHEMA = 1
MAX_LAUNCHER_BYTES = 100 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_VERSION_RE = re.compile(
    r"\d{4}(?:\.\d{2}\.\d{2}|-\d{2}-\d{2})(?:\.\d{1,3})?"
)
_MANIFEST_FIELDS = {"schema", "filename", "version", "size", "sha256", "signature"}


def _canonical_payload(payload: dict) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def validate_launcher_public_key(public_key_pem: str) -> str:
    """Valida que sea una clave publica PEM Ed25519 y retorna PEM normalizado."""
    try:
        raw = (public_key_pem or "").strip().encode("ascii", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("La clave pública del lanzador debe estar en formato PEM ASCII.") from exc
    if not raw:
        raise ValueError("Captura la clave pública Ed25519 del lanzador.")
    try:
        public_key = serialization.load_pem_public_key(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("La clave pública del lanzador no es un PEM válido.") from exc
    if not isinstance(public_key, Ed25519PublicKey):
        raise ValueError("La clave pública del lanzador debe ser Ed25519.")
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def launcher_version_key(version: str) -> tuple[int, int, int, int]:
    """Convierte YYYY.MM.DD[.N] o el formato legacy YYYY-MM-DD a una clave ordenable."""
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        raise ValueError("La versión del lanzador es inválida.")
    parts = version.replace("-", ".").split(".")
    year, month, day = (int(part) for part in parts[:3])
    try:
        date(year, month, day)
    except ValueError as exc:
        raise ValueError("La versión del lanzador contiene una fecha inválida.") from exc
    revision = int(parts[3]) if len(parts) == 4 else 0
    return year, month, day, revision


def require_newer_launcher_version(version: str, current_version: str) -> None:
    """Impide republicar o retroceder a un release firmado anterior."""
    new_key = launcher_version_key(version)
    if current_version and new_key <= launcher_version_key(current_version):
        raise ValueError(
            "La versión del lanzador debe ser posterior a la publicada actualmente."
        )


def launcher_storage_filename(version: str, sha256_hex: str) -> str:
    """Nombre inmutable para evitar reemplazar el release vigente en SharePoint."""
    launcher_version_key(version)
    normalized_sha256 = (sha256_hex or "").lower()
    if not _SHA256_RE.fullmatch(normalized_sha256):
        raise ValueError("El SHA-256 del lanzador es inválido.")
    return f"RenovarSesionCFE_{version}_{normalized_sha256[:12]}.exe"


def verify_launcher_manifest(
    manifest_bytes: bytes,
    *,
    public_key_pem: str,
    actual_filename: str,
    actual_size: int,
    actual_sha256: str,
) -> dict:
    """Verifica estructura, hash, tamaño, nombre y firma Ed25519 del manifiesto."""
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("El manifiesto del lanzador no es un JSON válido.") from exc
    if not isinstance(manifest, dict):
        raise ValueError("El manifiesto del lanzador debe ser un objeto JSON.")
    if set(manifest) != _MANIFEST_FIELDS:
        raise ValueError("El manifiesto del lanzador contiene campos inválidos.")

    signature_b64 = manifest.get("signature")
    payload = {
        "schema": manifest.get("schema"),
        "filename": manifest.get("filename"),
        "version": manifest.get("version"),
        "size": manifest.get("size"),
        "sha256": manifest.get("sha256"),
    }

    if payload["schema"] != LAUNCHER_MANIFEST_SCHEMA:
        raise ValueError("La versión del manifiesto del lanzador no es compatible.")
    if (
        not isinstance(payload["filename"], str)
        or "/" in payload["filename"]
        or "\\" in payload["filename"]
        or not payload["filename"].lower().endswith(".exe")
    ):
        raise ValueError("El nombre del ejecutable en el manifiesto es inválido.")
    try:
        launcher_version_key(payload["version"])
    except ValueError as exc:
        raise ValueError("La versión del lanzador en el manifiesto es inválida.") from exc
    if not isinstance(payload["size"], int) or payload["size"] <= 0:
        raise ValueError("El tamaño del lanzador en el manifiesto es inválido.")
    if not isinstance(payload["sha256"], str):
        raise ValueError("El SHA-256 del lanzador en el manifiesto es inválido.")

    manifest_sha256 = payload["sha256"].lower()
    if not _SHA256_RE.fullmatch(manifest_sha256):
        raise ValueError("El SHA-256 del lanzador en el manifiesto es inválido.")
    if payload["filename"].casefold() != actual_filename.casefold():
        raise ValueError("El nombre del ejecutable no coincide con el manifiesto firmado.")
    if payload["size"] != actual_size:
        raise ValueError("El tamaño del ejecutable no coincide con el manifiesto firmado.")
    if not secrets.compare_digest(manifest_sha256, actual_sha256.lower()):
        raise ValueError("El SHA-256 del ejecutable no coincide con el manifiesto firmado.")
    if not isinstance(signature_b64, str):
        raise ValueError("El manifiesto no contiene una firma Ed25519.")

    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("La firma del manifiesto no está codificada correctamente.") from exc

    normalized_pem = validate_launcher_public_key(public_key_pem)
    public_key = serialization.load_pem_public_key(normalized_pem.encode("ascii"))
    try:
        public_key.verify(signature, _canonical_payload(payload))
    except InvalidSignature as exc:
        raise ValueError("La firma Ed25519 del lanzador no es válida.") from exc

    payload["sha256"] = manifest_sha256
    return payload
