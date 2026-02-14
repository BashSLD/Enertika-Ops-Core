"""
Service Layer del Módulo Levantamientos
Implementa toda la lógica de negocio del sistema Kanban.
"""

from datetime import datetime
from uuid import UUID, uuid4
from typing import List, Optional, Dict
import logging
import asyncio
from zoneinfo import ZoneInfo
from fastapi import HTTPException
import json

logger = logging.getLogger("LevantamientosModule")

class LevantamientoService:
    """
    Service Layer para el módulo de levantamientos.
    
    Responsabilidades:
    - CRUD de levantamientos
    - Gestión de estados Kanban
    - Asignación de responsables
    - Integración con notificaciones
    - Registro de historial automático
    """
    
    # ========================================
    # CREACIÓN AUTOMÁTICA DESDE COMERCIAL
    # ========================================
    
    async def crear_desde_oportunidad(
        self,
        conn,
        id_oportunidad: UUID,
        user_context: dict
    ) -> UUID:
        """
        HOOK: Crea automáticamente un levantamiento cuando Comercial crea una oportunidad tipo LEVANTAMIENTO.
        
        Este método es llamado desde modules/comercial/service.py después de crear la oportunidad.
        
        Args:
            conn: Conexión a BD
            id_oportunidad: UUID de la oportunidad recién creada
            user_context: Contexto del usuario (user_db_id, user_name, email)
            
        Returns:
            UUID del levantamiento creado
        """
        logger.info(f"[LEVANTAMIENTO] Creando automáticamente para oportunidad {id_oportunidad}")
        
        # Obtener datos de la oportunidad
        opp = await conn.fetchrow("""
            SELECT o.id_oportunidad, o.titulo_proyecto, o.creado_por_id,
                   o.fecha_solicitud, s.id_sitio
            FROM tb_oportunidades o
            LEFT JOIN LATERAL (
                SELECT id_sitio 
                FROM tb_sitios_oportunidad 
                WHERE id_oportunidad = o.id_oportunidad 
                LIMIT 1
            ) s ON true
            WHERE o.id_oportunidad = $1
        """, id_oportunidad)
        
        if not opp:
            raise HTTPException(status_code=404, detail="Oportunidad no encontrada")
        
        # Si no hay sitio, crear uno por defecto
        id_sitio = opp['id_sitio']
        if not id_sitio:
            id_sitio = await self._crear_sitio_default(conn, id_oportunidad)
        
        # Crear levantamiento
        new_id = uuid4()
        now_mx = datetime.now(ZoneInfo("America/Mexico_City"))
        
        await conn.execute("""
            INSERT INTO tb_levantamientos (
                id_levantamiento, id_sitio, id_oportunidad,
                solicitado_por_id, id_estatus_global,
                fecha_solicitud, created_at, updated_at,
                updated_by_id
            ) VALUES ($1, $2, $3, $4, 8, $5, $5, $5, $4)
        """, new_id, id_sitio, id_oportunidad, opp['creado_por_id'], 
            opp['fecha_solicitud'] or now_mx)
        
        # Registrar en historial inicial
        await self._registrar_en_historial(
            conn=conn,
            id_levantamiento=new_id,
            estatus_anterior=None,
            estatus_nuevo=8,  # Pendiente
            user_context=user_context,
            observaciones="Levantamiento creado automáticamente desde solicitud comercial"
        )
        
        logger.info(f"[LEVANTAMIENTO] {new_id} creado exitosamente")
        return new_id
    
    async def _crear_sitio_default(self, conn, id_oportunidad: UUID) -> UUID:
        """Crea un sitio por defecto si la oportunidad no tiene sitios."""
        sitio_id = uuid4()
        await conn.execute("""
            INSERT INTO tb_sitios_oportunidad (id_sitio, id_oportunidad, direccion, nombre_sitio)
            SELECT $1, $2, 
                   COALESCE(direccion_obra, 'Sitio sin dirección especificada'), 
                   COALESCE(nombre_proyecto, 'Sitio principal')
            FROM tb_oportunidades
            WHERE id_oportunidad = $2
        """, sitio_id, id_oportunidad)
        
        logger.info(f"[LEVANTAMIENTO] Sitio default {sitio_id} creado para oportunidad {id_oportunidad}")
        return sitio_id
    
    # ========================================
    # KANBAN DATA
    # ========================================
    
    async def get_kanban_data(self, conn) -> dict:
        """
        Obtiene datos del tablero Kanban agrupados por estado.
        
        Optimizado con CTEs para evitar subconsultas correlacionadas.
        
        Returns:
            dict con 6 listas: pendientes, agendados, en_proceso, completados, entregados, pospuestos
        """
        # Query optimizada con Common Table Expressions (CTEs)
        query = """
            WITH comentarios_count AS (
                -- Contar comentarios por oportunidad (una sola pasada)
                SELECT id_oportunidad, COUNT(*) as total_comentarios
                FROM tb_comentarios_workflow
                GROUP BY id_oportunidad
            ),
            tiempo_en_estado AS (
                -- Calcular tiempo en estado actual (una sola pasada)
                SELECT 
                    lh.id_levantamiento,
                    MAX(lh.fecha_transicion) as ultima_transicion
                FROM tb_levantamientos_historial lh
                INNER JOIN tb_levantamientos l ON lh.id_levantamiento = l.id_levantamiento
                WHERE lh.id_estatus_nuevo = l.id_estatus_global
                GROUP BY lh.id_levantamiento
            )
            SELECT
                   l.id_levantamiento,
                   l.id_oportunidad,
                   l.id_estatus_global,
                   l.fecha_solicitud,
                   l.fecha_visita_programada,
                   l.created_at,
                   l.updated_at,
                   o.op_id_estandar,
                   o.titulo_proyecto,
                   o.nombre_proyecto,
                   o.cliente_nombre,
                   o.prioridad,
                   o.cantidad_sitios,
                   s.direccion,
                   s.nombre_sitio,
                   -- Logic for Multi-Technician Display
                   COALESCE(techs.nombres, u_tec.nombre) as tecnico_nombre,
                   u_tec.email as tecnico_email, -- Legacy
                   NULL as tecnico_area,
                   u_jefe.nombre as jefe_nombre,
                   u_jefe.id_usuario as jefe_id,
                   u_sol.nombre as solicitado_por_nombre,
                   -- Comentarios count desde CTE
                   COALESCE(cc.total_comentarios, 0) as comentarios_count,
                   -- Tiempo en estado desde CTE
                   EXTRACT(EPOCH FROM (
                       NOW() - COALESCE(te.ultima_transicion, l.created_at)
                   )) as segundos_en_estado
            FROM tb_levantamientos l
            INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            LEFT JOIN tb_sitios_oportunidad s ON l.id_sitio = s.id_sitio
            LEFT JOIN tb_usuarios u_tec ON l.tecnico_asignado_id = u_tec.id_usuario
            LEFT JOIN tb_usuarios u_jefe ON l.jefe_area_id = u_jefe.id_usuario
            LEFT JOIN tb_usuarios u_sol ON l.solicitado_por_id = u_sol.id_usuario
            -- JOIN con CTEs para optimización
            LEFT JOIN comentarios_count cc ON l.id_oportunidad = cc.id_oportunidad
            LEFT JOIN tiempo_en_estado te ON l.id_levantamiento = te.id_levantamiento
            -- LATERAL JOIN for Multiple Technicians
            LEFT JOIN LATERAL (
                SELECT string_agg(u.nombre, ', ') as nombres
                FROM tb_levantamiento_asignaciones la
                JOIN tb_usuarios u ON la.tecnico_id = u.id_usuario
                WHERE la.id_levantamiento = l.id_levantamiento
            ) techs ON true
        WHERE l.id_estatus_global IN (8, 9, 10, 11, 12, 13)
          AND o.email_enviado = true
        ORDER BY l.created_at DESC
    """
        rows = await conn.fetch(query)
        
        # Organizar en columnas del Kanban (6 columnas)
        kanban = {
            "pendientes": [],        # Estado 8
            "agendados": [],         # Estado 9
            "en_proceso": [],        # Estado 10
            "completados": [],       # Estado 11
            "entregados": [],        # Estado 12
            "pospuestos": []         # Estado 13
        }
        
        # Obtener Jefe Default para fallback visual
        jefe_default = await conn.fetchrow("""
             SELECT id_usuario, nombre FROM tb_usuarios 
             WHERE es_jefe_levantamientos_default = TRUE LIMIT 1
        """)
        jefe_default_nombre = jefe_default['nombre'] if jefe_default else "Sin asignar"
        jefe_default_id = jefe_default['id_usuario'] if jefe_default else None

        for row in rows:
            item = dict(row)
            # Calcular tiempo relativo
            item['tiempo_relativo'] = self._format_tiempo_relativo(item.get('segundos_en_estado', 0))
            
            # Fallback Jefe Default (Visual)
            if not item['jefe_nombre'] and jefe_default_nombre:
                item['jefe_nombre'] = jefe_default_nombre
                # Opcional: item['jefe_id'] = jefe_default_id

            st = item['id_estatus_global']
            if st == 8:
                kanban['pendientes'].append(item)
            elif st == 9:
                kanban['agendados'].append(item)
            elif st == 10:
                kanban['en_proceso'].append(item)
            elif st == 11:
                kanban['completados'].append(item)
            elif st == 12:
                kanban['entregados'].append(item)
            elif st == 13:
                kanban['pospuestos'].append(item)
        
        logger.debug(f"[KANBAN] Datos cargados: {sum(len(v) for v in kanban.values())} levantamientos")
        return kanban
    
    def _format_tiempo_relativo(self, segundos: float) -> str:
        """Formatea segundos a texto legible."""
        if not segundos or segundos < 60:
            return "Recién actualizado"
        elif segundos < 3600:
            mins = int(segundos / 60)
            return f"Hace {mins} min{'s' if mins > 1 else ''}"
        elif segundos < 86400:
            horas = int(segundos / 3600)
            return f"Hace {horas} hora{'s' if horas > 1 else ''}"
        else:
            dias = int(segundos / 86400)
            return f"Hace {dias} día{'s' if dias > 1 else ''}"
    
    # ========================================
    # ASIGNACIÓN DE RESPONSABLES
    # ========================================
    
    async def get_jefe_default(self, conn) -> Optional[UUID]:
        """Obtiene el ID del jefe de levantamientos por defecto."""
        return await conn.fetchval("""
            SELECT id_usuario 
            FROM tb_usuarios 
            WHERE es_jefe_levantamientos_default = TRUE 
            LIMIT 1
        """)

    async def assign_responsables(
        self,
        conn,
        id_levantamiento: UUID,
        tecnicos_ids: List[UUID],
        jefe_id: Optional[UUID],
        user_context: dict,
        observaciones: Optional[str] = None
    ):
        """
        Asigna técnicos (multiples) y/o jefe de área.
        Usa tb_levantamiento_asignaciones para técnicos.
        """
        # PERMISOS: Solo Admin, Manager o Admin de Levantamientos pueden asignar
        is_admin_or_manager = (
            user_context.get("role") in ["ADMIN", "MANAGER"] or 
            user_context.get("module_roles", {}).get("levantamientos") == "admin"
        )
        
        if not is_admin_or_manager:
            raise HTTPException(
                status_code=403,
                detail="No tienes permisos para asignar responsables. Contacta a un administrador."
            )
        # Validar levantamiento
        current = await conn.fetchrow("""
            SELECT id_levantamiento, jefe_area_id, id_oportunidad, id_estatus_global
            FROM tb_levantamientos
            WHERE id_levantamiento = $1
        """, id_levantamiento)
        
        if not current:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        # 1. Actualizar Jefe en tabla principal
        now_mx = datetime.now(ZoneInfo("America/Mexico_City"))
        
        # Mantener legacy tecnico_asignado_id con el primero de la lista (para compatibilidad)
        legacy_tecnico_id = tecnicos_ids[0] if tecnicos_ids else None

        await conn.execute("""
            UPDATE tb_levantamientos
            SET jefe_area_id = $1,
                tecnico_asignado_id = $2, -- Legacy support
                updated_at = $3,
                updated_by_id = $4
            WHERE id_levantamiento = $5
        """, jefe_id, legacy_tecnico_id, now_mx, user_context['user_db_id'], id_levantamiento)

        # 2. Actualizar Tabla Pivote (Sync Strategy: Borrar e Insertar)
        # Comparar con actuales para notificaciones
        old_tech_rows = await conn.fetch("""
            SELECT tecnico_id FROM tb_levantamiento_asignaciones WHERE id_levantamiento = $1
        """, id_levantamiento)
        old_tech_ids = [r['tecnico_id'] for r in old_tech_rows]
        
        # Borrar asignaciones existentes
        await conn.execute("DELETE FROM tb_levantamiento_asignaciones WHERE id_levantamiento = $1", id_levantamiento)
        
        # Insertar nuevas
        if tecnicos_ids:
            records = [(id_levantamiento, tid, user_context['user_db_id']) for tid in set(tecnicos_ids)]
            await conn.executemany("""
                INSERT INTO tb_levantamiento_asignaciones (id_levantamiento, tecnico_id, asignado_por_id)
                VALUES ($1, $2, $3)
            """, records)

        # 3. Registrar Historial
        obs_text = observaciones or "Asignación de responsables actualizada"
        metadata = {
            "tipo_cambio": "asignacion",
            "jefe_id": str(jefe_id) if jefe_id else None,
            "tecnicos_ids": [str(t) for t in tecnicos_ids]
        }
        
        await self._registrar_en_historial(
            conn=conn,
            id_levantamiento=id_levantamiento,
            estatus_anterior=current['id_estatus_global'],
            estatus_nuevo=current['id_estatus_global'],
            user_context=user_context,
            observaciones=obs_text,
            metadata=metadata
        )

        # 4. Notificaciones
        # Notificar a nuevos técnicos asignados
        new_techs = set(tecnicos_ids) - set(old_tech_ids)
        for new_tid in new_techs:
             asyncio.create_task(
                self._execute_notification_background(
                    self._notificar_asignacion_impl,
                    id_oportunidad=current['id_oportunidad'],
                    old_responsable_id=None, # Tratamos como nueva asignación
                    new_responsable_id=new_tid,
                    user_context=user_context
                )
            )
    
    # ========================================
    # CAMBIO DE ESTADO
    # ========================================
    
    async def cambiar_estado(
        self,
        conn,
        id_levantamiento: UUID,
        nuevo_estado: int,
        user_context: dict,
        observaciones: Optional[str] = None
    ):
        """
        Cambia el estado de un levantamiento y registra en historial.
        El trigger de BD se encarga del auto-registro.
        
        Args:
            conn: Conexión a BD
            id_levantamiento: ID del levantamiento
            nuevo_estado: Nuevo ID de estatus (8-13)
            user_context: Contexto del usuario
            observaciones: Comentarios sobre el cambio
        """
        # Validar estado
        estados_validos = [8, 9, 10, 11, 12, 13]
        if nuevo_estado not in estados_validos:
            raise HTTPException(
                status_code=400, 
                detail=f"Estado inválido: {nuevo_estado}. Debe ser entre 8-13"
            )
        
        # Obtener estado actual
        current = await conn.fetchrow("""
            SELECT id_estatus_global, id_oportunidad
            FROM tb_levantamientos
            WHERE id_levantamiento = $1
        """, id_levantamiento)
        
        if not current:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        # PERMISOS: Admin/Manager, Editor Module, o TÉCNICO ASIGNADO
        user_id = user_context.get("user_db_id")
        user_role = user_context.get("role")
        mod_role = user_context.get("module_roles", {}).get("levantamientos")
        
        is_admin_or_editor = (user_role in ["ADMIN", "MANAGER"] or mod_role in ["admin", "editor"])
        
        if not is_admin_or_editor:
            # Verificar si es técnico asignado
            from .db_service import get_db_service
            db_svc = get_db_service()
            assigned_techs = await db_svc.get_asignaciones_actuales(conn, id_levantamiento)
            
            if user_id not in assigned_techs:
                raise HTTPException(
                    status_code=403, 
                    detail="Solo los técnicos asignados o administradores pueden cambiar el estado."
                )
        
        estado_anterior = current['id_estatus_global']
        
        if estado_anterior == nuevo_estado:
            logger.info(f"[ESTADO] Sin cambio para levantamiento {id_levantamiento}")
            return  # Sin cambio
        
        # Actualizar estado (Manual history insertion to replace trigger)
        now_mx = datetime.now(ZoneInfo("America/Mexico_City"))
        
        async with conn.transaction():
            await conn.execute("""
                UPDATE tb_levantamientos
                SET id_estatus_global = $1,
                    updated_at = $2,
                    updated_by_id = $3
                WHERE id_levantamiento = $4
            """, nuevo_estado, now_mx, user_context['user_db_id'], id_levantamiento)
            
            # Insertar en Historial (Reemplazo de Trigger)
            await self._registrar_en_historial(
                conn=conn,
                id_levantamiento=id_levantamiento,
                estatus_anterior=estado_anterior,
                estatus_nuevo=nuevo_estado,
                user_context=user_context,
                observaciones=observaciones or "Cambio de estado manual"
            )
        
        # Notificar cambio de estado - Fire & Forget para respuesta instantánea
        asyncio.create_task(
            self._execute_notification_background(
                self._notificar_cambio_estado_impl,
                id_oportunidad=current['id_oportunidad'],
                old_status_id=estado_anterior,
                new_status_id=nuevo_estado,
                user_context=user_context
            )
        )
        
        logger.info(f"[ESTADO] Levantamiento {id_levantamiento}: {estado_anterior} -> {nuevo_estado}")

    async def validate_status_change_prerequisites(self, conn, id_levantamiento: UUID, nuevo_estado: int):
        """
        Valida reglas de negocio antes de cambiar de estado.
        Lanza HTTPException si no se cumplen.
        """
        from .db_service import get_db_service
        db_svc = get_db_service()

        # Regla 1: Para pasar a "En Proceso" (10), debe tener técnicos asignados
        if nuevo_estado == 10:
            has_techs = await db_svc.check_asignaciones(conn, id_levantamiento)
            if not has_techs:
                raise HTTPException(
                    status_code=400,
                    detail="Debes asignar al menos un ingeniero antes de iniciar el levantamiento."
                )

            # Regla 2: Para pasar a "En Proceso" (10), debe haber solicitado viáticos
            has_viaticos = await db_svc.check_viaticos_sent(conn, id_levantamiento)
            if not has_viaticos:
                 raise HTTPException(
                    status_code=400,
                    detail="Debes enviar la solicitud de viáticos antes de iniciar."
                )

    async def get_modal_data(self, conn, id_levantamiento: UUID) -> dict:
        """Obtiene datos estandarizados para los modales."""
        from .db_service import get_db_service
        db_svc = get_db_service()
        
        data = await db_svc.get_levantamiento_modal_header(conn, id_levantamiento)
        if not data:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")
        return data

    
    # ========================================
    # HISTORIAL
    # ========================================
    
    async def _registrar_en_historial(
        self,
        conn,
        id_levantamiento: UUID,
        estatus_anterior: Optional[int],
        estatus_nuevo: int,
        user_context: dict,
        observaciones: Optional[str] = None,
        metadata: Optional[dict] = None
    ):
        """
        Registra cambio en historial manualmente.
        Usado para creación inicial y asignaciones (el trigger solo registra cambios de estado).
        """
        await conn.execute("""
            INSERT INTO tb_levantamientos_historial (
                id_levantamiento, id_estatus_anterior, id_estatus_nuevo,
                modificado_por_id, modificado_por_nombre, modificado_por_email,
                observaciones, metadata
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
        """, 
            id_levantamiento, estatus_anterior, estatus_nuevo,
            user_context['user_db_id'], 
            user_context['user_name'], 
            user_context.get('email', user_context.get('user_email', '')),
            observaciones, 
            json.dumps(metadata or {})
        )
    
    async def get_historial_estados(self, conn, id_levantamiento: UUID) -> List[dict]:
        """Obtiene timeline de cambios."""
        rows = await conn.fetch("""
            SELECT 
                h.id,
                h.id_estatus_anterior,
                h.id_estatus_nuevo,
                h.fecha_transicion,
                h.modificado_por_nombre,
                h.modificado_por_email,
                h.observaciones,
                h.metadata,
                e_ant.nombre as nombre_estado_anterior,
                e_ant.color_hex as color_anterior,
                e_new.nombre as nombre_estado_nuevo,
                e_new.color_hex as color_nuevo
            FROM tb_levantamientos_historial h
            LEFT JOIN tb_cat_estatus_global e_ant ON h.id_estatus_anterior = e_ant.id
            INNER JOIN tb_cat_estatus_global e_new ON h.id_estatus_nuevo = e_new.id
            WHERE h.id_levantamiento = $1
            ORDER BY h.fecha_transicion DESC
        """, id_levantamiento)
        
        return [dict(r) for r in rows]
    
    # ========================================
    # NOTIFICACIONES (Fire & Forget Pattern)
    # ========================================
    
    async def _execute_notification_background(
        self,
        notification_func,
        **kwargs
    ):
        """
        Ejecuta notificaciones en segundo plano con manejo apropiado de conexiones.
        
        Este método obtiene su propia conexión a BD para el background task,
        evitando problemas con el ciclo de vida de conexiones de FastAPI.
        
        Args:
            notification_func: Función de notificación a ejecutar
            **kwargs: Argumentos para la función de notificación
        """
        try:
            from core.database import get_db_connection
            
            # Obtener nueva conexión para el background task
            async for conn in get_db_connection():
                await notification_func(conn=conn, **kwargs)
                break  # Solo necesitamos una iteración
        except Exception as e:
            logger.error(
                f"[BACKGROUND NOTIFICATION] Error en tarea de fondo: {e}",
                exc_info=True,
                extra={"notification_func": notification_func.__name__, "kwargs": kwargs}
            )
    
    async def _notificar_asignacion_impl(
        self,
        conn,
        id_oportunidad: UUID,
        old_responsable_id: Optional[UUID],
        new_responsable_id: Optional[UUID],
        user_context: dict
    ):
        """
        Implementación de notificación de asignación.
        Llamada por Fire & Forget desde assign_responsables.
        """
        if old_responsable_id == new_responsable_id:
            return
        
        try:
            from core.workflow.notification_service import get_notification_service
            
            notif_service = get_notification_service()
            await notif_service.notify_assignment(
                conn=conn,
                id_oportunidad=id_oportunidad,
                old_responsable_id=old_responsable_id,
                new_responsable_id=new_responsable_id,
                assigned_by_ctx=user_context,
                modulo_nombre="levantamiento",
            )
            logger.info(f"[NOTIFICACIÓN] Asignación notificada exitosamente para oportunidad {id_oportunidad}")
        except Exception as e:
            logger.error(
                f"[NOTIFICACIÓN] Error al notificar asignación: {e}",
                exc_info=True,
                extra={"id_oportunidad": str(id_oportunidad)}
            )
    
    async def _notificar_cambio_estado_impl(
        self,
        conn,
        id_oportunidad: UUID,
        old_status_id: int,
        new_status_id: int,
        user_context: dict
    ):
        """
        Implementación de notificación de cambio de estado.
        Llamada por Fire & Forget desde cambiar_estado.
        """
        try:
            from core.workflow.notification_service import get_notification_service
            
            notif_service = get_notification_service()
            await notif_service.notify_status_change(
                conn=conn,
                id_oportunidad=id_oportunidad,
                old_status_id=old_status_id,
                new_status_id=new_status_id,
                changed_by_ctx=user_context
            )
            logger.info(
                f"[NOTIFICACIÓN] Cambio de estado notificado exitosamente: "
                f"{old_status_id} -> {new_status_id} (oportunidad {id_oportunidad})"
            )
        except Exception as e:
            logger.error(
                f"[NOTIFICACIÓN] Error al notificar cambio de estado: {e}",
                exc_info=True,
                extra={
                    "id_oportunidad": str(id_oportunidad),
                    "old_status": old_status_id,
                    "new_status": new_status_id
                }
            )

    async def registrar_devolucion(
        self,
        conn,
        id_levantamiento: UUID,
        user_context: dict
    ):
        """
        Registra la devolución de viáticos y limpia los activos.
        Llamado cuando se pospone un levantamiento con la opción activada.
        """
        from .db_service import get_db_service
        db_svc = get_db_service()

        # 1. Registrar evento en histórico (Estado 'devuelto')
        await db_svc.registrar_devolucion_viaticos(
            conn, 
            id_levantamiento,
            user_context['user_db_id'],
            user_context.get('user_name', 'Usuario')
        )

        # 2. Limpiar viáticos activos (para que la próxima solicitud empiece de 0)
        await db_svc.clear_viaticos_activos(conn, id_levantamiento)

        logger.info(f"[VIATICOS] Devolución registrada para levantamiento {id_levantamiento}")

    async def _notificar_agendado_impl(
        self,
        conn,
        id_oportunidad: UUID,
        fecha_visita: str,
        user_context: dict
    ):
        """Notificación específica para cuando se agenda una visita."""
        try:
            from core.workflow.notification_service import get_notification_service
            
            # Emular notificacion de cambio de estatus a "Agendado" con fecha de visita.
            
            notif_service = get_notification_service()
            # We trigger a status change notification to 9 (Agendado) explictly
            await notif_service.notify_status_change(
                conn=conn,
                id_oportunidad=id_oportunidad,
                old_status_id=8, # Assumptions usually from Pendiente
                new_status_id=9, # Agendado
                changed_by_ctx=user_context,
                extra_data={"fecha_visita": str(fecha_visita)}
            )
            logger.info(f"[NOTIFICACIÓN] Visita agendada notificada para oportunidad {id_oportunidad}")
            
        except Exception as e:
            logger.error(f"[NOTIFICACIÓN] Error al notificar agenda: {e}", exc_info=True)

    async def _notificar_pospuesto_impl(
        self,
        conn,
        id_oportunidad: UUID,
        motivo: str,
        user_context: dict
    ):
        """Notificación específica para cuando se pospone."""
        try:
            from core.workflow.notification_service import get_notification_service
            notif_service = get_notification_service()
            
            await notif_service.notify_status_change(
                conn=conn,
                id_oportunidad=id_oportunidad,
                old_status_id=9, # Assumption
                new_status_id=13, # Pospuesto
                changed_by_ctx=user_context,
                extra_data={"motivo": motivo}
            )
            logger.info(f"[NOTIFICACIÓN] Posposición notificada para oportunidad {id_oportunidad}")
            
        except Exception as e:
            logger.error(f"[NOTIFICACIÓN] Error al notificar posponer: {e}", exc_info=True)
    
    # ========================================
    # CATÁLOGOS
    # ========================================
    
    async def get_usuarios_para_asignacion(self, conn) -> Dict[str, List[dict]]:
        """
        Obtiene listas de usuarios para asignación.
        
        Returns:
            {
                'tecnicos': [...],  # Usuarios con acceso a levantamientos
                'jefes': [...]      # Gerentes o usuarios marcados como jefes
            }
        """
        # Técnicos: Usuarios con permiso al módulo levantamientos
        tecnicos = await conn.fetch("""
            SELECT DISTINCT u.id_usuario, u.nombre, u.email
            FROM tb_usuarios u
            INNER JOIN tb_permisos_modulos pm ON u.id_usuario = pm.usuario_id

            WHERE pm.modulo_slug = 'levantamientos'
              AND u.is_active = true
            ORDER BY u.nombre
        """)
        
        # Jefes: Solo usuarios marcados como jefe default
        jefes = await conn.fetch("""
            SELECT id_usuario, nombre, email, rol_sistema
            FROM tb_usuarios
            WHERE es_jefe_levantamientos_default = true
              AND is_active = true
            ORDER BY nombre
            LIMIT 1
        """)
        
        return {
            'tecnicos': [dict(t) for t in tecnicos],
            'jefes': [dict(j) for j in jefes]
        }


def get_service():
    """Helper para inyección de dependencias."""
    return LevantamientoService()
