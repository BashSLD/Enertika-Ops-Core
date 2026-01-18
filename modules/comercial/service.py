from datetime import datetime, timedelta, time as dt_time
from uuid import UUID, uuid4
from typing import List, Optional, Tuple
import json
import logging
import asyncpg
from fastapi import HTTPException
from zoneinfo import ZoneInfo
import pandas as pd
import io
import re
from openpyxl import load_workbook
from fastapi.templating import Jinja2Templates
from .schemas import SitioImportacion

logger = logging.getLogger("ComercialModule")

# Constante para evitar magic strings
EVENTO_EXTRAORDINARIA = "EXTRAORDINARIA"

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
        - Toma las 2 PRIMERAS palabras significativas (>2 caracteres, sin puntos)
        - Formato: PRIMER_NOMBRE_PRIMER_APELLIDO
        - Si solo hay 1 palabra significativa: esa palabra
        - Si vacío o None: cadena vacía
        
        Ejemplos:
        - "Sharon V. Morales Perez" → "SHARON_MORALES" 
        - "Moises Jimenez" → "MOISES_JIMENEZ" 
        - "Admin" → "ADMIN" 
        """
        parts = (user_name or "").strip().split()
        
        # Filtrar palabras significativas (más de 2 caracteres, sin puntos)
        meaningful_parts = [
            p.replace('.', '') for p in parts 
            if len(p.replace('.', '')) > 2
        ]
        
        if len(meaningful_parts) >= 2:
            # Tomar las 2 PRIMERAS palabras significativas (no primera y última)
            return f"{meaningful_parts[0]}_{meaningful_parts[1]}".upper()
        elif len(meaningful_parts) == 1:
            return meaningful_parts[0].upper()
        elif len(parts) >= 2:
            # Fallback si no hay palabras significativas: usar primera_segunda original
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
        Carga IDs de catálogos para filtros rápidos.
        Usa caché de 5 minutos.
        
        Retorna estructura:
        {
            'estatus': {'entregado': 1, 'cancelado': 2, ...},
            'tipos': {'pre_oferta': 1, 'licitacion': 2, 'oferta_final': 3, ...}
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
        Lógica de Negocio:
        - Configuración dinámica (SLA desde BD).
        - Ajuste de fecha de arranque:
           - Sábado/Domingo: Pasan al Lunes.
           - Viernes > 17:30: Pasa al Lunes.
           - Lunes-Jueves > 17:30: Pasa al día siguiente.
           - Lunes-Viernes <= 17:30: Arranca el mismo día.
        - Cálculo: Fecha Arranque + Días SLA.
        - Vencimiento: Se fija a las 17:30 del día destino.
        """
        
        # Obtener configuración
        config = await self.get_configuracion_global(conn)
        
        # Obtener Hora de Corte
        hora_corte_str = config.get("HORA_CORTE_L_V", "17:30")
        h, m = map(int, hora_corte_str.split(":"))
        hora_corte = dt_time(h, m)

        # Obtener Días SLA (Dinámico)
        # Intentamos leer de BD, si falla o no existe, usamos 7 por defecto.
        try:
            dias_sla_str = config.get("DIAS_SLA_DEFAULT", "7")
            DIAS_SLA = int(dias_sla_str)
        except ValueError:
            DIAS_SLA = 7

        # Datos de la Fecha Actual
        # 0=Lun, 1=Mar, 2=Mie, 3=Jue, 4=Vie, 5=Sab, 6=Dom
        dia_semana = fecha_creacion.weekday() 
        hora_actual = fecha_creacion.time()
        
        # Reseteamos a 00:00:00 para sumar días completos
        fecha_base = fecha_creacion.replace(hour=0, minute=0, second=0, microsecond=0)
        
        dias_ajuste_inicio = 0

        # --- REGLAS DE NEGOCIO ---
        
        # Fin de Semana (Sábado o Domingo)
        # La hora NO importa, siempre se recorre al Lunes.
        if dia_semana == 5:   # Sábado -> Lunes (+2)
            dias_ajuste_inicio = 2
        elif dia_semana == 6: # Domingo -> Lunes (+1)
            dias_ajuste_inicio = 1
            
        # Entre Semana (Lunes a Viernes)
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

        # Cálculo Final
        # Fecha Inicio Real = Fecha Creación + Ajuste
        adjusted_start_date = fecha_base + timedelta(days=dias_ajuste_inicio)
        
        # Deadline = Fecha Inicio Real + SLA
        deadline_final = adjusted_start_date + timedelta(days=DIAS_SLA)
        
        # Fijar hora de vencimiento al cierre de jornada
        deadline_final = deadline_final.replace(hour=h, minute=m)
        
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
        tipos = await conn.fetch("SELECT id, nombre, codigo_interno FROM tb_cat_tipos_solicitud WHERE activo = true ORDER BY nombre")
        
        return {
            "tecnologias": [dict(t) for t in tecnologias],
            "tipos_solicitud": [dict(t) for t in tipos]
        }

    async def get_catalogos_creacion(self, conn, include_simulacion: bool = False) -> dict:
        """
        Carga catálogos filtrados específicamente para el Formulario de Creación (Paso 1).
        
        Args:
            include_simulacion: Si True, incluye 'SIMULACION' en la lista (para extraordinarias).
                              Si False, solo 'PRE_OFERTA' y 'LICITACION' (para normal).
        """
        # Tecnologías (Todas)
        tecnologias = await conn.fetch("SELECT id, nombre FROM tb_cat_tecnologias WHERE activo = true ORDER BY nombre")
        
        # Tipos de Solicitud (Filtrado Dinámico)
        # Base: PRE_OFERTA, LEVANTAMIENTO ('LICITACION' removido, ahora es flag transversal)
        codigos = ['PRE_OFERTA', 'LEVANTAMIENTO']
        
        if include_simulacion:
            codigos.append('SIMULACION')
            
        # Generar placeholders para la query IN ($1, $2, ...)
        placeholders = ",".join([f"${i+1}" for i in range(len(codigos))])
        
        tipos = await conn.fetch(f"""
            SELECT id, nombre, codigo_interno 
            FROM tb_cat_tipos_solicitud 
            WHERE activo = true 
            AND codigo_interno IN ({placeholders})
            ORDER BY nombre
        """, *codigos)
        
        # Usuarios (Para delegación)
        usuarios = await conn.fetch("SELECT id_usuario, nombre FROM tb_usuarios WHERE is_active = true ORDER BY nombre")

        return {
            "tecnologias": [dict(t) for t in tecnologias],
            "tipos_solicitud": [dict(t) for t in tipos],
            "usuarios": [dict(u) for u in usuarios]
        }

    async def get_catalogos_extraordinario(self, conn) -> dict:
        """
        Carga catálogos filtrados específicamente para el Formulario Extraordinario.
        Solo incluye PRE_OFERTA y SIMULACION (NO incluye LEVANTAMIENTO).
        
        Returns:
            dict con tecnologias, tipos_solicitud (solo PRE_OFERTA y SIMULACION), y usuarios
        """
        # Tecnologías (Todas)
        tecnologias = await conn.fetch("SELECT id, nombre FROM tb_cat_tecnologias WHERE activo = true ORDER BY nombre")
        
        # Tipos de Solicitud (PRE_OFERTA, SIMULACION, CAPTURA_RECIBOS)
        codigos = ['PRE_OFERTA', 'SIMULACION', 'CAPTURA_RECIBOS']
        placeholders = ",".join([f"${i+1}" for i in range(len(codigos))])
        
        tipos = await conn.fetch(f"""
            SELECT id, nombre, codigo_interno 
            FROM tb_cat_tipos_solicitud 
            WHERE activo = true 
            AND codigo_interno IN ({placeholders})
            ORDER BY nombre
        """, *codigos)
        
        # Usuarios (Para delegación)
        usuarios = await conn.fetch("SELECT id_usuario, nombre FROM tb_usuarios WHERE is_active = true ORDER BY nombre")

        return {
            "tecnologias": [dict(t) for t in tecnologias],
            "tipos_solicitud": [dict(t) for t in tipos],
            "usuarios": [dict(u) for u in usuarios]
        }

    async def get_id_tipo_actualizacion(self, conn) -> Optional[int]:
        """
        Obtiene el ID del tipo de solicitud 'ACTUALIZACION' desde catálogo.
        Usado en modo homologación para forzar tipo de solicitud.
        
        Returns:
            ID del tipo ACTUALIZACION o None si no existe
        """
        tipo_act = await conn.fetchrow(
            "SELECT id FROM tb_cat_tipos_solicitud WHERE codigo_interno = 'ACTUALIZACION' AND activo = true"
        )
        return tipo_act['id'] if tipo_act else None

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
                id_oportunidad, uso_sistema_json, cargas_criticas_kw, tiene_motores, potencia_motor_hp,
                tiempo_autonomia, voltaje_operacion, cargas_separadas, 
                tiene_planta_emergencia
            ) VALUES ($1, $2::jsonb, $3, $4, $5, $6, $7, $8, $9)
        """
        
        # Pydantic v2: model_dump() y json.dumps para el array
        uso_sistema_str = json.dumps(bess_data.uso_sistema_json)
        
        await conn.execute(query,
            id_oportunidad,
            uso_sistema_str,
            bess_data.cargas_criticas_kw,
            bess_data.tiene_motores,
            bess_data.potencia_motor_hp,
            bess_data.tiempo_autonomia,
            bess_data.voltaje_operacion,
            bess_data.cargas_separadas,
            bess_data.tiene_planta_emergencia
        )

    async def crear_oportunidad_transaccional(self, conn, datos, user_context: dict, legacy_search_term: Optional[str] = None) -> tuple:
        """
        Orquestador Transaccional (Fase 2).
        Maneja: Fechas, Identificadores, Oportunidad Base y BESS.
        
        Args:
            conn: Conexión asyncpg
            datos: OportunidadCreateCompleta (Pydantic v2)
            user_context: dict con user_db_id, user_name, role
            legacy_search_term: Término de búsqueda legacy para modo homologación (opcional)
            
        Returns:
            tuple: (new_id, op_id_estandar, es_fuera_horario)
        """
        logger.info(f"Iniciando creación de oportunidad para cliente {datos.cliente_nombre}")
        
        fecha_solicitud = await self.procesar_fecha_manual(conn, datos.fecha_manual_str)
        es_fuera_horario = await self.calcular_fuera_de_horario(conn, fecha_solicitud)
        deadline = await self.calcular_deadline_inicial(conn, fecha_solicitud)

        # BUSINESS LOGIC: Modo Homologación
        # El usuario ya seleccionó ACTUALIZACIÓN o LEVANTAMIENTO en el formulario
        # No forzamos el tipo, respetamos la selección del usuario
        if legacy_search_term:
            logger.info(f"MODO HOMOLOGACIÓN: Búsqueda de hilo con término '{legacy_search_term}'")

        # Generar Identificadores
        new_id = uuid4()
        now_mx = await self.get_current_datetime_mx(conn)
        op_id_estandar = now_mx.strftime("OP - %y%m%d%H%M")
        
        # ---------------------------------------------------------
        # GESTIÓN INTELIGENTE DE CLIENTES (Buscar o Crear)
        # 1. Si viene cliente_id: Usarlo y homologar nombre.
        # 2. Si no viene cliente_id: Buscar por nombre exacto.
        #    a. Si existe: Usar ID encontrado.
        #    b. Si no existe: Crear nuevo cliente.
        # ---------------------------------------------------------
        final_cliente_id = datos.cliente_id
        final_cliente_nombre = datos.cliente_nombre.strip().upper()

        if final_cliente_id:
            # Caso 1: ID explícito (seleccionado de autocompletado)
            # Opcional: Podríamos validar que exista, pero asumimos frontend correcto.
            # Homologamos el nombre con el oficial de la base de datos si se desea, 
            # o mantenemos el input manual. Por ahora mantenemos input manual pero vinculamos ID.
            pass
        else:
            # Caso 2: Nombre manual (Nuevo o No seleccionado)
            # Buscar coincidencia EXACTA (Case Insensitive)
            existing_client = await conn.fetchrow(
                "SELECT id, nombre_fiscal FROM tb_clientes WHERE nombre_fiscal ILIKE $1", 
                final_cliente_nombre
            )
            
            if existing_client:
                # Caso 2a: Ya existía, lo vinculamos
                final_cliente_id = existing_client['id']
                # Opcional: Usar el nombre oficial
                # final_cliente_nombre = existing_client['nombre_fiscal'] 
            else:
                # Caso 2b: Es totalmente nuevo -> Crear en tb_clientes
                final_cliente_id = uuid4()
                await conn.execute(
                    "INSERT INTO tb_clientes (id, nombre_fiscal) VALUES ($1, $2)",
                    final_cliente_id, final_cliente_nombre
                )
                logger.info(f"Nuevo cliente registrado automáticamente: {final_cliente_nombre} ({final_cliente_id})")

        
        # Obtener nombres de catálogos (Queries directos optimizados)
        nombre_tec = await conn.fetchval("SELECT nombre FROM tb_cat_tecnologias WHERE id = $1", datos.id_tecnologia)
        nombre_tipo = await conn.fetchval("SELECT nombre FROM tb_cat_tipos_solicitud WHERE id = $1", datos.id_tipo_solicitud)
        
        # Generar Títulos Legacy (AMBOS en MAYÚSCULAS)
        titulo = f"{nombre_tipo}_{final_cliente_nombre}_{datos.nombre_proyecto}_{nombre_tec}_{datos.canal_venta}".upper()
        id_interno = f"{op_id_estandar}_{datos.nombre_proyecto}_{final_cliente_nombre}".upper()[:150]

        # Insertar Oportunidad
        
        # Obtener ID de estatus inicial
        cats = await self.get_catalog_ids(conn)
        # Usamos 'pendiente' como default
        id_status_inicial = cats['estatus'].get('pendiente') or 1 

        # Lógica de Solicitado Por
        solicitado_por_nombre = user_context.get('user_name', 'Usuario')
        if datos.solicitado_por_id:
            # Si se delegó (Extraordinaria), obtenemos el nombre real
            solicitado_por_nombre = await conn.fetchval(
                "SELECT nombre FROM tb_usuarios WHERE id_usuario = $1", 
                datos.solicitado_por_id
            ) or solicitado_por_nombre

        query_op = """
            INSERT INTO tb_oportunidades (
                id_oportunidad, op_id_estandar, id_interno_simulacion,
                titulo_proyecto, nombre_proyecto, cliente_nombre, cliente_id, canal_venta,
                id_tecnologia, id_tipo_solicitud, id_estatus_global,
                cantidad_sitios, prioridad, 
                direccion_obra, coordenadas_gps, google_maps_link, sharepoint_folder_url,
                creado_por_id, fecha_solicitud,
                es_fuera_horario, deadline_calculado,
                solicitado_por, es_carga_manual,
                clasificacion_solicitud, solicitado_por_id, es_licitacion
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $26, $7,
                $8, $9, $22, 
                $10, $11, $12, $13, $14, $15, 
                $16, $17, 
                $18, $19,
                $20, $21,
                $23, $24, $25
            )
        """
        es_manual = bool(datos.fecha_manual_str)  # Flag de auditoría

        await conn.execute(query_op, 
            new_id, op_id_estandar, id_interno,
            titulo, datos.nombre_proyecto, final_cliente_nombre, datos.canal_venta,
            datos.id_tecnologia, datos.id_tipo_solicitud,
            datos.cantidad_sitios, datos.prioridad,
            datos.direccion_obra, datos.coordenadas_gps, datos.google_maps_link, datos.sharepoint_folder_url,
            user_context['user_db_id'], fecha_solicitud,
            es_fuera_horario, deadline,
            solicitado_por_nombre, es_manual,
            id_status_inicial,
            datos.clasificacion_solicitud, datos.solicitado_por_id, datos.es_licitacion,
            final_cliente_id # $26
        )


        # Insertar BESS (Si aplica y hay datos)
        if datos.detalles_bess:
            # Validación de negocio adicional: ¿Es tecnología BESS?
            await self._insertar_bess(conn, new_id, datos.detalles_bess)
        
        # ========================================
        # HOOK: Crear levantamiento automáticamente si es tipo LEVANTAMIENTO
        # ========================================
        tipo_datos = await conn.fetchrow(
            "SELECT codigo_interno FROM tb_cat_tipos_solicitud WHERE id = $1",
            datos.id_tipo_solicitud
        )
        if tipo_datos and tipo_datos['codigo_interno'] == 'LEVANTAMIENTO':
            try:
                from modules.levantamientos.service import LevantamientoService
                lev_service = LevantamientoService()
                lev_id = await lev_service.crear_desde_oportunidad(conn, new_id, user_context)
                logger.info(f"Levantamiento {lev_id} creado automáticamente para oportunidad {op_id_estandar}")
            except Exception as e:
                logger.error(f"Error creando levantamiento automático: {e}")
                # No fallar la creación de oportunidad por esto
        
        # Site Unico (Si aplica, pasar id_tipo_solicitud)
        if datos.cantidad_sitios == 1:
            await self.auto_crear_sitio_unico(
                conn, new_id, 
                datos.nombre_proyecto, 
                datos.direccion_obra, 
                datos.google_maps_link,
                datos.id_tipo_solicitud
            )
        
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

    async def get_oportunidad_for_email(self, conn, id_oportunidad: UUID) -> Optional[dict]:
        """
        Obtiene datos de oportunidad necesarios para envío de correo.       
        Args:
            conn: Conexión a base de datos
            id_oportunidad: UUID de la oportunidad
            
        Returns:
            dict con todos los campos de tb_oportunidades o None si no existe
        """
        row = await conn.fetchrow(
            "SELECT * FROM tb_oportunidades WHERE id_oportunidad = $1", 
            id_oportunidad
        )
        return dict(row) if row else None

    async def get_parent_titulo(self, conn, parent_id: UUID) -> Optional[str]:
        """
        Obtiene el título del proyecto padre para búsqueda de hilos de correo.
        
        Usado en modo SEGUIMIENTO para encontrar el hilo original.
        
        Args:
            conn: Conexión a base de datos
            parent_id: UUID de la oportunidad padre
            
        Returns:
            Título del proyecto padre o None si no existe
        """
        return await conn.fetchval(
            "SELECT titulo_proyecto FROM tb_oportunidades WHERE id_oportunidad = $1",
            parent_id
        )
    
    async def get_email_threading_context(
        self,
        conn,
        row: dict,
        legacy_search_term: Optional[str] = None
    ) -> dict:
        """
        Determina el contexto de threading para envío de correo.
        
        Lógica HÍBRIDA de búsqueda de hilos:
        1. Si existe legacy_search_term: HOMOLOGACIÓN (busca hilo viejo con datos nuevos)
        2. Si tiene parent_id: SEGUIMIENTO NORMAL (busca por título del padre)
        3. Caso contrario: ENVÍO INICIAL (nuevo, sin hilo previo)
        
        Args:
            conn: Database connection
            row: Oportunidad row data (debe contener 'parent_id' y 'op_id_estandar')
            legacy_search_term: Término de búsqueda legacy para homologación
            
        Returns:
            dict con:
                - search_key: Término para buscar hilo (None si es nuevo)
                - modo: "HOMOLOGACIÓN", "SEGUIMIENTO", o "NUEVO"
                - log_message: Mensaje descriptivo para logging
        """
        search_key = None
        modo = "NUEVO"
        log_message = f"ENVÍO INICIAL para '{row.get('op_id_estandar')}' | No se buscará hilo previo"
        
        if legacy_search_term:
            search_key = legacy_search_term
            modo = "HOMOLOGACIÓN"
            log_message = (
                f"MODO HOMOLOGACIÓN activado para '{row.get('op_id_estandar')}' | "
                f"Buscando hilo por término legacy: '{search_key}'"
            )
        elif row.get('parent_id'):
            search_key = await self.get_parent_titulo(conn, row['parent_id'])
            modo = "SEGUIMIENTO"
            log_message = (
                f"SEGUIMIENTO NORMAL detectado para '{row.get('op_id_estandar')}' | "
                f"Buscando hilo del padre: '{search_key}'"
            )
        
        return {
            "search_key": search_key,
            "modo": modo,
            "log_message": log_message
        }

    async def get_oportunidades_list(self, conn, user_context: dict, tab: str = "activos", q: str = None, limit: int = 15, subtab: str = None) -> List[dict]:
        """Recupera lista filtrada de oportunidades con permisos y paginación."""
        user_id = user_context.get("user_db_id")  # CORREGIDO: era "user_id"
        role = user_context.get("role", "USER")
        
        logger.debug(f"Consultando oportunidades - Tab: {tab}, Filtro: {q}, Usuario: {user_id}")

        # Cargar IDs de catálogos
        cats = await self.get_catalog_ids(conn)

        query = """
            SELECT 
                o.id_oportunidad, o.op_id_estandar, o.nombre_proyecto, o.cliente_nombre, o.canal_venta,
                o.fecha_solicitud, estatus.nombre as status_global, o.email_enviado, o.id_interno_simulacion,
                tipo_sol.nombre as tipo_solicitud, o.deadline_calculado, o.deadline_negociado, o.cantidad_sitios,
                o.titulo_proyecto, o.prioridad, o.es_fuera_horario,
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

        # Filtro por tab (Usa IDs)
        if tab == "historial":
            # Subtabs para historial: entregado vs cancelado-perdido
            if not subtab or subtab == 'entregado':
                # Por defecto: solo Entregado
                id_entregado = cats['estatus'].get('entregado')
                if id_entregado:
                    query += f" AND o.id_estatus_global = ${param_idx}"
                    params.append(id_entregado)
                    param_idx += 1
            elif subtab == 'cancelado_perdido':
                # Alternativa: Cancelado + Perdido
                ids_fallidos = [
                    cats['estatus'].get('cancelado'),
                    cats['estatus'].get('perdido')
                ]
                ids_fallidos = [i for i in ids_fallidos if i is not None]
                if ids_fallidos:
                    placeholders = ','.join([f'${i}' for i in range(param_idx, param_idx + len(ids_fallidos))])
                    query += f" AND o.id_estatus_global IN ({placeholders})"
                    params.extend(ids_fallidos)
                    param_idx += len(ids_fallidos)
                
        elif tab == "levantamientos":
            # Buscar ID del tipo "levantamiento"
            id_levantamiento = cats['tipos'].get('levantamiento')
            if id_levantamiento:
                query += f" AND o.id_tipo_solicitud = ${param_idx}"
                params.append(id_levantamiento)
                param_idx += 1
                
            # Sub-filtro por subtab
            if subtab == 'realizados':
                # 'Realizado' no existe en DB, usamos 'Entregado'
                id_entregado = cats['estatus'].get('entregado')
                if id_entregado:
                    query += f" AND o.id_estatus_global = ${param_idx}"
                    params.append(id_entregado)
                    param_idx += 1
            else:
                # Todo lo que NO sea Entregado (Pendiente, Proceso, etc)
                id_entregado = cats['estatus'].get('entregado')
                if id_entregado:
                    query += f" AND o.id_estatus_global != ${param_idx}"
                    params.append(id_entregado)
                    param_idx += 1
                    
        elif tab == "ganadas":
            id_ganada = cats['estatus'].get('ganada')
            if id_ganada:
                query += f" AND o.id_estatus_global = ${param_idx}"
                params.append(id_ganada)
                param_idx += 1
                
        else:  # activos
            # Estados ACTIVOS - Inclusión explícita
            ids_activos = [
                cats['estatus'].get('pendiente'),
                cats['estatus'].get('en revisión'),  # Con tilde según BD
                cats['estatus'].get('en proceso')
            ]
            ids_activos = [i for i in ids_activos if i is not None]
            if ids_activos:
                placeholders = ','.join([f'${i}' for i in range(param_idx, param_idx + len(ids_activos))])
                query += f" AND o.id_estatus_global IN ({placeholders})"
                params.extend(ids_activos)
                param_idx += len(ids_activos)
                
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
    
    async def update_oportunidad_prioridad(
        self, 
        conn, 
        id_oportunidad: UUID, 
        prioridad: str
    ) -> None:
        """
        Updates the priority of an opportunity.
        
        Args:
            conn: Database connection
            id_oportunidad: UUID of the opportunity
            prioridad: Priority value ('normal', 'alta', 'baja')
        """
        await conn.execute(
            "UPDATE tb_oportunidades SET prioridad = $1 WHERE id_oportunidad = $2",
            prioridad,
            id_oportunidad
        )
        logger.info(f"Prioridad actualizada a '{prioridad}' para oportunidad {id_oportunidad}")
    
    async def check_user_has_access_token(
        self, 
        conn, 
        user_db_id: UUID
    ) -> bool:
        """
        Checks if a user has a valid access token stored.
        
        Args:
            conn: Database connection
            user_db_id: User's database ID
            
        Returns:
            True if user has an access token, False otherwise
        """
        has_token = await conn.fetchval(
            """SELECT CASE WHEN access_token IS NOT NULL THEN true ELSE false END 
               FROM tb_usuarios WHERE id_usuario = $1""",
            user_db_id
        )
        return has_token or False

    async def create_followup_oportunidad(self, parent_id: UUID, nuevo_tipo_solicitud: str, prioridad: str, conn, user_id: UUID, user_name: str) -> UUID:
        """Crea seguimiento clonando padre + sitios."""
        
        # Fuente de verdad temporal (Corrección Zona Horaria)
        # Obtenemos la hora con timezone de México. Asyncpg la convertirá a UTC al guardar.
        now_mx = await self.get_current_datetime_mx(conn)

        parent = await conn.fetchrow("SELECT * FROM tb_oportunidades WHERE id_oportunidad = $1", parent_id)
        if not parent: 
            raise HTTPException(status_code=404, detail="Oportunidad original no encontrada")

        # Convertir string de tipo_solicitud a ID
        # El parámetro nuevo_tipo_solicitud viene como "OFERTA_FINAL", "ACTUALIZACION", etc.
        id_tipo_solicitud = await conn.fetchval(
            "SELECT id FROM tb_cat_tipos_solicitud WHERE UPPER(codigo_interno) = UPPER($1)",
            nuevo_tipo_solicitud
        )
        
        if not id_tipo_solicitud:
            raise HTTPException(status_code=400, detail=f"Tipo de solicitud '{nuevo_tipo_solicitud}' no encontrado en catálogo")

        new_uuid = uuid4()
        timestamp_id = now_mx.strftime('%y%m%d%H%M')
        op_id_estandar_new = f"OP - {timestamp_id}"
        
        # Calcular es_fuera_horario para seguimientos (antes faltaba)
        es_fuera_horario = await self.calcular_fuera_de_horario(conn, now_mx)
        deadline = await self.calcular_deadline_inicial(conn, now_mx)
        
        # Obtener datos completos para construir título igual que en creación inicial
        nombre_tipo = await conn.fetchval("SELECT nombre FROM tb_cat_tipos_solicitud WHERE id = $1", id_tipo_solicitud)
        nombre_tec = await conn.fetchval("SELECT nombre FROM tb_cat_tecnologias WHERE id = $1", parent['id_tecnologia'])
        
        # Título completo con el MISMO formato que la creación inicial
        titulo_new = f"{nombre_tipo}_{parent['cliente_nombre']}_{parent['nombre_proyecto']}_{nombre_tec}_{parent['canal_venta']}".upper()

        # Obtener ID dinámico
        cats = await self.get_catalog_ids(conn)
        id_status_inicial = cats['estatus'].get('pendiente') or 1

        # Agregar id_tecnologia que faltaba en seguimientos
        # Usar placeholders $22 y $23
        query_insert = """
            INSERT INTO tb_oportunidades (
                id_oportunidad, creado_por_id, parent_id,
                titulo_proyecto, nombre_proyecto, cliente_nombre, cliente_id,
                canal_venta, solicitado_por,
                id_tecnologia, id_tipo_solicitud, cantidad_sitios, prioridad,
                direccion_obra, coordenadas_gps, google_maps_link, sharepoint_folder_url,
                id_interno_simulacion, op_id_estandar,
                id_estatus_global,     -- $22 (Dinámico)
                deadline_calculado, es_fuera_horario, 
                fecha_solicitud,       -- $23 (now_mx)
                email_enviado,
                es_licitacion         -- HEREDADO
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, 
                $22,  -- ID Estatus (Ya no es 1 fijo)
                $20, $21, 
                $23,  -- Fecha Solicitud (Ya no es NOW())
                FALSE,
                $24   -- es_licitacion
            ) RETURNING id_oportunidad
        """
        await conn.fetchval(query_insert,
            new_uuid, user_id, parent_id,
            titulo_new, parent['nombre_proyecto'], parent['cliente_nombre'], parent['cliente_id'],
            parent['canal_venta'], user_name,
            parent['id_tecnologia'], id_tipo_solicitud, parent['cantidad_sitios'], prioridad,
            parent['direccion_obra'], parent['coordenadas_gps'], parent['google_maps_link'], parent['sharepoint_folder_url'],
            parent['id_interno_simulacion'], op_id_estandar_new, deadline, es_fuera_horario,
            id_status_inicial,  # Parámetro $22
            now_mx,             # Parámetro $23
            parent['es_licitacion'] # Parámetro $24 (Herencia)
        )

        # Clonar sitios (Heredan id_tipo_solicitud del NUEVO tipo, no del viejo)
        query_clone = """
            INSERT INTO tb_sitios_oportunidad (id_sitio, id_oportunidad, nombre_sitio, direccion, tipo_tarifa, google_maps_link, numero_servicio, comentarios, id_estatus_global, id_tipo_solicitud)
            SELECT gen_random_uuid(), $1, nombre_sitio, direccion, tipo_tarifa, google_maps_link, numero_servicio, comentarios, 1, $3
            FROM tb_sitios_oportunidad WHERE id_oportunidad = $2
        """
        await conn.execute(query_clone, new_uuid, parent_id, id_tipo_solicitud)
        
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
        user_id = user_context.get("user_db_id")
        role = user_context.get("role", "USER")
        
        # Filtros de Seguridad
        params = []
        conditions = ["o.email_enviado = true"] # Solo activas en sistema
        
        roles_sin_restriccion = ['MANAGER', 'ADMIN', 'DIRECTOR']
        if role not in roles_sin_restriccion:
            conditions.append(f"o.creado_por_id = ${len(params)+1}")
            params.append(user_id)
            
        where_str = "WHERE " + " AND ".join(conditions)
        
        # Cargar catálogos para búsquedas
        cats = await self.get_catalog_ids(conn)
        
        # Queries de KPIs
        
        # Preparamos los IDs y parámetros adicionales
        id_ganada = cats['estatus'].get('ganada')
        id_perdido = cats['estatus'].get('perdido')
        
        # Calculamos índices para los parámetros nuevos
        idx_ganada = len(params) + 1
        idx_perdido = len(params) + 2
        
        q_kpis = f"""
            SELECT 
                count(*) as total,
                count(*) FILTER (WHERE t.codigo_interno = 'LEVANTAMIENTO') as levantamientos,
                count(*) FILTER (WHERE o.id_estatus_global = ${idx_ganada}) as ganadas,
                count(*) FILTER (WHERE o.id_estatus_global = ${idx_perdido}) as perdidas
            FROM tb_oportunidades o
            LEFT JOIN tb_cat_tipos_solicitud t ON o.id_tipo_solicitud = t.id
            {where_str}
        """
        
        # Ejecutamos 1 sola vez pasando todos los parámetros
        row_kpis = await conn.fetchrow(q_kpis, *params, id_ganada, id_perdido)
        
        # Extraemos resultados
        total = row_kpis['total']
        levantamientos = row_kpis['levantamientos']
        ganadas = row_kpis['ganadas']
        perdidas = row_kpis['perdidas']
        
        # Datos para Gráficas
        
        # A) Semana Actual Completa (7 días, Lun-Dom, con ceros)
        q_week = f"""
            WITH semana_actual AS (
                SELECT 
                    EXTRACT(ISODOW FROM (fecha_solicitud AT TIME ZONE 'America/Mexico_City'))::int as day_num,
                    count(*) as count
                FROM tb_oportunidades o
                {where_str}
                AND (fecha_solicitud AT TIME ZONE 'America/Mexico_City')::date 
                    >= DATE_TRUNC('week', (NOW() AT TIME ZONE 'America/Mexico_City')::date)
                AND (fecha_solicitud AT TIME ZONE 'America/Mexico_City')::date
                    < DATE_TRUNC('week', (NOW() AT TIME ZONE 'America/Mexico_City')::date) + INTERVAL '7 days'
                GROUP BY day_num
            )
            SELECT 
                s.day_num,
                COALESCE(sa.count, 0) as count
            FROM generate_series(1, 7) AS s(day_num)
            LEFT JOIN semana_actual sa ON s.day_num = sa.day_num
            ORDER BY s.day_num
        """
        rows_week = await conn.fetch(q_week, *params)
        
        # Mapeo de números de día a nombres en español (1=Lun, 7=Dom)
        day_map = {1: 'Lun', 2: 'Mar', 3: 'Mié', 4: 'Jue', 5: 'Vie', 6: 'Sáb', 7: 'Dom'}
        
        chart_week = {
            "labels": [day_map[r['day_num']] for r in rows_week],
            "data": [r['count'] for r in rows_week]
        }
        
        # B) Evolución Mensual (Últimos 6 meses)
        # Para gerentes: desglose por vendedor (apilado)
        # Para usuarios: solo total
        if role in roles_sin_restriccion:
            # GERENTES: Desglose por canal_venta (vendedor)
            q_monthly = f"""
                SELECT 
                    TO_CHAR((fecha_solicitud AT TIME ZONE 'America/Mexico_City'), 'Mon YY') as mes,
                    DATE_TRUNC('month', (fecha_solicitud AT TIME ZONE 'America/Mexico_City')) as mes_date,
                    canal_venta,
                    count(*) as count
                FROM tb_oportunidades o
                {where_str}
                AND fecha_solicitud >= NOW() - INTERVAL '6 months'
                GROUP BY mes_date, mes, canal_venta
                ORDER BY mes_date, canal_venta
            """
            rows_monthly = await conn.fetch(q_monthly, *params)
            
            # Agrupar por vendedor para datasets apilados
            from collections import defaultdict
            meses_unicos = []
            vendedores_data = defaultdict(lambda: defaultdict(int))
            
            for row in rows_monthly:
                mes = row['mes']
                vendedor = row['canal_venta'] or 'Sin asignar'
                count = row['count']
                
                if mes not in meses_unicos:
                    meses_unicos.append(mes)
                vendedores_data[vendedor][mes] = count
            
            # Construir datasets para Chart.js (stacked)
            datasets = []
            colors = ['#00BABB', '#123456', '#22c55e', '#f97316', '#8b5cf6', '#ec4899', '#fbbf24']
            for idx, (vendedor, meses_counts) in enumerate(vendedores_data.items()):
                datasets.append({
                    "label": vendedor,
                    "data": [meses_counts.get(mes, 0) for mes in meses_unicos],
                    "backgroundColor": colors[idx % len(colors)]
                })
            
            chart_monthly = {
                "labels": meses_unicos,
                "datasets": datasets,
                "stacked": True  # Flag para indicar que debe ser apilado
            }
        else:
            # USUARIOS: Solo totales mensuales
            q_monthly = f"""
                SELECT 
                    TO_CHAR((fecha_solicitud AT TIME ZONE 'America/Mexico_City'), 'Mon YY') as mes,
                    count(*) as count
                FROM tb_oportunidades o
                {where_str}
                AND fecha_solicitud >= NOW() - INTERVAL '6 months'
                GROUP BY 
                    DATE_TRUNC('month', (fecha_solicitud AT TIME ZONE 'America/Mexico_City')),
                    TO_CHAR((fecha_solicitud AT TIME ZONE 'America/Mexico_City'), 'Mon YY')
                ORDER BY DATE_TRUNC('month', (fecha_solicitud AT TIME ZONE 'America/Mexico_City'))
            """
            rows_monthly = await conn.fetch(q_monthly, *params)
            
            chart_monthly = {
                "labels": [r['mes'] for r in rows_monthly],
                "data": [r['count'] for r in rows_monthly],
                "stacked": False
            }
        
        # C) Mix Tecnológico (sin cambios)
        q_mix = f"""
            SELECT t.nombre as label, count(*) as count
            FROM tb_oportunidades o
            JOIN tb_cat_tecnologias t ON o.id_tecnologia = t.id
            {where_str}
            GROUP BY t.nombre
            ORDER BY count DESC
        """
        rows_mix = await conn.fetch(q_mix, *params)
        chart_mix = {
            "labels": [r['label'] for r in rows_mix],
            "data": [r['count'] for r in rows_mix]
        }
        
        # D) Estatus del Pipeline (Top 5)
        q_status = f"""
            SELECT 
                e.nombre as label,
                count(*) as count
            FROM tb_oportunidades o
            JOIN tb_cat_estatus_global e ON o.id_estatus_global = e.id
            {where_str}
            GROUP BY e.nombre
            ORDER BY count DESC
            LIMIT 5
        """
        rows_status = await conn.fetch(q_status, *params)
        chart_status = {
            "labels": [r['label'] for r in rows_status],
            "data": [r['count'] for r in rows_status]
        }
        
        return {
            "kpis": {
                "total": total,
                "levantamientos": levantamientos,
                "ganadas": ganadas,
                "perdidas": perdidas
            },
            "charts": {
                "week": chart_week,           # Semana actual 
                "monthly": chart_monthly,      # Evolución 6 meses
                "mix": chart_mix,              # Mix tecnológico
                "status": chart_status         # Estado pipeline
            }
        }

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
                db.uso_sistema_json,
                db.cargas_criticas_kw,
                db.tiene_motores,
                db.potencia_motor_hp,
                db.tiempo_autonomia,
                db.voltaje_operacion,
                db.cargas_separadas,
                db.tiene_planta_emergencia
            FROM tb_detalles_bess db
            WHERE db.id_oportunidad = $1
        """, id_oportunidad)
        
        if not row:
            return None
            
        # Convertir a dict y parsear JSON
        bess_data = dict(row)
        
        # Parsear uso_sistema_json de string a lista
        if bess_data.get('uso_sistema_json'):
            try:
                if isinstance(bess_data['uso_sistema_json'], str):
                    bess_data['uso_sistema_json'] = json.loads(bess_data['uso_sistema_json'])
            except (json.JSONDecodeError, TypeError):
                bess_data['uso_sistema_json'] = []
        
        return bess_data
    
    async def get_data_for_email_form(self, conn, id_oportunidad: UUID) -> dict:
        """
        Prepara TODOS los datos necesarios para el formulario de correo (Paso 3).
        Incluye lógica de reglas de negocio (triggers) para TO/CC automáticos.
        """
        # Query Principal con Joins
        row = await conn.fetchrow(
            """SELECT o.*, 
                    tec.nombre as tipo_tecnologia,
                    tipo_sol.nombre as tipo_solicitud,
                    tipo_sol.es_seguimiento,
                    eg.nombre as status_global,
                    db.cargas_criticas_kw,
                    db.tiene_motores,
                    db.potencia_motor_hp,
                    db.tiempo_autonomia,
                    db.voltaje_operacion,
                    db.cargas_separadas,
                    db.tiene_planta_emergencia
            FROM tb_oportunidades o
            LEFT JOIN tb_cat_tecnologias tec ON o.id_tecnologia = tec.id
            LEFT JOIN tb_cat_tipos_solicitud tipo_sol ON o.id_tipo_solicitud = tipo_sol.id
            LEFT JOIN tb_cat_estatus_global eg ON o.id_estatus_global = eg.id
            LEFT JOIN tb_detalles_bess db ON o.id_oportunidad = db.id_oportunidad
            WHERE o.id_oportunidad = $1""", 
            id_oportunidad
        )
        if not row:
            return None

        # Sitios
        sitios_rows = await conn.fetch("SELECT * FROM tb_sitios_oportunidad WHERE id_oportunidad = $1 ORDER BY nombre_sitio", id_oportunidad)
        
        # Lógica de Defaults y Reglas
        defaults_row = await conn.fetchrow("SELECT * FROM tb_email_defaults WHERE id = 1")
        def_to = (defaults_row['default_to'] or "").replace(";", ",").split(",") if defaults_row else []
        def_cc = (defaults_row['default_cc'] or "").replace(";", ",").split(",") if defaults_row else []
        
        fixed_to = [d.strip() for d in def_to if d.strip()] 
        fixed_cc = [d.strip() for d in def_cc if d.strip()]

        # Reglas dinámicas (Triggers)
        rules = await conn.fetch("SELECT * FROM tb_config_emails WHERE modulo = 'COMERCIAL'")
        
        FIELD_MAPPING = {
            "Tecnología": "id_tecnologia",
            "Tipo Solicitud": "id_tipo_solicitud",
            "Estatus": "id_estatus_global",
            "Cliente": "cliente_nombre"
        }

        for rule in rules:
            field_admin = rule['trigger_field']
            val_trigger = str(rule['trigger_value']).strip().upper()
            db_key = FIELD_MAPPING.get(field_admin, field_admin)
            val_actual = row.get(db_key)
            
            match = False
            if field_admin == "Cliente":
                if val_trigger in str(val_actual or "").upper(): match = True
            else:
                if str(val_actual or "") == val_trigger: match = True
            
            if match:
                email = rule['email_to_add']
                if rule['type'] == 'TO':
                    if email not in fixed_to: fixed_to.append(email)
                else:
                    if email not in fixed_cc: fixed_cc.append(email)

        # Formatear Objetivos BESS
        # Parsear BESS objetivos para email si existen
        bess_objetivos_str = ""
        if row.get('id_tecnologia'):
            # Buscar si hay BESS asociado
            bess_row = await conn.fetchrow(
                "SELECT uso_sistema_json FROM tb_detalles_bess WHERE id_oportunidad = $1", 
                row['id_oportunidad']
            )
            if bess_row and bess_row['uso_sistema_json']:
                try:
                    raw_usos = bess_row['uso_sistema_json']
                    loaded = json.loads(raw_usos) if isinstance(raw_usos, str) else raw_usos
                    if isinstance(loaded, list):
                        bess_objetivos_str = ", ".join(loaded)
                except Exception:
                    pass

        return {
            "op": row,
            "sitios": sitios_rows,
            "fixed_to": fixed_to,
            "fixed_cc": fixed_cc,
            "bess_objetivos_str": bess_objetivos_str,
            "has_multisitio_file": (row['cantidad_sitios'] or 0) > 1,
            "editable": row.get('es_seguimiento', False) and (row['cantidad_sitios'] or 0) > 1,
            "is_followup": row.get('es_seguimiento', False)
        }

    async def get_email_recipients_context(
        self,
        conn,
        recipients_str: str,
        fixed_to: List[str],
        fixed_cc: List[str],
        extra_cc: str
    ) -> dict:
        """
        Consolida lógica de destinatarios TO, CC, BCC incluyendo reglas de negocio.
        Encapsula consultas a tb_email_defaults.
        
        Args:
            conn: Conexión a BD
            recipients_str: String de destinatarios manuales (chips)
            fixed_to: Lista de destinatarios TO fijos (desde reglas)
            fixed_cc: Lista de destinatarios CC fijos (desde reglas)
            extra_cc: String de CC adicionales manuales
            
        Returns:
            Dict con listas TO, CC, BCC limpias y deduplicadas
        """
        # Procesar TO
        final_to = set()
        
        # Chips manuales
        if recipients_str:
            raw_list = recipients_str.replace(",", ";").split(";")
            for email in raw_list:
                if email.strip():
                    final_to.add(email.strip())
        
        # Fixed rules
        for email in fixed_to:
            if email.strip():
                final_to.add(email.strip())
        
        # Procesar CC
        final_cc = set()
        
        # Fixed rules
        for email in fixed_cc:
            if email.strip():
                final_cc.add(email.strip())
        
        # Manual input
        if extra_cc:
            raw_cc = extra_cc.replace(",", ";").split(";")
            for email in raw_cc:
                if email.strip():
                    final_cc.add(email.strip())
        
        # Procesar BCC (desde tb_email_defaults)
        final_bcc = set()
        defaults = await conn.fetchrow("SELECT * FROM tb_email_defaults ORDER BY id LIMIT 1")
        if defaults:
            def_cco = (defaults['default_cco'] or "").upper().replace(",", ";").split(";")
            for email in def_cco:
                if email.strip():
                    final_bcc.add(email.strip())
        
        return {
            "to": list(final_to),
            "cc": list(final_cc),
            "bcc": list(final_bcc)
        }

    async def preview_site_upload(self, conn, file_contents: bytes, id_oportunidad: UUID) -> dict:
        """
        Procesa el Excel en memoria y valida estructura/cantidad.
        Retorna dict con datos para previsualización o raises HTTPException.
        """
        # Validar Cantidad Esperada en BD
        expected_qty = await conn.fetchval(
            "SELECT cantidad_sitios FROM tb_oportunidades WHERE id_oportunidad = $1", 
            id_oportunidad
        )
        if expected_qty is None:
            raise HTTPException(status_code=404, detail="Oportunidad no encontrada")

        # Leer Excel
        try:
            wb = load_workbook(filename=io.BytesIO(file_contents), data_only=True)
            ws = wb.active
            headers = [str(cell.value).strip().upper() for cell in ws[1] if cell.value]
            
            full_data_list = []
            preview_rows = []
            
            for row in ws.iter_rows(min_row=2, values_only=True):
                row_data = dict(zip(headers, row))
                if not any(row_data.values()): continue
                
                clean_data = {k: (v if v is not None else "") for k, v in row_data.items()}
                preview_rows.append(list(clean_data.values()))
                full_data_list.append(clean_data)
                
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error leyendo Excel: {str(e)}")

        # Validaciones de Negocio
        cols_req = ["NOMBRE", "DIRECCION"]
        if not all(col in headers for col in cols_req):
            missing = ", ".join([c for c in cols_req if c not in headers])
            raise HTTPException(status_code=400, detail=f"Faltan columnas: {missing}")

        # Validar consistencia
        if len(full_data_list) != expected_qty:
            raise HTTPException(status_code=400, detail=f"Cantidad incorrecta. Esperados: {expected_qty}, Encontrados: {len(full_data_list)}")

        return {
            "columns": headers,
            "preview_rows": preview_rows,
            "total_rows": len(full_data_list),
            "json_data": json.dumps(full_data_list, default=str)
        }

    async def confirm_site_upload(self, conn, id_oportunidad: UUID, json_data: str) -> int:
        """Deserializa JSON, valida y realiza INSERT masivo ATÓMICO."""
        try:
            raw_data = json.loads(json_data)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="JSON corrupto")

        records = []
        # Preparar datos en memoria primero
        for item in raw_data:
            try:
                # Usar Schema Pydantic para validación
                sitio = SitioImportacion(**item)
                records.append((
                    uuid4(), id_oportunidad, sitio.nombre_sitio, sitio.direccion,
                    sitio.tipo_tarifa, sitio.google_maps_link, sitio.numero_servicio, sitio.comentarios
                ))
            except Exception as e:
                logger.warning(f"Saltando fila inválida: {e}")
                continue

        # Obtener id_tipo_solicitud de la oportunidad padre
        id_tipo_solicitud = await conn.fetchval("SELECT id_tipo_solicitud FROM tb_oportunidades WHERE id_oportunidad = $1", id_oportunidad)
        
        # Ejecutar Bloque Atómico
        # Si algo falla aquí, Postgres hace rollback automático del DELETE
        async with conn.transaction():
            # Limpiar anteriores
            await conn.execute("DELETE FROM tb_sitios_oportunidad WHERE id_oportunidad = $1", id_oportunidad)
            
            if records:
                q = """INSERT INTO tb_sitios_oportunidad (
                            id_sitio, id_oportunidad, nombre_sitio, direccion, tipo_tarifa, 
                            google_maps_link, numero_servicio, comentarios, id_estatus_global, id_tipo_solicitud
                       ) 
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 1, $9)"""
                
                # Adjuntar id_tipo_solicitud a cada tupla
                records_with_type = [r + (id_tipo_solicitud,) for r in records]
                await conn.executemany(q, records_with_type)
        
        return len(records)

    async def delete_sitio(self, conn, id_sitio: UUID):
        """Elimina un sitio específico."""
        await conn.execute("DELETE FROM tb_sitios_oportunidad WHERE id_sitio = $1", id_sitio)

    # --- MÉTODOS DE LIMPIEZA ---

    async def get_sitios_simple(self, conn, id_oportunidad: UUID) -> List[dict]:
        """Obtiene lista simple de sitios para la UI (Partial)."""
        rows = await conn.fetch(
            "SELECT * FROM tb_sitios_oportunidad WHERE id_oportunidad = $1 ORDER BY id_sitio",
            id_oportunidad
        )
        return [dict(r) for r in rows]

    async def auto_crear_sitio_unico(self, conn, id_oportunidad: UUID, nombre: str, direccion: str, link: Optional[str], id_tipo_solicitud: int):
        """Crea automáticamente el registro de sitio para flujos de un solo sitio."""
        try:
            await conn.execute("""
                INSERT INTO tb_sitios_oportunidad (id_sitio, id_oportunidad, nombre_sitio, direccion, google_maps_link, id_estatus_global, id_tipo_solicitud)
                VALUES ($1, $2, $3, $4, $5, 1, $6)
            """, uuid4(), id_oportunidad, nombre, direccion, link, id_tipo_solicitud)
        except Exception as e:
            logger.error(f"Error auto-creando sitio único: {e}")

    async def marcar_extraordinaria_enviada(self, conn, id_oportunidad: UUID):
        """Marca una solicitud extraordinaria como 'enviada' sin mandar correo real."""
        await conn.execute("""
            UPDATE tb_oportunidades SET email_enviado = TRUE WHERE id_oportunidad = $1
        """, id_oportunidad)

    async def cancelar_oportunidad(self, conn, id_oportunidad: UUID):
        """
        Elimina de forma transaccional una oportunidad y TODAS sus dependencias.
        Orden crítico: eliminar hijos antes que padre para evitar FK violations.
        """
        try:
            async with conn.transaction():
                # Eliminar TODAS las tablas hijas (en orden de dependencias)
                await conn.execute("DELETE FROM tb_comentarios_workflow WHERE id_oportunidad = $1", id_oportunidad)
                await conn.execute("DELETE FROM tb_notificaciones WHERE id_oportunidad = $1", id_oportunidad)
                await conn.execute("DELETE FROM tb_documentos_attachments WHERE id_oportunidad = $1", id_oportunidad)
                await conn.execute("DELETE FROM tb_levantamientos WHERE id_oportunidad = $1", id_oportunidad)
                await conn.execute("DELETE FROM tb_detalles_bess WHERE id_oportunidad = $1", id_oportunidad)
                await conn.execute("DELETE FROM tb_sitios_oportunidad WHERE id_oportunidad = $1", id_oportunidad)
                
                # Finalmente eliminar la oportunidad padre
                await conn.execute("DELETE FROM tb_oportunidades WHERE id_oportunidad = $1", id_oportunidad)
                
        except asyncpg.ForeignKeyViolationError:
            # Solo debería fallar si hay proyectos/compras (dependencias externas críticas)
            logger.warning(f"Intento de eliminar oportunidad {id_oportunidad} con dependencias críticas.")
            raise HTTPException(
                status_code=409,
                detail="No se puede eliminar: La oportunidad ya tiene Proyectos o Registros de Compra asociados."
            )

    # Helper para inyección de dependencias
    # --- MÉTODO DE NOTIFICACIÓN ---
    async def enviar_notificacion_extraordinaria(self, conn, ms_auth, token: str, id_oportunidad: UUID, base_url: str, user_email: str):
        """
        Envía notificación automática para solicitudes extraordinarias.
        Busca reglas configuradas con trigger EVENTO=EXTRAORDINARIA.
        
        Args:
            conn: Conexión a base de datos
            ms_auth: Instancia de MicrosoftAuth
            token: Access token de Graph API
            id_oportunidad: UUID de la oportunidad
            base_url: URL base de la aplicación
            user_email: Email del usuario que crea la solicitud (para from_email)
        """
        try:
            # Buscar reglas de destinatarios usando la constante
            reglas = await conn.fetch("""
                SELECT email_to_add, type 
                FROM tb_config_emails 
                WHERE modulo = 'COMERCIAL' 
                AND trigger_field = 'EVENTO' 
                AND trigger_value = $1
            """, EVENTO_EXTRAORDINARIA)
            
            if not reglas:
                logger.info(f"No hay reglas de notificación configuradas para evento {EVENTO_EXTRAORDINARIA}. Omitiendo correo.")
                return

            # Obtener datos de la oportunidad para el template
            op_data = await conn.fetchrow("""
                SELECT 
                    o.op_id_estandar, o.id_interno_simulacion, o.cliente_nombre, o.nombre_proyecto, o.solicitado_por,
                    to_char(o.fecha_solicitud AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City', 'DD/MM/YYYY HH24:MI') as fecha_solicitud,
                    t.nombre as tecnologia_nombre
                FROM tb_oportunidades o
                LEFT JOIN tb_cat_tecnologias t ON o.id_tecnologia = t.id
                WHERE o.id_oportunidad = $1
            """, id_oportunidad)

            if not op_data:
                return

            # Preparar destinatarios
            recipients = [r['email_to_add'] for r in reglas if r['type'] == 'TO']
            cc_recipients = [r['email_to_add'] for r in reglas if r['type'] == 'CC']
            
            # LOG DETALLADO para diagnóstico
            logger.info(f"EXTRAORDINARIA {op_data['op_id_estandar']}: Destinatarios TO: {recipients}")
            logger.info(f"EXTRAORDINARIA {op_data['op_id_estandar']}: Destinatarios CC: {cc_recipients}")
            logger.info(f"EXTRAORDINARIA {op_data['op_id_estandar']}: FROM (usuario): {user_email}")
            
            # Renderizar Template
            templates = Jinja2Templates(directory="templates")
            template = templates.get_template("comercial/emails/notification_extraordinaria.html")
            html_body = template.render({
                "op": op_data,
                "dashboard_url": f"{base_url}/comercial/ui"
            })

            # Enviar Correo
            subject = f"Nueva Solicitud Extraordinaria: {op_data['op_id_estandar']} - {op_data['cliente_nombre']}"
            
            logger.info(f"Enviando correo extraordinario con asunto: {subject}")
            
            success, msg = ms_auth.send_email_with_attachments(
                access_token=token,
                from_email=user_email,  # CRÍTICO: Agregar from_email
                subject=subject,
                body=html_body,
                recipients=recipients,
                cc_recipients=cc_recipients,
                importance="high"
            )

            if success:
                logger.info(f"Notificación extraordinaria enviada para {op_data['op_id_estandar']}")
            else:
                logger.error(f"Error enviando notificación extraordinaria: {msg}")

        except Exception as e:
            logger.error(f"Excepción en notificación extraordinaria: {e}")

    async def buscar_clientes(self, conn, query: str) -> List[dict]:
        """
        Búsqueda inteligente de clientes por nombre fiscal.
        Args:
            conn: Conexión BD
            query: Texto a buscar (case insensitive)
        Returns:
            List[dict]: [{id, nombre_fiscal}, ...] lim 10
        """
        if not query or len(query.strip()) < 2:
            return []
            
        # Normalizar query para búsqueda ILIKE segura
        search_term = f"%{query.strip()}%"
        
        rows = await conn.fetch("""
            SELECT id, nombre_fiscal 
            FROM tb_clientes 
            WHERE nombre_fiscal ILIKE $1 
            ORDER BY nombre_fiscal 
            LIMIT 10
        """, search_term)
        
        return [{"id": str(r["id"]), "nombre_fiscal": r["nombre_fiscal"]} for r in rows]

def get_comercial_service():
    return ComercialService()