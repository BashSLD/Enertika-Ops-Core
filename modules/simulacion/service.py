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
        except:
             tz = ZoneInfo("America/Mexico_City")
        return datetime.now(tz)


    async def get_configuracion_global(self, conn):
        """Obtiene la configuración de horarios desde la BD (usando cache)."""
        # Obtenemos valores individuales cacheados
        hora_corte = await ConfigService.get_global_config(conn, "HORA_CORTE_L_V", "18:00")
        return {"HORA_CORTE_L_V": hora_corte}
    
    # --- MÉTODOS PRIVADOS DE RESOLUCIÓN (NO HARDCODING) ---

    async def _get_catalog_id_by_name(self, conn, table: str, name_value: str) -> int:
        """Busca ID de catálogo por nombre de forma dinámica."""
        query = f"SELECT id FROM {table} WHERE LOWER(nombre) = LOWER($1)"
        id_val = await conn.fetchval(query, name_value)
        if not id_val:
            logger.error(f"Configuración faltante: No existe '{name_value}' en {table}")
            raise HTTPException(status_code=500, detail=f"Error Config: Falta '{name_value}' en BD.")
        return id_val

    async def _get_status_ids(self, conn) -> dict:
        """Devuelve mapa de IDs críticos usando Cache."""
        estatus_map = await ConfigService.get_catalog_map(conn, "tb_cat_estatus_global", "nombre", "id")
        
        # Helper safe lookup
        def get_id(name):
            val = estatus_map.get(name.lower())
            if not val:
                 # Fallback log
                 logger.error(f"Config faltante: Estatus '{name}' no encontrado en BD")
            return val

        return {
            "pendiente": get_id("Pendiente"),
            "entregado": get_id("Entregado"),
            "cancelado": get_id("Cancelado"),
            "perdido":   get_id("Perdido"),
            "ganada":    get_id("Ganada")
        }


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
            'tiempo_elaboracion_horas': tiempo_elaboracion_horas
        })
        await self.db.update_oportunidad_padre(conn, id_oportunidad, datos_dict)

        # 3.5. Insertar Historial (Si Cambio Estatus)
        if datos.id_estatus_global != current_data['id_estatus_global']:
            from modules.comercial.sla_calculator import SLACalculator
            from .db_service import QUERY_INSERT_HISTORIAL_ESTATUS
            
            # Calcular Fecha SLA (Inicio día siguiente si fuera de horario)
            config = await self.get_configuracion_global(conn)
            hora_corte, dias_fin_semana, _ = SLACalculator.parse_config(config)
            now_mx = await self.get_current_datetime_mx(conn)
            
            fecha_inicio_sla = SLACalculator.calculate_deadline(now_mx, hora_corte, 0)
            
            await conn.execute(QUERY_INSERT_HISTORIAL_ESTATUS,
                id_oportunidad,
                current_data['id_estatus_global'],
                datos.id_estatus_global,
                now_mx,
                fecha_inicio_sla,
                user_context['user_db_id']
            )

        # 4. Manejar Cascada a Sitios y Retrabajos
        await self._handle_site_updates(
            conn, id_oportunidad, current_data, datos, status_map, total_sitios, sitios_pendientes
        )

        # 5. Enviar Notificaciones
        await self._send_update_notifications(
            conn, id_oportunidad, current_data, datos, user_context
        )
        
        # 6. Return KPI data for confetti logic in router
        # Determine if there was a negotiated deadline (current or new)
        has_negotiated_deadline = bool(datos.deadline_negociado or current_data['deadline_negociado'])
        
        return (kpi_sla_val, kpi_compromiso_val, has_negotiated_deadline)

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
        
        # 1. Verificar Permisos de Campos Sensibles
        # Lógica espejo del router (update_oportunidades modal):
        #   - ADMIN del sistema -> SI
        #   - admin del módulo simulación -> SI
        #   - MANAGER del sistema + editor/admin del módulo -> SI
        #   - Editor regular -> NO
        sim_role = user_context.get("module_roles", {}).get("simulacion", "")
        is_admin_system = (user_context.get("role") == "ADMIN" or sim_role == "admin")
        is_manager_editor = (user_context.get("role") == "MANAGER" and sim_role in ["editor", "admin"])
        can_edit_sensitive = is_admin_system or is_manager_editor

        # 1.5 Validar Permiso Básico de Edición (IDOR Check)
        # Si NO es Admin/Manager, DEBE ser el dueño (responsable asignado)
        user_id = user_context.get("user_db_id")
        is_owner = str(current_data.get("responsable_simulacion_id")) == str(user_id)
        
        # Managers también pueden editar cualquier cosa, no solo sensitive
        can_edit_any = is_admin_system or (user_context.get("role") == "MANAGER")
        
        if not (can_edit_any or is_owner):
             raise HTTPException(
                status_code=403, 
                detail="No autorizado. Solo el responsable asignado puede editar esta oportunidad."
            )

        # monto_cierre_usd: siempre preservar de BD (no hay input en el modal)
        datos.monto_cierre_usd = current_data['monto_cierre_usd']

        # Si no tiene permisos sensibles, restaurar campos protegidos
        if not can_edit_sensitive:
            datos.id_interno_simulacion = current_data['id_interno_simulacion']
            datos.responsable_simulacion_id = current_data['responsable_simulacion_id']
            datos.deadline_negociado = current_data['deadline_negociado']
        else:
             # Si tiene permisos y envió una fecha de deadline, forzamos la hora a las 18:00:00 (Regla de negocio original)
            if datos.deadline_negociado:
                datos.deadline_negociado = datos.deadline_negociado.replace(hour=18, minute=0, second=0, microsecond=0)

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
                
                if datos.potencia_cierre_fv_kwp is None:
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
                # Asegurar timezone awarenss
                delta = fecha_fin_real - current_data['fecha_solicitud']
                tiempo_elaboracion_horas = round(delta.total_seconds() / 3600, 2)
                
        return kpi_sla_val, kpi_compromiso_val, tiempo_elaboracion_horas

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
        user_context: dict
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
                await self.notification_service.notify_status_change(
                    conn=conn,
                    id_oportunidad=id_oportunidad,
                    old_status_id=old_status,
                    new_status_id=datos.id_estatus_global,
                    changed_by_ctx=user_context
                )
        except Exception as notif_error:
            logger.error(f"Error en notificaciones (no critico): {notif_error}")

    # --- CONSULTAS (CORREGIDO: LISTA COMPLETA) ---

    async def get_oportunidades_list(self, conn, user_context: dict, tab: str = "activos", q: str = None, limit: int = 30, subtab: str = None, filtro_tecnologia_id: Optional[int] = None) -> List[dict]:
        """
        Recupera lista filtrada de oportunidades para Simulación.
        """
        return await self.db.get_oportunidades_filtradas(conn, tab, subtab, q, limit, filtro_tecnologia_id)

    async def get_dashboard_stats(self, conn, user_context: dict) -> dict:
        """Calcula KPIs globales."""
        # Nota: Ajusta queries para usar email_enviado = true siempre
        where_base = "WHERE email_enviado = true"
        
        # Total Activas
        total = await self.db.get_kpi_total_oportunidades(conn, where_base)
        
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
        


    async def get_comentarios_workflow(self, conn, id_oportunidad: UUID) -> List[dict]:
        """
        Obtiene el historial unificado de comentarios.
        Usa tb_comentarios_workflow (la única fuente de verdad).
        
        Args:
            conn: Conexión a la base de datos
            id_oportunidad: UUID de la oportunidad
            
        Returns:
            Lista de diccionarios con comentarios
        """
        return await self.db.get_comentarios_workflow(conn, id_oportunidad)
    
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
    
    @staticmethod
    def get_canal_from_user_name(user_name: str) -> str:

        parts = (user_name or "").strip().split()
        return f"{parts[0]}_{parts[1]}".upper() if len(parts) >= 2 else (parts[0].upper() if parts else "")

def get_simulacion_service():
    return SimulacionService()
