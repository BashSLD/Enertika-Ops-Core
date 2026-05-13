from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from uuid import UUID

from core.config_service import ConfigService
from core.timezone import today_mx
from modules.asistencia import db_service as asistencia_db
from modules.asistencia.constants import ASISTENCIA_ESTADOS
from modules.vacaciones import db_service as vac_db
from modules.vacaciones.holidays import generar_feriados_mexico

logger = logging.getLogger("rrhh.service")


async def get_dashboard_data(conn) -> dict:
    hoy = today_mx()
    vacaciones_hoy = await vac_db.get_vacaciones_hoy(conn, hoy)
    pendientes = await vac_db.get_todas_solicitudes_pendientes(conn)
    total_empleados = await vac_db.count_empleados(conn)
    return {
        "vacaciones_hoy": vacaciones_hoy,
        "pendientes": pendientes,
        "total_empleados": total_empleados,
        "hoy": hoy,
    }


async def get_empleado_edit_ctx(conn, usuario_id: UUID) -> dict:
    empleado = await vac_db.get_empleado_datos(conn, usuario_id)
    usuario = await conn.fetchrow(
        "SELECT id_usuario, nombre, email FROM tb_usuarios WHERE id_usuario = $1",
        usuario_id,
    )
    jefes = await vac_db.get_jefes_con_nombre(conn, usuario_id)
    usuarios = await vac_db.get_usuarios_activos_simples(conn)
    jefes_ids = {j["id_usuario"] for j in jefes}
    return {
        "empleado": empleado,
        "usuario": dict(usuario) if usuario else {},
        "jefes": jefes,
        "jefes_ids": jefes_ids,
        "usuarios": usuarios,
    }


async def get_admin_ctx(conn, anio: int | None = None) -> dict:
    anio = anio or today_mx().year
    meses_exp = await ConfigService.get_global_config(conn, "VACACIONES_MESES_EXPIRACION", 18, int)
    return {
        "anio": anio,
        "festivos": await vac_db.get_festivos_by_year(conn, anio),
        "tipos": await vac_db.get_tipos_ausencia_admin(conn),
        "dias_vacaciones": await vac_db.get_catalogo_dias_admin(conn),
        "vacaciones_meses_expiracion": meses_exp,
    }


async def guardar_config_vacaciones(conn, *, meses_expiracion: int) -> None:
    if meses_expiracion < 1 or meses_expiracion > 120:
        raise ValueError("Los meses de expiracion deben estar entre 1 y 120")
    await conn.execute(
        """
        INSERT INTO tb_configuracion_global (clave, valor, tipo_dato, descripcion)
        VALUES (
            'VACACIONES_MESES_EXPIRACION', $1::text, 'int',
            'Meses hasta que expira un periodo de vacaciones no utilizado'
        )
        ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor
        """,
        str(meses_expiracion),
    )


async def get_reportes_ctx(conn) -> dict:
    hoy = today_mx()
    return {
        "fecha_inicio": hoy - timedelta(days=30),
        "fecha_fin": hoy,
        "usuarios": await vac_db.get_usuarios_activos_simples(conn),
        "sucursales": await asistencia_db.get_sucursales(conn),
        "estados_asistencia": ASISTENCIA_ESTADOS,
        "estados_vacaciones": ["pendiente", "aprobado", "rechazado", "cancelado"],
    }


def validar_rango_reportes(fecha_inicio: date, fecha_fin: date, *, max_dias: int = 92) -> None:
    if fecha_fin < fecha_inicio:
        raise ValueError("La fecha final no puede ser menor que la inicial")
    if (fecha_fin - fecha_inicio).days > max_dias:
        raise ValueError(f"El rango maximo permitido es de {max_dias} dias")


async def get_reporte_vacaciones(
    conn,
    *,
    fecha_inicio: date,
    fecha_fin: date,
    usuario_id: UUID | None = None,
    estado: str | None = None,
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT
            sa.id,
            sa.fecha_inicio,
            sa.fecha_fin,
            sa.fecha_presentarse,
            sa.dias_solicitados,
            sa.estado,
            sa.fecha_solicitud,
            sa.fecha_resolucion,
            ta.nombre AS tipo_nombre,
            u.id_usuario,
            u.nombre AS empleado_nombre,
            u.email AS empleado_email,
            ed.numero_empleado,
            COALESCE(ed.departamento, u.department) AS departamento,
            aprobador.nombre AS aprobado_por_nombre
        FROM tb_solicitudes_ausencia sa
        JOIN tb_cat_tipos_ausencia ta ON ta.id = sa.tipo_ausencia_id
        JOIN tb_usuarios u ON u.id_usuario = sa.usuario_id
        LEFT JOIN tb_empleados_datos ed ON ed.usuario_id = u.id_usuario
        LEFT JOIN tb_usuarios aprobador ON aprobador.id_usuario = sa.aprobado_por
        WHERE ta.slug = 'vacaciones'
          AND sa.fecha_inicio <= $2
          AND sa.fecha_fin >= $1
          AND ($3::uuid IS NULL OR sa.usuario_id = $3)
          AND ($4::text IS NULL OR sa.estado = $4)
        ORDER BY sa.fecha_inicio DESC, u.nombre
        """,
        fecha_inicio,
        fecha_fin,
        usuario_id,
        estado,
    )
    return [dict(row) for row in rows]


async def generar_festivos_anio(conn, anio: int, user_id: UUID | None = None) -> int:
    if anio < 2026 or anio > 2100:
        raise ValueError("El ano debe estar entre 2026 y 2100")
    return await vac_db.insert_festivos_generados(
        conn,
        generar_feriados_mexico(anio),
        created_by=user_id,
    )


async def guardar_festivo(
    conn,
    *,
    fecha,
    descripcion: str,
    es_oficial: bool,
    user_id: UUID,
    festivo_id: UUID | None = None,
) -> None:
    descripcion = (descripcion or "").strip()
    if not descripcion:
        raise ValueError("La descripcion es obligatoria")
    if festivo_id:
        updated = await vac_db.update_festivo(
            conn, festivo_id, fecha, descripcion, es_oficial, user_id
        )
        if not updated:
            raise ValueError("Festivo no encontrado")
    else:
        await vac_db.create_festivo(conn, fecha, descripcion, es_oficial, user_id)


def _normalizar_slug(slug: str) -> str:
    value = (slug or "").strip().lower()
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        raise ValueError("El slug es obligatorio")
    if len(value) > 30:
        raise ValueError("El slug no puede exceder 30 caracteres")
    return value


async def crear_tipo_ausencia(
    conn,
    *,
    nombre: str,
    slug: str,
    abreviatura: str,
    afecta_saldo: bool,
    requiere_aprobacion: bool,
    is_active: bool,
    orden: int,
    user_id: UUID,
) -> None:
    nombre = (nombre or "").strip()
    abreviatura = (abreviatura or "").strip().upper()
    if not nombre:
        raise ValueError("El nombre es obligatorio")
    if not abreviatura or len(abreviatura) > 5:
        raise ValueError("La abreviatura es obligatoria y debe tener maximo 5 caracteres")
    await vac_db.create_tipo_ausencia(
        conn,
        nombre=nombre,
        slug=_normalizar_slug(slug),
        abreviatura=abreviatura,
        afecta_saldo=afecta_saldo,
        requiere_aprobacion=requiere_aprobacion,
        is_active=is_active,
        orden=orden,
        updated_by=user_id,
    )


async def actualizar_tipo_ausencia(
    conn,
    *,
    tipo_id: UUID,
    nombre: str,
    abreviatura: str,
    afecta_saldo: bool,
    requiere_aprobacion: bool,
    is_active: bool,
    orden: int,
    user_id: UUID,
) -> None:
    tipo = await vac_db.get_tipo_ausencia_admin_by_id(conn, tipo_id)
    if not tipo:
        raise ValueError("Tipo de permiso no encontrado")
    if tipo["es_sistema"] and not is_active:
        raise ValueError("Los tipos base del sistema no se pueden desactivar")
    nombre = (nombre or "").strip()
    abreviatura = (abreviatura or "").strip().upper()
    if not nombre:
        raise ValueError("El nombre es obligatorio")
    if not abreviatura or len(abreviatura) > 5:
        raise ValueError("La abreviatura es obligatoria y debe tener maximo 5 caracteres")
    await vac_db.update_tipo_ausencia(
        conn,
        tipo_id=tipo_id,
        nombre=nombre,
        abreviatura=abreviatura,
        afecta_saldo=afecta_saldo,
        requiere_aprobacion=requiere_aprobacion,
        is_active=is_active,
        orden=orden,
        updated_by=user_id,
    )


async def guardar_dias_vacaciones(
    conn,
    *,
    antiguedad_anios: int,
    antiguedad_anios_fin: int | None,
    dias_lft: int,
    dias_enertika: int,
    is_active: bool,
    user_id: UUID,
    row_id: UUID | None = None,
) -> None:
    _validar_rango_dias(antiguedad_anios, antiguedad_anios_fin, dias_lft, dias_enertika)
    await _validar_no_solapa_rango(
        conn, antiguedad_anios, antiguedad_anios_fin, is_active, excluir_id=row_id
    )
    if row_id:
        updated = await vac_db.update_dias_vacaciones(
            conn,
            row_id=row_id,
            antiguedad_anios=antiguedad_anios,
            antiguedad_anios_fin=antiguedad_anios_fin,
            dias_lft=dias_lft,
            dias_enertika=dias_enertika,
            is_active=is_active,
            updated_by=user_id,
        )
        if not updated:
            raise ValueError("Rango de antiguedad no encontrado")
    else:
        await vac_db.create_dias_vacaciones(
            conn,
            antiguedad_anios=antiguedad_anios,
            antiguedad_anios_fin=antiguedad_anios_fin,
            dias_lft=dias_lft,
            dias_enertika=dias_enertika,
            is_active=is_active,
            updated_by=user_id,
        )


def _validar_rango_dias(
    antiguedad_anios: int,
    antiguedad_anios_fin: int | None,
    dias_lft: int,
    dias_enertika: int,
) -> None:
    if antiguedad_anios <= 0:
        raise ValueError("La antiguedad inicial debe ser mayor a cero")
    if antiguedad_anios_fin is not None and antiguedad_anios_fin < antiguedad_anios:
        raise ValueError("La antiguedad final no puede ser menor a la inicial")
    if dias_lft <= 0 or dias_enertika <= 0:
        raise ValueError("Los dias deben ser mayores a cero")
    if dias_enertika < dias_lft:
        raise ValueError("Los dias Enertika no pueden ser menores que LFT")


async def _validar_no_solapa_rango(
    conn,
    inicio: int,
    fin: int | None,
    is_active: bool,
    excluir_id: UUID | None = None,
) -> None:
    if not is_active:
        return
    rows = await vac_db.get_catalogo_dias_admin(conn)
    nuevo_fin = fin if fin is not None else 999
    for row in rows:
        if not row["is_active"] or row["id"] == excluir_id:
            continue
        row_inicio = row["antiguedad_anios"]
        row_fin = row["antiguedad_anios_fin"] if row["antiguedad_anios_fin"] is not None else 999
        if inicio <= row_fin and nuevo_fin >= row_inicio:
            raise ValueError("El rango de antiguedad se empalma con otro rango activo")


async def guardar_empleado(
    conn,
    usuario_id: UUID,
    numero_empleado: str | None,
    fecha_contratacion,
    puesto: str | None,
    departamento: str | None,
    id_aprobador_vacaciones: UUID | None,
    dias_vacaciones_ajuste: int,
    jefes_ids: list[UUID],
    updated_by: UUID,
) -> None:
    await vac_db.upsert_empleado_datos(
        conn,
        usuario_id=usuario_id,
        numero_empleado=numero_empleado,
        fecha_contratacion=fecha_contratacion,
        puesto=puesto,
        departamento=departamento,
        id_aprobador_vacaciones=id_aprobador_vacaciones,
        dias_vacaciones_ajuste=dias_vacaciones_ajuste,
        updated_by=updated_by,
    )
    await vac_db.set_jefes(conn, usuario_id, jefes_ids)
