# core/cfdi/service.py
"""Validacion fiscal del receptor de un CFDI contra los datos configurados de la
empresa (tb_config_empresa), y orquestacion de "validar + auditar" compartida
entre modulos (Compras hoy; Finanzas/Construccion como futuros consumidores)."""

from typing import List, Optional
import logging

import asyncpg

from .schemas import CfdiData
from .db_service import get_cfdi_db_service

logger = logging.getLogger("Cfdi.Service")


def validar_datos_fiscales_receptor(
    cfdi: CfdiData,
    empresa: Optional[dict],
    *,
    exigir_uso_cfdi: bool = True,
    exigir_forma_pago: bool = True,
) -> List[tuple[str, str]]:
    """
    Compara los datos fiscales del receptor del XML contra `empresa` (fila de
    `tb_config_empresa`, forma generica -- no asume que el receptor sea Enertika,
    aunque hoy el unico consumidor real lo sea).

    Reglas:
    - RFC/razon social/CP/regimen del receptor deben coincidir exacto (normalizado)
      con los de `empresa`.
    - UsoCFDI: se exige 'G03' salvo en complementos de pago (tipo_comprobante='P'),
      que usan 'CP01' por regla SAT y no se comparan. Se puede desactivar con
      `exigir_uso_cfdi=False` (punto de extension para un futuro consumidor con
      reglas de UsoCFDI distintas -- sin implementar todavia).
    - FormaPago: se exige '03' (transferencia) solo cuando MetodoPago='PUE'. Con
      MetodoPago='PPD' no se valida (FormaPago='99' es correcto en ese caso, la
      transferencia real llega despues via complemento de pago). Se puede
      desactivar con `exigir_forma_pago=False` (mismo motivo que arriba).
    - Si `empresa` es None o su RFC sigue en el placeholder sembrado
      ('PENDIENTE_CONFIGURAR'), no hay nada contra que comparar: retorna lista
      vacia sin evaluar nada (antes duplicado con variantes distintas en cada
      caller; ahora centralizado aqui).

    Returns:
        Lista de (tipo_error, mensaje) por cada mismatch encontrado; vacia si todo OK.
    """
    if not empresa or (empresa.get("rfc") or "") == "PENDIENTE_CONFIGURAR":
        return []

    errores: List[tuple[str, str]] = []

    rfc_empresa = (empresa.get("rfc") or "").strip().upper()
    razon_empresa = (empresa.get("razon_social") or "").strip().upper()
    cp_empresa = (empresa.get("codigo_postal") or "").strip()
    regimen_empresa = (empresa.get("regimen_fiscal") or "").strip()
    nombre_empresa = empresa.get("razon_social") or "la empresa configurada"

    receptor_rfc = (cfdi.receptor_rfc or "").strip().upper()
    if receptor_rfc and receptor_rfc != rfc_empresa:
        errores.append((
            "RFC_RECEPTOR",
            f"RFC receptor ({receptor_rfc}) no coincide con {nombre_empresa} ({rfc_empresa})",
        ))

    receptor_nombre = (cfdi.receptor_nombre or "").strip().upper()
    if receptor_nombre and razon_empresa and receptor_nombre != razon_empresa:
        errores.append((
            "RAZON_SOCIAL_RECEPTOR",
            f"Razon social receptor ({cfdi.receptor_nombre}) no coincide con {nombre_empresa}",
        ))

    receptor_cp = (cfdi.receptor_cp or "").strip()
    if receptor_cp and cp_empresa and receptor_cp != cp_empresa:
        errores.append((
            "CP_RECEPTOR",
            f"CP receptor ({receptor_cp}) no coincide con {nombre_empresa} ({cp_empresa})",
        ))

    receptor_regimen = (cfdi.receptor_regimen_fiscal or "").strip()
    if receptor_regimen and regimen_empresa and receptor_regimen != regimen_empresa:
        errores.append((
            "REGIMEN_RECEPTOR",
            f"Regimen fiscal receptor ({receptor_regimen}) no coincide con {nombre_empresa} ({regimen_empresa})",
        ))

    if exigir_uso_cfdi and cfdi.tipo_comprobante != "P":
        uso_cfdi = (cfdi.uso_cfdi or "").strip().upper()
        if uso_cfdi and uso_cfdi != "G03":
            errores.append((
                "USO_CFDI",
                f"UsoCFDI ({uso_cfdi}) distinto de G03 esperado para facturas a {nombre_empresa}",
            ))

    if exigir_forma_pago and cfdi.metodo_pago == "PUE":
        forma_pago = (cfdi.forma_pago or "").strip()
        if forma_pago and forma_pago != "03":
            errores.append((
                "FORMA_PAGO",
                f"FormaPago ({forma_pago}) distinta de 03 (transferencia) esperada con MetodoPago=PUE",
            ))

    return errores


async def validar_y_auditar_xml(
    conn,
    cfdi: CfdiData,
    empresa: Optional[dict],
    *,
    modulo_slug: str,
    canal: str,
    uploaded_by_id,
    exigir_uso_cfdi: bool = True,
    exigir_forma_pago: bool = True,
) -> List[tuple[str, str]]:
    """
    Centraliza "validar datos fiscales + registrar auditoria si falla", hoy
    duplicado con variantes ligeras en `procesar_xmls` (Compras, carga manual) y
    `_procesar_match_unico` (Compras, Buzon SAT).

    `empresa` se recibe ya resuelta por el caller (no se relee aqui) para
    preservar el patron de lectura unica antes de un lote (ver
    `_Planes_Activos/2026-08-19-cfdi-servicio-compartido.md`, decision 8): leer
    `tb_config_empresa` una vez por XML agregaria una query por archivo sin
    beneficio real frente al riesgo (tabla singleton, editada casi nunca).

    La funcion sigue siendo agnostica de severidad -- retorna la lista de fallos
    (vacia si todo OK) y nunca lanza; cada caller decide si bloquear o solo
    advertir con el resultado. La insercion de auditoria es best-effort (no
    bloquea el flujo de negocio si falla).

    Returns:
        Lista de (tipo_error, mensaje); vacia si el CFDI paso la validacion.
    """
    fallos = validar_datos_fiscales_receptor(
        cfdi, empresa,
        exigir_uso_cfdi=exigir_uso_cfdi,
        exigir_forma_pago=exigir_forma_pago,
    )
    if not fallos:
        return []

    tipo_error = ",".join(codigo for codigo, _ in fallos)
    detalle = "; ".join(msg for _, msg in fallos)

    db_svc = get_cfdi_db_service()
    try:
        await db_svc.insert_error_fiscal(
            conn,
            archivo=cfdi.archivo,
            uuid_factura=cfdi.uuid,
            emisor_rfc=cfdi.emisor_rfc,
            emisor_nombre=cfdi.emisor_nombre,
            tipo_error=tipo_error,
            detalle=detalle,
            modulo_slug=modulo_slug,
            canal=canal,
            uploaded_by_id=uploaded_by_id,
        )
    except asyncpg.PostgresError:
        logger.exception(
            "No se pudo registrar auditoria de XML con datos fiscales invalidos: %s (modulo=%s)",
            cfdi.archivo, modulo_slug,
        )

    return fallos
