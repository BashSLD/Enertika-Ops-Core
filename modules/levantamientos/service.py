"""
Service Layer del Módulo Levantamientos
Implementa toda la lógica de negocio del sistema Kanban.

Cumple con GUIA_MAESTRA:
- Separación de responsabilidades
- Timestamps con timezone
- Integración con WorkflowService
- Notificaciones automáticas
"""

from datetime import datetime
from uuid import UUID, uuid4
from typing import List, Optional, Dict
import logging
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
        
        Returns:
            dict con 6 listas: pendientes, agendados, en_proceso, completados, entregados, pospuestos
        """
        query = """
            SELECT DISTINCT ON (l.id_levantamiento)
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
                   u_tec.nombre as tecnico_nombre,
                   u_tec.id_usuario as tecnico_id,
                   u_tec.email as tecnico_email,
                   dept_tec.departamento_rol as tecnico_area,
                   u_jefe.nombre as jefe_nombre,
                   u_jefe.id_usuario as jefe_id,
                   u_sol.nombre as solicitado_por_nombre,
                   -- Contar comentarios
                   (SELECT COUNT(*) FROM tb_comentarios_workflow 
                    WHERE id_oportunidad = l.id_oportunidad) as comentarios_count,
                   -- Calcular tiempo en estado actual
                   EXTRACT(EPOCH FROM (NOW() - 
                       COALESCE(
                           (SELECT MAX(fecha_transicion) 
                            FROM tb_levantamientos_historial 
                            WHERE id_levantamiento = l.id_levantamiento
                              AND id_estatus_nuevo = l.id_estatus_global),
                           l.created_at
                       )
                   )) as segundos_en_estado
            FROM tb_levantamientos l
            INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            LEFT JOIN tb_sitios_oportunidad s ON l.id_sitio = s.id_sitio
            LEFT JOIN tb_usuarios u_tec ON l.tecnico_asignado_id = u_tec.id_usuario
            LEFT JOIN tb_permisos_usuarios dept_tec ON dept_tec.usuario_id = u_tec.id_usuario
            LEFT JOIN tb_usuarios u_jefe ON l.jefe_area_id = u_jefe.id_usuario
            LEFT JOIN tb_usuarios u_sol ON l.solicitado_por_id = u_sol.id_usuario
            WHERE l.id_estatus_global IN (8, 9, 10, 11, 12, 13)
            ORDER BY l.id_levantamiento, o.prioridad DESC, l.fecha_solicitud ASC
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
        
        for row in rows:
            item = dict(row)
            # Calcular tiempo relativo
            item['tiempo_relativo'] = self._format_tiempo_relativo(item.get('segundos_en_estado', 0))
            
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
    
    async def assign_responsables(
        self,
        conn,
        id_levantamiento: UUID,
        tecnico_id: Optional[UUID],
        jefe_id: Optional[UUID],
        user_context: dict,
        observaciones: Optional[str] = None
    ):
        """
        Asigna técnico y/o jefe de área a un levantamiento.
        Envía notificaciones automáticamente.
        
        Args:
            conn: Conexión a BD
            id_levantamiento: ID del levantamiento
            tecnico_id: ID del técnico a asignar (None para desasignar)
            jefe_id: ID del jefe de área a asignar (None para desasignar)
            user_context: Contexto del usuario que asigna
            observaciones: Comentarios sobre la asignación
        """
        # Obtener asignaciones actuales
        current = await conn.fetchrow("""
            SELECT tecnico_asignado_id, jefe_area_id, id_oportunidad, id_estatus_global
            FROM tb_levantamientos
            WHERE id_levantamiento = $1
        """, id_levantamiento)
        
        if not current:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")
        
        # Actualizar asignaciones
        now_mx = datetime.now(ZoneInfo("America/Mexico_City"))
        await conn.execute("""
            UPDATE tb_levantamientos
            SET tecnico_asignado_id = $1,
                jefe_area_id = $2,
                updated_at = $3,
                updated_by_id = $4
            WHERE id_levantamiento = $5
        """, tecnico_id, jefe_id, now_mx, user_context['user_db_id'], id_levantamiento)
        
        # Registrar en historial (sin cambio de estado, solo asignación)
        obs_text = observaciones or "Asignación de responsables actualizada"
        await self._registrar_en_historial(
            conn=conn,
            id_levantamiento=id_levantamiento,
            estatus_anterior=current['id_estatus_global'],
            estatus_nuevo=current['id_estatus_global'],  # Mismo estado
            user_context=user_context,
            observaciones=obs_text,
            metadata={
                "tipo_cambio": "asignacion", 
                "tecnico_id": str(tecnico_id) if tecnico_id else None, 
                "jefe_id": str(jefe_id) if jefe_id else None
            }
        )
        
        # Notificar al técnico asignado (si cambió)
        if tecnico_id and tecnico_id != current['tecnico_asignado_id']:
            await self._notificar_asignacion(
                conn=conn,
                id_oportunidad=current['id_oportunidad'],
                old_responsable_id=current['tecnico_asignado_id'],
                new_responsable_id=tecnico_id,
                user_context=user_context
            )
        
        logger.info(f"[ASIGNACIÓN] Levantamiento {id_levantamiento} - Técnico: {tecnico_id}, Jefe: {jefe_id}")
    
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
        
        estado_anterior = current['id_estatus_global']
        
        if estado_anterior == nuevo_estado:
            logger.info(f"[ESTADO] Sin cambio para levantamiento {id_levantamiento}")
            return  # Sin cambio
        
        # Actualizar estado (el trigger registrará en historial)
        now_mx = datetime.now(ZoneInfo("America/Mexico_City"))
        await conn.execute("""
            UPDATE tb_levantamientos
            SET id_estatus_global = $1,
                updated_at = $2,
                updated_by_id = $3
            WHERE id_levantamiento = $4
        """, nuevo_estado, now_mx, user_context['user_db_id'], id_levantamiento)
        
        # Si hay observaciones, actualizar el último registro de historial
        if observaciones:
            await conn.execute("""
                UPDATE tb_levantamientos_historial
                SET observaciones = $1
                WHERE id_levantamiento = $2
                  AND id_estatus_nuevo = $3
                ORDER BY fecha_transicion DESC
                LIMIT 1
            """, observaciones, id_levantamiento, nuevo_estado)
        
        # Notificar cambio de estado
        await self._notificar_cambio_estado(
            conn=conn,
            id_oportunidad=current['id_oportunidad'],
            old_status_id=estado_anterior,
            new_status_id=nuevo_estado,
            user_context=user_context
        )
        
        logger.info(f"[ESTADO] Levantamiento {id_levantamiento}: {estado_anterior} -> {nuevo_estado}")
    
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
    # NOTIFICACIONES (Integración)
    # ========================================
    
    async def _notificar_asignacion(
        self,
        conn,
        id_oportunidad: UUID,
        old_responsable_id: Optional[UUID],
        new_responsable_id: Optional[UUID],
        user_context: dict
    ):
        """Envía notificación de asignación usando el servicio existente."""
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
                assigned_by_ctx=user_context
            )
        except Exception as e:
            logger.error(f"[NOTIFICACIÓN] Error al notificar asignación: {e}")
    
    async def _notificar_cambio_estado(
        self,
        conn,
        id_oportunidad: UUID,
        old_status_id: int,
        new_status_id: int,
        user_context: dict
    ):
        """Envía notificación de cambio de estado."""
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
        except Exception as e:
            logger.error(f"[NOTIFICACIÓN] Error al notificar cambio de estado: {e}")
    
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
            SELECT DISTINCT u.id_usuario, u.nombre, u.email, dept.departamento_rol
            FROM tb_usuarios u
            INNER JOIN tb_permisos_modulos pm ON u.id_usuario = pm.usuario_id
            LEFT JOIN tb_permisos_usuarios dept ON u.id_usuario = dept.usuario_id
            WHERE pm.modulo_slug = 'levantamientos'
              AND u.is_active = true
            ORDER BY u.nombre
        """)
        
        # Jefes: Gerentes O usuarios con flag puede_ser_jefe_area
        jefes = await conn.fetch("""
            SELECT id_usuario, nombre, email, rol_sistema
            FROM tb_usuarios
            WHERE (
                    rol_sistema IN ('MANAGER', 'DIRECTOR', 'ADMIN')
                    OR puede_ser_jefe_area = true
                  )
              AND is_active = true
            ORDER BY nombre
        """)
        
        return {
            'tecnicos': [dict(t) for t in tecnicos],
            'jefes': [dict(j) for j in jefes]
        }


def get_service():
    """Helper para inyección de dependencias."""
    return LevantamientoService()
