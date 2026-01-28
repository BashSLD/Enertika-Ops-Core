"""
SCRIPT DE MIGRACIÓN: EXCEL/CSV → PostgreSQL (tb_oportunidades)
=================================================================

Características:
- Maneja catálogos por TEXTO (busca ID automáticamente)
- Crea clientes automáticamente si no existen
- Mapea usuarios por nombre
- Calcula parent_id automáticamente (versiones)
- Recalcula KPIs si están vacíos
- Timezone México para fechas
- Genera campos automáticos (UUID, op_id_estandar, titulo_proyecto)

Uso:
    python migrate_oportunidades.py muestra.xlsx

Requisitos:
    pip install pandas openpyxl asyncpg python-dotenv
"""

import pandas as pd
import asyncpg
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from uuid import uuid4
import sys
import os
from typing import Optional, Dict, List
import re
from dotenv import load_dotenv
from pathlib import Path

# Cargar variables de entorno desde .env (buscar en directorio padre si el script está en scripts/)
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)


def limpiar_nombre_cliente(nombre: str) -> str:
    """
    Limpia y normaliza nombre de cliente.
    
    - Quita puntos y caracteres especiales
    - Elimina espacios extra
    - Convierte a mayúsculas
    
    Ejemplo: "S.A. de  C.V." → "SA DE CV"
    """
    if not nombre:
        return ""
    # Quitar puntos y caracteres especiales
    nombre = nombre.replace('.', '').replace(',', '')
    # Quitar espacios extra
    nombre = ' '.join(nombre.split())
    return nombre.upper()


def safe_str(value, default: str = None) -> Optional[str]:
    """
    Convierte valor a string, manejando NaN y None.
    
    Args:
        value: Valor del Excel (puede ser str, float, NaN, None)
        default: Valor por defecto si es nulo
        
    Returns:
        String limpio o default si es nulo
    """
    if value is None or pd.isna(value):
        return default
    return str(value).strip() if value else default


def safe_bool(value, default: bool = False) -> bool:
    """
    Convierte valor de Excel a booleano.
    
    Maneja: TRUE/FALSE (texto), True/False (bool), 1/0, SI/NO
    
    Args:
        value: Valor del Excel
        default: Valor por defecto si es nulo
        
    Returns:
        Boolean
    """
    if value is None or pd.isna(value):
        return default
    
    # Si ya es booleano
    if isinstance(value, bool):
        return value
    
    # Si es número
    if isinstance(value, (int, float)):
        return bool(value)
    
    # Si es texto
    if isinstance(value, str):
        return value.strip().upper() in ('TRUE', 'SI', 'SÍ', '1', 'YES', 'VERDADERO')
    
    return default


# Configuración
ZONA_MEXICO = ZoneInfo("America/Mexico_City")

# Extraer host de SUPABASE_URL (quitar https:// o http://)
supabase_url = os.getenv("SUPABASE_URL", "")
db_host = supabase_url.replace("https://", "").replace("http://", "").strip()

DB_CONFIG = {
    "host": db_host if db_host else os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "database": os.getenv("DB_NAME", "postgres"),  # Supabase usa "postgres" por defecto
    "user": os.getenv("DB_USER", "postgres").strip(),
    "password": os.getenv("DB_PASSWORD", "").strip()
}


class MigracionService:
    """Servicio para migrar oportunidades desde Excel a PostgreSQL"""
    
    def __init__(self, conn):
        self.conn = conn
        self.cache_catalogos = {}
        self.cache_usuarios = {}
        self.cache_clientes = {}
        self.user_id_sistema = None  # Usuario que ejecuta la migración
    
    async def initialize(self):
        """Cargar catálogos y cachés en memoria"""
        print("📚 Cargando catálogos...")
        
        # Cargar tecnologías (solo tiene: id, activo, nombre)
        rows = await self.conn.fetch("SELECT id, UPPER(nombre) as nombre FROM tb_cat_tecnologias WHERE activo = true")
        self.cache_catalogos['tecnologias'] = {
            row['nombre']: row['id'] for row in rows
        }
        # También mapear por nombre como "código" para compatibilidad
        self.cache_catalogos['tecnologias_codigo'] = self.cache_catalogos['tecnologias']
        
        # Cargar tipos de solicitud (tiene: id, nombre, codigo_interno)
        rows = await self.conn.fetch("SELECT id, UPPER(nombre) as nombre, UPPER(codigo_interno) as codigo FROM tb_cat_tipos_solicitud WHERE activo = true")
        self.cache_catalogos['tipos_solicitud'] = {
            row['nombre']: row['id'] for row in rows
        }
        self.cache_catalogos['tipos_solicitud_codigo'] = {
            row['codigo']: row['id'] for row in rows if row['codigo']
        }
        
        # Cargar estatus
        rows = await self.conn.fetch("SELECT id, UPPER(nombre) as nombre FROM tb_cat_estatus_global WHERE activo = true")
        self.cache_catalogos['estatus'] = {
            row['nombre']: row['id'] for row in rows
        }
        
        # Cargar motivos de cierre (usa 'motivo' en lugar de 'nombre')
        rows = await self.conn.fetch("SELECT id, UPPER(motivo) as nombre FROM tb_cat_motivos_cierre WHERE activo = true")
        self.cache_catalogos['motivos_cierre'] = {
            row['nombre']: row['id'] for row in rows
        }
        
        # Cargar usuarios
        rows = await self.conn.fetch("SELECT id_usuario, nombre, UPPER(nombre) as nombre_upper FROM tb_usuarios WHERE is_active = true")
        for row in rows:
            # Almacenar por nombre completo
            self.cache_usuarios[row['nombre_upper']] = row['id_usuario']
            # Almacenar por nombre sin acentos (para fuzzy matching)
            nombre_limpio = self._limpiar_nombre(row['nombre'])
            self.cache_usuarios[nombre_limpio] = row['id_usuario']
        
        # Cargar clientes existentes (usa 'id' y 'nombre_fiscal')
        rows = await self.conn.fetch("SELECT id, UPPER(nombre_fiscal) as nombre FROM tb_clientes")
        for row in rows:
            self.cache_clientes[row['nombre']] = row['id']
        
        # Usuario del sistema (para creado_por_id)
        # Buscar usuario "Sistema" o usar el primero disponible
        sistema_user = await self.conn.fetchrow(
            "SELECT id_usuario FROM tb_usuarios WHERE LOWER(nombre) LIKE '%sistema%' OR LOWER(nombre) LIKE '%migration%' LIMIT 1"
        )
        if sistema_user:
            self.user_id_sistema = sistema_user['id_usuario']
        else:
            # Usar primer usuario activo
            first_user = await self.conn.fetchrow("SELECT id_usuario FROM tb_usuarios WHERE is_active = true LIMIT 1")
            self.user_id_sistema = first_user['id_usuario']
        
        print(f"✅ Catálogos cargados:")
        print(f"   - Tecnologías: {len(self.cache_catalogos['tecnologias'])}")
        print(f"   - Tipos Solicitud: {len(self.cache_catalogos['tipos_solicitud'])}")
        print(f"   - Estatus: {len(self.cache_catalogos['estatus'])}")
        print(f"   - Usuarios: {len(self.cache_usuarios)}")
        print(f"   - Clientes: {len(self.cache_clientes)}")
    
    def _limpiar_nombre(self, nombre: str) -> str:
        """Limpia nombre para fuzzy matching (sin acentos, mayúsculas, espacios extra)"""
        if not nombre:
            return ""
        # Remover acentos
        replacements = {
            'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U',
            'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
            'Ñ': 'N', 'ñ': 'n'
        }
        for old, new in replacements.items():
            nombre = nombre.replace(old, new)
        # Uppercase y quitar espacios extra
        return ' '.join(nombre.upper().split())
    
    def buscar_catalogo_id(self, tabla: str, valor: str) -> Optional[int]:
        """
        Busca ID en catálogo por nombre o código.
        
        Estrategia:
        1. Buscar por código exacto (ej: "FV" → id_tecnologia)
        2. Buscar por nombre exacto (ej: "COTIZACION" → id_tipo_solicitud)
        3. Buscar por similitud (para typos)
        """
        if not valor or pd.isna(valor):
            return None
        
        valor_upper = str(valor).strip().upper()
        
        # Intento 1: Buscar en cache por código
        if f"{tabla}_codigo" in self.cache_catalogos:
            if valor_upper in self.cache_catalogos[f"{tabla}_codigo"]:
                return self.cache_catalogos[f"{tabla}_codigo"][valor_upper]
        
        # Intento 2: Buscar en cache por nombre
        if tabla in self.cache_catalogos:
            if valor_upper in self.cache_catalogos[tabla]:
                return self.cache_catalogos[tabla][valor_upper]
        
        # Intento 3: Fuzzy matching (para typos comunes)
        if tabla in self.cache_catalogos:
            for nombre_cat, id_cat in self.cache_catalogos[tabla].items():
                if valor_upper in nombre_cat or nombre_cat in valor_upper:
                    print(f"⚠️  Fuzzy match: '{valor}' → '{nombre_cat}'")
                    return id_cat
        
        print(f"❌ No se encontró '{valor}' en catálogo '{tabla}'")
        return None
    
    def buscar_usuario_id(self, nombre_usuario: str) -> Optional[str]:
        """Busca UUID de usuario por nombre (con fuzzy matching)"""
        if not nombre_usuario or pd.isna(nombre_usuario):
            return None
        
        nombre_limpio = self._limpiar_nombre(nombre_usuario)
        
        if nombre_limpio in self.cache_usuarios:
            return self.cache_usuarios[nombre_limpio]
        
        # Fuzzy: buscar por apellido
        apellidos = nombre_limpio.split()
        for apellido in apellidos:
            if len(apellido) > 3:  # Evitar palabras cortas
                for nombre_cat, id_cat in self.cache_usuarios.items():
                    if apellido in nombre_cat:
                        print(f"⚠️  Usuario fuzzy match: '{nombre_usuario}' → '{nombre_cat}'")
                        return id_cat
        
        print(f"❌ Usuario no encontrado: '{nombre_usuario}'")
        return self.user_id_sistema  # Fallback a usuario sistema
    
    async def get_or_create_cliente(self, nombre_cliente: str) -> str:
        """Obtiene o crea un cliente. Retorna UUID."""
        if not nombre_cliente or pd.isna(nombre_cliente):
            return None
        
        # Limpiar nombre: quitar puntos, comas, espacios extra y convertir a mayúsculas
        nombre_limpio = limpiar_nombre_cliente(nombre_cliente)
        
        # Verificar si existe en cache
        if nombre_limpio in self.cache_clientes:
            return self.cache_clientes[nombre_limpio]
        
        # Buscar en BD (por si fue creado en otra sesión) - usa 'id' y 'nombre_fiscal'
        row = await self.conn.fetchrow(
            "SELECT id FROM tb_clientes WHERE UPPER(REPLACE(REPLACE(nombre_fiscal, '.', ''), ',', '')) = $1",
            nombre_limpio
        )
        
        if row:
            self.cache_clientes[nombre_limpio] = row['id']
            return row['id']
        
        # Crear nuevo cliente con nombre limpio
        nuevo_id = uuid4()
        await self.conn.execute(
            """
            INSERT INTO tb_clientes (id, nombre_fiscal)
            VALUES ($1, $2)
            """,
            nuevo_id,
            nombre_limpio  # Guardar nombre normalizado
        )
        
        self.cache_clientes[nombre_limpio] = nuevo_id
        print(f"✨ Cliente creado: '{nombre_cliente}' → '{nombre_limpio}' ({nuevo_id})")
        return nuevo_id
    
    def generar_op_id_estandar(self, fecha_solicitud: datetime, cliente_nombre: str, contador: int) -> str:
        """
        Genera OP ID estándar.
        
        Formato: OP-YYMMDD-CLIENTE-NNN
        Ejemplo: OP-250116-STREGIS-001
        """
        fecha_str = fecha_solicitud.strftime("%y%m%d")
        cliente_corto = "".join(c for c in cliente_nombre.upper() if c.isalnum())[:8]
        return f"OP-{fecha_str}-{cliente_corto}-{contador:03d}"
    
    def generar_titulo_proyecto(self, cliente: str, nombre_proyecto: str, tipo_solicitud: str) -> str:
        """
        Genera título automático.
        
        Formato: [TIPO] Cliente - Proyecto
        Ejemplo: [COTIZACIÓN] ST REGIS - COMISARIATO
        """
        tipo_corto = tipo_solicitud.upper()[:15]
        return f"[{tipo_corto}] {cliente} - {nombre_proyecto}"
    
    def calcular_kpis(
        self, 
        fecha_entrega: Optional[datetime],
        deadline_calculado: Optional[datetime],
        deadline_negociado: Optional[datetime]
    ) -> tuple:
        """
        Calcula KPIs Duales si fecha_entrega existe.
        
        Returns:
            (kpi_status_interno, kpi_status_compromiso)
        """
        if not fecha_entrega or not deadline_calculado:
            return None, None
        
        # KPI Interno: vs deadline calculado
        kpi_interno = "Entrega a tiempo" if fecha_entrega <= deadline_calculado else "Entrega tarde"
        
        # KPI Compromiso: vs deadline negociado o calculado
        deadline_compromiso = deadline_negociado if deadline_negociado else deadline_calculado
        kpi_compromiso = "Entrega a tiempo" if fecha_entrega <= deadline_compromiso else "Entrega tarde"
        
        return kpi_interno, kpi_compromiso
    
    def convertir_fecha_mexico(self, fecha) -> Optional[datetime]:
        """Convierte fecha de Excel a datetime con timezone México"""
        if pd.isna(fecha):
            return None
        
        if isinstance(fecha, str):
            # Parsear string (formato: DD/MM/YYYY o YYYY-MM-DD)
            try:
                fecha = pd.to_datetime(fecha, dayfirst=True)
            except:
                return None
        
        # Asegurar timezone México
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=ZONA_MEXICO)
        else:
            fecha = fecha.astimezone(ZONA_MEXICO)
        
        return fecha
    
    async def detectar_parent_id(self, row: pd.Series, oportunidades_existentes: List[Dict]) -> Optional[str]:
        """
        Detecta si esta oportunidad es una versión (parent_id).
        
        Criterios:
        1. Mismo cliente + mismo proyecto
        2. Fecha solicitud POSTERIOR a otra oportunidad
        3. Es tipo "ACTUALIZACIÓN DE OFERTA"
        
        Returns:
            UUID del padre o None
        """
        if pd.isna(row.get('cliente_nombre')) or pd.isna(row.get('nombre_proyecto')):
            return None
        
        cliente = row['cliente_nombre'].strip().upper()
        proyecto = row['nombre_proyecto'].strip().upper()
        fecha_actual = self.convertir_fecha_mexico(row['fecha_solicitud'])
        tipo = str(row.get('id_tipo_solicitud', '')).upper()
        
        if not fecha_actual:
            return None
        
        # Buscar oportunidad padre
        for opp in oportunidades_existentes:
            if (opp['cliente_nombre'].upper() == cliente and 
                opp['nombre_proyecto'].upper() == proyecto and
                opp['fecha_solicitud'] < fecha_actual and
                'ACTUALIZACION' in tipo):
                
                print(f"🔗 Parent detectado: {opp['op_id_estandar']} → versión actual")
                return opp['id_oportunidad']
        
        return None
    
    async def migrar_fila(self, row: pd.Series, index: int, oportunidades_existentes: List[Dict]) -> bool:
        """Migra una fila del Excel a tb_oportunidades"""
        
        try:
            # ============================================
            # 1. CAMPOS AUTOMÁTICOS
            # ============================================
            id_oportunidad = uuid4()
            fecha_solicitud = self.convertir_fecha_mexico(row['fecha_solicitud'])
            
            if not fecha_solicitud:
                print(f"❌ Fila {index}: fecha_solicitud inválida")
                return False
            
            op_id_estandar = self.generar_op_id_estandar(
                fecha_solicitud, 
                row.get('cliente_nombre', 'CLIENTE'),
                index + 1
            )
            
            titulo_proyecto = self.generar_titulo_proyecto(
                row.get('cliente_nombre', ''),
                row.get('nombre_proyecto', ''),
                row.get('id_tipo_solicitud', 'GENERAL')
            )
            
            # ============================================
            # 2. CATÁLOGOS (TEXTO → ID)
            # ============================================
            id_tecnologia = self.buscar_catalogo_id('tecnologias', row.get('id_tecnologia'))
            id_tipo_solicitud = self.buscar_catalogo_id('tipos_solicitud', row.get('id_tipo_solicitud'))
            id_estatus_global = self.buscar_catalogo_id('estatus', row.get('id_estatus_global'))
            id_motivo_cierre = self.buscar_catalogo_id('motivos_cierre', row.get('Motivo Cancelacion'))
            
            if not all([id_tecnologia, id_tipo_solicitud, id_estatus_global]):
                print(f"❌ Fila {index}: Faltan catálogos obligatorios")
                return False
            
            # ============================================
            # 3. RELACIONES (USUARIOS, CLIENTES)
            # ============================================
            cliente_id = await self.get_or_create_cliente(row.get('cliente_nombre'))
            responsable_simulacion_id = self.buscar_usuario_id(row.get('responsable_simulacion_id'))
            solicitado_por_id = self.buscar_usuario_id(row.get('solicitado_por'))
            creado_por_id = self.user_id_sistema
            
            # ============================================
            # 4. FECHAS CON TIMEZONE
            # ============================================
            deadline_calculado = self.convertir_fecha_mexico(row.get('deadline_calculado'))
            deadline_negociado = self.convertir_fecha_mexico(row.get('deadline_negociado'))
            fecha_entrega = self.convertir_fecha_mexico(row.get('fecha_entrega_simulacion'))
            fecha_creacion = fecha_solicitud  # Usar misma fecha
            
            # ============================================
            # 5. KPIs (RECALCULAR SI ESTÁN VACÍOS)
            # ============================================
            kpi_interno_excel = row.get('kpi_status_sla_interno')
            kpi_compromiso_excel = row.get('kpi_status_compromiso')
            
            if pd.isna(kpi_interno_excel) or pd.isna(kpi_compromiso_excel):
                kpi_interno, kpi_compromiso = self.calcular_kpis(
                    fecha_entrega,
                    deadline_calculado,
                    deadline_negociado
                )
            else:
                kpi_interno = kpi_interno_excel
                kpi_compromiso = kpi_compromiso_excel
            
            # ============================================
            # 6. VERSIONES (PARENT_ID)
            # ============================================
            parent_id = await self.detectar_parent_id(row, oportunidades_existentes)
            
            # ============================================
            # 7. CAMPOS BOOLEANOS (usar safe_bool para manejar TRUE/FALSE texto)
            # ============================================
            es_fuera_horario = safe_bool(row.get('es_fuera_horario'), False)
            es_licitacion = safe_bool(row.get('es_licitacion'), False)
            email_enviado = True  # Migración marca como enviado
            
            # ============================================
            # 8. OTROS CAMPOS (usar safe_str para manejar NaN)
            # ============================================
            prioridad = safe_str(row.get('prioridad'), 'Normal')
            clasificacion = safe_str(row.get('clasificacion_solicitud'), 'NORMAL')
            canal_venta = safe_str(row.get('canal_venta'), 'ENERTIKA')
            
            # ============================================
            # 9. INSERT
            # ============================================
            query = """
                INSERT INTO tb_oportunidades (
                    id_oportunidad,
                    op_id_estandar,
                    titulo_proyecto,
                    nombre_proyecto,
                    cliente_nombre,
                    cliente_id,
                    creado_por_id,
                    responsable_simulacion_id,
                    solicitado_por,
                    canal_venta,
                    id_tecnologia,
                    id_tipo_solicitud,
                    id_estatus_global,
                    id_motivo_cierre,
                    fecha_solicitud,
                    fecha_creacion,
                    deadline_calculado,
                    deadline_negociado,
                    fecha_entrega_simulacion,
                    kpi_status_sla_interno,
                    kpi_status_compromiso,
                    parent_id,
                    es_fuera_horario,
                    es_licitacion,
                    email_enviado,
                    prioridad,
                    clasificacion_solicitud,
                    cantidad_sitios
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
                    $21, $22, $23, $24, $25, $26, $27, $28
            )
            """
            
            await self.conn.execute(
                query,
                id_oportunidad,
                op_id_estandar,
                titulo_proyecto,
                safe_str(row.get('nombre_proyecto')),
                safe_str(row.get('cliente_nombre')),
                cliente_id,
                creado_por_id,
                responsable_simulacion_id,
                safe_str(row.get('solicitado_por')),
                canal_venta,
                id_tecnologia,
                id_tipo_solicitud,
                id_estatus_global,
                id_motivo_cierre,
                fecha_solicitud,
                fecha_creacion,
                deadline_calculado,
                deadline_negociado,
                fecha_entrega,
                kpi_interno,
                kpi_compromiso,
                parent_id,
                es_fuera_horario,
                es_licitacion,
                email_enviado,
                prioridad,
                clasificacion,
                1  # cantidad_sitios = 1 (según tu indicación)
            )
            
            # ============================================
            # 10. CREAR SITIO AUTOMÁTICAMENTE (Unisitio)
            # ============================================
            # El sistema requiere un registro en tb_sitios_oportunidad
            # para calcular KPIs correctamente
            id_sitio = uuid4()
            nombre_sitio = safe_str(row.get('nombre_proyecto'), 'Sitio Principal')
            direccion_sitio = safe_str(row.get('direccion_obra'), 'Sin dirección')
            
            query_sitio = """
                INSERT INTO tb_sitios_oportunidad (
                    id_sitio,
                    id_oportunidad,
                    nombre_sitio,
                    direccion,
                    id_estatus_global,
                    id_tipo_solicitud,
                    fecha_cierre,
                    kpi_status_interno,
                    kpi_status_compromiso
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9
                )
            """
            
            await self.conn.execute(
                query_sitio,
                id_sitio,
                id_oportunidad,
                nombre_sitio,
                direccion_sitio,
                id_estatus_global,  # Mismo estatus que el padre
                id_tipo_solicitud,  # Mismo tipo que el padre
                fecha_entrega,      # fecha_cierre = fecha_entrega_simulacion
                kpi_interno,        # Heredar KPI interno
                kpi_compromiso      # Heredar KPI compromiso
            )
            
            # Agregar a lista de existentes (para detectar parent_id en siguientes filas)
            oportunidades_existentes.append({
                'id_oportunidad': id_oportunidad,
                'op_id_estandar': op_id_estandar,
                'cliente_nombre': row.get('cliente_nombre', ''),
                'nombre_proyecto': row.get('nombre_proyecto', ''),
                'fecha_solicitud': fecha_solicitud
            })
            
            print(f"✅ Fila {index}: {op_id_estandar} migrada exitosamente")
            return True
            
        except Exception as e:
            print(f"❌ Error en fila {index}: {str(e)}")
            import traceback
            traceback.print_exc()
            return False


async def main(archivo_excel: str):
    """Función principal de migración"""
    
    print(f"""
╔═══════════════════════════════════════════════════════════════╗
║        MIGRACIÓN DE OPORTUNIDADES DESDE EXCEL                 ║
║        Archivo: {archivo_excel:40s}  ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    # 1. Leer Excel
    print("📖 Leyendo archivo Excel...")
    df = pd.read_excel(archivo_excel)
    print(f"✅ {len(df)} filas encontradas")
    
    # 2. Conectar a BD
    print("\n🔌 Conectando a base de datos...")
    conn = await asyncpg.connect(**DB_CONFIG)
    print("✅ Conectado")
    
    try:
        # 3. Inicializar servicio
        service = MigracionService(conn)
        await service.initialize()
        
        # 4. Migrar filas
        print(f"\n🚀 Iniciando migración de {len(df)} oportunidades...\n")
        
        exitosos = 0
        fallidos = 0
        oportunidades_existentes = []
        
        for index, row in df.iterrows():
            success = await service.migrar_fila(row, index, oportunidades_existentes)
            if success:
                exitosos += 1
            else:
                fallidos += 1
        
        # 5. Resumen
        print(f"""
╔═══════════════════════════════════════════════════════════════╗
║                    RESUMEN DE MIGRACIÓN                       ║
╠═══════════════════════════════════════════════════════════════╣
║  Total filas:          {len(df):4d}                                  ║
║  ✅ Exitosas:          {exitosos:4d}                                  ║
║  ❌ Fallidas:          {fallidos:4d}                                  ║
║  Clientes creados:     {len(service.cache_clientes):4d}                   ║
╚═══════════════════════════════════════════════════════════════╝
        """)
        
    finally:
        await conn.close()
        print("\n🔒 Conexión cerrada")


if __name__ == "__main__":
    # Si se pasa argumento, usarlo; si no, buscar archivo.xlsx en scripts/
    if len(sys.argv) >= 2:
        archivo = sys.argv[1]
    else:
        # Buscar archivo.xlsx en la misma carpeta del script
        script_dir = Path(__file__).parent
        archivo = script_dir / "archivo.xlsx"
        if not archivo.exists():
            print("Uso: python migrate_oportunidades.py <archivo.xlsx>")
            print("  O coloca 'archivo.xlsx' en la carpeta scripts/")
            sys.exit(1)
        archivo = str(archivo)
    
    if not os.path.exists(archivo):
        print(f"❌ Archivo no encontrado: {archivo}")
        sys.exit(1)
    
    print(f"📁 Usando archivo: {archivo}")
    asyncio.run(main(archivo))
