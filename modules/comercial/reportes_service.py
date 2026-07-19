"""Filtros, limites operativos y armado del DTO del reporte de clientes de Comercial."""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional
from uuid import UUID

import asyncpg

from core.config_service import ConfigService
from core.timezone import MX_TZ, today_mx
from modules.rrhh.excel_utils import format_date

from . import reportes_db_service as db

logger = logging.getLogger("ComercialReportes")

LIMITE_SOLICITUDES = "comercial.reporte_clientes_max_solicitudes"
LIMITE_CLIENTES_EXCEL = "comercial.reporte_clientes_max_clientes_excel"
LIMITE_FILAS_DETALLE = "comercial.reporte_clientes_max_filas_detalle"
LIMITE_CLIENTES_PDF = "comercial.reporte_clientes_max_clientes_pdf"
LIMITE_FILAS_DETALLE_PDF = "comercial.reporte_clientes_max_filas_detalle_pdf"

_DEFAULT_LIMITE_SOLICITUDES = 10_000
_DEFAULT_LIMITE_CLIENTES_EXCEL = 10_000
_DEFAULT_LIMITE_FILAS_DETALLE = 10_000
_DEFAULT_LIMITE_CLIENTES_PDF = 1_000
_DEFAULT_LIMITE_FILAS_DETALLE_PDF = 1_000

_LIMITES_RESUMEN_CLIENTES = {
    "pdf": (LIMITE_CLIENTES_PDF, _DEFAULT_LIMITE_CLIENTES_PDF),
    "excel": (LIMITE_CLIENTES_EXCEL, _DEFAULT_LIMITE_CLIENTES_EXCEL),
}
_LIMITES_FILAS_DETALLE = {
    "pdf": (LIMITE_FILAS_DETALLE_PDF, _DEFAULT_LIMITE_FILAS_DETALLE_PDF),
    "excel": (LIMITE_FILAS_DETALLE, _DEFAULT_LIMITE_FILAS_DETALLE),
}


@dataclass
class FiltrosReporteClientes:
    filtro_tipo_id: Optional[int] = None
    filtro_tecnologia_id: Optional[int] = None
    filtro_estatus_id: Optional[int] = None
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    filtro_cliente_id: Optional[UUID] = None
    solo_activos: bool = False


def _describir_vista(solo_activos: bool) -> str:
    """Etiqueta legible del modo de vista del resumen general."""
    if solo_activos:
        return "Vista: solo clientes con actividad en el rango"
    return "Vista: todos los clientes (incluye sin actividad en el rango)"


def defaults_fecha_reporte() -> tuple[date, date]:
    """Rango sugerido para el panel: 1 de enero MX del anio actual hasta hoy MX."""
    hoy = today_mx()
    return date(hoy.year, 1, 1), hoy


def _parse_fecha(valor: Optional[str], nombre_campo: str) -> Optional[date]:
    if not valor or not valor.strip():
        return None
    try:
        return datetime.strptime(valor.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{nombre_campo} invalida, formato esperado YYYY-MM-DD") from exc


def parse_filtros_reporte_clientes(
    *,
    filtro_tipo_id: Optional[int] = None,
    filtro_tecnologia_id: Optional[int] = None,
    filtro_estatus_id: Optional[int] = None,
    filtro_fecha_inicio: Optional[str] = None,
    filtro_fecha_fin: Optional[str] = None,
    filtro_cliente_id: Optional[UUID] = None,
    solo_activos: bool = False,
) -> FiltrosReporteClientes:
    fecha_inicio = _parse_fecha(filtro_fecha_inicio, "filtro_fecha_inicio")
    fecha_fin = _parse_fecha(filtro_fecha_fin, "filtro_fecha_fin")
    if fecha_inicio and fecha_fin and fecha_inicio > fecha_fin:
        raise ValueError("filtro_fecha_inicio no puede ser posterior a filtro_fecha_fin")
    if solo_activos and filtro_cliente_id:
        raise ValueError("solo_activos no aplica cuando se especifica un cliente")
    return FiltrosReporteClientes(
        filtro_tipo_id=filtro_tipo_id,
        filtro_tecnologia_id=filtro_tecnologia_id,
        filtro_estatus_id=filtro_estatus_id,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        filtro_cliente_id=filtro_cliente_id,
        solo_activos=solo_activos,
    )


def _limites_timestamptz(filtros: FiltrosReporteClientes) -> tuple[Optional[datetime], Optional[datetime]]:
    """Convierte el rango civil MX [inicio, fin] a limites timestamptz [inicio, fin+1d) para filtrar por indice."""
    inicio_mx = (
        datetime.combine(filtros.fecha_inicio, time.min, tzinfo=MX_TZ)
        if filtros.fecha_inicio else None
    )
    fin_mx_exclusive = (
        datetime.combine(filtros.fecha_fin + timedelta(days=1), time.min, tzinfo=MX_TZ)
        if filtros.fecha_fin else None
    )
    return inicio_mx, fin_mx_exclusive


async def _verificar_limite(
    conn: asyncpg.Connection,
    *,
    clave: str,
    default: int,
    total: int,
    mensaje_base: str,
    sugerencia: str,
) -> None:
    """Consulta el limite configurado y lanza ValueError si `total` lo rebasa."""
    limite = await ConfigService.get_global_config(conn, clave, default, tipo=int)
    if total > limite:
        raise ValueError(f"{mensaje_base} ({total} > {limite}). {sugerencia}")


async def describir_filtros(conn: asyncpg.Connection, filtros: FiltrosReporteClientes) -> str:
    """Resumen legible de los filtros aplicados, para el encabezado del PDF."""
    etiquetas = await db.obtener_etiquetas_filtros(
        conn,
        filtro_tipo_id=filtros.filtro_tipo_id,
        filtro_tecnologia_id=filtros.filtro_tecnologia_id,
        filtro_estatus_id=filtros.filtro_estatus_id,
        filtro_cliente_id=filtros.filtro_cliente_id,
    )
    partes = []
    if filtros.fecha_inicio or filtros.fecha_fin:
        partes.append(
            f"Fechas: {format_date(filtros.fecha_inicio) or 'inicio'} a {format_date(filtros.fecha_fin) or 'hoy'}"
        )
    else:
        partes.append("Fechas: histórico completo")

    for filtro_id, etiqueta_clave, label in (
        (filtros.filtro_tipo_id, "tipo_nombre", "Tipo"),
        (filtros.filtro_tecnologia_id, "tecnologia_nombre", "Tecnología"),
        (filtros.filtro_estatus_id, "estatus_nombre", "Estatus Simulación"),
        (filtros.filtro_cliente_id, "cliente_nombre", "Cliente"),
    ):
        if filtro_id:
            partes.append(f"{label}: {etiquetas.get(etiqueta_clave) or filtro_id}")
    if not filtros.filtro_cliente_id:
        partes.append(_describir_vista(filtros.solo_activos))
    return " | ".join(partes)


async def generar_dataset_general(
    conn: asyncpg.Connection,
    filtros: FiltrosReporteClientes,
    *,
    formato: str,
    solicitante_email: str,
) -> dict:
    """Arma el DTO del modo general (resumen por cliente + detalle de solicitudes)."""
    inicio_mx, fin_mx_exclusive = _limites_timestamptz(filtros)

    total_solicitudes = await db.contar_oportunidades_filtradas(
        conn,
        filtro_tipo_id=filtros.filtro_tipo_id,
        filtro_tecnologia_id=filtros.filtro_tecnologia_id,
        filtro_estatus_id=filtros.filtro_estatus_id,
        fecha_inicio_mx=inicio_mx,
        fecha_fin_mx_exclusive=fin_mx_exclusive,
    )
    await _verificar_limite(
        conn,
        clave=LIMITE_SOLICITUDES,
        default=_DEFAULT_LIMITE_SOLICITUDES,
        total=total_solicitudes,
        mensaje_base="El reporte excede el maximo de solicitudes permitido",
        sugerencia="Acota fechas, estatus o usa el modo por cliente.",
    )

    limite_clave, limite_default = _LIMITES_RESUMEN_CLIENTES.get(
        formato, _LIMITES_RESUMEN_CLIENTES["excel"]
    )
    # Con solo_activos=True, contar primero y despues volver a filtrar en obtener_resumen_clientes
    # escanearia tb_oportunidades dos veces para la misma respuesta; se trae el resumen una sola
    # vez y el limite se valida con len() — mismo trade-off ya aceptado en generar_dataset_por_cliente.
    if filtros.solo_activos:
        resumen = await db.obtener_resumen_clientes(
            conn,
            filtro_tipo_id=filtros.filtro_tipo_id,
            filtro_tecnologia_id=filtros.filtro_tecnologia_id,
            filtro_estatus_id=filtros.filtro_estatus_id,
            fecha_inicio_mx=inicio_mx,
            fecha_fin_mx_exclusive=fin_mx_exclusive,
            solo_activos=True,
        )
        total_filas_resumen = len(resumen)
    else:
        # Con solo_activos=False (default), los filtros de solicitud (fecha/tipo/estatus)
        # no reducen el conteo de clientes canonicos sin solicitudes (contar_filas_resumen_general
        # sigue el total de tb_clientes); acotarlos no ayuda a bajar del limite, solo el modo por
        # cliente o marcar solo_activos lo hacen. Aqui el conteo si es mas barato que el fetch
        # (COUNT(*) simple vs. el CTE completo), asi que se mantiene el chequeo previo.
        total_filas_resumen = await db.contar_filas_resumen_general(
            conn,
            filtro_tipo_id=filtros.filtro_tipo_id,
            filtro_tecnologia_id=filtros.filtro_tecnologia_id,
            filtro_estatus_id=filtros.filtro_estatus_id,
            fecha_inicio_mx=inicio_mx,
            fecha_fin_mx_exclusive=fin_mx_exclusive,
        )
        resumen = None

    await _verificar_limite(
        conn,
        clave=limite_clave,
        default=limite_default,
        total=total_filas_resumen,
        mensaje_base=f"El resumen excede el maximo de clientes permitido para {formato.upper()}",
        sugerencia="Usa el modo por cliente.",
    )

    if resumen is None:
        resumen = await db.obtener_resumen_clientes(
            conn,
            filtro_tipo_id=filtros.filtro_tipo_id,
            filtro_tecnologia_id=filtros.filtro_tecnologia_id,
            filtro_estatus_id=filtros.filtro_estatus_id,
            fecha_inicio_mx=inicio_mx,
            fecha_fin_mx_exclusive=fin_mx_exclusive,
            solo_activos=False,
        )
    # El PDF general solo presenta el resumen (ver templates/pdf/comercial/reporte_clientes.html);
    # el detalle de solicitudes es exclusivo de Excel — evita la consulta si no se va a usar.
    detalle = []
    if formato != "pdf":
        detalle = await db.obtener_detalle_general(
            conn,
            filtro_tipo_id=filtros.filtro_tipo_id,
            filtro_tecnologia_id=filtros.filtro_tecnologia_id,
            filtro_estatus_id=filtros.filtro_estatus_id,
            fecha_inicio_mx=inicio_mx,
            fecha_fin_mx_exclusive=fin_mx_exclusive,
        )

    logger.info(
        "Reporte clientes generado (general): solicitante=%s formato=%s con_cliente=False "
        "rango=%s..%s filas_resumen=%d filas_detalle=%d",
        solicitante_email, formato, filtros.fecha_inicio, filtros.fecha_fin, len(resumen), len(detalle),
    )
    return {
        "modo": "general",
        "resumen": resumen,
        "detalle": detalle,
        "filtros": filtros,
        "nota_vista": _describir_vista(filtros.solo_activos),
    }


async def generar_dataset_por_cliente(
    conn: asyncpg.Connection,
    filtros: FiltrosReporteClientes,
    *,
    formato: str,
    solicitante_email: str,
) -> dict:
    """Arma el DTO del modo enfocado por cliente (una fila por sitio/proyecto)."""
    if not filtros.filtro_cliente_id:
        raise ValueError("filtro_cliente_id es obligatorio en el modo enfocado por cliente")

    inicio_mx, fin_mx_exclusive = _limites_timestamptz(filtros)

    total_solicitudes = await db.contar_oportunidades_filtradas(
        conn,
        filtro_tipo_id=filtros.filtro_tipo_id,
        filtro_tecnologia_id=filtros.filtro_tecnologia_id,
        filtro_estatus_id=filtros.filtro_estatus_id,
        fecha_inicio_mx=inicio_mx,
        fecha_fin_mx_exclusive=fin_mx_exclusive,
        filtro_cliente_id=filtros.filtro_cliente_id,
    )
    await _verificar_limite(
        conn,
        clave=LIMITE_SOLICITUDES,
        default=_DEFAULT_LIMITE_SOLICITUDES,
        total=total_solicitudes,
        mensaje_base="El reporte excede el maximo de solicitudes permitido",
        sugerencia="Acota fechas o estatus.",
    )

    # Fetch unico: el mismo UNION ALL serviria de "conteo" y de "fetch", asi que se evalua
    # una sola vez y el limite se aplica sobre len(detalle) en Python. Trade-off conocido:
    # a diferencia del COUNT(*) que se hacia antes, un cliente cerca/por-encima del limite
    # ahora paga la transferencia + conversion a dict de TODAS sus filas antes de rechazar
    # (el COUNT descartaba el resultado sin materializarlo). Aceptable mientras el volumen
    # por cliente sea bajo (~320 oportunidades totales en PROD a 2026-07); si un cliente
    # individual empieza a acercarse regularmente a _LIMITES_FILAS_DETALLE, revisar volver
    # a un COUNT-first o envolver en una CTE que devuelva count+rows en un solo round-trip.
    detalle = await db.obtener_detalle_por_cliente(
        conn,
        filtro_cliente_id=filtros.filtro_cliente_id,
        filtro_tipo_id=filtros.filtro_tipo_id,
        filtro_tecnologia_id=filtros.filtro_tecnologia_id,
        filtro_estatus_id=filtros.filtro_estatus_id,
        fecha_inicio_mx=inicio_mx,
        fecha_fin_mx_exclusive=fin_mx_exclusive,
    )
    limite_clave, limite_default = _LIMITES_FILAS_DETALLE.get(formato, _LIMITES_FILAS_DETALLE["excel"])
    await _verificar_limite(
        conn,
        clave=limite_clave,
        default=limite_default,
        total=len(detalle),
        mensaje_base=f"El detalle excede el maximo de filas permitido para {formato.upper()}",
        sugerencia="Acota fechas o estatus.",
    )

    cliente_nombre = await db.obtener_nombre_cliente(conn, filtros.filtro_cliente_id)

    logger.info(
        "Reporte clientes generado (por cliente): solicitante=%s formato=%s con_cliente=True "
        "rango=%s..%s filas_detalle=%d",
        solicitante_email, formato, filtros.fecha_inicio, filtros.fecha_fin, len(detalle),
    )
    return {"modo": "cliente", "detalle": detalle, "filtros": filtros, "cliente_nombre": cliente_nombre}
