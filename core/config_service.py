from dataclasses import dataclass
from typing import Dict, Optional, Any
import asyncpg

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
    
    _cache_umbrales: Dict[str, UmbralesKPI] = {}
    
    @classmethod
    async def get_umbrales_kpi(
        cls, 
        conn: asyncpg.Connection,
        tipo_kpi: str = "kpi_interno",
        departamento: str = "SIMULACION"
    ) -> UmbralesKPI:
        """
        Obtiene umbrales activos para un tipo de KPI.
        Usa cache para evitar queries repetidas.
        """
        cache_key = f"{departamento}_{tipo_kpi}"
        
        # Verificar cache
        if cache_key in cls._cache_umbrales:
            return cls._cache_umbrales[cache_key]
        
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
                    color_excelente="emerald", # Verde Tailwind
                    color_bueno="yellow",      # Amarillo Tailwind
                    color_critico="red"        # Rojo Tailwind
                )
            else:
                umbrales = UmbralesKPI(
                    tipo_kpi=row['tipo_kpi'],
                    umbral_excelente=float(row['umbral_excelente']),
                    umbral_bueno=float(row['umbral_bueno']),
                    color_excelente=row['color_excelente'],
                    color_bueno=row['color_bueno'],
                    color_critico=row['color_critico']
                )
            
            # Guardar en cache
            cls._cache_umbrales[cache_key] = umbrales
            
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
                color_excelente="emerald",
                color_bueno="yellow",
                color_critico="red"
            )
    
    @classmethod
    def invalidar_cache(cls):
        """Invalida el cache de umbrales (llamar al guardar cambios)"""
        cls._cache_umbrales.clear()
        cls._cache_global.clear()

    _cache_global: Dict[str, Any] = {}

    @classmethod
    async def get_global_config(cls, conn: asyncpg.Connection, clave: str, default: Any, tipo: type = str) -> Any:
        """
        Obtiene un valor de configuración global con cast de tipo.
        Usa cache simple.
        """
        if clave in cls._cache_global:
            return cls._cache_global[clave]

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

            cls._cache_global[clave] = val_typed
            return val_typed
        except Exception:
            return default
