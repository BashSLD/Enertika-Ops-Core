import logging
from dataclasses import dataclass

import asyncpg
from satcfdi.models import Signer

from core.integrations.sharepoint import SharePointService
from core.microsoft import get_ms_auth

logger = logging.getLogger("SATFielLoader")

SAT_EMPRESA = "ISA"


@dataclass
class FielConfig:
    empresa: str
    sp_path_cer: str
    sp_path_key: str
    password_fiel: str


async def cargar_fiel_config(conn: asyncpg.Connection) -> FielConfig:
    """Lee la configuracion FIEL activa de tb_sat_fiel_config."""
    row = await conn.fetchrow(
        "SELECT empresa, sp_path_cer, sp_path_key, password_fiel "
        "FROM tb_sat_fiel_config WHERE activo = TRUE AND empresa = $1 LIMIT 1",
        SAT_EMPRESA,
    )
    if not row:
        raise ValueError("No hay configuracion FIEL activa para ISA en tb_sat_fiel_config")
    if not row["sp_path_cer"] or not row["sp_path_key"] or not row["password_fiel"]:
        raise ValueError("Configuracion FIEL incompleta: falta ruta .cer, .key o contrasena")
    return FielConfig(
        empresa=row["empresa"],
        sp_path_cer=row["sp_path_cer"],
        sp_path_key=row["sp_path_key"],
        password_fiel=row["password_fiel"],
    )


async def cargar_signer(conn: asyncpg.Connection, sat_site_id: str, sat_drive_id: str) -> Signer:
    """
    Carga el Signer de satcfdi en memoria desde SharePoint SAT site.
    Nunca escribe archivos a disco.
    sat_site_id / sat_drive_id: credenciales del site SAT privado.
    """
    config = await cargar_fiel_config(conn)

    token = await get_ms_auth().get_application_token()
    if not token:
        raise ValueError("No se pudo obtener token de aplicacion Microsoft para SharePoint SAT")

    sp = SharePointService(access_token=token)
    sp.site_id = sat_site_id
    sp.drive_id = sat_drive_id

    logger.info("Descargando FIEL ISA desde SharePoint SAT site")
    cer_bytes = await sp.download_file_by_path(config.sp_path_cer)
    key_bytes = await sp.download_file_by_path(config.sp_path_key)

    signer = Signer.load(
        certificate=cer_bytes,
        key=key_bytes,
        password=config.password_fiel.encode(),
    )
    logger.info("FIEL cargada correctamente - RFC: %s", signer.rfc)
    return signer


async def probar_conexion_fiel(conn: asyncpg.Connection, sat_site_id: str, sat_drive_id: str) -> str:
    """
    Verifica que la FIEL se puede cargar correctamente.
    Retorna el RFC detectado o lanza ValueError con el motivo del fallo.
    """
    signer = await cargar_signer(conn, sat_site_id, sat_drive_id)
    return signer.rfc
