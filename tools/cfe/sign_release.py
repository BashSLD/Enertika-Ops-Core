#!/usr/bin/env python3
"""Genera claves Ed25519 y firma manifests de releases del lanzador CFE."""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_VERSION_RE = re.compile(
    r"\d{4}(?:\.\d{2}\.\d{2}|-\d{2}-\d{2})(?:\.\d{1,3})?"
)


def _canonical_payload(payload: dict) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _read_password(*, confirm: bool = False) -> bytes:
    value = os.getenv("CFE_SIGNING_KEY_PASSWORD")
    if value:
        return value.encode("utf-8")
    password = getpass.getpass("Password de la clave privada Ed25519: ")
    if not password:
        raise ValueError("La clave privada debe protegerse con password.")
    if confirm:
        repeated = getpass.getpass("Confirma el password: ")
        if password != repeated:
            raise ValueError("Los passwords no coinciden.")
    return password.encode("utf-8")


def _validate_version(version: str) -> None:
    if not _VERSION_RE.fullmatch(version):
        raise ValueError("La version debe usar el formato YYYY.MM.DD o YYYY.MM.DD.N.")
    parts = version.replace("-", ".").split(".")
    try:
        date(*(int(part) for part in parts[:3]))
    except ValueError as exc:
        raise ValueError("La version contiene una fecha invalida.") from exc


def generate_keypair(private_key_path: Path, public_key_path: Path) -> None:
    if private_key_path.exists() or public_key_path.exists():
        raise ValueError("Los archivos de clave ya existen; no se sobrescribieron.")
    private_key = Ed25519PrivateKey.generate()
    password = _read_password(confirm=True)
    private_key_path.parent.mkdir(parents=True, exist_ok=True)
    public_key_path.parent.mkdir(parents=True, exist_ok=True)
    private_key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.BestAvailableEncryption(password),
        )
    )
    public_key_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    print(f"Clave privada creada: {private_key_path}")
    print(f"Clave publica creada: {public_key_path}")


def sign_release(
    executable_path: Path,
    private_key_path: Path,
    version: str,
    output_path: Path,
) -> None:
    if not executable_path.is_file():
        raise ValueError(f"No existe el ejecutable: {executable_path}")
    if not private_key_path.is_file():
        raise ValueError(f"No existe la clave privada: {private_key_path}")
    _validate_version(version)

    executable_bytes = executable_path.read_bytes()
    payload = {
        "schema": 1,
        "filename": executable_path.name,
        "version": version,
        "size": len(executable_bytes),
        "sha256": hashlib.sha256(executable_bytes).hexdigest(),
    }
    private_key = serialization.load_pem_private_key(
        private_key_path.read_bytes(),
        password=_read_password(),
    )
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("La clave privada debe ser Ed25519.")

    signature = private_key.sign(_canonical_payload(payload))
    manifest = {
        **payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    output_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(f"Manifest firmado: {output_path}")
    print(f"SHA-256: {payload['sha256']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate-keypair")
    generate.add_argument("--private-key", type=Path, required=True)
    generate.add_argument("--public-key", type=Path, required=True)

    sign = subparsers.add_parser("sign")
    sign.add_argument("--exe", type=Path, required=True)
    sign.add_argument("--private-key", type=Path, required=True)
    sign.add_argument("--version", required=True)
    sign.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "generate-keypair":
            generate_keypair(args.private_key, args.public_key)
        else:
            sign_release(args.exe, args.private_key, args.version, args.output)
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
