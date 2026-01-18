from datetime import datetime, timedelta, time as dt_time
from uuid import UUID, uuid4
from typing import List, Optional
import json
import logging
from decimal import Decimal
import asyncpg
from fastapi import HTTPException
from zoneinfo import ZoneInfo

# Importar schemas locales
from .schemas import SimulacionUpdate, DetalleBessCreate, OportunidadCreateCompleta
from core.workflow.notification_service import get_notification_service

logger = logging.getLogger("SimulacionModule")

class SimulacionService:
    """Encapsula la lógica de negocio del módulo Simulación (v3.1 Multisitio)."""

    async def get_current_datetime_mx(self, conn=None) -> datetime:
        """Fuente de verdad de tiempo (CDMX)."""
        return datetime.now(ZoneInfo("America/Mexico_City"))

    async def get_configuracion_global(self, conn):
        """Obtiene la configuración de horarios desde la BD."""
        rows = await conn.fetch("SELECT clave, valor, tipo_dato FROM tb_configuracion_global")
        config = {r['clave']: r['valor'] for r in rows}
        return config
    
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
        """Devuelve mapa de IDs críticos."""
        return {
            "pendiente": await self._get_catalog_id_by_name(conn, "tb_cat_estatus_global", "Pendiente"),
            "entregado": await self._get_catalog_id_by_name(conn, "tb_cat_estatus_global", "Entregado"),
            "cancelado": await self._get_catalog_id_by_name(conn, "tb_cat_estatus_global", "Cancelado"),
            "perdido":   await self._get_catalog_id_by_name(conn, "tb_cat_estatus_global", "Perdido"),
            "ganada":    await self._get_catalog_id_by_name(conn, "tb_cat_estatus_global", "Ganada")
        }

    # --- LÓGICA DE NEGOCIO ---

    async def get_responsables_dropdown(self, conn) -> List[dict]:
        """
        Obtiene usuarios filtrados ESTRICTAMENTE por departamento 'Simulación'.
        """
        query = """
            SELECT id_usuario, nombre, department as departamento
            FROM tb_usuarios
            WHERE is_active = true 
            AND LOWER(department) = 'simulación'
            ORDER BY nombre
        """
        rows = await conn.fetch(query)
        return [dict(r) for r in rows]

    async def update_simulacion_padre(self, conn, id_oportunidad: UUID, datos: SimulacionUpdate, user_context: dict):
        """
        Actualiza la oportunidad aplicando reglas estrictas de cierre multisitio y orquestación de notificaciones.
        """
        notification_service = get_notification_service()

        status_map = await self._get_status_ids(conn)
        
        # 0. Obtener estado ACTUAL para comparación (Antes del update)
        current = await conn.fetchrow(
            "SELECT responsable_simulacion_id, id_estatus_global FROM tb_oportunidades WHERE id_oportunidad = $1",
            id_oportunidad
        )
        old_responsable = current['responsable_simulacion_id'] if current else None
        old_status = current['id_estatus_global'] if current else None

        # Validacion: Fecha Entrega Real solo permitida en estatus terminales
        if datos.fecha_entrega_simulacion:
            estatus_permitidos_fecha = [
                status_map["entregado"],
                status_map["cancelado"],
                status_map["perdido"]
            ]
            if datos.id_estatus_global not in estatus_permitidos_fecha:
                raise HTTPException(
                    status_code=400,
                    detail="Fecha Entrega Real solo puede asignarse en estatus: Entregado, Perdido o Cancelado"
                )
        
        # 0.5. Obtener conteo total de sitios para validación inteligente
        total_sitios = await conn.fetchval(
            "SELECT count(*) FROM tb_sitios_oportunidad WHERE id_oportunidad = $1", 
            id_oportunidad
        )

        # 1. Validación de Regla: Cierre (Entregado)
        if datos.id_estatus_global == status_map["entregado"]:
            # VALIDACIÓN INTELIGENTE:
            # - Si es Multisitio (>1): Exigimos cierre manual uno por uno (Strict Mode)
            # - Si es Sitio Único (1): Permitimos el paso para hacer Auto-Cierre (Cascada)
            
            if total_sitios > 1:
                # Verificar sitios pendientes
                query_check = """
                    SELECT count(*) FROM tb_sitios_oportunidad 
                    WHERE id_oportunidad = $1 
                    AND id_estatus_global NOT IN ($2, $3, $4)
                """
                sitios_pendientes = await conn.fetchval(
                    query_check, 
                    id_oportunidad, 
                    status_map["entregado"], 
                    status_map["cancelado"], 
                    status_map["perdido"]
                )
                
                if sitios_pendientes > 0:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Bloqueo de Calidad: Existen {sitios_pendientes} sitios activos. Debe finalizar todos los sitios antes de entregar."
                    )
            # ELSE: Si es == 1, pasamos directo a la cascada
            
            # Validación estricta de campos de cierre
            if datos.monto_cierre_usd is None or datos.potencia_cierre_fv_kwp is None:
                raise HTTPException(
                    status_code=400,
                    detail="Para marcar como Entregado, capture Monto Cierre (USD) y Potencia FV (KWp)."
                )

        # 2. Ejecutar Update del Padre
        query_padre = """
            UPDATE tb_oportunidades SET
                id_interno_simulacion = $1,
                responsable_simulacion_id = $2,
                fecha_entrega_simulacion = $3,
                deadline_negociado = $4,
                id_estatus_global = $5,
                id_motivo_cierre = $6,
                monto_cierre_usd = $7,
                potencia_cierre_fv_kwp = $8,
                capacidad_cierre_bess_kwh = $9
            WHERE id_oportunidad = $10
        """
        await conn.execute(query_padre,
            datos.id_interno_simulacion,
            datos.responsable_simulacion_id,
            datos.fecha_entrega_simulacion,
            datos.deadline_negociado,
            datos.id_estatus_global,
            datos.id_motivo_cierre,
            datos.monto_cierre_usd,
            datos.potencia_cierre_fv_kwp,
            datos.capacidad_cierre_bess_kwh,
            id_oportunidad
        )

        # 3. Regla de Cascada: Cancelación/Pérdida (Siempre) OR Entregado (Solo si es sitio único)
        should_cascade = False
        if datos.id_estatus_global in [status_map["cancelado"], status_map["perdido"]]:
            should_cascade = True
        elif datos.id_estatus_global == status_map["entregado"] and total_sitios == 1:
            should_cascade = True

        if should_cascade:
            fecha_cierre_cascada = datos.fecha_entrega_simulacion or await self.get_current_datetime_mx()
            # Actualiza todos los sitios abiertos (cascada)
            query_cascada = """
                UPDATE tb_sitios_oportunidad
                SET id_estatus_global = $1,
                fecha_cierre = $2
                WHERE id_oportunidad = $3
            """
            await conn.execute(query_cascada,
                datos.id_estatus_global, fecha_cierre_cascada, id_oportunidad
            )
            
        # 4. Notificaciones (Orquestación aquí)
        # Comparar `old_responsable` vs `datos.responsable_simulacion_id`
        # Comparar `old_status` vs `datos.id_estatus_global`
        try:
             # Notificar asignación si cambió
            if datos.responsable_simulacion_id and old_responsable != datos.responsable_simulacion_id:
                await notification_service.notify_assignment(
                    conn=conn,
                    id_oportunidad=id_oportunidad,
                    old_responsable_id=old_responsable,
                    new_responsable_id=datos.responsable_simulacion_id,
                    assigned_by_ctx=user_context
                )
            
            # Notificar cambio de estatus si cambió
            if datos.id_estatus_global and old_status != datos.id_estatus_global:
                await notification_service.notify_status_change(
                    conn=conn,
                    id_oportunidad=id_oportunidad,
                    old_status_id=old_status,
                    new_status_id=datos.id_estatus_global,
                    changed_by_ctx=user_context
                )
        except Exception as notif_error:
            logger.error(f"Error en notificaciones (no critico): {notif_error}")

    async def update_sitios_batch(self, conn, ids_sitios: List[UUID], nuevo_estatus: int, fecha_manual: Optional[datetime] = None):
        """Actualización masiva de sitios."""
        status_map = await self._get_status_ids(conn)
        fecha_actual = await self.get_current_datetime_mx()
        
        es_cierre = nuevo_estatus in [status_map["entregado"], status_map["cancelado"], status_map["perdido"]]
        
        # Manejar fecha_cierre correctamente considerando timezone
        if es_cierre:
            if fecha_manual:
                # Si fecha_manual viene como string, convertir a datetime con timezone
                if isinstance(fecha_manual, str):
                    from datetime import datetime
                    from zoneinfo import ZoneInfo
                    # Parse ISO string y agregar timezone si no lo tiene
                    parsed_date = datetime.fromisoformat(fecha_manual.replace('Z', '+00:00'))
                    if parsed_date.tzinfo is None:
                        # Si es naive, asumir que es hora de México
                        fecha_cierre_final = parsed_date.replace(tzinfo=ZoneInfo("America/Mexico_City"))
                    else:
                        fecha_cierre_final = parsed_date
                else:
                    # Si ya es datetime
                    if fecha_manual.tzinfo is None:
                        # Si es naive, agregar timezone de México
                        from zoneinfo import ZoneInfo
                        fecha_cierre_final = fecha_manual.replace(tzinfo=ZoneInfo("America/Mexico_City"))
                    else:
                        fecha_cierre_final = fecha_manual
            else:
                fecha_cierre_final = fecha_actual
        else:
            fecha_cierre_final = None
            
        query = """
            UPDATE tb_sitios_oportunidad
            SET id_estatus_global = $1,
                fecha_cierre = CASE WHEN $2::timestamptz IS NOT NULL THEN $2::timestamptz ELSE fecha_cierre END
            WHERE id_sitio = ANY($3::uuid[])
        """
        await conn.execute(query, nuevo_estatus, fecha_cierre_final, ids_sitios)

    # --- CONSULTAS (CORREGIDO: LISTA COMPLETA) ---

    async def get_oportunidades_list(self, conn, user_context: dict, tab: str = "activos", q: str = None, limit: int = 30, subtab: str = None) -> List[dict]:
        """
        Recupera lista filtrada de oportunidades para Simulación.
        """
        status_map = await self._get_status_ids(conn)
        
        # Query base: Incluye columnas NUEVAS (responsable_sim, fechas, estatus)
        # Mantiene email_enviado = true por seguridad
        query = """
            SELECT 
                o.id_oportunidad, o.op_id_estandar, o.nombre_proyecto, o.titulo_proyecto, o.cliente_nombre,
                o.fecha_solicitud, estatus.nombre as status_global, o.id_estatus_global,
                o.id_interno_simulacion, o.deadline_calculado, o.deadline_negociado,
                o.fecha_entrega_simulacion, o.cantidad_sitios, o.prioridad, o.es_fuera_horario,
                tipo_sol.nombre as tipo_solicitud,
                u_creador.nombre as solicitado_por,
                u_sim.nombre as responsable_simulacion,
                u_sim.email as responsable_email,
                CASE WHEN db.id IS NOT NULL THEN true ELSE false END as tiene_detalles_bess
            FROM tb_oportunidades o
            LEFT JOIN tb_cat_estatus_global estatus ON o.id_estatus_global = estatus.id
            LEFT JOIN tb_cat_tipos_solicitud tipo_sol ON o.id_tipo_solicitud = tipo_sol.id
            LEFT JOIN tb_usuarios u_creador ON o.creado_por_id = u_creador.id_usuario
            LEFT JOIN tb_usuarios u_sim ON o.responsable_simulacion_id = u_sim.id_usuario
            LEFT JOIN tb_detalles_bess db ON o.id_oportunidad = db.id_oportunidad
            WHERE o.email_enviado = true
        """
        
        params = []
        param_idx = 1

        # Filtro de Tabs (Usando IDs dinámicos del mapa)
        if tab == "historial":
            # Sub-tab filter logic
            if subtab == "entregado":
                 ids_historial = [status_map["entregado"]]
            elif subtab == "cancelado_perdido":
                 ids_historial = [status_map["cancelado"], status_map["perdido"]]
            else:
                 # Default full history (Entregado + Cancelado + Perdido + Ganada)
                 ids_historial = [status_map["entregado"], status_map["cancelado"], status_map["perdido"], status_map["ganada"]]
            
            placeholders = ','.join([f'${i}' for i in range(param_idx, param_idx + len(ids_historial))])
            query += f" AND o.id_estatus_global IN ({placeholders})"
            params.extend(ids_historial)
            param_idx += len(ids_historial)

        elif tab == "levantamientos":
             # 1. Filtro Tipo = Levantamiento
            id_levantamiento = await self._get_catalog_id_by_name(conn, "tb_cat_tipos_solicitud", "Levantamiento")
            query += f" AND o.id_tipo_solicitud = ${param_idx}"
            params.append(id_levantamiento)
            param_idx += 1
            
            # 2. Sub-filtro Estatus
            if subtab == 'realizados':
                # Realizados = Entregado
                id_entregado = status_map.get('entregado')
                query += f" AND o.id_estatus_global = ${param_idx}"
                params.append(id_entregado)
                param_idx += 1
            else:
                # Solicitados (Default) = NO Entregado
                id_entregado = status_map.get('entregado')
                query += f" AND o.id_estatus_global != ${param_idx}"
                params.append(id_entregado)
                param_idx += 1
                
        elif tab == "ganadas":
             # Específico Ganadas
             id_ganada = status_map.get('ganada')
             query += f" AND o.id_estatus_global = ${param_idx}"
             params.append(id_ganada)
             param_idx += 1
                
        else:  # ACTIVOS (Default)
            # Todo lo que NO es terminal
            ids_terminales = [
                status_map["entregado"], 
                status_map["cancelado"], 
                status_map["perdido"], 
                status_map["ganada"]
            ]
            placeholders = ','.join([f'${i}' for i in range(param_idx, param_idx + len(ids_terminales))])
            query += f" AND o.id_estatus_global NOT IN ({placeholders})"
            params.extend(ids_terminales)
            param_idx += len(ids_terminales)
            
            # Excluir Levantamientos de Activos (Mismo comportamiento que Comercial)
            try:
                id_levantamiento = await self._get_catalog_id_by_name(conn, "tb_cat_tipos_solicitud", "Levantamiento")
                query += f" AND o.id_tipo_solicitud != ${param_idx}"
                params.append(id_levantamiento)
                param_idx += 1
            except:
                pass # Si falla catalogo, no filtramos

        # Búsqueda
        if q:
            query += f" AND (o.op_id_estandar ILIKE ${param_idx} OR o.nombre_proyecto ILIKE ${param_idx} OR o.cliente_nombre ILIKE ${param_idx})"
            params.append(f"%{q}%")
            param_idx += 1

        query += " ORDER BY o.fecha_solicitud DESC"
        
        if limit > 0:
            query += f" LIMIT {limit}"
        
        rows = await conn.fetch(query, *params)
        return [dict(row) for row in rows]

    async def get_dashboard_stats(self, conn, user_context: dict) -> dict:
        """Calcula KPIs globales."""
        # Nota: Ajusta queries para usar email_enviado = true siempre
        where_base = "WHERE email_enviado = true"
        
        # Total Activas
        q_total = f"SELECT count(*) FROM tb_oportunidades {where_base}"
        total = await conn.fetchval(q_total)
        
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
                placeholders = ",".join([f"${i+1}" for i in range(len(ids_positivos))])
                query_ganadas = f"SELECT COUNT(*) FROM tb_oportunidades WHERE id_estatus_global IN ({placeholders}) AND email_enviado = true"
                row_ganadas = await conn.fetchval(query_ganadas, *ids_positivos)
                stats["kpis"]["ganadas"] = row_ganadas or 0
            
            # Perdidas = Perdido + Cancelado
            ids_negativos = [i for i in [id_perdido, id_cancelado] if i is not None]
            if ids_negativos:
                # Construir query dinámica para IN
                placeholders = ",".join([f"${i+1}" for i in range(len(ids_negativos))])
                query_perdidas = f"SELECT COUNT(*) FROM tb_oportunidades WHERE id_estatus_global IN ({placeholders}) AND email_enviado = true"
                row_perdidas = await conn.fetchval(query_perdidas, *ids_negativos)
                stats["kpis"]["perdidas"] = row_perdidas or 0

            # 5. KPIs: Levantamientos (Placeholder lógico: Total - (Ganadas + Perdidas))
            # O si hay un estatus específico de 'Levantamiento', usarlo.
            # Por ahora, asumiremos que son las 'En Proceso' (ni ganadas ni perdidas)
            stats["kpis"]["levantamientos"] = (
                stats["kpis"]["total"] - stats["kpis"]["ganadas"] - stats["kpis"]["perdidas"]
            )
            if stats["kpis"]["levantamientos"] < 0: stats["kpis"]["levantamientos"] = 0

            # 6. Chart: Mix por Tecnología
            rows_tech = await conn.fetch("""
                SELECT t.nombre, COUNT(o.id_oportunidad) as total 
                FROM tb_oportunidades o
                JOIN tb_cat_tecnologias t ON o.id_tecnologia = t.id
                WHERE o.email_enviado = true
                GROUP BY t.nombre
                ORDER BY total DESC
                LIMIT 5
            """)
            stats["charts"]["mix"]["labels"] = [r["nombre"] for r in rows_tech]
            stats["charts"]["mix"]["data"] = [r["total"] for r in rows_tech]

            # 7. Chart: Tendencia (Últimos 30 días) - Simplificado por fecha de creación
            rows_trend = await conn.fetch("""
                SELECT to_char(fecha_solicitud, 'YYYY-MM-DD') as fecha, COUNT(*) as total
                FROM tb_oportunidades
                WHERE fecha_solicitud >= NOW() - INTERVAL '30 days' AND email_enviado = true
                GROUP BY 1
                ORDER BY 1 ASC
            """)
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
            fecha_solicitud = await self.get_current_datetime_mx()
            
        # Calcular si es fuera de horario usando configuración global
        config = await self.get_configuracion_global(conn)
        hora_corte_str = config.get("HORA_CORTE_L_V", "18:00")
        h, m = map(int, hora_corte_str.split(":"))
        hora_corte = dt_time(h, m)
        
        es_fuera_horario = False
        # Fines de semana (5=Sab, 6=Dom) o después de hora corte
        if fecha_solicitud.weekday() >= 5 or fecha_solicitud.time() > hora_corte:
             es_fuera_horario = True

        # ---------------------------------------------------------
        # 2. GESTIÓN INTELIGENTE DE CLIENTES (Homologado)
        # ---------------------------------------------------------
        final_cliente_id = datos.cliente_id
        final_cliente_nombre = datos.cliente_nombre.strip().upper()

        if final_cliente_id:
            # Caso 1: ID explícito. Asumimos válido.
            pass
        else:
            # Caso 2: Nombre manual -> Buscar o Crear
            existing_client = await conn.fetchrow(
                "SELECT id FROM tb_clientes WHERE nombre_fiscal = $1", 
                final_cliente_nombre
            )
            
            if existing_client:
                final_cliente_id = existing_client['id']
            else:
                final_cliente_id = uuid4()
                await conn.execute(
                    "INSERT INTO tb_clientes (id, nombre_fiscal) VALUES ($1, $2)",
                    final_cliente_id, final_cliente_nombre
                )
                logger.info(f"Nuevo cliente (Simulación) registrado: {final_cliente_nombre}")

        # 3. Generar Identificadores
        new_id = uuid4()
        timestamp_id = fecha_solicitud.strftime("%y%m%d%H%M")
        op_id_estandar = f"OP-{timestamp_id}"  # Formato OP-YYMMDDHHMM
        
        # ID Interno: USAR final_cliente_nombre
        base_interno = f"{op_id_estandar}_{datos.nombre_proyecto}_{final_cliente_nombre}"
        id_interno = base_interno.upper().replace(" ", "_")[:150]

        # 3. Título del Proyecto (Generación standard)
        # Necesitamos nombres de catalogos
        nombre_tec = await conn.fetchval("SELECT nombre FROM tb_cat_tecnologias WHERE id = $1", datos.id_tecnologia)
        nombre_tipo = await conn.fetchval("SELECT nombre FROM tb_cat_tipos_solicitud WHERE id = $1", datos.id_tipo_solicitud)
        
        titulo_proyecto = f"{nombre_tipo}_{final_cliente_nombre}_{datos.nombre_proyecto}_{nombre_tec}_{datos.canal_venta}".upper()

        # 4. Insertar con Transacción Atómica
        async with conn.transaction():
            query_padre = """
                INSERT INTO tb_oportunidades (
                    id_oportunidad, op_id_estandar, id_interno_simulacion,
                    titulo_proyecto, nombre_proyecto, cliente_nombre,
                    canal_venta, id_tecnologia, id_tipo_solicitud,
                    id_estatus_global, cantidad_sitios, prioridad,
                    direccion_obra, google_maps_link, coordenadas_gps, sharepoint_folder_url,
                    fecha_solicitud, creado_por_id, solicitado_por,
                    es_fuera_horario, es_carga_manual,
                    clasificacion_solicitud
                ) VALUES (
                    $1, $2, $3,
                    $4, $5, $6,
                    $7, $8, $9,
                    $10, $11, $12,
                    $13, $14, $15, $16,
                    $17, $18, $19,
                    $20, $21,
                    $22
                )
            """
            
            await conn.execute(query_padre,
                new_id, op_id_estandar, id_interno,
                titulo_proyecto, datos.nombre_proyecto, final_cliente_nombre,
                datos.canal_venta, datos.id_tecnologia, datos.id_tipo_solicitud,
                datos.id_estatus_global, datos.cantidad_sitios, datos.prioridad,
                datos.direccion_obra, datos.google_maps_link, datos.coordenadas_gps, datos.sharepoint_folder_url,
                fecha_solicitud, user_context['user_db_id'], user_context.get('user_name'),
                es_fuera_horario, True if datos.fecha_manual_str else False,
                datos.clasificacion_solicitud
            )

            # 5. Insertar BESS si existe
            if datos.detalles_bess:
                query_bess = """
                    INSERT INTO tb_detalles_bess (
                        id_oportunidad, uso_sistema_json, cargas_criticas_kw, tiene_motores, potencia_motor_hp,
                        tiempo_autonomia, voltaje_operacion, cargas_separadas, 
                        tiene_planta_emergencia
                    ) VALUES ($1, $2::jsonb, $3, $4, $5, $6, $7, $8, $9)
                """
                
                uso_sistema_str = json.dumps(datos.detalles_bess.uso_sistema_json)
                
                await conn.execute(query_bess,
                    new_id,
                    uso_sistema_str,
                    datos.detalles_bess.cargas_criticas_kw,
                    datos.detalles_bess.tiene_motores,
                    datos.detalles_bess.potencia_motor_hp,
                    datos.detalles_bess.tiempo_autonomia,
                    datos.detalles_bess.voltaje_operacion,
                    datos.detalles_bess.cargas_separadas,
                    datos.detalles_bess.tiene_planta_emergencia
                )
            
        # 6. Notificar creación (Opcional, si se requiere en futuro)
        # Por ahora solo retornamos
        
        logger.info(f"Oportunidad Transaccional Creada: {op_id_estandar}")
        return (new_id, op_id_estandar, es_fuera_horario)

    async def get_sitios(self, conn, id_oportunidad: UUID) -> List[dict]:
        rows = await conn.fetch("""
            SELECT s.id_sitio, s.nombre_sitio, s.direccion, s.id_estatus_global,
                   e.nombre as nombre_estatus, s.fecha_cierre
            FROM tb_sitios_oportunidad s
            LEFT JOIN tb_cat_estatus_global e ON s.id_estatus_global = e.id
            WHERE s.id_oportunidad = $1 ORDER BY s.nombre_sitio
        """, id_oportunidad)
        return [dict(r) for r in rows]
    
    async def get_detalles_bess(self, conn, id_oportunidad: UUID):
        row = await conn.fetchrow("SELECT * FROM tb_detalles_bess WHERE id_oportunidad = $1", id_oportunidad)
        return dict(row) if row else None
        


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
        rows = await conn.fetch("""
            SELECT 
                comentario,
                usuario_nombre,
                modulo_origen,
                fecha_comentario AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City' as fecha_comentario
            FROM tb_comentarios_workflow
            WHERE id_oportunidad = $1
            ORDER BY fecha_comentario DESC
        """, id_oportunidad)
        return [dict(r) for r in rows]
    
    async def get_catalogos_ui(self, conn) -> dict:
        tecnologias = await conn.fetch("SELECT id, nombre FROM tb_cat_tecnologias WHERE activo = true ORDER BY nombre")
        
        # Filtrar tipos igual que en Comercial (Pre-Oferta, Simulacion, etc.)
        codigos = ['PRE_OFERTA', 'SIMULACION', 'CAPTURA_RECIBOS']
        placeholders = ",".join([f"${i+1}" for i in range(len(codigos))])
        
        tipos = await conn.fetch(f"""
            SELECT id, nombre 
            FROM tb_cat_tipos_solicitud 
            WHERE activo = true 
            AND codigo_interno IN ({placeholders})
            ORDER BY nombre
        """, *codigos)
        
        # Usuarios para delegación (Fix para dropdown vacío)
        usuarios = await conn.fetch("SELECT id_usuario, nombre FROM tb_usuarios WHERE is_active = true ORDER BY nombre")
        
        return {
            "tecnologias": [dict(t) for t in tecnologias],
            "tipos_solicitud": [dict(t) for t in tipos],
            "usuarios": [dict(u) for u in usuarios]
        }
    
    async def auto_crear_sitio_unico(self, conn, id_oportunidad, nombre_proyecto, direccion, google_maps, id_tipo):
        """
        Crea automáticamente el Sitio 01 para opportunidades de 1 solo sitio.
        Espejo de la lógica comercial para mantener consistencia.
        """
        await conn.execute("""
            INSERT INTO tb_sitios_oportunidad (
                id_sitio, id_oportunidad, nombre_sitio, 
                direccion_completa, enlace_google_maps, 
                id_tipo_solicitud, id_estatus_sitio
            ) VALUES (
                $1, $2, $3, $4, $5, $6, 1
            )
        """, uuid4(), id_oportunidad, nombre_proyecto, direccion, google_maps, id_tipo)

    @staticmethod
    def get_canal_from_user_name(user_name: str) -> str:
        parts = (user_name or "").strip().split()
        return f"{parts[0]}_{parts[1]}".upper() if len(parts) >= 2 else (parts[0].upper() if parts else "")

def get_simulacion_service():
    return SimulacionService()
