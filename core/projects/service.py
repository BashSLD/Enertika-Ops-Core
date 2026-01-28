# Archivo: core/projects/service.py
"""
Servicio compartido para gestión de Proyectos Gate.
Usado por: Compras, Construcción, y futuros módulos.
"""

from uuid import UUID, uuid4
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import HTTPException
import logging

logger = logging.getLogger("ProjectsService")


class ProjectsGateService:
    """
    Lógica de negocio para creación y gestión de proyectos Gate.
    
    Un proyecto Gate se crea cuando una oportunidad es GANADA y
    necesita pasar a las fases de ejecución (Ingeniería, Construcción, O&M).
    """
    
    # ID del estatus "Ganada" en tb_cat_estatus_global
    ESTATUS_GANADA_ID = 7
    
    async def get_oportunidades_ganadas(self, conn) -> List[Dict[str, Any]]:
        """
        Obtiene oportunidades marcadas como GANADAS que aún no tienen proyecto.
        
        Returns:
            Lista de oportunidades disponibles para crear proyecto
        """
        query = """
            SELECT 
                o.id_oportunidad,
                o.op_id_estandar,
                o.nombre_proyecto,
                o.cliente_nombre,
                o.id_tecnologia,
                t.nombre as tecnologia_nombre,
                o.fecha_solicitud
            FROM tb_oportunidades o
            LEFT JOIN tb_cat_tecnologias t ON o.id_tecnologia = t.id
            WHERE o.id_estatus_global = $1
            AND NOT EXISTS (
                SELECT 1 FROM tb_proyectos_gate p 
                WHERE p.id_oportunidad = o.id_oportunidad
            )
            ORDER BY o.fecha_solicitud DESC
        """
        
        rows = await conn.fetch(query, self.ESTATUS_GANADA_ID)
        return [dict(r) for r in rows]
    
    async def get_tecnologias(self, conn) -> List[Dict[str, Any]]:
        """
        Obtiene catálogo de tecnologías activas.
        """
        rows = await conn.fetch("""
            SELECT id, nombre 
            FROM tb_cat_tecnologias 
            WHERE activo = true 
            ORDER BY id
        """)
        return [dict(r) for r in rows]
    
    async def validar_consecutivo_unico(self, conn, consecutivo: int) -> bool:
        """
        Valida que el consecutivo no exista en proyectos.
        
        Returns:
            True si está disponible, False si ya existe
        """
        exists = await conn.fetchval("""
            SELECT 1 FROM tb_proyectos_gate 
            WHERE consecutivo = $1
        """, consecutivo)
        
        return not exists
    
    async def generar_proyecto_id_estandar(
        self,
        prefijo: str,
        consecutivo: int,
        tecnologia_nombre: str,
        nombre_corto: str
    ) -> str:
        """
        Genera el ID estándar del proyecto.
        
        Formato: MX-50055-FV Santa Teresa
        """
        return f"{prefijo}-{consecutivo}-{tecnologia_nombre} {nombre_corto}".strip()
    
    async def crear_proyecto(
        self,
        conn,
        id_oportunidad: UUID,
        prefijo: str,
        consecutivo: int,
        id_tecnologia: int,
        nombre_corto: str,
        user_id: UUID
    ) -> Dict[str, Any]:
        """
        Crea un nuevo proyecto Gate.
        
        Args:
            conn: Conexión a BD
            id_oportunidad: UUID de la oportunidad ganada
            prefijo: Prefijo del proyecto (ej: MX)
            consecutivo: Número consecutivo único
            id_tecnologia: ID de la tecnología
            nombre_corto: Nombre descriptivo corto
            user_id: Usuario que crea el proyecto
            
        Returns:
            Proyecto creado con todos sus datos
            
        Raises:
            HTTPException: Si hay errores de validación
        """
        # 1. Validar que la oportunidad existe y está ganada
        oportunidad = await conn.fetchrow("""
            SELECT id_oportunidad, id_estatus_global, nombre_proyecto, cliente_nombre
            FROM tb_oportunidades 
            WHERE id_oportunidad = $1
        """, id_oportunidad)
        
        if not oportunidad:
            raise HTTPException(status_code=404, detail="Oportunidad no encontrada")
        
        if oportunidad['id_estatus_global'] != self.ESTATUS_GANADA_ID:
            raise HTTPException(
                status_code=400, 
                detail="Solo se pueden crear proyectos de oportunidades GANADAS"
            )
        
        # 2. Validar que no exista proyecto para esta oportunidad
        existe_proyecto = await conn.fetchval("""
            SELECT 1 FROM tb_proyectos_gate 
            WHERE id_oportunidad = $1
        """, id_oportunidad)
        
        if existe_proyecto:
            raise HTTPException(
                status_code=400, 
                detail="Ya existe un proyecto para esta oportunidad"
            )
        
        # 3. Validar consecutivo único
        if not await self.validar_consecutivo_unico(conn, consecutivo):
            raise HTTPException(
                status_code=400, 
                detail=f"El consecutivo {consecutivo} ya está en uso"
            )
        
        # 4. Obtener nombre de tecnología
        tecnologia_nombre = await conn.fetchval("""
            SELECT nombre FROM tb_cat_tecnologias WHERE id = $1
        """, id_tecnologia)
        
        if not tecnologia_nombre:
            raise HTTPException(status_code=400, detail="Tecnología no válida")
        
        # 5. Generar ID estándar
        proyecto_id_estandar = await self.generar_proyecto_id_estandar(
            prefijo, consecutivo, tecnologia_nombre, nombre_corto
        )
        
        # 6. Insertar proyecto
        new_id = uuid4()
        
        await conn.execute("""
            INSERT INTO tb_proyectos_gate (
                id_proyecto,
                id_oportunidad,
                proyecto_id_estandar,
                status_fase,
                aprobacion_direccion,
                fecha_aprobacion,
                prefijo,
                consecutivo,
                id_tecnologia,
                nombre_corto,
                created_at,
                created_by_id
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
            )
        """,
            new_id,
            id_oportunidad,
            proyecto_id_estandar,
            'INGENIERIA',  # Fase inicial
            True,          # Aprobado por defecto (creación manual implica aprobación)
            datetime.now(),
            prefijo,
            consecutivo,
            id_tecnologia,
            nombre_corto,
            datetime.now(),
            user_id
        )
        
        logger.info(f"Proyecto creado: {proyecto_id_estandar} por usuario {user_id}")
        
        # 7. Retornar proyecto creado
        return await self.get_proyecto_by_id(conn, new_id)
    
    async def get_proyecto_by_id(self, conn, id_proyecto: UUID) -> Optional[Dict[str, Any]]:
        """
        Obtiene un proyecto por su ID con datos relacionados.
        """
        row = await conn.fetchrow("""
            SELECT 
                p.*,
                t.nombre as tecnologia_nombre,
                o.nombre_proyecto as oportunidad_nombre,
                o.cliente_nombre,
                o.op_id_estandar,
                u.nombre as creado_por_nombre
            FROM tb_proyectos_gate p
            LEFT JOIN tb_cat_tecnologias t ON p.id_tecnologia = t.id
            LEFT JOIN tb_oportunidades o ON p.id_oportunidad = o.id_oportunidad
            LEFT JOIN tb_usuarios u ON p.created_by_id = u.id_usuario
            WHERE p.id_proyecto = $1
        """, id_proyecto)
        
        return dict(row) if row else None
    
    async def get_proyectos_list(
        self, 
        conn,
        solo_aprobados: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Obtiene lista de proyectos para dropdowns.
        
        Args:
            solo_aprobados: Si True, solo retorna proyectos con aprobacion_direccion=True
        """
        query = """
            SELECT 
                p.id_proyecto,
                p.proyecto_id_estandar as nombre,
                p.consecutivo,
                t.nombre as tecnologia
            FROM tb_proyectos_gate p
            LEFT JOIN tb_cat_tecnologias t ON p.id_tecnologia = t.id
            WHERE 1=1
        """
        
        if solo_aprobados:
            query += " AND p.aprobacion_direccion = true"
        
        query += " ORDER BY p.consecutivo DESC"
        
        rows = await conn.fetch(query)
        return [dict(r) for r in rows]
    
    async def get_siguiente_consecutivo_sugerido(self, conn) -> int:
        """
        Sugiere el siguiente consecutivo disponible.
        Útil para ayudar al usuario.
        
        Returns:
            Siguiente número disponible (máximo + 1)
        """
        max_consecutivo = await conn.fetchval("""
            SELECT COALESCE(MAX(consecutivo), 0) FROM tb_proyectos_gate
        """)
        
        return max_consecutivo + 1


def get_projects_gate_service():
    """Dependency injection para FastAPI."""
    return ProjectsGateService()
