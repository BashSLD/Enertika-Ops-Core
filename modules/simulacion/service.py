from datetime import datetime, timedelta, time as dt_time
from uuid import UUID, uuid4
from typing import List, Optional, Tuple, Dict
import json
import logging
from decimal import Decimal
from datetime import date
import asyncpg
from fastapi import HTTPException
from zoneinfo import ZoneInfo

# Importar schemas locales
from .schemas import SimulacionUpdate, DetalleBessCreate, OportunidadCreateCompleta, SitiosBatchUpdate
from core.workflow.notification_service import get_notification_service
from modules.shared.services import IdGeneratorService, ClientService, BessService, SiteService
from core.config_service import ConfigService


from .db_service import SimulacionDBService

logger = logging.getLogger("SimulacionModule")


def resolve_update_permissions(user_context: dict) -> dict:
    """Regla unica de permisos para el modal y la actualizacion de simulacion."""
    sim_role = user_context.get("module_roles", {}).get("simulacion", "")
    system_role = user_context.get("role")
    is_admin_system = system_role == "ADMIN"
    is_module_admin = sim_role == "admin"
    is_manager_editor = system_role == "MANAGER" and sim_role in ["editor", "admin"]
    can_edit_sensitive = is_admin_system or is_module_admin or is_manager_editor

    return {
        "sim_role": sim_role,
        "can_manage": is_admin_system or sim_role in ["editor", "admin"],
        "can_edit_any": is_admin_system or is_module_admin or system_role == "MANAGER",
        "can_edit_sensitive": can_edit_sensitive,
        "can_assign_others": can_edit_sensitive,
        "can_edit_assignment_fields": can_edit_sensitive or sim_role == "editor",
    }


class SimulacionService:
    """Encapsula la lógica de negocio del módulo Simulación (v3.1 Multisitio)."""

    def __init__(self):
        self.db = SimulacionDBService()
        self.notification_service = get_notification_service()

    async def get_current_datetime_mx(self, conn) -> datetime:
        """Fuente de verdad de tiempo (CDMX o Configurado)."""
        tz_str = await ConfigService.get_global_config(conn, "ZONA_HORARIA_DEFAULT", "America/Mexico_City")
        try:
             tz = ZoneInfo(tz_str)
        except (KeyError, ValueError) as e:
             logger.warning(f"Zona horaria invalida '{tz_str}', usando default: {e}")
             tz = ZoneInfo("America/Mexico_City")
        return datetime.now(tz)


    async def get_configuracion_global(self, conn):
        """Obtiene la configuración de horarios desde la BD (usando cache)."""
        # Obtenemos valores individuales cacheados
        hora_corte = await ConfigService.get_global_config(conn, "HORA_CORTE_L_V", "18:00")
        return {"HORA_CORTE_L_V": hora_corte}
    
    # --- MÉTODOS PRIVADOS DE RESOLUCIÓN (NO HARDCODING) ---

    # Whitelist de tablas catalogo permitidas para busqueda dinamica
    _ALLOWED_CATALOG_TABLES = frozenset({
        "tb_cat_tecnologias",
        "tb_cat_tipos_solicitud",
        "tb_cat_estatus_oportunidades",
        "tb_cat_motivos_cierre",
        "tb_cat_motivos_retrabajo",
    })

    async def _get_catalog_id_by_name(self, conn, table: str, name_value: str) -> int:
        """Busca ID de catálogo por nombre. Valida tabla contra whitelist."""
        if table not in self._ALLOWED_CATALOG_TABLES:
            raise ValueError(f"Tabla no permitida para busqueda de catalogo: {table}")
        query = f"SELECT id FROM {table} WHERE LOWER(nombre) = LOWER($1)"
        id_val = await conn.fetchval(query, name_value)
        if not id_val:
            logger.error(f"Configuracion faltante: No existe '{name_value}' en {table}")
            raise HTTPException(status_code=500, detail=f"Error Config: Falta '{name_value}' en BD.")
        return id_val

    async def _get_status_ids(self, conn) -> dict:
        """Devuelve mapa de IDs críticos usando Cache."""
        estatus_map = await ConfigService.get_catalog_map(conn, "tb_cat_estatus_oportunidades", "nombre", "id")
        
        # Helper safe lookup
        def get_id(name):
            val = estatus_map.get(name.lower())
            if not val:
                 # Fallback log
                 logger.error(f"Config faltante: Estatus '{name}' no encontrado en BD")
            return val

        return {
            "pendiente":               get_id("Pendiente"),
            "entregado":               get_id("Entregado"),
            "cancelado":               get_id("Cancelado"),
            "perdido":                 get_id("Perdido"),
            "ganada":                  get_id("Ganada"),
            "monitoreo_cotizacion":    get_id("Monitoreo de Cotización"),
            "montaje_oferta":          get_id("Montaje de oferta"),
            "comentarios_recibidos":   get_id("Comentarios Recibidos"),
        }


    @staticmethod
    def _as_aware(dt: datetime) -> datetime:
        """Convierte un datetime naive a Mexico City-aware. Si ya tiene tzinfo, lo devuelve sin cambios."""
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=ZoneInfo("America/Mexico_City"))
        return dt

    def calcular_kpis_entrega(self, fecha_entrega: datetime, deadline_original: datetime, deadline_negociado: datetime = None) -> tuple:
        """
        Calcula DOS indicadores de cumplimiento:
        1. KPI SLA Interno: Fecha Real vs Deadline Original (Sistema)
        2. KPI Compromiso: Fecha Real vs Deadline Negociado (Cliente/Acuerdo)

        Returns:
            (kpi_sla_interno, kpi_compromiso)
        """
        if not fecha_entrega or not deadline_original:
            return None, None

        fecha_entrega = self._as_aware(fecha_entrega)
        deadline_original = self._as_aware(deadline_original)
        deadline_negociado = self._as_aware(deadline_negociado)

        # --- 1. KPI SLA Interno ---
        # Regla: Comparar contra lo que el sistema calculó originalmente
        kpi_sla = "Entrega a tiempo" if fecha_entrega <= deadline_original else "Entrega tarde"

        # --- 2. KPI Compromiso ---
        # Regla: Si hay negociado, es la verdad absoluta. Si no, fallback al original.
        fecha_compromiso = deadline_negociado if deadline_negociado else deadline_original
        kpi_compromiso = "Entrega a tiempo" if fecha_entrega <= fecha_compromiso else "Entrega tarde"

        return kpi_sla, kpi_compromiso

    def calcular_kpis_sitio(
        self,
        fecha_cierre_sitio: datetime,
        deadline_calculado_padre: datetime,
        deadline_negociado_padre: Optional[datetime]
    ) -> tuple:
        """
        Calcula KPIs duales para un SITIO individual.
        
        Args:
            fecha_cierre_sitio: Fecha real de cierre del sitio
            deadline_calculado_padre: Deadline original del sistema (padre)
            deadline_negociado_padre: Deadline negociado con cliente (padre, opcional)
        
        Returns:
            (kpi_status_interno, kpi_status_compromiso)
            
        Ejemplo:
            ("Entrega a tiempo", "Entrega tarde")
        """
        if not fecha_cierre_sitio or not deadline_calculado_padre:
            return None, None

        fecha_cierre_sitio = self._as_aware(fecha_cierre_sitio)
        deadline_calculado_padre = self._as_aware(deadline_calculado_padre)
        deadline_negociado_padre = self._as_aware(deadline_negociado_padre)

        # KPI Interno: vs deadline calculado (SLA del sistema)
        kpi_interno = (
            "Entrega a tiempo"
            if fecha_cierre_sitio <= deadline_calculado_padre
            else "Entrega tarde"
        )

        # KPI Compromiso: vs deadline negociado o calculado
        deadline_compromiso = deadline_negociado_padre or deadline_calculado_padre
        kpi_compromiso = (
            "Entrega a tiempo" 
            if fecha_cierre_sitio <= deadline_compromiso 
            else "Entrega tarde"
        )
        
        return kpi_interno, kpi_compromiso

    # --- LÓGICA DE NEGOCIO ---

    async def get_responsables_dropdown(self, conn) -> List[dict]:
        """
        Obtiene usuarios filtrados ESTRICTAMENTE por departamento 'Simulación'.
        """
        return await self.db.get_responsables_simulacion(conn)

    async def registrar_cambio_deadline(
        self,
        conn,
        id_oportunidad: UUID,
        deadline_anterior: Optional[datetime],
        deadline_nuevo: datetime,
        id_motivo_cambio: int,
        comentario: Optional[str],
        user_context: dict
    ):
        """
        Registra un cambio de deadline_negociado en el historial.
        
        REGLA DE NEGOCIO:
        - Si se cambia deadline_negociado, DEBE haber motivo
        - Se registra en tb_historial_cambios_deadline

        NOTA: Esta funcionalidad está actualmente INACTIVA en el frontend (no se envía motivo).
        Se mantiene el código para futura implementación de trazabilidad de cambios.
        """
        user_id = user_context.get("user_db_id")
        user_name = user_context.get("user_name")
        
        await self.db.registrar_cambio_deadline(
            conn, id_oportunidad, deadline_anterior, deadline_nuevo,
            id_motivo_cambio, comentario, user_id, user_name
        )
        
        logger.info(
            f"Cambio de deadline registrado - Oportunidad: {id_oportunidad}, "
            f"Anterior: {deadline_anterior}, Nuevo: {deadline_nuevo}, "
            f"Motivo: {id_motivo_cambio}, Usuario: {user_name}"
        )

    async def update_simulacion_padre(self, conn, id_oportunidad: UUID, datos: SimulacionUpdate, user_context: dict):
        """
        Actualiza la oportunidad padre y sus sitios asociados.
        Refactorizado para usar métodos auxiliares privados.
        
        Returns:
            tuple: (kpi_sla_interno, kpi_compromiso, has_negotiated_deadline) para lógica de confetti
        """
        # 0. Obtener estado actual y configuración
        status_map = await self._get_status_ids(conn)

        async with conn.transaction():
            current_data = await self.db.get_oportunidad_for_update(conn, id_oportunidad)

            if not current_data:
                raise HTTPException(status_code=404, detail="Oportunidad no encontrada")

            total_sitios = await self.db.get_total_sitios_count(conn, id_oportunidad)

            # 0.5 Validacion Inteligente Multisitio (Pre-Permission Check)
            # Permitir si queda 1 solo sitio pendiente (se cerrará en cascada)
            sitios_pendientes = 0
            if total_sitios > 1:
                sitios_pendientes = await self.db.get_sitios_pendientes_count(
                    conn, id_oportunidad, 
                    [status_map["entregado"], status_map["cancelado"], status_map["perdido"], status_map["ganada"]]
                )

                # Solo bloqueamos si hay MÁS de 1 sitio pendiente
                if datos.id_estatus_global == status_map["entregado"] and sitios_pendientes > 1:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Bloqueo de Calidad: Existen {sitios_pendientes} sitios activos. Debe cerrar sitios individuales hasta que quede solo uno."
                    )

            # 0.6 Historial de Cambios de Deadline (FUTURA IMPLEMENTACIÓN)
            # Actualmente el frontend no envía 'id_motivo_cambio_deadline', por lo que este bloque no se ejecuta.
            # Se planea activar cuando se requiera justificar cambios de fecha negociada.
            current_deadline_nego = current_data['deadline_negociado']
            if datos.deadline_negociado and datos.deadline_negociado != current_deadline_nego:
                if datos.id_motivo_cambio_deadline:
                    await self.registrar_cambio_deadline(
                        conn,
                        id_oportunidad,
                        deadline_anterior=current_deadline_nego,
                        deadline_nuevo=datos.deadline_negociado,
                        id_motivo_cambio=datos.id_motivo_cambio_deadline,
                        comentario=datos.comentario_cambio_deadline,
                        user_context=user_context
                    )

            # 1. Resolver Permisos y Validaciones (In-Place Update of datos)
            datos = await self._resolve_update_permissions(
                conn, current_data, datos, user_context, status_map, total_sitios
            )

            # 1.5. Validar transición de estatus y fecha/hora real (enforcement §5.1 / §5.2)
            now_mx = await self.get_current_datetime_mx(conn)
            es_cierre_terminal, activa_exclusion_kpis = await self._validate_status_transition(conn, id_oportunidad, current_data, datos, now_mx)

            # 2. Calcular KPIs de Entrega (Padre)
            kpi_sla_val, kpi_compromiso_val, tiempo_elaboracion_horas = await self._calculate_kpis_entrega_padre(
                conn, current_data, datos, status_map
            )

            # 3. Ejecutar Update del Padre
            # Helper params dict update
            datos_dict = datos.model_dump()
            datos_dict.update({
                'kpi_sla_val': kpi_sla_val,
                'kpi_compromiso_val': kpi_compromiso_val,
                'tiempo_elaboracion_horas': tiempo_elaboracion_horas,
                # Al entrar a Monitoreo/Montaje se marca la exclusión; el UPDATE es monótono
                # (OR) por lo que se conserva aunque la op pase después a Entregado.
                'excluir_kpis_simulacion': activa_exclusion_kpis,
            })
            await self.db.update_oportunidad_padre(conn, id_oportunidad, datos_dict)

            # 3.1. Si deadline_negociado cambió y la op es (o pasa a ser) terminal,
            # recalcular KPIs de sitios ya cerrados individualmente.
            # update_sitios_cascada omite terminales (NOT IN), así que el recálculo
            # debe hacerse explícitamente para que el reporte refleje el nuevo deadline.
            _terminales = {
                status_map["entregado"], status_map["perdido"],
                status_map["cancelado"], status_map["ganada"],
            }
            if (
                datos.deadline_negociado != current_deadline_nego
                and current_data['deadline_calculado'] is not None
                and (
                    current_data['id_estatus_global'] in _terminales
                    or datos.id_estatus_global in _terminales
                )
            ):
                await self.db.recalcular_kpis_sitios_por_deadline(
                    conn,
                    id_oportunidad,
                    current_data['deadline_calculado'],
                    datos.deadline_negociado,
                )

            # 3.5. Insertar Historial (Si Cambio Estatus)
            if datos.id_estatus_global != current_data['id_estatus_global']:
                # Usar fecha capturada por el usuario (backdating) o la hora actual
                fecha_real = datos.fecha_cambio_real or now_mx
                fecha_sla = await self._calculate_fecha_sla(conn, fecha_real)

                await self.db.insert_historial_estatus(
                    conn,
                    id_oportunidad,
                    current_data['id_estatus_global'],
                    datos.id_estatus_global,
                    fecha_real,
                    fecha_sla,
                    user_context['user_db_id'],
                )

            # 4. Manejar Cascada a Sitios y Retrabajos
            await self._handle_site_updates(
                conn, id_oportunidad, current_data, datos, status_map, total_sitios, sitios_pendientes
            )

            # 4.5. Guardar simulaciones adicionales (solo en cierre Entregado/Perdido)
            es_cierre_kpi = datos.id_estatus_global in [status_map["entregado"], status_map["perdido"]]
            if es_cierre_kpi and datos.simulaciones_adicionales:
                await self.db.insert_simulaciones_adicionales(
                    conn,
                    id_oportunidad,
                    datos.simulaciones_adicionales,
                    kpi_sla_val,
                    kpi_compromiso_val,
                    datos.fecha_entrega_simulacion
                )

        # 4.6. Sincronizar tabla de componentes (decouple FV/BESS). Post-commit y best-effort
        # por la misma razon que las notificaciones: un PostgresError aqui no debe revertir el
        # cierre ya comiteado. Ver PLAN_DECOUPLE_FV_BESS.md Fase 5.
        try:
            await self.db.sync_componentes_oportunidad(conn, id_oportunidad)
        except asyncpg.PostgresError as sync_err:
            logger.error(f"Sync componentes fallo (no critico) para {id_oportunidad}: {sync_err}")

        # 5. Enviar Notificaciones (fuera de la transacción a propósito).
        # _send_update_notifications traga PostgresError ("no critico"); si corriera
        # dentro de la transacción, ese error la dejaria abortada y el COMMIT fallaria,
        # revirtiendo el negocio. Post-commit, una falla de notificacion queda aislada
        # y el pg_notify/outbox solo se emiten si la transaccion realmente comiteo.
        await self._send_update_notifications(
            conn, id_oportunidad, current_data, datos, user_context
        )
        
        # 6. Return KPI data for confetti logic in router
        has_negotiated_deadline = bool(datos.deadline_negociado or current_data['deadline_negociado'])
        return (kpi_sla_val, kpi_compromiso_val, has_negotiated_deadline, es_cierre_terminal)

    async def update_sitios_batch(
        self, 
        conn, 
        id_oportunidad: UUID, 
        datos: SitiosBatchUpdate,
        user_context: dict
    ):
        """
        Actualiza múltiples sitios en batch con KPIs individuales.
        
        RESPONSABILIDADES:
        - Validar permisos (IDOR Check)
        - Calcular kpi_status_interno y kpi_status_compromiso por sitio
        - Manejar marcado de retrabajo (es_retrabajo, id_motivo_retrabajo)
        - El trigger trg_recalcular_retrabajo_padre se ejecuta automáticamente
        """
        
        # 0. Validar Existencia y Permisos (IDOR)
        # Obtenemos datos mínimos para validar dueño
        current_data = await self.db.get_oportunidad_for_update(conn, id_oportunidad)
        if not current_data:
            raise HTTPException(status_code=404, detail="Oportunidad no encontrada")
            
        # Check IDOR: Solo Admin/Manager o el Responsable asignado pueden editar
        user_id = user_context.get("user_db_id")
        sim_role = user_context.get("module_roles", {}).get("simulacion", "")
        
        is_admin = user_context.get("role") in ["ADMIN", "MANAGER"]
        is_module_admin = sim_role == "admin"
        is_owner = str(current_data.get("responsable_simulacion_id")) == str(user_id)
        
        if not (is_admin or is_module_admin or is_owner):
            raise HTTPException(
                status_code=403, 
                detail="No autorizado. Solo el responsable asignado o un administrador pueden editar esta oportunidad."
            )

        # 1. Obtener deadlines del PADRE (necesarios para KPIs de sitios)
        padre_data = await self.db.get_deadlines_padre(conn, id_oportunidad)
        
        if not padre_data:
            raise HTTPException(status_code=404, detail="Oportunidad padre no encontrada")
        
        deadline_calc_padre = padre_data['deadline_calculado']
        deadline_nego_padre = padre_data['deadline_negociado']
        
        # 2. Preparar datos de actualización
        status_map = await self._get_status_ids(conn)
        fecha_actual = await self.get_current_datetime_mx(conn)
        
        es_cierre = datos.id_estatus_global in [
            status_map["entregado"], 
            status_map["cancelado"], 
            status_map["perdido"]
        ]
        
        # Manejar fecha_cierre correctamente considerando timezone
        if es_cierre:
            if datos.fecha_cierre:
                # Si fecha viene como string, convertir a datetime con timezone
                if isinstance(datos.fecha_cierre, str):
                    parsed_date = datetime.fromisoformat(datos.fecha_cierre.replace('Z', '+00:00'))
                    if parsed_date.tzinfo is None:
                        fecha_cierre_final = parsed_date.replace(tzinfo=ZoneInfo("America/Mexico_City"))
                    else:
                        fecha_cierre_final = parsed_date
                else:
                    # Si ya es datetime
                    if datos.fecha_cierre.tzinfo is None:
                        fecha_cierre_final = datos.fecha_cierre.replace(tzinfo=ZoneInfo("America/Mexico_City"))
                    else:
                        fecha_cierre_final = datos.fecha_cierre
            else:
                fecha_cierre_final = fecha_actual
        else:
            fecha_cierre_final = None
        
        # 3. Calcular KPIs (solo para estados terminales relevantes)
        kpi_interno = None
        kpi_compromiso = None
        
        calcular_kpis = datos.id_estatus_global in [
            status_map.get("entregado"),
            status_map.get("perdido")
        ]
        
        if calcular_kpis and fecha_cierre_final and deadline_calc_padre:
            kpi_interno, kpi_compromiso = self.calcular_kpis_sitio(
                fecha_cierre_sitio=fecha_cierre_final,
                deadline_calculado_padre=deadline_calc_padre,
                deadline_negociado_padre=deadline_nego_padre
            )
        
        # 4. Update batch de sitios con nuevos campos
        await self.db.update_sitios_batch_execute(
            conn, id_oportunidad, datos, 
            fecha_cierre_final, kpi_interno, kpi_compromiso
        )
        
        logger.info(f"Sitios batch actualizados. KPIs: interno={kpi_interno}, compromiso={kpi_compromiso}, retrabajo={datos.es_retrabajo}")

        # Sincronizar tabla de componentes (decouple FV/BESS). Best-effort.
        try:
            await self.db.sync_componentes_oportunidad(conn, id_oportunidad)
        except asyncpg.PostgresError as sync_err:
            logger.error(f"Sync componentes fallo (no critico) para {id_oportunidad}: {sync_err}")

    async def marcar_fv_terminado(self, conn, id_oportunidad: UUID, user_context: dict) -> Tuple[datetime, int]:
        """Marca la parte FV de un hibrido (FV+BESS) como terminada, independiente del estatus.

        Fecha automatica (now_mx), como los demas estatus. Asegura que existan los componentes
        FV (sincroniza), fija su fecha + editado_manual y recalcula KPI FV. Solo aplica a
        id_tecnologia = 3. Idempotente. Devuelve (fecha, num_componentes_fv).
        """
        op = await self.db.get_oportunidad_by_id(conn, id_oportunidad)
        if not op:
            raise HTTPException(status_code=404, detail="Oportunidad no encontrada")
        if op["id_tecnologia"] != 3:
            raise HTTPException(
                status_code=400,
                detail="Marcar 'FV Terminado' solo aplica a oportunidades FV + BESS.",
            )

        now_mx = await self.get_current_datetime_mx(conn)
        # Asegurar que existan filas de componente FV (una op activa puede no tenerlas aun)
        await self.db.sync_componentes_oportunidad(conn, id_oportunidad)
        filas = await self.db.marcar_fv_terminado(conn, id_oportunidad, now_mx)
        logger.info(
            f"FV terminado marcado en {id_oportunidad}: {filas} componente(s) FV, fecha {now_mx}"
        )
        return now_mx, filas

    async def _resolve_update_permissions(
        self, 
        conn, 
        current_data: dict, 
        datos: SimulacionUpdate, 
        user_context: dict,
        status_map: dict,
        total_sitios: int = 0
    ) -> SimulacionUpdate:
        """
        Resuelve permisos de edición sensible y validaciones de negocio.
        Modifica el objeto 'datos' in-place revirtiendo cambios no autorizados.
        """
        id_oportunidad = current_data.get('id_oportunidad') # Ensure we have ID for queries if needed
        # Or pass it? current_data might not have it. Let's rely on caller passing it if strictly needed, 
        # but for the multisite query we need it. 
        # Wait, current_data in my fetch includes: id_interno, responsable... but maybe not id_oportunidad if I didn't select it? 
        # The caller 'update_simulacion_padre' has 'id_oportunidad' in args. 
        # I should add 'id_oportunidad' to this helper signature.
        
        # 1. Verificar permisos de campos protegidos
        permisos_update = resolve_update_permissions(user_context)
        can_edit_sensitive = permisos_update["can_edit_sensitive"]
        can_assign_others = permisos_update["can_assign_others"]
        can_edit_assignment_fields = permisos_update["can_edit_assignment_fields"]
        can_edit_any = permisos_update["can_edit_any"]

        # 1.5 Validar Permiso Básico de Edición (IDOR Check)
        # Si NO es Admin/Manager, DEBE ser el dueño o estar autoasignandose.
        user_id = user_context.get("user_db_id")
        is_owner = str(current_data.get("responsable_simulacion_id")) == str(user_id)
        requested_responsable = datos.responsable_simulacion_id
        is_self_assignment = (
            can_edit_assignment_fields
            and requested_responsable is not None
            and str(requested_responsable) == str(user_id)
        )
        
        if not (can_edit_any or is_owner or is_self_assignment):
            raise HTTPException(
                status_code=403, 
                detail="No autorizado. Solo el responsable asignado puede editar esta oportunidad o autoasignarse."
            )

        # monto_cierre_usd: preservar de BD si no viene en el form (campo opcional)
        if datos.monto_cierre_usd is None:
            datos.monto_cierre_usd = current_data['monto_cierre_usd']

        # ID interno permanece limitado a Admin/Manager autorizado.
        if not can_edit_sensitive:
            datos.id_interno_simulacion = current_data['id_interno_simulacion']

        if not can_edit_assignment_fields:
            datos.responsable_simulacion_id = current_data['responsable_simulacion_id']
            datos.deadline_negociado = current_data['deadline_negociado']
        else:
            if not can_assign_others:
                current_responsable = current_data['responsable_simulacion_id']
                requested_is_self = (
                    datos.responsable_simulacion_id is not None
                    and str(datos.responsable_simulacion_id) == str(user_id)
                )
                if datos.responsable_simulacion_id is None:
                    datos.responsable_simulacion_id = current_responsable
                elif not requested_is_self and datos.responsable_simulacion_id != current_responsable:
                    raise HTTPException(
                        status_code=403,
                        detail="No autorizado. Solo puedes autoasignarte oportunidades."
                    )

            if datos.deadline_negociado:
                # Guard de idempotencia: solo reescribir si la fecha (en MX) cambio
                # de verdad. Sin esto, un guardado que solo mueve el estatus
                # reescribe el deadline y, al reaplicar la hora de corte, lo corre
                # +1 dia en cada edicion.
                current_dn = current_data['deadline_negociado']
                incoming_date = datos.deadline_negociado.date()
                current_date_mx = (
                    current_dn.astimezone(ZoneInfo("America/Mexico_City")).date()
                    if current_dn else None
                )
                if current_date_mx is not None and incoming_date == current_date_mx:
                    # Sin cambio real de fecha: preservar el valor almacenado tal cual.
                    datos.deadline_negociado = current_dn
                else:
                    config = await self.get_configuracion_global(conn)
                    parts = config.get("HORA_CORTE_L_V", "18:00").split(":")
                    h, m = int(parts[0]), int(parts[1])
                    datos.deadline_negociado = datos.deadline_negociado.replace(
                        hour=h, minute=m, second=0, microsecond=0,
                        tzinfo=ZoneInfo("America/Mexico_City")
                    )

        # 2. Validaciones de Reglas de Negocio para Cierre
        es_cierre = datos.id_estatus_global in [
            status_map["entregado"], 
            status_map["perdido"], 
            status_map["cancelado"]
        ]
        
        if es_cierre:
            # Validación: Motivo de cierre obligatorio
            # SOLO para Perdido y Cancelado (Entregado es éxito, no requiere motivo de "cierre/falla")
            if datos.id_estatus_global in [status_map["perdido"], status_map["cancelado"]]:
                if not datos.id_motivo_cierre:
                    raise HTTPException(
                        status_code=400, 
                        detail="El motivo de cierre es obligatorio para estados terminales (Perdido/Cancelado)."
                    )

            # Validación específica Entregado
            if datos.id_estatus_global == status_map["entregado"]:
                # VALIDACIÓN INTELIGENTE:
                # - Si es Multisitio (>1): Exigimos cierre manual uno por uno (Strict Mode)
                if total_sitios > 1:
                     # Verificar sitios pendientes (que no estén en Entregado, Cancelado, Perdido)
                    # Necesitamos 'id_oportunidad'. It is NOT in args. 
                    # Assuming we add it to args.
                    pass # See NOTE below. The original code did a query here.
                    
                    # NOTE: To avoid adding 'id_oportunidad' and 'conn' queries inside this helper if possible, 
                    # we could trust the caller to pass 'sites_pending_count' or let this helper do it.
                    # Since I am adding 'total_sitios', I should add 'id_oportunidad' too to be clean.
                    pass
                
                # BESS puro (id_tecnologia == 2): potencia FV no es obligatoria
                is_bess_only = current_data.get('id_tecnologia') == 2
                if not is_bess_only and datos.potencia_cierre_fv_kwp is None:
                    raise HTTPException(
                        status_code=400,
                        detail="Para marcar como Entregado, capture Potencia FV (KWp)."
                    )

        return datos

    async def _calculate_kpis_entrega_padre(
        self, 
        conn, 
        current_data: dict, 
        datos: SimulacionUpdate, 
        status_map: dict
    ) -> Tuple[Optional[str], Optional[str], Optional[float]]:
        """
        Calcula KPIs de entrega (Interno y Compromiso) y tiempo de elaboración.
        Actualiza fecha_entrega_simulacion en 'datos' si es necesario.
        """
        kpi_sla_val = None
        kpi_compromiso_val = None
        tiempo_elaboracion_horas = None
        
        # Regla: Fecha Automática para estatus terminales (Entregado, Cancelado, Perdido)
        # Se ignora cualquier input manual de fecha y se usa timestamp actual
        estatus_terminales = [
            status_map["entregado"],
            status_map["cancelado"],
            status_map["perdido"]
        ]
        
        if datos.id_estatus_global in estatus_terminales:
             fecha_fin_real = datos.fecha_entrega_simulacion or await self.get_current_datetime_mx(conn)
             datos.fecha_entrega_simulacion = fecha_fin_real
        else:
            # Si no es terminal, verificar reactivación (terminal -> no terminal)
            old_status = current_data['id_estatus_global']
            if old_status in estatus_terminales and datos.id_estatus_global not in estatus_terminales:
                 datos.fecha_entrega_simulacion = None
        
        # Calcular KPIs solo para Entregado/Perdido (Cancelado no lleva KPIs de eficiencia)
        if datos.id_estatus_global in [status_map["entregado"], status_map["perdido"]]:
            # Usar la fecha determinada arriba
            fecha_fin_real = datos.fecha_entrega_simulacion

            ts_deadline_calc = current_data['deadline_calculado']
            # OJO: Si el update trae un nuevo deadline negociado, usalo. Si no, usa el de base de datos.
            ts_deadline_nego = datos.deadline_negociado if datos.deadline_negociado else current_data['deadline_negociado']
            
            kpi_sla_val, kpi_compromiso_val = self.calcular_kpis_entrega(
                fecha_fin_real, 
                ts_deadline_calc, 
                ts_deadline_nego
            )

            # Cálculo de Tiempo Real
            if current_data['fecha_solicitud']:
                delta = self._as_aware(fecha_fin_real) - self._as_aware(current_data['fecha_solicitud'])
                tiempo_elaboracion_horas = round(delta.total_seconds() / 3600, 2)
                
        return kpi_sla_val, kpi_compromiso_val, tiempo_elaboracion_horas

    async def _calculate_fecha_sla(self, conn, fecha_real: datetime) -> datetime:
        from modules.comercial.sla_calculator import SLACalculator

        config = await self.get_configuracion_global(conn)
        hora_corte, _, _ = SLACalculator.parse_config(config)
        return SLACalculator.calculate_deadline(fecha_real, hora_corte, 0)

    async def get_historial_timeline(self, conn, id_oportunidad: UUID) -> List[dict]:
        return await self.db.get_historial_estatus_timeline(conn, id_oportunidad)

    async def _get_catalogo_estatus(self, conn) -> tuple[dict, dict]:
        rows = await self.db.get_estatus_oportunidades_activos(conn)
        catalog = {row["id"]: row for row in rows}
        by_orden = {row["orden"]: row for row in rows if row.get("orden") is not None}
        return catalog, by_orden

    @staticmethod
    def _is_entregado(estatus: dict) -> bool:
        return (estatus.get("nombre") or "").lower() == "entregado"

    def _validate_status_pair(self, origen: dict, destino: dict, by_orden: dict) -> None:
        if not origen or not destino:
            raise HTTPException(status_code=400, detail="Estatus no válido.")

        if origen["id"] == destino["id"]:
            raise HTTPException(
                status_code=400,
                detail=f"El estatus '{destino['nombre']}' no puede repetirse de forma consecutiva.",
            )

        if origen["es_estatus_final"]:
            raise HTTPException(
                status_code=400,
                detail=f"No se puede continuar el flujo después del estatus terminal '{origen['nombre']}'.",
            )

        if destino["es_estatus_final"]:
            if self._is_entregado(destino) and not (
                origen["nombre"] == "Comentarios Recibidos"
                or origen["activa_exclusion_kpis_simulacion"]
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Para marcar como 'Entregado' la oportunidad debe pasar primero por "
                        "'Comentarios Recibidos'."
                    ),
                )
            return

        # Estatus especiales (Monitoreo/Montaje): entrada/salida desde cualquier activo.
        if origen["activa_exclusion_kpis_simulacion"] or destino["activa_exclusion_kpis_simulacion"]:
            return

        if origen["orden"] is None or destino["orden"] is None:
            return

        diferencia = destino["orden"] - origen["orden"]
        if diferencia > 1:
            siguiente = by_orden.get(origen["orden"] + 1, {}).get("nombre", "el siguiente estatus")
            raise HTTPException(
                status_code=400,
                detail=(
                    f"El flujo es secuencial. Desde '{origen['nombre']}' el siguiente paso "
                    f"es '{siguiente}', no '{destino['nombre']}'."
                ),
            )
        if diferencia not in (1, -1):
            anterior = by_orden.get(origen["orden"] - 1, {}).get("nombre", "el estatus anterior")
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Solo se permite retroceder un paso. Desde '{origen['nombre']}' "
                    f"el retroceso permitido es a '{anterior}'."
                ),
            )

    async def insertar_transicion_historica(
        self,
        conn,
        id_oportunidad: UUID,
        id_estatus: int,
        fecha_real: datetime,
        user_context: dict,
    ) -> dict:
        fecha_real = self._as_aware(fecha_real)
        now_mx = await self.get_current_datetime_mx(conn)
        if fecha_real > now_mx:
            raise HTTPException(status_code=400, detail="La fecha del evento no puede ser futura.")

        catalog, by_orden = await self._get_catalogo_estatus(conn)
        nuevo = catalog.get(id_estatus)
        if not nuevo:
            raise HTTPException(status_code=400, detail="Estatus no válido.")

        min_gap = await ConfigService.get_global_config(conn, "MIN_MINUTOS_ENTRE_ESTATUS", 1, int)

        async with conn.transaction():
            locked = await self.db.lock_oportunidad_for_update(conn, id_oportunidad)
            if not locked:
                raise HTTPException(status_code=404, detail="Oportunidad no encontrada.")

            timeline = await self.db.get_historial_estatus_timeline(conn, id_oportunidad)
            if len(timeline) < 2:
                raise HTTPException(
                    status_code=400,
                    detail="La reconstrucción requiere al menos dos eventos existentes en el historial.",
                )

            anteriores = []
            siguientes = []
            for evento in timeline:
                t = self._as_aware(evento["fecha_cambio_real"])
                if t == fecha_real:
                    raise HTTPException(
                        status_code=400,
                        detail="Ya existe un evento registrado exactamente en esa fecha y hora.",
                    )
                if t < fecha_real:
                    anteriores.append(evento)
                else:
                    siguientes.append(evento)
            if not anteriores or not siguientes:
                raise HTTPException(
                    status_code=400,
                    detail="La reconstrucción solo puede insertarse entre dos eventos existentes.",
                )

            anterior = anteriores[-1]
            siguiente = siguientes[0]
            fecha_anterior = self._as_aware(anterior["fecha_cambio_real"])
            fecha_siguiente = self._as_aware(siguiente["fecha_cambio_real"])

            gap_anterior = (fecha_real - fecha_anterior).total_seconds() / 60
            gap_siguiente = (fecha_siguiente - fecha_real).total_seconds() / 60
            if gap_anterior < min_gap or gap_siguiente < min_gap:
                raise HTTPException(
                    status_code=400,
                    detail=f"Deben existir al menos {min_gap} minuto(s) entre eventos consecutivos.",
                )

            estatus_anterior = catalog.get(anterior["id_estatus_nuevo"])
            estatus_siguiente = catalog.get(siguiente["id_estatus_nuevo"])
            self._validate_status_pair(estatus_anterior, nuevo, by_orden)
            self._validate_status_pair(nuevo, estatus_siguiente, by_orden)

            fecha_sla = await self._calculate_fecha_sla(conn, fecha_real)
            return await self.db.insert_historial_estatus(
                conn,
                id_oportunidad,
                anterior["id_estatus_nuevo"],
                id_estatus,
                fecha_real,
                fecha_sla,
                user_context["user_db_id"],
                "Reconstrucción manual (correo)",
            )

    async def revertir_cierre_admin(
        self,
        conn,
        id_oportunidad: UUID,
        id_estatus_destino: int,
        user_context: dict,
    ) -> dict:
        if user_context.get("role") != "ADMIN":
            raise HTTPException(status_code=403, detail="Solo un Administrador puede revertir un cierre.")

        current_data = await self.db.get_oportunidad_for_update(conn, id_oportunidad)
        if not current_data:
            raise HTTPException(status_code=404, detail="Oportunidad no encontrada.")

        catalog, _ = await self._get_catalogo_estatus(conn)
        actual = catalog.get(current_data["id_estatus_global"])
        destino = catalog.get(id_estatus_destino)
        if not actual or not destino:
            raise HTTPException(status_code=400, detail="Estatus no válido.")
        if not actual["es_estatus_final"]:
            raise HTTPException(
                status_code=400,
                detail="La reversión Admin solo aplica a oportunidades en estatus terminal.",
            )
        if destino["es_estatus_final"] or destino.get("orden") not in (1, 2, 3, 4):
            raise HTTPException(
                status_code=400,
                detail="Seleccione un estatus activo válido para reabrir la oportunidad.",
            )

        now_mx = await self.get_current_datetime_mx(conn)
        datos_fecha = SimulacionUpdate(
            id_estatus_global=id_estatus_destino,
            fecha_cambio_real=None,
        )
        await self._validate_fecha_cambio(conn, id_oportunidad, datos_fecha, now_mx)
        fecha_real = datos_fecha.fecha_cambio_real
        fecha_sla = await self._calculate_fecha_sla(conn, fecha_real)

        async with conn.transaction():
            locked = await self.db.lock_oportunidad_for_update(conn, id_oportunidad)
            if not locked or locked["id_estatus_global"] != actual["id"]:
                raise HTTPException(
                    status_code=409,
                    detail="El estatus de la oportunidad cambió mientras se procesaba la solicitud. Intente de nuevo.",
                )
            await self.db.revertir_oportunidad_a_estatus(conn, id_oportunidad, id_estatus_destino)
            return await self.db.insert_historial_estatus(
                conn,
                id_oportunidad,
                actual["id"],
                id_estatus_destino,
                fecha_real,
                fecha_sla,
                user_context["user_db_id"],
                "Reversión de cierre (Admin)",
            )

    async def _validate_fecha_cambio(
        self,
        conn,
        id_oportunidad: UUID,
        datos: SimulacionUpdate,
        now_mx: datetime
    ) -> None:
        """
        Valida la fecha/hora real del cambio de estatus (§5.2):
        1. No futura.
        2. Mayor que el último cambio registrado.
        3. Gap >= MIN_MINUTOS_ENTRE_ESTATUS.
        Solo aplica validación de gap/orden cuando el usuario proporcionó backdating.
        Sin backdating (fecha_cambio_real=None), se normaliza a now_mx y se omite la validación.
        """
        backdating = datos.fecha_cambio_real is not None
        fecha_real = datos.fecha_cambio_real or now_mx
        if fecha_real.tzinfo is None:
            fecha_real = fecha_real.replace(tzinfo=ZoneInfo("America/Mexico_City"))
        datos.fecha_cambio_real = fecha_real

        if not backdating:
            return

        if fecha_real > now_mx:
            raise HTTPException(status_code=400, detail="La fecha del cambio no puede ser futura.")

        ultima_fecha_raw = await self.db.get_ultima_fecha_cambio_real(conn, id_oportunidad)
        if not ultima_fecha_raw:
            return

        ultima_fecha = self._as_aware(ultima_fecha_raw)
        if fecha_real <= ultima_fecha:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"La fecha del cambio debe ser posterior al último registro "
                    f"({ultima_fecha.strftime('%d/%m/%Y %H:%M')})."
                )
            )

        min_gap = await ConfigService.get_global_config(conn, "MIN_MINUTOS_ENTRE_ESTATUS", 1, int)

        gap_minutos = (fecha_real - ultima_fecha).total_seconds() / 60
        if gap_minutos < min_gap:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Deben pasar al menos {min_gap} minuto(s) entre cambios de estatus. "
                    f"El último cambio fue el {ultima_fecha.strftime('%d/%m/%Y %H:%M')}."
                )
            )

    async def _should_notify_status_change(
        self,
        conn,
        id_oportunidad: UUID,
        old_status_id: int,
        new_status_id: int,
        datos: SimulacionUpdate,
        notify_status: bool = True
    ) -> bool:
        """Decide si un cambio de estatus debe enviar correo para evitar spam."""
        if not notify_status:
            logger.info(
                "Correo de estatus omitido por bandera notify_status=false: oportunidad %s",
                id_oportunidad,
            )
            return False

        rows = await self.db.get_estatus_by_ids(conn, [new_status_id])
        new_status = rows[0] if rows else None
        if not new_status:
            return False

        hitos_config = await ConfigService.get_global_config(conn, "ESTATUS_HITO_CORREO", "Entregado")
        hitos = {
            hito.strip().lower()
            for hito in str(hitos_config).split(",")
            if hito.strip()
        }
        new_status_name = new_status["nombre"]
        if new_status_name.lower() not in hitos:
            logger.info(
                "Correo de estatus omitido: %s no es estatus hito para oportunidad %s",
                new_status_name,
                id_oportunidad,
            )
            return False

        registro_actual = await self.db.get_ultimo_historial_por_estatus(
            conn,
            id_oportunidad,
            new_status_id,
        )

        now_mx = await self.get_current_datetime_mx(conn)
        fecha_creacion_actual = self._as_aware(
            registro_actual["fecha_creacion"] if registro_actual else now_mx
        )
        fecha_real = self._as_aware(
            registro_actual["fecha_cambio_real"] if registro_actual else (datos.fecha_cambio_real or now_mx)
        )
        umbral_lag = await ConfigService.get_global_config(conn, "UMBRAL_LAG_NOTIFICACION", 1440, int)
        lag_minutos = (fecha_creacion_actual - fecha_real).total_seconds() / 60
        if lag_minutos > umbral_lag:
            logger.info(
                "Correo de estatus omitido por cambio retroactivo: oportunidad %s, lag %.1f min",
                id_oportunidad,
                lag_minutos,
            )
            return False

        ventana_bloque = await ConfigService.get_global_config(conn, "VENTANA_BLOQUE_REGISTRO_MIN", 2, int)
        previo = await self.db.get_historial_anterior(conn, id_oportunidad)
        if previo and not new_status["es_estatus_final"]:
            fecha_previa = self._as_aware(previo["fecha_creacion"])
            minutos_desde_previo = (fecha_creacion_actual - fecha_previa).total_seconds() / 60
            if minutos_desde_previo < ventana_bloque:
                logger.info(
                    "Correo de estatus omitido por registro en bloque: oportunidad %s, ventana %.1f min",
                    id_oportunidad,
                    minutos_desde_previo,
                )
                return False

        return True

    async def _validate_status_transition(
        self,
        conn,
        id_oportunidad: UUID,
        current_data: dict,
        datos: SimulacionUpdate,
        now_mx: datetime
    ) -> bool:
        """
        Valida que la transición de estatus siga el flujo secuencial (§5.1)
        y la fecha real sea coherente (§5.2).
        Lanza HTTPException(400) si alguna regla es violada.
        Devuelve (es_terminal, activa_exclusion):
        - es_terminal: True si el nuevo estatus es terminal (cierre de modal).
        - activa_exclusion: True si el nuevo estatus marca la oportunidad como excluida de KPIs
          (Monitoreo de Cotización / Montaje de oferta), por su flag de catálogo.
        """
        id_actual = current_data['id_estatus_global']
        id_nuevo = datos.id_estatus_global

        if id_actual == id_nuevo:
            return False, False

        # Cargar catálogo completo (< 10 filas) para evitar roundtrips extra en mensajes de error
        catalog, by_orden = await self._get_catalogo_estatus(conn)

        actual = catalog.get(id_actual)
        nuevo = catalog.get(id_nuevo)

        if not actual or not nuevo:
            raise HTTPException(status_code=400, detail="Estatus no válido.")

        # Reversión de terminales solo por endpoint dedicado (§5.7)
        if actual['es_estatus_final']:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"La oportunidad está en estatus terminal '{actual['nombre']}'. "
                    f"Solo un Administrador puede revertir un cierre."
                )
            )

        if nuevo['es_estatus_final']:
            # Entregado requiere pasar primero por Comentarios Recibidos (revisión obligatoria)
            # o desde un estatus especial de exclusión (Monitoreo/Montaje).
            if nuevo['nombre'] == 'Entregado' and not (
                actual['nombre'] == 'Comentarios Recibidos'
                or actual['activa_exclusion_kpis_simulacion']
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Para marcar como 'Entregado' la oportunidad debe pasar primero por "
                        f"'Comentarios Recibidos'. Estatus actual: '{actual['nombre']}'."
                    )
                )
            # Cancelado/Perdido: permitidos desde cualquier activo → sin más restricción
        elif actual['activa_exclusion_kpis_simulacion'] or nuevo['activa_exclusion_kpis_simulacion']:
            pass  # stand-by (Monitoreo/Montaje): entrada desde cualquier activo, salida a cualquier activo
        elif actual['orden'] is not None and nuevo['orden'] is not None:
            diferencia = nuevo['orden'] - actual['orden']
            if diferencia > 1:
                siguiente = by_orden.get(actual['orden'] + 1, {}).get('nombre', 'el siguiente estatus')
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"El flujo es secuencial. Desde '{actual['nombre']}' el siguiente paso "
                        f"es '{siguiente}', no '{nuevo['nombre']}'."
                    )
                )
            elif diferencia not in (1, -1):
                anterior = by_orden.get(actual['orden'] - 1, {}).get('nombre', 'el estatus anterior')
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Solo se permite retroceder un paso. Desde '{actual['nombre']}' "
                        f"el retroceso permitido es a '{anterior}'."
                    )
                )

        await self._validate_fecha_cambio(conn, id_oportunidad, datos, now_mx)
        return nuevo['es_estatus_final'], bool(nuevo['activa_exclusion_kpis_simulacion'])

    async def _handle_site_updates(
        self,
        conn,
        id_oportunidad: UUID,
        current_data: dict,
        datos: SimulacionUpdate,
        status_map: dict,
        total_sitios: int,
        sitios_pendientes: int
    ):
        """
        Maneja actualizaciones en cascada a sitios y marcado de retrabajos.
        """
        # 1. Regla de Cascada Mejorada: 
        # - Cancelación/Pérdida: Aplica a TODOS los sitios pendientes
        # - Entregado: Aplica si es unisitio o si solo queda 1 sitio pendiente (Smart Close)
        should_cascade = False
        
        if datos.id_estatus_global in [status_map["cancelado"], status_map["perdido"]]:
            should_cascade = True
        elif datos.id_estatus_global == status_map["entregado"]:
            # Cascada si es unisitio O si estamos en el último sitio activo
            if total_sitios == 1 or sitios_pendientes <= 1:
                should_cascade = True

        if should_cascade:
            fecha_cierre_cascada = datos.fecha_entrega_simulacion or await self.get_current_datetime_mx(conn)
            
            # Calcular KPIs duales para sitios
            kpi_sitio_interno, kpi_sitio_compromiso = self.calcular_kpis_sitio(
                fecha_cierre_cascada,
                current_data['deadline_calculado'],
                datos.deadline_negociado or current_data['deadline_negociado']
            )
            
            # Actualiza todos los sitios abiertos (cascada) con KPIs duales
            await self.db.update_sitios_cascada(
                conn, id_oportunidad, datos.id_estatus_global, 
                fecha_cierre_cascada, kpi_sitio_interno, kpi_sitio_compromiso
            )
        
        # 2. Procesar Retrabajos si estatus = ENTREGADO y es_retrabajo = True
        if datos.id_estatus_global == status_map["entregado"] and datos.es_retrabajo:
            if total_sitios == 1:
                # Mono-sitio: Marcar el único sitio como retrabajo
                await self.db.update_retrabajo_single(conn, id_oportunidad, datos.id_motivo_retrabajo)
            elif datos.sitios_retrabajo_ids:
                # Multi-sitio: Marcar solo los sitios seleccionados
                await self.db.update_retrabajo_multi(
                    conn, id_oportunidad, datos.sitios_retrabajo_ids, datos.id_motivo_retrabajo
                )
            
            logger.info(f"Retrabajos marcados para oportunidad {id_oportunidad}. Motivo: {datos.id_motivo_retrabajo}")

        # 3. Sincronizar flag es_retrabajo del padre (Reemplazo de Trigger)
        # Verifica si algún sitio quedó como retrabajo y actualiza el padre
        has_retrabajo = await self.db.check_any_retrabajo(conn, id_oportunidad)
        await self.db.update_es_retrabajo_parent(conn, id_oportunidad, has_retrabajo)

    async def _send_update_notifications(
        self, 
        conn, 
        id_oportunidad: UUID, 
        current_data: dict, 
        datos: SimulacionUpdate, 
        user_context: dict,
        notify_status: bool = True
    ):
        """
        Envía notificaciones de cambio de asignación y cambio de estatus.
        """
        old_responsable = current_data['responsable_simulacion_id']
        old_status = current_data['id_estatus_global']
        
        try:
            # Notificar asignación si cambió
            if datos.responsable_simulacion_id and old_responsable != datos.responsable_simulacion_id:
                await self.notification_service.notify_assignment(
                    conn=conn,
                    id_oportunidad=id_oportunidad,
                    old_responsable_id=old_responsable,
                    new_responsable_id=datos.responsable_simulacion_id,
                    assigned_by_ctx=user_context,
                    modulo_nombre="simulación",
                )
            
            # Notificar cambio de estatus si cambió
            if datos.id_estatus_global and old_status != datos.id_estatus_global:
                should_notify = await self._should_notify_status_change(
                    conn,
                    id_oportunidad,
                    old_status,
                    datos.id_estatus_global,
                    datos,
                    notify_status
                )
                if should_notify:
                    await self.notification_service.notify_status_change(
                        conn=conn,
                        id_oportunidad=id_oportunidad,
                        old_status_id=old_status,
                        new_status_id=datos.id_estatus_global,
                        changed_by_ctx=user_context
                    )
        except (
            asyncpg.PostgresError,
            KeyError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as notif_error:
            logger.error(f"Error en notificaciones (no critico): {notif_error}")

    # --- CONSULTAS (CORREGIDO: LISTA COMPLETA) ---

    async def get_oportunidades_list(self, conn, user_context: dict, tab: str = "activos", q: str = None, limit: int = 20, page: int = 1, subtab: str = None, filtro_tecnologia_id: Optional[int] = None) -> dict:
        """Recupera lista paginada de oportunidades para Simulación."""
        limit = max(1, min(limit, 50))
        page = max(1, page)
        return await self.db.get_oportunidades_filtradas(conn, tab, subtab, q, limit, page, filtro_tecnologia_id)

    async def get_dashboard_stats(self, conn, user_context: dict) -> dict:
        """Calcula KPIs globales."""
        # Total Activas (email_enviado = true)
        total = await self.db.get_kpi_total_oportunidades(conn, email_enviado=True)
        
        try:
            # 2. Obtener IDs clave dinámicamente
            status_map = await self._get_status_ids(conn)
            id_entregado = status_map.get("entregado")
            id_perdido = status_map.get("perdido")
            id_cancelado = status_map.get("cancelado")
            id_ganada = status_map.get("ganada")
            
            stats = {
                "kpis": {
                    "total": total or 0,
                    "levantamientos": 0,
                    "ganadas": 0,
                    "perdidas": 0
                },
                "charts": {
                    "trend": {"labels": [], "data": []},
                    "mix": {"labels": [], "data": []}
                }
            }

            # 4. KPIs: Ganadas/Perdidas
            # Ganadas = Entregado + Ganada (Incluimos estado final de éxito)
            ids_positivos = [i for i in [id_entregado, id_ganada] if i is not None]
            if ids_positivos:
                stats["kpis"]["ganadas"] = await self.db.get_kpi_conteo_estatus(conn, ids_positivos) or 0
            
            # Perdidas = Perdido + Cancelado
            ids_negativos = [i for i in [id_perdido, id_cancelado] if i is not None]
            if ids_negativos:
                stats["kpis"]["perdidas"] = await self.db.get_kpi_conteo_estatus(conn, ids_negativos) or 0

            # 5. KPIs: Levantamientos (Conteo real por Tipo de Solicitud)
            try:
                # Obtener ID del tipo 'Levantamiento'
                id_levantamiento = await self._get_catalog_id_by_name(conn, "tb_cat_tipos_solicitud", "Levantamiento")
                if id_levantamiento:
                    # Contar registros activos de ese tipo
                    stats["kpis"]["levantamientos"] = await self.db.get_kpi_levantamientos(conn, id_levantamiento) or 0
            except Exception as e_lev:
                logger.warning(f"No se pudo calcular KPI Levantamientos: {e_lev}")
                # Fallbback seguro (pero preferimos 0 a un cálculo erróneo)
                stats["kpis"]["levantamientos"] = 0

            # 6. Chart: Mix por Tecnología
            rows_tech = await self.db.get_chart_tech_mix(conn)
            stats["charts"]["mix"]["labels"] = [r["nombre"] for r in rows_tech]
            stats["charts"]["mix"]["data"] = [r["total"] for r in rows_tech]

            # 7. Chart: Tendencia (Últimos 30 días) - Simplificado por fecha de creación
            rows_trend = await self.db.get_chart_trend(conn)
            stats["charts"]["trend"]["labels"] = [r["fecha"] for r in rows_trend]
            stats["charts"]["trend"]["data"] = [r["total"] for r in rows_trend]
            
            return stats

        except Exception as e:
            logger.error(f"Error calculando dashboard stats: {e}")
            # Retorno seguro completo para que Jinja2 no falle
            return {
                "kpis": {
                    "total": 0,
                    "levantamientos": 0,
                    "ganadas": 0,
                    "perdidas": 0
                },
                "charts": {
                    "trend": {"labels": [], "data": []},
                    "mix": {"labels": [], "data": []}
                }
            } 

    async def crear_oportunidad_transaccional(self, conn, datos: OportunidadCreateCompleta, user_context: dict) -> tuple:
        """
        Crea una oportunidad de manera transaccional (Formulario Extraordinario).
        Genera op_id_estandar dinámico y maneja BESS.
        """
        # 1. Preparar Fechas y Horarios
        if datos.fecha_manual_str:
            fecha_solicitud = datetime.fromisoformat(datos.fecha_manual_str).replace(tzinfo=ZoneInfo("America/Mexico_City"))
        else:
            fecha_solicitud = await self.get_current_datetime_mx(conn)
            
        # Calcular si es fuera de horario usando configuración global
        config = await self.get_configuracion_global(conn)
        hora_corte_str = config.get("HORA_CORTE_L_V", "18:00")
        h, m = map(int, hora_corte_str.split(":"))
        hora_corte = dt_time(h, m)
        
        es_fuera_horario = False
        if fecha_solicitud.weekday() >= 5 or fecha_solicitud.time() > hora_corte:
             es_fuera_horario = True

        # ---------------------------------------------------------
        # 2. GESTIÓN INTELIGENTE DE CLIENTES (Shared Service)
        # ---------------------------------------------------------
        final_cliente_id, final_cliente_nombre = await ClientService.get_or_create_client_by_name(
            conn, datos.cliente_nombre, datos.cliente_id
        )

        # 3. Generar Identificadores
        new_id = uuid4()
        op_id_estandar = IdGeneratorService.generate_standard_op_id(fecha_solicitud)
        
        # ID Interno
        id_interno = IdGeneratorService.generate_internal_id(
            op_id_estandar, final_cliente_nombre, datos.nombre_proyecto, datos.cantidad_sitios
        )

        # 3. Título del Proyecto (Generación standard)
        nombre_tec, nombre_tipo = await self.db.get_catalogos_create(conn, datos.id_tecnologia, datos.id_tipo_solicitud)
        
        titulo_proyecto = IdGeneratorService.generate_project_title(
             nombre_tipo, final_cliente_nombre, datos.nombre_proyecto, nombre_tec, datos.canal_venta
        )

        # 4. Insertar con Transacción Atómica
        async with conn.transaction():
            # Prepare data dict
            data_insert = datos.model_dump()
            data_insert.update({
                'id': new_id, 'op_id_estandar': op_id_estandar, 'id_interno': id_interno,
                'titulo_proyecto': titulo_proyecto, 'cliente_nombre': final_cliente_nombre,
                'fecha_solicitud': fecha_solicitud, 'creado_por_id': user_context['user_db_id'],
                'solicitado_por': user_context.get('user_name'),
                'es_fuera_horario': es_fuera_horario, 
                'es_carga_manual': True if datos.fecha_manual_str else False,
                'cliente_id': final_cliente_id
            })
            await self.db.insert_oportunidad_completa(conn, data_insert)

            # 5. Insertar BESS si existe (Shared Service)
            if datos.detalles_bess:
                await BessService.create_bess_details(conn, new_id, datos.detalles_bess)
            
        # 6. Notificar creación (Opcional, si se requiere en futuro)
        # Por ahora solo retornamos
        
        logger.info(f"Oportunidad Transaccional Creada: {op_id_estandar}")
        return (new_id, op_id_estandar, es_fuera_horario)

    async def get_sitios(self, conn, id_oportunidad: UUID) -> List[dict]:
        return await self.db.get_sitios_list(conn, id_oportunidad)
    
    async def get_detalles_bess(self, conn, id_oportunidad: UUID):
        data = await self.db.get_detalles_bess(conn, id_oportunidad)
        if not data:
            return None
            
        # Fix: Ensure JSON is parsed if returned as text
        if data.get("uso_sistema_json") and isinstance(data["uso_sistema_json"], str):
            try:
                data["uso_sistema_json"] = json.loads(data["uso_sistema_json"])
            except json.JSONDecodeError:
                logger.error(f"Error decoding JSON for BESS {id_oportunidad}")
                data["uso_sistema_json"] = []
                
        return data
        


    async def get_catalogos_ui(self, conn) -> dict:
        tecnologias = await self.db.get_catalog_tecnologias(conn)
        
        # Filtrar tipos igual que en Comercial (Pre-Oferta, Simulacion, etc.)
        codigos = ['PRE_OFERTA', 'SIMULACION', 'CAPTURA_RECIBOS']
        tipos = await self.db.get_catalog_tipos_solicitud_ui(conn, codigos)
        
        # Usuarios para delegación (Fix para dropdown vacío)
        usuarios = await self.db.get_usuarios_all(conn)
        
        return {
            "tecnologias": tecnologias,
            "tipos_solicitud": tipos,
            "usuarios": usuarios
        }

    async def get_tecnologias_only(self, conn) -> dict:
        cache_key = "SIM_tecnologias_list"
        cached = await ConfigService.get_cached_value(cache_key)
        if cached:
            return {"tecnologias": cached}
        tecnologias = await self.db.get_catalog_tecnologias(conn)
        await ConfigService.set_cached_value(cache_key, tecnologias)
        return {"tecnologias": tecnologias}
    
    @staticmethod
    def get_canal_from_user_name(user_name: str) -> str:

        parts = (user_name or "").strip().split()
        return f"{parts[0]}_{parts[1]}".upper() if len(parts) >= 2 else (parts[0].upper() if parts else "")

def get_simulacion_service():
    return SimulacionService()
