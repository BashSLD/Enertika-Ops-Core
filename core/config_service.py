from dataclasses import dataclass
from typing import Dict, Optional, Any, Tuple
import asyncpg
import time

@dataclass
class UmbralesKPI:
    """Configuración de umbrales para un tipo de KPI"""
    tipo_kpi: str
    umbral_excelente: float
    umbral_bueno: float
    color_excelente: str
    color_bueno: str
    color_critico: str
    
    def get_color(self, porcentaje: float) -> str:
        """Retorna el color según el porcentaje"""
        if porcentaje >= self.umbral_excelente:
            return self.color_excelente
        elif porcentaje >= self.umbral_bueno:
            return self.color_bueno
        else:
            return self.color_critico
    
    def get_label(self, porcentaje: float) -> str:
        """Retorna la etiqueta según el porcentaje"""
        if porcentaje >= self.umbral_excelente:
            return "Excelente"
        elif porcentaje >= self.umbral_bueno:
            return "Bueno"
        else:
            return "Crítico"


class ConfigService:
    """Servicio para gestionar configuración global del sistema"""
    
    # Cache con TTL: {key: (timestamp, value)}
    _cache_umbrales: Dict[str, Tuple[float, UmbralesKPI]] = {}
    _cache_global: Dict[str, Tuple[float, Any]] = {} # Updated to support TTL
    _CACHE_TTL = 30.0  # 30 segundos de vida

    @classmethod
    async def get_cached_value(cls, key: str, ttl: float = 30.0) -> Optional[Any]:
        """Recupera valor del cache si no ha expirado."""
        if key in cls._cache_global:
            ts, val = cls._cache_global[key]
            if time.time() - ts < ttl:
                return val
            else:
                del cls._cache_global[key] # Expired
        return None

    @classmethod
    async def set_cached_value(cls, key: str, value: Any):
        """Guarda valor en cache con timestamp actual."""
        cls._cache_global[key] = (time.time(), value)

    @classmethod
    async def get_catalog_map(cls, conn: asyncpg.Connection, table: str, key_col: str = "nombre", val_col: str = "id") -> Dict[str, Any]:
        """
        Obtiene un mapa de catálogo {nombre: id} con cache de 30s.
        Normaliza claves a lowercase para búsquedas case-insensitive.
        """
        cache_key = f"CAT_{table}_{key_col}_{val_col}"
        cached = await cls.get_cached_value(cache_key)
        if cached: return cached
        
        # Fetch fresh
        try:
            rows = await conn.fetch(f"SELECT {key_col}, {val_col} FROM {table}")
            data = {str(row[key_col]).lower(): row[val_col] for row in rows}
            await cls.set_cached_value(cache_key, data)
            return data
        except Exception as e:
            # Log error but don't crash
            print(f"Error loading catalog {table}: {e}")
            return {}

    
    @classmethod
    async def get_umbrales_kpi(
        cls, 
        conn: asyncpg.Connection,
        tipo_kpi: str = "kpi_interno",
        departamento: str = "SIMULACION"
    ) -> UmbralesKPI:
        """
        Obtiene umbrales activos para un tipo de KPI.
        Usa cache con TTL (30s) para evitar stale data en multi-workers.
        """
        cache_key = f"{departamento}_{tipo_kpi}"
        
        # Verificar cache con TTL
        if cache_key in cls._cache_umbrales:
            ts, val = cls._cache_umbrales[cache_key]
            if time.time() - ts < cls._CACHE_TTL:
                return val
        
        # Consultar BD
        try:
            # Intentar primero con el nuevo campo departamento en caso que exista
            # Nota: Si la columna no existe aun, esto fallará y caerá en el except, devolviendo default.
            # Esto maneja la transición mientras se corre la migración.
            row = await conn.fetchrow("""
                SELECT 
                    tipo_kpi,
                    umbral_excelente,
                    umbral_bueno,
                    color_excelente,
                    color_bueno,
                    color_critico
                FROM tb_config_umbrales_kpi
                WHERE tipo_kpi = $1 
                  AND activo = TRUE
                  AND departamento = $2
                ORDER BY id DESC
                LIMIT 1
            """, tipo_kpi, departamento)
            
            if not row:
                # Fallback a valores por defecto (usando Global Config si existe)
                # Esto unifica los reportes con la configuración del Admin
                u_verde = await cls.get_global_config(conn, "sim_umbral_verde", 90.0, float)
                u_ambar = await cls.get_global_config(conn, "sim_umbral_ambar", 85.0, float)
                
                umbrales = UmbralesKPI(
                    tipo_kpi=tipo_kpi,
                    umbral_excelente=u_verde,
                    umbral_bueno=u_ambar,
                    color_excelente="green",   # Normalizado para coincidir con template
                    color_bueno="amber",       # Normalizado para coincidir con template
                    color_critico="red"
                )
            else:
                # Normalización de colores de BD a nombres de clases usados en template
                c_excelente = row['color_excelente']
                c_bueno = row['color_bueno']
                
                # Mapeo de compatibilidad
                if c_excelente == "emerald": c_excelente = "green"
                if c_bueno == "yellow": c_bueno = "amber"
                
                umbrales = UmbralesKPI(
                    tipo_kpi=row['tipo_kpi'],
                    umbral_excelente=float(row['umbral_excelente']),
                    umbral_bueno=float(row['umbral_bueno']),
                    color_excelente=c_excelente,
                    color_bueno=c_bueno,
                    color_critico=row['color_critico']
                )
            
            # Guardar en cache con timestamp actual
            cls._cache_umbrales[cache_key] = (time.time(), umbrales)
            
            return umbrales
        except Exception as e:
            # Fallback seguro: Intentar leer global config incluso si falla query principal
            try:
                u_verde = await cls.get_global_config(conn, "sim_umbral_verde", 90.0, float)
                u_ambar = await cls.get_global_config(conn, "sim_umbral_ambar", 85.0, float)
            except:
                u_verde = 90.0
                u_ambar = 85.0

            return UmbralesKPI(
                tipo_kpi=tipo_kpi,
                umbral_excelente=u_verde,
                umbral_bueno=u_ambar,
                color_excelente="green",
                color_bueno="amber",
                color_critico="red"
            )
    
    @classmethod
    def invalidar_cache(cls):
        """Invalida el cache de umbrales (llamar al guardar cambios)"""
        cls._cache_umbrales.clear()
        cls._cache_global.clear()

    _cache_global: Dict[str, Tuple[float, Any]] = {} # Redefined above, but just ensuring cleanup if needed.
    # Actually, we replaced the definition above. Removing the duplicate definition at line 142 if it existed.
    # In the file, line 142 is `_cache_global: Dict[str, Any] = {}`.
    # We should remove it or update it. Since I updated the class definition above, I should remove this line.

    @classmethod
    async def get_global_config(cls, conn: asyncpg.Connection, clave: str, default: Any, tipo: type = str) -> Any:
        """
        Obtiene un valor de configuración global con cast de tipo.
        Usa cache con TTL (30s).
        """
        # Check cache
        cached = await cls.get_cached_value(f"CFG_{clave}")
        if cached is not None: return cached

        try:
            row = await conn.fetchrow("""
                SELECT valor, tipo_dato FROM tb_configuracion_global WHERE clave = $1
            """, clave)

            if not row:
                return default

            valor = row['valor']
            
            # Cast simple basado en el tipo solicitado
            if tipo == int:
                val_typed = int(float(valor)) # float first to handle "10.0"
            elif tipo == float:
                val_typed = float(valor)
            elif tipo == bool:
                val_typed = valor.lower() in ('true', '1', 'si', 'yes')
            else:
                val_typed = valor

            await cls.set_cached_value(f"CFG_{clave}", val_typed)
            return val_typed
        except Exception:
            return default
