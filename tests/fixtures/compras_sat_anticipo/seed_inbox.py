import argparse
import asyncio
import logging
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import asyncpg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
sys.path.append(str(ROOT))

load_dotenv()

from core.database import close_db_connection, connect_to_db, get_db_pool
from core.integrations.sharepoint import SharePointService
from core.microsoft import get_ms_auth
from modules.compras import sat_db_service
from core.cfdi.extractor import parse_cfdi_xml

logger = logging.getLogger("SeedComprasSatAnticipos")

FIXTURE_DIR = Path(__file__).resolve().parent
JOB_ID = UUID("20000000-0000-4000-8000-000000000001")

PROVEEDOR_RFC = "PAT2605015A1"
PROVEEDOR_NOMBRE = "PROVEEDOR ANTICIPOS TEST SA DE CV"
ANTICIPO_RELACION_UUID = UUID("10000006-0000-4000-8000-0000000000A6")

INBOX_FIXTURES = [
    ("05_anticipo.xml", "ANTICIPO"),
    ("06_cierre_anticipo_relacion_07.xml", "CIERRE_ANTICIPO"),
    ("07_cierre_anticipo_sin_07.xml", "CIERRE_ANTICIPO"),
    ("08_cierre_anticipo_sin_07_pendiente.xml", "CIERRE_ANTICIPO"),
]

COMPROBANTES = [
    {
        "id": UUID("30000005-0000-4000-8000-000000000005"),
        "fecha_pago": date(2026, 5, 1),
        "beneficiario": "CASO 5 PENDIENTE ANTICIPO TEST",
        "monto": Decimal("11600.00"),
        "estatus": "PENDIENTE",
        "monto_facturado": Decimal("0.00"),
        "uuid_factura": None,
        "es_anticipo": False,
        "tipo_factura": "NORMAL",
    },
    {
        "id": UUID("30000015-0000-4000-8000-000000000015"),
        "fecha_pago": date(2026, 5, 2),
        "beneficiario": "CASO 5 PARCIAL ANTICIPO TEST",
        "monto": Decimal("21600.00"),
        "estatus": "PARCIALMENTE_FACTURADO",
        "monto_facturado": Decimal("10000.00"),
        "uuid_factura": None,
        "es_anticipo": False,
        "tipo_factura": "NORMAL",
    },
    {
        "id": UUID("30000025-0000-4000-8000-000000000025"),
        "fecha_pago": date(2026, 5, 3),
        "beneficiario": "CASO 5 ANTICIPO ABIERTO TEST",
        "monto": Decimal("31600.00"),
        "estatus": "ANTICIPO",
        "monto_facturado": Decimal("11600.00"),
        "uuid_factura": None,
        "es_anticipo": True,
        "tipo_factura": "ANTICIPO",
    },
    {
        "id": UUID("30000006-0000-4000-8000-000000000006"),
        "fecha_pago": date(2026, 5, 6),
        "beneficiario": "CASO 6 ANTICIPO RELACION 07 TEST",
        "monto": Decimal("6006.00"),
        "estatus": "ANTICIPO",
        "monto_facturado": Decimal("6006.00"),
        "uuid_factura": ANTICIPO_RELACION_UUID,
        "es_anticipo": True,
        "tipo_factura": "ANTICIPO",
    },
    {
        "id": UUID("30000007-0000-4000-8000-000000000007"),
        "fecha_pago": date(2026, 5, 7),
        "beneficiario": "CASO 7 ANTICIPO FALLBACK TEST",
        "monto": Decimal("7007.00"),
        "estatus": "ANTICIPO",
        "monto_facturado": Decimal("7007.00"),
        "uuid_factura": None,
        "es_anticipo": True,
        "tipo_factura": "ANTICIPO",
    },
    {
        "id": UUID("30000008-0000-4000-8000-000000000008"),
        "fecha_pago": date(2026, 5, 8),
        "beneficiario": "CASO 8 ANTICIPO PARCIAL TEST",
        "monto": Decimal("11600.00"),
        "estatus": "ANTICIPO",
        "monto_facturado": Decimal("11600.00"),
        "uuid_factura": None,
        "es_anticipo": True,
        "tipo_factura": "ANTICIPO",
    },
]


def _rows_affected(result: str) -> int:
    try:
        return int(result.split()[-1])
    except (AttributeError, IndexError, ValueError):
        return 0


def load_fixture_uuids(fixtures_dir: Path) -> list[str]:
    uuids = []
    for filename, _tipo_detectado in INBOX_FIXTURES:
        cfdi = parse_cfdi_xml((fixtures_dir / filename).read_bytes(), filename)
        uuids.append(cfdi.uuid)
    return uuids


async def get_user_id(conn: asyncpg.Connection, email: str) -> UUID:
    row = await conn.fetchrow(
        """
        SELECT id_usuario
        FROM tb_usuarios
        WHERE email = $1 AND is_active = true
        """,
        email,
    )
    if not row:
        raise ValueError(f"No existe usuario activo con email {email}")
    return row["id_usuario"]


async def upsert_proveedor(conn: asyncpg.Connection) -> UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO tb_proveedores (rfc, razon_social, nombre_comercial, activo, created_at, updated_at)
        VALUES ($1, $2, $2, true, NOW(), NOW())
        ON CONFLICT (rfc) DO UPDATE SET
            razon_social = EXCLUDED.razon_social,
            nombre_comercial = EXCLUDED.nombre_comercial,
            activo = true,
            updated_at = NOW()
        RETURNING id_proveedor
        """,
        PROVEEDOR_RFC,
        PROVEEDOR_NOMBRE,
    )
    return row["id_proveedor"]


async def upsert_comprobantes(conn: asyncpg.Connection, id_proveedor: UUID, user_id: UUID) -> None:
    for comp in COMPROBANTES:
        await conn.execute(
            """
            INSERT INTO tb_comprobantes_pago (
                id_comprobante, fecha_pago, beneficiario_orig, monto, moneda,
                id_proveedor, estatus, uuid_factura, capturado_por_id,
                es_anticipo, tipo_factura, monto_facturado,
                id_comprobante_anticipo, created_at, updated_at
            )
            VALUES ($1,$2,$3,$4,'MXN',$5,$6,$7,$8,$9,$10,$11,NULL,NOW(),NOW())
            ON CONFLICT (id_comprobante) DO UPDATE SET
                fecha_pago = EXCLUDED.fecha_pago,
                beneficiario_orig = EXCLUDED.beneficiario_orig,
                monto = EXCLUDED.monto,
                moneda = EXCLUDED.moneda,
                id_proveedor = EXCLUDED.id_proveedor,
                estatus = EXCLUDED.estatus,
                uuid_factura = EXCLUDED.uuid_factura,
                capturado_por_id = EXCLUDED.capturado_por_id,
                es_anticipo = EXCLUDED.es_anticipo,
                tipo_factura = EXCLUDED.tipo_factura,
                monto_facturado = EXCLUDED.monto_facturado,
                id_comprobante_anticipo = NULL,
                updated_at = NOW()
            """,
            comp["id"],
            comp["fecha_pago"],
            comp["beneficiario"],
            comp["monto"],
            id_proveedor,
            comp["estatus"],
            comp["uuid_factura"],
            user_id,
            comp["es_anticipo"],
            comp["tipo_factura"],
            comp["monto_facturado"],
        )
        logger.info("Comprobante fixture listo: %s %s", comp["id"], comp["estatus"])


async def reset_fixture_data(
    conn: asyncpg.Connection,
    id_proveedor: UUID,
    fixture_uuid_texts: list[str],
) -> None:
    fixture_uuids = [UUID(uuid_text) for uuid_text in fixture_uuid_texts]
    comprobante_ids = [comp["id"] for comp in COMPROBANTES]
    comprobante_id_texts = [str(comp_id) for comp_id in comprobante_ids]
    beneficiarios = [comp["beneficiario"] for comp in COMPROBANTES] + [PROVEEDOR_NOMBRE]

    logger.info(
        "Reset fixtures compras SAT anticipos: %d UUIDs, %d comprobantes",
        len(fixture_uuid_texts),
        len(comprobante_ids),
    )

    result = await conn.execute(
        """
        UPDATE tb_documentos_attachments
        SET activo = false
        WHERE origen_slug = 'factura_xml'
          AND activo = true
          AND (
              metadata->>'uuid_factura' = ANY($1::text[])
              OR metadata->>'id_comprobante' = ANY($2::text[])
          )
        """,
        fixture_uuid_texts,
        comprobante_id_texts,
    )
    logger.info("Attachments factura_xml desactivados: %s", _rows_affected(result))

    result = await conn.execute(
        """
        DELETE FROM tb_cfdi_relacionados
        WHERE uuid_factura = ANY($1::uuid[])
           OR uuid_relacionado = ANY($1::uuid[])
        """,
        fixture_uuids,
    )
    logger.info("CFDI relacionados eliminados: %s", _rows_affected(result))

    result = await conn.execute(
        """
        DELETE FROM tb_materiales_historial
        WHERE uuid_factura = ANY($1::uuid[])
           OR id_comprobante = ANY($2::uuid[])
        """,
        fixture_uuids,
        comprobante_ids,
    )
    logger.info("Materiales historial eliminados: %s", _rows_affected(result))

    result = await conn.execute(
        """
        DELETE FROM tb_comprobante_facturas
        WHERE uuid_factura = ANY($1::text[])
           OR id_comprobante = ANY($2::uuid[])
        """,
        fixture_uuid_texts,
        comprobante_ids,
    )
    logger.info("Vinculos comprobante-factura eliminados: %s", _rows_affected(result))

    result = await conn.execute(
        """
        DELETE FROM tb_xml_staging
        WHERE uuid_factura = ANY($1::text[])
        """,
        fixture_uuid_texts,
    )
    logger.info("XML staging eliminado: %s", _rows_affected(result))

    result = await conn.execute(
        """
        DELETE FROM tb_sat_inbox
        WHERE uuid_cfdi = ANY($1::text[])
           OR job_id = $2
        """,
        fixture_uuid_texts,
        JOB_ID,
    )
    logger.info("SAT inbox fixture eliminado: %s", _rows_affected(result))

    result = await conn.execute(
        """
        DELETE FROM tb_beneficiario_proveedor
        WHERE id_proveedor = $1
          AND beneficiario_nombre = ANY($2::text[])
        """,
        id_proveedor,
        beneficiarios,
    )
    logger.info("Relaciones beneficiario-proveedor fixture eliminadas: %s", _rows_affected(result))

    result = await conn.execute(
        """
        UPDATE tb_comprobantes_pago
        SET id_comprobante_anticipo = NULL,
            uuid_factura = NULL,
            monto_facturado = 0,
            estatus = 'PENDIENTE',
            es_anticipo = false,
            tipo_factura = 'NORMAL',
            updated_at = NOW()
        WHERE id_comprobante = ANY($1::uuid[])
        """,
        comprobante_ids,
    )
    logger.info("Comprobantes fixture limpiados: %s", _rows_affected(result))


async def upsert_job(conn: asyncpg.Connection, user_id: UUID) -> None:
    await conn.execute(
        """
        INSERT INTO tb_sat_jobs (
            id, estado, empresa, fecha_inicio_rango, fecha_fin_rango,
            cfdi_encontrados, cfdi_duplicados, creado_por, created_at, updated_at
        )
        VALUES ($1, 'completado', 'ISA', $2, $3, $4, 0, $5, NOW(), NOW())
        ON CONFLICT (id) DO UPDATE SET
            estado = EXCLUDED.estado,
            fecha_inicio_rango = EXCLUDED.fecha_inicio_rango,
            fecha_fin_rango = EXCLUDED.fecha_fin_rango,
            cfdi_encontrados = EXCLUDED.cfdi_encontrados,
            creado_por = EXCLUDED.creado_por,
            updated_at = NOW()
        """,
        JOB_ID,
        date(2026, 5, 1),
        date(2026, 5, 4),
        len(INBOX_FIXTURES),
        user_id,
    )


async def upload_xmls(conn: asyncpg.Connection, fixtures_dir: Path) -> dict[str, dict]:
    sat_site_id, sat_drive_id, base_folder = await sat_db_service.get_sat_sp_config(conn)
    token = await get_ms_auth().get_application_token()
    if not token:
        raise RuntimeError("No se pudo obtener token de aplicacion Microsoft")

    sp = SharePointService(access_token=token)
    sp.site_id = sat_site_id
    sp.drive_id = sat_drive_id

    folder = f"{base_folder}/ISA/fixtures-anticipos"
    uploaded = {}
    for filename, _tipo_detectado in INBOX_FIXTURES:
        path = fixtures_dir / filename
        content = path.read_bytes()
        cfdi = parse_cfdi_xml(content, filename)
        result = await sp.upload_bytes_direct(content, f"{cfdi.uuid}.xml", folder)
        uploaded[filename] = {
            "cfdi": cfdi,
            "sharepoint_url": result.get("webUrl") or "",
            "sharepoint_item_id": result.get("id"),
        }
        logger.info("XML subido a SharePoint: %s -> %s", filename, result.get("id"))
    return uploaded


async def upsert_inbox(conn: asyncpg.Connection, uploaded: dict[str, dict]) -> None:
    for filename, tipo_detectado in INBOX_FIXTURES:
        item = uploaded[filename]
        cfdi = item["cfdi"]
        fecha_cfdi = date.fromisoformat(cfdi.fecha[:10]) if cfdi.fecha else None
        await conn.execute(
            """
            INSERT INTO tb_sat_inbox (
                job_id, uuid_cfdi, rfc_emisor, nombre_emisor, fecha_cfdi,
                total, moneda, sharepoint_url, sharepoint_item_id, estado,
                tipo_detectado, created_at, updated_at
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'pendiente',$10,NOW(),NOW())
            ON CONFLICT (uuid_cfdi) DO UPDATE SET
                job_id = EXCLUDED.job_id,
                rfc_emisor = EXCLUDED.rfc_emisor,
                nombre_emisor = EXCLUDED.nombre_emisor,
                fecha_cfdi = EXCLUDED.fecha_cfdi,
                total = EXCLUDED.total,
                moneda = EXCLUDED.moneda,
                sharepoint_url = EXCLUDED.sharepoint_url,
                sharepoint_item_id = EXCLUDED.sharepoint_item_id,
                estado = 'pendiente',
                comprobante_id = NULL,
                tipo_detectado = EXCLUDED.tipo_detectado,
                updated_at = NOW()
            """,
            JOB_ID,
            cfdi.uuid,
            cfdi.emisor_rfc,
            cfdi.emisor_nombre,
            fecha_cfdi,
            cfdi.total,
            cfdi.moneda,
            item["sharepoint_url"],
            item["sharepoint_item_id"],
            tipo_detectado,
        )
        logger.info("Inbox fixture listo: %s tipo_detectado=%s", cfdi.uuid, tipo_detectado)


async def seed(args: argparse.Namespace) -> None:
    fixtures_dir = Path(args.fixtures_dir).resolve() if args.fixtures_dir else FIXTURE_DIR
    if not fixtures_dir.exists():
        raise FileNotFoundError(f"No existe fixtures_dir: {fixtures_dir}")

    await connect_to_db()
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            user_id = await get_user_id(conn, args.user_email)
            id_proveedor = await upsert_proveedor(conn)
            fixture_uuids = load_fixture_uuids(fixtures_dir)
            async with conn.transaction():
                if args.reset:
                    await reset_fixture_data(conn, id_proveedor, fixture_uuids)
                await upsert_comprobantes(conn, id_proveedor, user_id)
                await upsert_job(conn, user_id)
            uploaded = await upload_xmls(conn, fixtures_dir)
            await upsert_inbox(conn, uploaded)
    finally:
        await close_db_connection()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Carga fixtures XML de SAT Inbox para pruebas de anticipos en Compras."
    )
    parser.add_argument(
        "--user-email",
        required=True,
        help="Email de un usuario activo para creado_por/capturado_por_id.",
    )
    parser.add_argument(
        "--fixtures-dir",
        default=None,
        help="Directorio alterno con los XML. Por defecto usa tests/fixtures/compras_sat_anticipo.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Limpia vinculos y registros generados por estos fixtures antes de cargar de nuevo.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    args = parse_args()
    asyncio.run(seed(args))


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()
