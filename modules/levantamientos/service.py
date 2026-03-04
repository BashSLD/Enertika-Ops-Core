"""
Service Layer del Módulo Levantamientos
Implementa toda la lógica de negocio del sistema Kanban.
"""

from datetime import datetime
from uuid import UUID, uuid4
from typing import List, Optional, Dict
from collections import defaultdict
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
            SELECT id_oportunidad, titulo_proyecto, creado_por_id, fecha_solicitud
            FROM tb_oportunidades
            WHERE id_oportunidad = $1
        """, id_oportunidad)

        if not opp:
            raise HTTPException(status_code=404, detail="Oportunidad no encontrada")

        # Obtener TODOS los sitios de la oportunidad (multisite)
        sitios = await conn.fetch("""
            SELECT id_sitio, nombre_sitio
            FROM tb_sitios_oportunidad
            WHERE id_oportunidad = $1
            ORDER BY fecha_carga ASC
        """, id_oportunidad)

        # Si no hay sitios, crear uno por defecto
        if not sitios:
            id_sitio_default = await self._crear_sitio_default(conn, id_oportunidad)
            sitios = [{"id_sitio": id_sitio_default}]

        # Verificar sitios que ya tienen levantamiento (evitar duplicados)
        sitios_con_lev = await conn.fetch("""
            SELECT id_sitio FROM tb_levantamientos
            WHERE id_oportunidad = $1 AND id_sitio IS NOT NULL
        """, id_oportunidad)
        sitios_ya_creados = {r['id_sitio'] for r in sitios_con_lev}

        from .db_service import get_db_service as _get_db
        _db = _get_db()
        estatus_map = await _db.get_estatus_map(conn)
        estatus_pendiente_id = estatus_map['pendiente']

        now_mx = datetime.now(ZoneInfo("America/Mexico_City"))
        first_id = None

        for sitio in sitios:
            id_sitio = sitio['id_sitio']

            if id_sitio in sitios_ya_creados:
                logger.debug(f"[LEVANTAMIENTO] Sitio {id_sitio} ya tiene levantamiento, omitiendo")
                continue

            new_id = uuid4()

            await conn.execute("""
                INSERT INTO tb_levantamientos (
                    id_levantamiento, id_sitio, id_oportunidad,
                    solicitado_por_id, id_estatus_global,
                    fecha_solicitud, created_at, updated_at,
                    updated_by_id
                ) VALUES ($1, $2, $3, $4, $6, $5, $5, $5, $4)
            """, new_id, id_sitio, id_oportunidad, opp['creado_por_id'],
                opp['fecha_solicitud'] or now_mx, estatus_pendiente_id)

            # Registrar en historial inicial
            await self._registrar_en_historial(
                conn=conn,
                id_levantamiento=new_id,
                estatus_anterior=None,
                estatus_nuevo=estatus_pendiente_id,
                user_context=user_context,
                observaciones="Levantamiento creado automáticamente desde solicitud comercial"
            )

            if first_id is None:
                first_id = new_id

            logger.info(f"[LEVANTAMIENTO] {new_id} creado para sitio {id_sitio}")

        if first_id is None:
            # Todos los sitios ya tenían levantamiento, retornar el existente
            first_id = await conn.fetchval("""
                SELECT id_levantamiento FROM tb_levantamientos
                WHERE id_oportunidad = $1 ORDER BY created_at ASC LIMIT 1
            """, id_oportunidad)

        logger.info(f"[LEVANTAMIENTO] Creación multisite completada para oportunidad {id_oportunidad}")
        return first_id
    
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
                -- Contar comentarios por cadena completa (padre + hermanos)
                SELECT o.id_oportunidad, COUNT(cw.id) as total_comentarios
                FROM tb_oportunidades o
                LEFT JOIN tb_comentarios_workflow cw ON cw.id_oportunidad IN (
                    -- La propia oportunidad
                    SELECT o.id_oportunidad
                    UNION
                    -- Sus hijos (si es padre)
                    SELECT child.id_oportunidad FROM tb_oportunidades child WHERE child.parent_id = o.id_oportunidad
                    UNION
                    -- Su padre (si es hijo)
                    SELECT o.parent_id WHERE o.parent_id IS NOT NULL
                    UNION
                    -- Sus hermanos (si es hijo)
                    SELECT sib.id_oportunidad FROM tb_oportunidades sib 
                    WHERE sib.parent_id = o.parent_id AND o.parent_id IS NOT NULL
                )
                GROUP BY o.id_oportunidad
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
            ),
            asignaciones_check AS (
                -- Levantamientos que ya tienen al menos una asignacion en la tabla pivote
                SELECT DISTINCT id_levantamiento FROM tb_levantamiento_asignaciones
            )
            SELECT
                   l.id_levantamiento,
                   l.id_oportunidad,
                   l.id_estatus_global,
                   l.solicitado_por_id,
                   l.fecha_solicitud             AT TIME ZONE 'America/Mexico_City' AS fecha_solicitud,
                   l.fecha_visita_programada     AT TIME ZONE 'America/Mexico_City' AS fecha_visita_programada,
                   l.fecha_ideal_solicitante     AT TIME ZONE 'America/Mexico_City' AS fecha_ideal_solicitante,
                   l.created_at                  AT TIME ZONE 'America/Mexico_City' AS created_at,
                   l.updated_at                  AT TIME ZONE 'America/Mexico_City' AS updated_at,
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
                   )) as segundos_en_estado,
                   -- Flag "es_nuevo": creado < 48h, sin asignacion pivot ni legacy
                   CASE WHEN
                       l.created_at > NOW() - INTERVAL '48 hours'
                       AND a_check.id_levantamiento IS NULL
                       AND l.tecnico_asignado_id IS NULL
                   THEN true ELSE false END AS es_nuevo
            FROM tb_levantamientos l
            INNER JOIN tb_oportunidades o ON l.id_oportunidad = o.id_oportunidad
            LEFT JOIN tb_sitios_oportunidad s ON l.id_sitio = s.id_sitio
            LEFT JOIN tb_usuarios u_tec ON l.tecnico_asignado_id = u_tec.id_usuario
            LEFT JOIN tb_usuarios u_jefe ON l.jefe_area_id = u_jefe.id_usuario
            LEFT JOIN tb_usuarios u_sol ON l.solicitado_por_id = u_sol.id_usuario
            -- JOIN con CTEs para optimización
            LEFT JOIN comentarios_count cc ON l.id_oportunidad = cc.id_oportunidad
            LEFT JOIN tiempo_en_estado te ON l.id_levantamiento = te.id_levantamiento
            LEFT JOIN asignaciones_check a_check ON l.id_levantamiento = a_check.id_levantamiento
            -- LATERAL JOIN for Multiple Technicians
            LEFT JOIN LATERAL (
                SELECT string_agg(u.nombre, ', ') as nombres
                FROM tb_levantamiento_asignaciones la
                JOIN tb_usuarios u ON la.tecnico_id = u.id_usuario
                WHERE la.id_levantamiento = l.id_levantamiento
            ) techs ON true
        WHERE l.id_estatus_global = ANY($1::int[])
          AND o.email_enviado = true
        ORDER BY l.created_at DESC
    """
        from .db_service import get_db_service as _get_db_svc
        _db_svc = _get_db_svc()
        estatus_map = await _db_svc.get_estatus_map(conn)
        id_to_codigo = {v: k for k, v in estatus_map.items()}
        # Excluir "cancelado" del Kanban — se muestra solo en vista lista
        cancelado_id = estatus_map.get('cancelado')
        todos_los_ids = [id for id in estatus_map.values() if id != cancelado_id]
        rows = await conn.fetch(query, todos_los_ids)

        # Pre-calcular sitio_num y sitio_total para badge multisite
        # Agrupar IDs de levantamientos por oportunidad (en el orden devuelto por la query)
        op_to_lev_ids: dict = defaultdict(list)
        for row in rows:
            op_to_lev_ids[row['id_oportunidad']].append(row['id_levantamiento'])

        # Organizar en columnas del Kanban (6 columnas)
        kanban = {
            "pendientes": [],        # Estado 1
            "agendados": [],         # Estado 2
            "en_proceso": [],        # Estado 3
            "completados": [],       # Estado 5
            "entregados": [],        # Estado 6
            "pospuestos": []         # Estado 4
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

            # Badge multisite: calcular posición dentro del grupo de la oportunidad
            lev_ids_en_op = op_to_lev_ids[item['id_oportunidad']]
            item['sitio_total'] = len(lev_ids_en_op)
            try:
                item['sitio_num'] = lev_ids_en_op.index(item['id_levantamiento']) + 1
            except ValueError:
                item['sitio_num'] = 1

            codigo = id_to_codigo.get(item['id_estatus_global'], '')
            if codigo == 'pendiente':
                kanban['pendientes'].append(item)
            elif codigo == 'agendado':
                kanban['agendados'].append(item)
            elif codigo == 'en_proceso':
                kanban['en_proceso'].append(item)
            elif codigo == 'completado':
                kanban['completados'].append(item)
            elif codigo == 'entregado':
                kanban['entregados'].append(item)
            elif codigo == 'pospuesto':
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
        observaciones: Optional[str] = None,
        responsable_id: Optional[UUID] = None
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

        # Detectar si cambia el responsable (para limpiar viáticos)
        old_responsable_row = await conn.fetchrow("""
            SELECT tecnico_id FROM tb_levantamiento_asignaciones
            WHERE id_levantamiento = $1 AND es_responsable = true
        """, id_levantamiento)
        old_responsable_id = old_responsable_row['tecnico_id'] if old_responsable_row else None

        # Auto-responsable: si hay un solo técnico y no se indicó responsable explícito
        unique_techs = list(set(tecnicos_ids))
        if responsable_id is None and len(unique_techs) == 1:
            responsable_id = unique_techs[0]

        responsable_cambio = (responsable_id is not None and old_responsable_id != responsable_id)

        # Borrar asignaciones existentes
        await conn.execute("DELETE FROM tb_levantamiento_asignaciones WHERE id_levantamiento = $1", id_levantamiento)

        # Insertar nuevas con flag es_responsable
        if tecnicos_ids:
            records = [
                (id_levantamiento, tid, user_context['user_db_id'], tid == responsable_id)
                for tid in unique_techs
            ]
            await conn.executemany("""
                INSERT INTO tb_levantamiento_asignaciones
                    (id_levantamiento, tecnico_id, asignado_por_id, es_responsable)
                VALUES ($1, $2, $3, $4)
            """, records)

        # Limpiar viáticos activos si el responsable cambió
        if responsable_cambio:
            from .db_service import get_db_service as _get_db
            _db = _get_db()
            tiene_viaticos = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM tb_levantamiento_viaticos WHERE id_levantamiento = $1)",
                id_levantamiento
            )
            if tiene_viaticos:
                await _db.clear_viaticos_activos(conn, id_levantamiento)
                logger.info(f"[VIATICOS] Limpiados por cambio de responsable en levantamiento {id_levantamiento}")

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
            nuevo_estado: Nuevo ID de estatus (1-6)
            user_context: Contexto del usuario
            observaciones: Comentarios sobre el cambio
        """
        # Validar estado contra catálogo de BD
        from .db_service import get_db_service as _get_db_cambiar
        _estatus_map = await _get_db_cambiar().get_estatus_map(conn)
        estados_validos = list(_estatus_map.values())
        if nuevo_estado not in estados_validos:
            raise HTTPException(
                status_code=400,
                detail=f"Estado inválido: {nuevo_estado}."
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
        estatus_map = await db_svc.get_estatus_map(conn)
        id_en_proceso = estatus_map.get('en_proceso')

        # Regla 1: Para pasar a "En Proceso", debe tener técnicos asignados
        if nuevo_estado == id_en_proceso:
            has_techs = await db_svc.check_asignaciones(conn, id_levantamiento)
            if not has_techs:
                raise HTTPException(
                    status_code=400,
                    detail="Debes asignar al menos un ingeniero antes de iniciar el levantamiento."
                )

            # Regla 2: Para pasar a "En Proceso", debe haber solicitado viáticos
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
            LEFT JOIN tb_cat_estatus_levantamiento e_ant ON h.id_estatus_anterior = e_ant.id
            INNER JOIN tb_cat_estatus_levantamiento e_new ON h.id_estatus_nuevo = e_new.id
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
                changed_by_ctx=user_context,
                modulo_origen='levantamientos'
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
            from .db_service import get_db_service as _get_db_notif
            _estatus_map = await _get_db_notif().get_estatus_map(conn)

            notif_service = get_notification_service()
            await notif_service.notify_status_change(
                conn=conn,
                id_oportunidad=id_oportunidad,
                old_status_id=_estatus_map.get('pendiente', 0),
                new_status_id=_estatus_map.get('agendado', 0),
                changed_by_ctx=user_context,
                extra_data={"fecha_visita": str(fecha_visita)},
                modulo_origen='levantamientos'
            )
            logger.info(f"[NOTIFICACIÓN] Visita agendada notificada para oportunidad {id_oportunidad}")
            
        except Exception as e:
            logger.error(f"[NOTIFICACIÓN] Error al notificar agenda: {e}", exc_info=True)

    async def _notificar_solicitud_reasignacion_impl(
        self,
        conn,
        id_levantamiento: UUID,
        id_oportunidad: UUID,
        motivo: str,
        user_context: dict
    ):
        """Notifica solicitud de reasignación a quien asignó al responsable + quien solicitó el levantamiento."""
        try:
            from core.workflow.notification_service import get_notification_service
            notif = get_notification_service()
            await notif.notify_reassignment_request(
                conn=conn,
                id_levantamiento=id_levantamiento,
                id_oportunidad=id_oportunidad,
                solicitado_por_ctx=user_context,
                motivo=motivo,
            )
        except Exception as e:
            logger.error(f"[NOTIFICACION] Error solicitud reasignacion: {e}", exc_info=True)

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
            from .db_service import get_db_service as _get_db_notif2
            _estatus_map2 = await _get_db_notif2().get_estatus_map(conn)
            notif_service = get_notification_service()

            await notif_service.notify_status_change(
                conn=conn,
                id_oportunidad=id_oportunidad,
                old_status_id=_estatus_map2.get('agendado', 0),
                new_status_id=_estatus_map2.get('pospuesto', 0),
                changed_by_ctx=user_context,
                extra_data={"motivo": motivo},
                modulo_origen='levantamientos'
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
        # Responsables: solo editor/admin del módulo levantamientos
        # Son quienes gestionan activamente el levantamiento (pueden cambiar estados, etc.)
        responsables = await conn.fetch("""
            SELECT DISTINCT u.id_usuario, u.nombre, u.email
            FROM tb_usuarios u
            JOIN tb_permisos_modulos pm ON pm.usuario_id = u.id_usuario
            WHERE u.is_active = true
              AND pm.modulo_slug = 'levantamientos'
              AND pm.rol_modulo IN ('editor', 'admin')
            ORDER BY u.nombre
        """)

        # Acompañantes: flag explícito O cualquier permiso en el módulo
        # Incluye personas de otras áreas que suelen acompañar levantamientos
        acompaniantes = await conn.fetch("""
            SELECT DISTINCT u.id_usuario, u.nombre, u.email
            FROM tb_usuarios u
            WHERE u.is_active = true
              AND (
                  u.puede_asignarse_levantamientos = true
                  OR EXISTS (
                      SELECT 1 FROM tb_permisos_modulos pm
                      WHERE pm.usuario_id = u.id_usuario
                        AND pm.modulo_slug = 'levantamientos'
                  )
              )
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
            'responsables': [dict(t) for t in responsables],
            'acompaniantes': [dict(t) for t in acompaniantes],
            'jefes': [dict(j) for j in jefes]
        }


    # ========================================
    # CANCELAR / REACTIVAR
    # ========================================

    async def cancelar_levantamiento(
        self,
        conn,
        id_levantamiento: UUID,
        motivo: str,
        user_context: dict,
    ):
        """
        Cancela un levantamiento:
        1. Cambia estado a 'cancelado'
        2. Cancela la oportunidad asociada en tb_oportunidades
        3. Limpia viáticos activos
        4. Registra en historial
        5. Fire & Forget: notificación a jefe de área + solicitante
        """
        from .db_service import get_db_service as _get_db
        _db = _get_db()
        estatus_map = await _db.get_estatus_map(conn)
        id_cancelado = estatus_map.get('cancelado')
        if not id_cancelado:
            raise HTTPException(status_code=500, detail="Estado 'cancelado' no configurado en catalogo")

        lev = await conn.fetchrow("""
            SELECT id_levantamiento, id_oportunidad, id_estatus_global, jefe_area_id, solicitado_por_id
            FROM tb_levantamientos
            WHERE id_levantamiento = $1
        """, id_levantamiento)
        if not lev:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        if lev['id_estatus_global'] == id_cancelado:
            raise HTTPException(status_code=400, detail="El levantamiento ya esta cancelado")

        now_mx = datetime.now(ZoneInfo("America/Mexico_City"))

        async with conn.transaction():
            # 1. Cancelar levantamiento (reutilizamos motivo_pospone para guardar el motivo)
            await conn.execute("""
                UPDATE tb_levantamientos
                SET id_estatus_global = $1,
                    motivo_pospone    = $2,
                    updated_at        = $3,
                    updated_by_id     = $4
                WHERE id_levantamiento = $5
            """, id_cancelado, motivo, now_mx, user_context['user_db_id'], id_levantamiento)

            # 2. Cancelar oportunidad asociada
            id_cancelado_opp = await conn.fetchval("""
                SELECT id FROM tb_cat_estatus_oportunidades
                WHERE LOWER(nombre) LIKE '%cancelad%' AND activo = true
                LIMIT 1
            """)
            if id_cancelado_opp:
                await conn.execute("""
                    UPDATE tb_oportunidades
                    SET id_estatus_global = $1,
                        updated_at        = $2
                    WHERE id_oportunidad = $3
                """, id_cancelado_opp, now_mx, lev['id_oportunidad'])
            else:
                logger.warning(f"[CANCELAR] No se encontro estado 'cancelado' en tb_cat_estatus_oportunidades para opp {lev['id_oportunidad']}")

            # 3. Limpiar viáticos activos
            await _db.clear_viaticos_activos(conn, id_levantamiento)

            # 4. Historial
            await self._registrar_en_historial(
                conn=conn,
                id_levantamiento=id_levantamiento,
                estatus_anterior=lev['id_estatus_global'],
                estatus_nuevo=id_cancelado,
                user_context=user_context,
                observaciones=motivo,
                metadata={"tipo_cambio": "cancelacion"}
            )

        # 5. Notificación Fire & Forget
        asyncio.create_task(
            self._execute_notification_background(
                self._notificar_cancelacion_impl,
                id_levantamiento=id_levantamiento,
                id_oportunidad=lev['id_oportunidad'],
                motivo=motivo,
                user_context=user_context,
            )
        )

        logger.info(f"[CANCELAR] Levantamiento {id_levantamiento} cancelado por {user_context['user_name']}")

    async def reactivar_levantamiento(
        self,
        conn,
        id_levantamiento: UUID,
        user_context: dict,
    ):
        """
        Reactiva un levantamiento cancelado, devolviéndolo a 'pendiente'.
        La oportunidad queda en estado cancelado — el equipo comercial decide qué hacer.
        """
        from .db_service import get_db_service as _get_db
        _db = _get_db()
        estatus_map = await _db.get_estatus_map(conn)
        id_cancelado = estatus_map.get('cancelado')
        id_pendiente = estatus_map.get('pendiente')

        lev = await conn.fetchrow("""
            SELECT id_levantamiento, id_estatus_global
            FROM tb_levantamientos
            WHERE id_levantamiento = $1
        """, id_levantamiento)
        if not lev:
            raise HTTPException(status_code=404, detail="Levantamiento no encontrado")

        if lev['id_estatus_global'] != id_cancelado:
            raise HTTPException(status_code=400, detail="Solo se pueden reactivar levantamientos cancelados")

        now_mx = datetime.now(ZoneInfo("America/Mexico_City"))

        await conn.execute("""
            UPDATE tb_levantamientos
            SET id_estatus_global = $1,
                motivo_pospone    = NULL,
                updated_at        = $2,
                updated_by_id     = $3
            WHERE id_levantamiento = $4
        """, id_pendiente, now_mx, user_context['user_db_id'], id_levantamiento)

        await self._registrar_en_historial(
            conn=conn,
            id_levantamiento=id_levantamiento,
            estatus_anterior=id_cancelado,
            estatus_nuevo=id_pendiente,
            user_context=user_context,
            observaciones="Levantamiento reactivado manualmente",
            metadata={"tipo_cambio": "reactivacion"}
        )

        logger.info(f"[REACTIVAR] Levantamiento {id_levantamiento} reactivado por {user_context['user_name']}")

    async def _notificar_cancelacion_impl(
        self,
        conn,
        id_levantamiento: UUID,
        id_oportunidad: UUID,
        motivo: str,
        user_context: dict,
    ):
        """Notifica la cancelación del levantamiento al jefe de área + quien solicitó."""
        try:
            from core.workflow.notification_service import get_notification_service
            notif = get_notification_service()
            await notif.notify_cancellation(
                conn=conn,
                id_levantamiento=id_levantamiento,
                id_oportunidad=id_oportunidad,
                cancelado_por_ctx=user_context,
                motivo=motivo,
            )
        except Exception as e:
            logger.error(f"[NOTIFICACION] Error notificando cancelacion lev {id_levantamiento}: {e}", exc_info=True)


def get_service():
    """Helper para inyección de dependencias."""
    return LevantamientoService()
