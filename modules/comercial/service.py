from datetime import datetime, timedelta, time as dt_time
from uuid import UUID, uuid4
from typing import List, Optional
import json
import logging
import asyncpg
from fastapi import HTTPException
from zoneinfo import ZoneInfo
import pandas as pd
import io

logger = logging.getLogger("ComercialModule")

class ComercialService:
    """Encapsula la lógica de negocio del módulo Comercial."""
    
    async def get_zona_horaria_default(self, conn) -> ZoneInfo:
        """
        Lee la configuración ZONA_HORARIA_DEFAULT de la base de datos.
        Si falla o no existe, usa CDMX como respaldo.
        """
        try:
            # Reutilizamos el método existente que carga toda la config
            config = await self.get_configuracion_global(conn)
            tz_str = config.get("ZONA_HORARIA_DEFAULT", "America/Mexico_City")
            return ZoneInfo(tz_str)
        except Exception:
            # Fallback de seguridad extrema por si la BD falla
            return ZoneInfo("America/Mexico_City")
    
    async def get_current_datetime_mx(self, conn) -> datetime:
        """
        Obtiene la hora actual EXACTA respetando la configuración de zona horaria en BD.
        
        Esta función es la fuente de verdad para todos los timestamps del módulo comercial.
        Lee ZONA_HORARIA_DEFAULT de tb_configuracion_global (fallback: America/Mexico_City).
        Retorna un datetime con timezone-aware (ZoneInfo).
        
        PostgreSQL acepta este objeto directamente y lo maneja correctamente.
        """
        zona_horaria = await self.get_zona_horaria_default(conn)
        return datetime.now(zona_horaria)
    
    @staticmethod
    def get_canal_from_user_name(user_name: str) -> str:
        """
        Genera el canal de venta basado en el nombre del usuario.
        
        Regla de negocio:
        - Si nombre tiene 2+ palabras: PRIMERA_SEGUNDA
        - Si tiene 1 palabra: PALABRA
        - Si vacío o None: retorna cadena vacía
        """
        parts = (user_name or "").strip().split()
        if len(parts) >= 2:
            return f"{parts[0]}_{parts[1]}".upper()
        elif len(parts) == 1:
            return parts[0].upper()
        else:
            return ""

    async def get_configuracion_global(self, conn):
        """Obtiene la configuración de horarios desde la BD."""
        rows = await conn.fetch("SELECT clave, valor, tipo_dato FROM tb_configuracion_global")
        config = {r['clave']: r['valor'] for r in rows}
        return config

    async def get_catalog_ids(self, conn) -> dict:
        """
        Carga IDs de catálogos para filtros rápidos basados en IDs (INTEGER).
        OPTIMIZACIÓN: Usa caché de 5 minutos para evitar queries redundantes.
        
        Retorna estructura:
        {
            'estatus': {'entregado': 1, 'cancelado': 2, ...},
            'tipos': {'pre_oferta': 1, 'licitacion': 2, 'cotizacion': 3, ...}
        }
        """
        import time
        
        # Variables de caché a nivel de clase (compartidas entre instancias)
        if not hasattr(self.__class__, '_catalog_cache'):
            self.__class__._catalog_cache = None
            self.__class__._cache_timestamp = None
            self.__class__._CACHE_TTL_SECONDS = 300  # 5 minutos
        
        now = time.time()
        
        # Si hay caché válido, retornarlo
        if (self.__class__._catalog_cache is not None and 
            self.__class__._cache_timestamp is not None and 
            (now - self.__class__._cache_timestamp) < self.__class__._CACHE_TTL_SECONDS):
            logger.debug("CACHE - Usando caché de catálogos")
            return self.__class__._catalog_cache
        
        # Si no, cargar de BD y cachear
        logger.debug("CACHE - Recargando catálogos desde BD")
        estatus = await conn.fetch("SELECT id, LOWER(nombre) as nombre FROM tb_cat_estatus_global WHERE activo = true")
        tipos = await conn.fetch("SELECT id, LOWER(codigo_interno) as codigo FROM tb_cat_tipos_solicitud WHERE activo = true")
        
        result = {
            "estatus": {row['nombre']: row['id'] for row in estatus},
            "tipos": {row['codigo']: row['id'] for row in tipos}
        }
        
        # Actualizar caché
        self.__class__._catalog_cache = result
        self.__class__._cache_timestamp = now
        
        return result

    async def calcular_fuera_de_horario(self, conn, fecha_creacion: datetime) -> bool:
        """
        Valida si la fecha dada cae fuera del horario laboral configurado.
        Traducción de fórmula PowerApps a Python.
        """
        config = await self.get_configuracion_global(conn)
        
        # Obtener parámetros con defaults de seguridad
        hora_corte_str = config.get("HORA_CORTE_L_V", "17:30")
        dias_fin_semana_str = config.get("DIAS_FIN_SEMANA", "[5, 6]")
        
        # Convertir a objetos Python
        h, m = map(int, hora_corte_str.split(":"))
        hora_corte = dt_time(h, m)
        dias_fin_semana = json.loads(dias_fin_semana_str)

        # Análisis de la fecha
        dia_semana = fecha_creacion.weekday()
        hora_actual = fecha_creacion.time()

        # Lógica: Fin de semana o después de hora de corte
        if dia_semana in dias_fin_semana:
            return True
        if hora_actual > hora_corte:
            return True
        return False

    async def calcular_deadline_inicial(self, conn, fecha_creacion: datetime) -> datetime:
        """
        Calcula el deadline inicial (Meta).
        
        Lógica de Negocio:
        1. Configuración dinámica (SLA desde BD).
        2. Ajuste de fecha de arranque:
           - Sábado/Domingo: Pasan al Lunes (Hora irrelevante).
           - Viernes > 17:30: Pasa al Lunes.
           - Lunes-Jueves > 17:30: Pasa al día siguiente.
           - Lunes-Viernes <= 17:30: Arranca el mismo día.
        3. Cálculo: Fecha Arranque + Días SLA.
        4. Vencimiento: Se fija a las 17:30 del día destino.
        """
        
        # 1. Obtener toda la configuración de golpe
        config = await self.get_configuracion_global(conn)
        
        # A. Obtener Hora de Corte
        hora_corte_str = config.get("HORA_CORTE_L_V", "17:30")
        h, m = map(int, hora_corte_str.split(":"))
        hora_corte = dt_time(h, m)

        # B. Obtener Días SLA (Dinámico)
        # Intentamos leer de BD, si falla o no existe, usamos 7 por defecto.
        try:
            dias_sla_str = config.get("DIAS_SLA_DEFAULT", "7")
            DIAS_SLA = int(dias_sla_str)
        except ValueError:
            DIAS_SLA = 7

        # 2. Datos de la Fecha Actual
        # 0=Lun, 1=Mar, 2=Mie, 3=Jue, 4=Vie, 5=Sab, 6=Dom
        dia_semana = fecha_creacion.weekday() 
        hora_actual = fecha_creacion.time()
        
        # Reseteamos a 00:00:00 para sumar días completos limpiamente
        fecha_base = fecha_creacion.replace(hour=0, minute=0, second=0, microsecond=0)
        
        dias_ajuste_inicio = 0

        # --- LÓGICA DE REGLAS DE NEGOCIO ---
        
        # CASO 1: Fin de Semana (Sábado o Domingo)
        # La hora NO importa, siempre se recorre al Lunes.
        if dia_semana == 5:   # Sábado -> Lunes (+2)
            dias_ajuste_inicio = 2
        elif dia_semana == 6: # Domingo -> Lunes (+1)
            dias_ajuste_inicio = 1
            
        # CASO 2: Entre Semana (Lunes a Viernes)
        else:
            if hora_actual > hora_corte:
                # Se envió tarde (Fuera de horario laboral)
                if dia_semana == 4: # Viernes tarde -> Lunes (+3)
                    dias_ajuste_inicio = 3
                else:               # Lun-Jue tarde -> Día siguiente (+1)
                    dias_ajuste_inicio = 1
            else:
                # Se envió a tiempo -> Cuenta desde hoy (+0)
                dias_ajuste_inicio = 0

        # 3. Cálculo Final
        # Fecha Inicio Real = Fecha Creación + Ajuste
        adjusted_start_date = fecha_base + timedelta(days=dias_ajuste_inicio)
        
        # Deadline = Fecha Inicio Real + SLA
        deadline_final = adjusted_start_date + timedelta(days=DIAS_SLA)
        
        # 4. Estética: Fijar hora de vencimiento al cierre de jornada
        deadline_final = deadline_final.replace(hour=17, minute=30)
        
        return deadline_final

    def calcular_kpis_entrega(self, fecha_entrega: datetime, deadline_original: datetime, deadline_negociado: datetime = None):
        """Calcula si la entrega fue 'A tiempo' o 'Tarde'."""
        if not fecha_entrega or not deadline_original:
            return "Pendiente"

        fecha_compromiso = deadline_negociado if deadline_negociado else deadline_original

        if fecha_entrega <= fecha_compromiso:
            return "Entrega a tiempo"
        else:
            return "Entrega tarde"

    async def get_catalogos_ui(self, conn) -> dict:
        """Recupera los catálogos para llenar los <select> del formulario."""
        tecnologias = await conn.fetch("SELECT id, nombre FROM tb_cat_tecnologias WHERE activo = true ORDER BY nombre")
        tipos = await conn.fetch("SELECT id, nombre FROM tb_cat_tipos_solicitud WHERE activo = true ORDER BY nombre")
        
        return {
            "tecnologias": [dict(t) for t in tecnologias],
            "tipos_solicitud": [dict(t) for t in tipos]
        }

    async def get_catalogos_creacion(self, conn) -> dict:
        """
        Carga catálogos filtrados específicamente para el Formulario de Creación (Paso 1).
        Solo muestra 'Pre Oferta' y 'Licitación'.
        """
        # 1. Tecnologías (Todas)
        tecnologias = await conn.fetch("SELECT id, nombre FROM tb_cat_tecnologias WHERE activo = true ORDER BY nombre")
        
        # 2. Tipos de Solicitud (FILTRADO: Solo Pre Oferta y Licitación)
        # Usamos los codigos_internos definidos en el script SQL inicial
        tipos = await conn.fetch("""
            SELECT id, nombre 
            FROM tb_cat_tipos_solicitud 
            WHERE activo = true 
            AND codigo_interno IN ('PRE_OFERTA', 'LICITACION')
            ORDER BY nombre
        """)
        
        return {
            "tecnologias": [dict(t) for t in tecnologias],
            "tipos_solicitud": [dict(t) for t in tipos]
        }

    async def procesar_fecha_manual(self, conn, fecha_input_str: Optional[str]) -> datetime:
        """
        Regla de Negocio: Solicitudes Extraordinarias (Gerentes).
        Input: "2025-10-20T10:00" (String ISO del navegador, usualmente naive).
        Output: Datetime con timezone America/Mexico_City.
        """
        zona_mx = await self.get_zona_horaria_default(conn)
        
        if not fecha_input_str:
            return datetime.now(zona_mx)
            
        try:
            # 1. Parsear string ISO
            dt = datetime.fromisoformat(fecha_input_str)
            
            # 2. Asignar Zona Horaria
            # El input datetime-local NO envía zona horaria, asumimos que el gerente
            # está capturando la hora de CDMX.
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=zona_mx)
            else:
                # Si viniera con zona, convertimos a CDMX
                dt = dt.astimezone(zona_mx)
                
            return dt
        except ValueError:
            logger.error(f"Fecha manual inválida: {fecha_input_str}, usando NOW()")
            return datetime.now(zona_mx)

    async def _insertar_bess(self, conn, id_oportunidad: UUID, bess_data):
        """
        Helper privado: Inserta detalles BESS.
        Recibe DetalleBessCreate (Pydantic v2).
        """
        query = """
            INSERT INTO tb_detalles_bess (
                id_oportunidad, cargas_criticas_kw, tiene_motores, potencia_motor_hp,
                tiempo_autonomia, voltaje_operacion, cargas_separadas, 
                objetivos_json, tiene_planta_emergencia
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """
        # Pydantic v2: model_dump() y json.dumps para el array
        objetivos_str = json.dumps(bess_data.objetivos_json)
        
        await conn.execute(query,
            id_oportunidad,
            bess_data.cargas_criticas_kw,
            bess_data.tiene_motores,
            bess_data.potencia_motor_hp,
            bess_data.tiempo_autonomia,
            bess_data.voltaje_operacion,
            bess_data.cargas_separadas,
            objetivos_str,
            bess_data.tiene_planta_emergencia
        )

    async def crear_oportunidad_transaccional(self, conn, datos, user_context: dict) -> tuple:
        """
        Orquestador Transaccional (Fase 2).
        Maneja: Fechas, Identificadores, Oportunidad Base y BESS.
        
        Args:
            conn: Conexión asyncpg
            datos: OportunidadCreateCompleta (Pydantic v2)
            user_context: dict con user_db_id, user_name, role
            
        Returns:
            tuple: (new_id, op_id_estandar, es_fuera_horario)
        """
        logger.info(f"Iniciando creación de oportunidad para cliente {datos.cliente_nombre}")
        
        # 1. Procesar Fecha
        fecha_solicitud = await self.procesar_fecha_manual(conn, datos.fecha_manual_str)
        es_fuera_horario = await self.calcular_fuera_de_horario(conn, fecha_solicitud)
        deadline = await self.calcular_deadline_inicial(conn, fecha_solicitud)

        # 2. Generar Identificadores
        new_id = uuid4()
        now_mx = await self.get_current_datetime_mx(conn)
        op_id_estandar = now_mx.strftime("OP - %y%m%d%H%M")
        
        # Obtener nombres de catálogos (Queries directos optimizados)
        nombre_tec = await conn.fetchval("SELECT nombre FROM tb_cat_tecnologias WHERE id = $1", datos.id_tecnologia)
        nombre_tipo = await conn.fetchval("SELECT nombre FROM tb_cat_tipos_solicitud WHERE id = $1", datos.id_tipo_solicitud)
        
        # Generar Títulos Legacy
        titulo = f"{nombre_tipo}_{datos.cliente_nombre}_{datos.nombre_proyecto}_{nombre_tec}_{datos.canal_venta}".upper()
        id_interno = f"{op_id_estandar}_{datos.nombre_proyecto}_{datos.cliente_nombre}"[:150]

        # 3. Insertar Oportunidad
        query_op = """
            INSERT INTO tb_oportunidades (
                id_oportunidad, op_id_estandar, id_interno_simulacion,
                titulo_proyecto, nombre_proyecto, cliente_nombre, canal_venta,
                id_tecnologia, id_tipo_solicitud, id_estatus_global,
                cantidad_sitios, prioridad, 
                direccion_obra, coordenadas_gps, google_maps_link, sharepoint_folder_url,
                creado_por_id, fecha_solicitud,
                es_fuera_horario, deadline_calculado,
                solicitado_por, es_carga_manual
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7,
                $8, $9, 1, 
                $10, $11, $12, $13, $14, $15, 
                $16, $17, 
                $18, $19,
                $20, $21
            )
        """
        es_manual = bool(datos.fecha_manual_str)  # Flag de auditoría

        await conn.execute(query_op, 
            new_id, op_id_estandar, id_interno,
            titulo, datos.nombre_proyecto, datos.cliente_nombre, datos.canal_venta,
            datos.id_tecnologia, datos.id_tipo_solicitud,
            datos.cantidad_sitios, datos.prioridad,
            datos.direccion_obra, datos.coordenadas_gps, datos.google_maps_link, datos.sharepoint_folder_url,
            user_context['user_db_id'], fecha_solicitud,
            es_fuera_horario, deadline,
            user_context.get('user_name', 'Usuario'), es_manual
        )

        # 4. Insertar BESS (Si aplica y hay datos)
        if datos.detalles_bess:
            # Validación de negocio adicional: ¿Es tecnología BESS?
            # Se puede relajar si permitimos híbridos, por ahora confiamos en que si mandan datos BESS, se guarden.
            await self._insertar_bess(conn, new_id, datos.detalles_bess)
        
        logger.info(f"Oportunidad {op_id_estandar} creada exitosamente por usuario {user_context.get('user_db_id')}")
        return new_id, op_id_estandar, es_fuera_horario


    async def get_or_create_cliente(self, conn, nombre_cliente: str) -> UUID:
        """Obtiene o crea un cliente usando upsert atómico."""
        nombre_clean = nombre_cliente.strip().upper()
        
        # Upsert atómico (requiere UNIQUE CONSTRAINT en nombre_fiscal)
        query_insert = """
            INSERT INTO tb_clientes (id, nombre_fiscal) 
            VALUES ($1, $2) 
            ON CONFLICT (nombre_fiscal) DO NOTHING
        """
        new_id = uuid4()
        await conn.execute(query_insert, new_id, nombre_clean)
        
        # Recuperar ID (nuevo o existente)
        row = await conn.fetchrow("SELECT id FROM tb_clientes WHERE nombre_fiscal = $1", nombre_clean)
        return row['id']

    async def get_oportunidades_list(self, conn, user_context: dict, tab: str = "activos", q: str = None, limit: int = 15, subtab: str = None) -> List[dict]:
        """Recupera lista filtrada de oportunidades con permisos y paginación."""
        user_id = user_context.get("user_db_id")  # CORREGIDO: era "user_id"
        role = user_context.get("role", "USER")
        
        logger.debug(f"Consultando oportunidades - Tab: {tab}, Filtro: {q}, Usuario: {user_id}")

        # OPTIMIZACIÓN: Cargar IDs de catálogos una sola vez
        cats = await self.get_catalog_ids(conn)

        query = """
            SELECT 
                o.id_oportunidad, o.op_id_estandar, o.nombre_proyecto, o.cliente_nombre, o.canal_venta,
                o.fecha_solicitud, estatus.nombre as status_global, o.email_enviado, o.id_interno_simulacion,
                tipo_sol.nombre as tipo_solicitud, o.deadline_calculado, o.deadline_negociado, o.cantidad_sitios,
                o.titulo_proyecto, o.prioridad, o.es_fuera_horario,
                u_creador.nombre as solicitado_por,
                CASE WHEN db.id IS NOT NULL THEN true ELSE false END as tiene_detalles_bess
            FROM tb_oportunidades o
            LEFT JOIN tb_cat_estatus_global estatus ON o.id_estatus_global = estatus.id
            LEFT JOIN tb_cat_tipos_solicitud tipo_sol ON o.id_tipo_solicitud = tipo_sol.id
            LEFT JOIN tb_usuarios u_creador ON o.creado_por_id = u_creador.id_usuario
            LEFT JOIN tb_detalles_bess db ON o.id_oportunidad = db.id_oportunidad
            WHERE o.email_enviado = true
        """
        
        params = []
        param_idx = 1

        # Filtro por tab (OPTIMIZADO: usa IDs en lugar de LOWER(nombre))
        if tab == "historial":
            # Buscar IDs de los estados del historial
            ids_historial = [
                cats['estatus'].get('entregado'),
                cats['estatus'].get('cancelado'),
                cats['estatus'].get('perdida')
            ]
            ids_historial = [i for i in ids_historial if i is not None]
            if ids_historial:
                placeholders = ','.join([f'${i}' for i in range(param_idx, param_idx + len(ids_historial))])
                query += f" AND o.id_estatus_global IN ({placeholders})"
                params.extend(ids_historial)
                param_idx += len(ids_historial)
                
        elif tab == "levantamientos":
            # Buscar ID del tipo "levantamiento"
            id_levantamiento = cats['tipos'].get('levantamiento')
            if id_levantamiento:
                query += f" AND o.id_tipo_solicitud = ${param_idx}"
                params.append(id_levantamiento)
                param_idx += 1
                
            # Sub-filtro por subtab
            if subtab == 'realizados':
                id_realizado = cats['estatus'].get('realizado')
                if id_realizado:
                    query += f" AND o.id_estatus_global = ${param_idx}"
                    params.append(id_realizado)
                    param_idx += 1
            else:
                id_realizado = cats['estatus'].get('realizado')
                if id_realizado:
                    query += f" AND o.id_estatus_global != ${param_idx}"
                    params.append(id_realizado)
                    param_idx += 1
                    
        elif tab == "ganadas":
            id_ganada = cats['estatus'].get('ganada')
            if id_ganada:
                query += f" AND o.id_estatus_global = ${param_idx}"
                params.append(id_ganada)
                param_idx += 1
                
        else:  # activos
            # Estados NO activos
            ids_no_activos = [
                cats['estatus'].get('entregado'),
                cats['estatus'].get('cancelado'),
                cats['estatus'].get('perdida'),
                cats['estatus'].get('cerrada')
            ]
            ids_no_activos = [i for i in ids_no_activos if i is not None]
            if ids_no_activos:
                placeholders = ','.join([f'${i}' for i in range(param_idx, param_idx + len(ids_no_activos))])
                query += f" AND o.id_estatus_global NOT IN ({placeholders})"
                params.extend(ids_no_activos)
                param_idx += len(ids_no_activos)
                
            # Excluir levantamientos de activos
            id_levantamiento = cats['tipos'].get('levantamiento')
            if id_levantamiento:
                query += f" AND o.id_tipo_solicitud != ${param_idx}"
                params.append(id_levantamiento)
                param_idx += 1

        # Búsqueda
        if q:
            query += f" AND (o.titulo_proyecto ILIKE ${param_idx} OR o.nombre_proyecto ILIKE ${param_idx} OR o.cliente_nombre ILIKE ${param_idx})"
            params.append(f"%{q}%")
            param_idx += 1

        # Filtro de seguridad (solo ADMIN, MANAGER, DIRECTOR ven todo)
        roles_sin_restriccion = ['MANAGER', 'ADMIN', 'DIRECTOR']
        if role not in roles_sin_restriccion:
            query += f" AND o.creado_por_id = ${param_idx}"
            params.append(user_id)
            param_idx += 1

        query += " ORDER BY o.fecha_solicitud DESC"
        
        if limit > 0:
            query += f" LIMIT {limit}"
        
        rows = await conn.fetch(query, *params)
        
        logger.debug(f"Retornando {len(rows)} oportunidades")
        return [dict(row) for row in rows]


    async def update_email_status(self, conn, id_oportunidad: UUID):
        """Marca una oportunidad como enviada por email."""
        logger.info(f"Marcando oportunidad {id_oportunidad} como enviada por email")
        await conn.execute("UPDATE tb_oportunidades SET email_enviado = TRUE WHERE id_oportunidad = $1", id_oportunidad)

    async def create_followup_oportunidad(self, parent_id: UUID, nuevo_tipo_solicitud: str, prioridad: str, conn, user_id: UUID, user_name: str) -> UUID:
        """Crea seguimiento clonando padre + sitios."""
        parent = await conn.fetchrow("SELECT * FROM tb_oportunidades WHERE id_oportunidad = $1", parent_id)
        if not parent: 
            raise HTTPException(status_code=404, detail="Oportunidad original no encontrada")

        # CORRECCIÓN CRÍTICA: Convertir string de tipo_solicitud a ID
        # El parámetro nuevo_tipo_solicitud viene como "COTIZACION", "ACTUALIZACION", etc.
        id_tipo_solicitud = await conn.fetchval(
            "SELECT id FROM tb_cat_tipos_solicitud WHERE UPPER(codigo_interno) = UPPER($1)",
            nuevo_tipo_solicitud
        )
        
        if not id_tipo_solicitud:
            raise HTTPException(status_code=400, detail=f"Tipo de solicitud '{nuevo_tipo_solicitud}' no encontrado en catálogo")

        new_uuid = uuid4()
        timestamp_id = (await self.get_current_datetime_mx(conn)).strftime('%y%m%d%H%M')
        op_id_estandar_new = f"OP - {timestamp_id}"
        deadline = await self.calcular_deadline_inicial(conn, await self.get_current_datetime_mx(conn))
        
        # Obtener datos completos para construir título igual que en creación inicial
        nombre_tipo = await conn.fetchval("SELECT nombre FROM tb_cat_tipos_solicitud WHERE id = $1", id_tipo_solicitud)
        nombre_tec = await conn.fetchval("SELECT nombre FROM tb_cat_tecnologias WHERE id = $1", parent['id_tecnologia'])
        
        # Título completo con el MISMO formato que la creación inicial (línea 344)
        titulo_new = f"{nombre_tipo}_{parent['cliente_nombre']}_{parent['nombre_proyecto']}_{nombre_tec}_{parent['canal_venta']}".upper()

        # CORRECCIÓN: Usar id_tipo_solicitud (INTEGER) en lugar de tipo_solicitud (TEXT)
        query_insert = """
            INSERT INTO tb_oportunidades (
                id_oportunidad, creado_por_id, parent_id,
                titulo_proyecto, nombre_proyecto, cliente_nombre, cliente_id,
                canal_venta, solicitado_por,
                id_tipo_solicitud, cantidad_sitios, prioridad,
                direccion_obra, coordenadas_gps, google_maps_link, sharepoint_folder_url,
                id_interno_simulacion, op_id_estandar,
                id_estatus_global, deadline_calculado, fecha_solicitud, email_enviado
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, 1, $19, NOW(), FALSE
            ) RETURNING id_oportunidad
        """
        await conn.fetchval(query_insert,
            new_uuid, user_id, parent_id,
            titulo_new, parent['nombre_proyecto'], parent['cliente_nombre'], parent['cliente_id'],
            parent['canal_venta'], user_name,
            id_tipo_solicitud, parent['cantidad_sitios'], prioridad,  # <-- CAMBIO AQUÍ: usa ID en vez de string
            parent['direccion_obra'], parent['coordenadas_gps'], parent['google_maps_link'], parent['sharepoint_folder_url'],
            parent['id_interno_simulacion'], op_id_estandar_new, deadline
        )

        # Clonar sitios
        query_clone = """
            INSERT INTO tb_sitios_oportunidad (id_sitio, id_oportunidad, nombre_sitio, direccion, tipo_tarifa, google_maps_link, numero_servicio, comentarios)
            SELECT gen_random_uuid(), $1, nombre_sitio, direccion, tipo_tarifa, google_maps_link, numero_servicio, comentarios
            FROM tb_sitios_oportunidad WHERE id_oportunidad = $2
        """
        await conn.execute(query_clone, new_uuid, parent_id)
        
        return new_uuid


    async def generate_multisite_excel(self, conn, id_oportunidad: UUID, id_interno: str) -> Optional[dict]:
        """Genera el archivo Excel para oportunidades multisitio."""
        try:
            sites_rows = await conn.fetch(
                "SELECT nombre_sitio, numero_servicio, direccion, tipo_tarifa, google_maps_link, comentarios FROM tb_sitios_oportunidad WHERE id_oportunidad = $1", 
                id_oportunidad
            )
            if sites_rows:
                df_sites = pd.DataFrame([dict(r) for r in sites_rows])
                # Mapeo de columnas para usuario
                df_sites.columns = ["NOMBRE", "# DE SERVICIO", "DIRECCION", "TARIFA", "LINK GOOGLE", "COMENTARIOS"]
                
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                    df_sites.to_excel(writer, index=False, sheet_name='Sitios')
                
                return {
                    "name": f"Listado_Multisitios_{id_interno}.xlsx",
                    "content_bytes": buf.getvalue(),
                    "contentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                }
        except Exception as e:
            logger.error(f"Error generando excel adjunto: {e}")
            return None

    async def get_dashboard_stats(self, conn, user_context: dict) -> dict:
        """
        Calcula KPIs y datos para gráficos del Dashboard Comercial.
        """
        user_id = user_context.get("user_db_id")  # CORREGIDO: era "user_id"
        role = user_context.get("role", "USER")
        
        # 1. Filtros de Seguridad
        params = []
        conditions = ["o.email_enviado = true"] # Solo activas en sistema
        
        roles_sin_restriccion = ['MANAGER', 'ADMIN', 'DIRECTOR']
        if role not in roles_sin_restriccion:
            conditions.append(f"o.creado_por_id = ${len(params)+1}")
            params.append(user_id)
            
        where_str = "WHERE " + " AND ".join(conditions)
        
        # 2. Queries de KPIs
        
        # Total
        q_total = f"SELECT count(*) FROM tb_oportunidades o {where_str}"
        total = await conn.fetchval(q_total, *params)
        
        # Levantamientos
        # Buscamos JOIN con tipos de solicitud que sean 'LEVANTAMIENTO'
        q_lev = f"""
            SELECT count(*) 
            FROM tb_oportunidades o
            JOIN tb_cat_tipos_solicitud t ON o.id_tipo_solicitud = t.id
            {where_str} AND (t.nombre ILIKE '%LEVANTAMIENTO%' OR t.codigo_interno = 'LEVANTAMIENTO')
        """
        levantamientos = await conn.fetchval(q_lev, *params)
        
        # Ganadas (Cerrada)
        q_ganadas = f"""
            SELECT count(*) 
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
            {where_str} AND (e.nombre ILIKE 'CERRADA' OR e.nombre ILIKE 'GANADA')
        """
        ganadas = await conn.fetchval(q_ganadas, *params)
        
        # Perdidas
        q_perdidas = f"""
            SELECT count(*) 
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
            {where_str} AND e.nombre ILIKE 'PERDIDA'
        """
        perdidas = await conn.fetchval(q_perdidas, *params)
        
        # 3. Datos para Gráficas
        
        # A) Tendencia (Últimos 7 días con actividad)
        # Usamos to_char con 'Day' para nombre del día, pero solo los primeros 3 chars
        q_trend = f"""
            SELECT to_char(fecha_solicitud, 'Dy') as label, count(*) as count
            FROM tb_oportunidades o
            {where_str}
            AND fecha_solicitud >= NOW() - INTERVAL '30 days'
            GROUP BY to_char(fecha_solicitud, 'Dy'), fecha_solicitud::date
            ORDER BY fecha_solicitud::date DESC
            LIMIT 5
        """
        rows_trend = await conn.fetch(q_trend, *params)
        # Invertir para mostrar cronológicamente (Older -> Newer)
        chart_trend = {
            "labels": [r['label'] for r in reversed(rows_trend)],
            "data": [r['count'] for r in reversed(rows_trend)]
        }
        
        # B) Mix Tecnológico
        q_mix = f"""
            SELECT t.nombre as label, count(*) as count
            FROM tb_oportunidades o
            JOIN tb_cat_tecnologias t ON o.id_tecnologia = t.id
            {where_str}
            GROUP BY t.nombre
        """
        rows_mix = await conn.fetch(q_mix, *params)
        chart_mix = {
            "labels": [r['label'] for r in rows_mix],
            "data": [r['count'] for r in rows_mix]
        }
        
        return {
            "kpis": {
                "total": total,
                "levantamientos": levantamientos,
                "ganadas": ganadas,
                "perdidas": perdidas
            },
            "charts": {
                "trend": chart_trend,
                "mix": chart_mix
            }
        }

    async def get_comentarios_simulacion(self, conn, id_oportunidad: UUID) -> List[dict]:
        """
        Obtiene comentarios de simulación ordenados por fecha (más reciente primero).
        
        Args:
            conn: Conexión a la base de datos
            id_oportunidad: UUID de la oportunidad
            
        Returns:
            Lista de diccionarios con comentarios
        """
        rows = await conn.fetch("""
            SELECT 
                bs.comentario,
                bs.usuario_email,
                bs.etapa,
                bs.fecha_comentario
            FROM tb_bitacora_simulacion bs
            WHERE bs.id_oportunidad = $1
            ORDER BY bs.fecha_comentario DESC
        """, id_oportunidad)
        return [dict(r) for r in rows]

    async def get_detalles_bess(self, conn, id_oportunidad: UUID) -> Optional[dict]:
        """
        Obtiene detalles BESS si existen para la oportunidad.
        
        Args:
            conn: Conexión a la base de datos
            id_oportunidad: UUID de la oportunidad
            
        Returns:
            Diccionario con detalles BESS o None si no existen
        """
        row = await conn.fetchrow("""
            SELECT 
                db.cargas_criticas_kw,
                db.tiene_motores,
                db.potencia_motor_hp,
                db.tiempo_autonomia,
                db.voltaje_operacion,
                db.cargas_separadas,
                db.objetivos_json,
                db.tiene_planta_emergencia
            FROM tb_detalles_bess db
            WHERE db.id_oportunidad = $1
        """, id_oportunidad)
        
        if not row:
            return None
            
        # Convertir a dict y parsear JSON
        bess_data = dict(row)
        
        # Parsear objetivos_json de string a lista
        if bess_data.get('objetivos_json'):
            try:
                # Si es string JSON, parsearlo
                if isinstance(bess_data['objetivos_json'], str):
                    bess_data['objetivos_json'] = json.loads(bess_data['objetivos_json'])
            except (json.JSONDecodeError, TypeError):
                # Si falla el parsing, dejar como lista vacía
                bess_data['objetivos_json'] = []
        
        return bess_data

# Helper para inyección de dependencias
def get_comercial_service():
    return ComercialService()