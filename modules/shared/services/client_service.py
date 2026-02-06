import difflib
import re
from uuid import UUID, uuid4
import logging
from typing import Optional, Tuple

logger = logging.getLogger("SharedServices")

class ClientService:
    """
    Servicio compartido para gestión de Clientes.
    Maneja la búsqueda y creación (Upsert) de clientes.
    """

    # Sufijos comunes a ignorar para la comparación
    SUFFIXES = [
        r"\bS\.?A\.? DE C\.?V\.?\b",
        r"\bS\.?A\.?\b",
        r"\bS\.? DE R\.?L\.?\b",
        r"\bLTD\b",
        r"\bINC\b",
        r"\bLLC\b",
        r"\bS\.?A\.?P\.?I\.?\b",
        r"\bS\.?C\.?\b",
        r"\bA\.?C\.?\b",
        r"\bCORP\b",
        r"\bS\.?A\.?S\.?\b",
        r"\bGROUP\b",
        r"\bS\.?A\.?B\.?\b",
        r"\bDE C\.?V\.?\b"
    ]

    @classmethod
    def _normalize_name(cls, name: str) -> str:
        """
        Normaliza el nombre para comparación:
        1. Mayúsculas
        2. Elimina sufijos legales (SA de CV, etc)
        3. Elimina caracteres especiales y espacios extra
        """
        clean = name.upper()
        
        # Eliminar sufijos
        for suffix in cls.SUFFIXES:
            clean = re.sub(suffix, "", clean, flags=re.IGNORECASE)
            
        # Eliminar caracteres no alfanuméricos (excepto espacios)
        clean = re.sub(r"[^A-Z0-9\s]", "", clean)
        
        return clean.strip()

    @staticmethod
    def _sanitize_for_storage(name: str) -> str:
        """
        Limpia errores de dedo comunes al INICIO y FINAL del nombre.
        No toca el contenido interno.
        
        Elimina: Espacios, puntos, pipes, comas, guiones, guiones bajos, asteriscos.
        Ejemplos:
          "EMPRESA|" -> "EMPRESA"
          ".EMPRESA." -> "EMPRESA"
          "| EMPRESA |" -> "EMPRESA"
          "S.A. DE C.V." -> "S.A. DE C.V"
        """
        if not name:
            return ""
            
        # Regex para caracteres "sucios" en los extremos
        # \s = whitespace
        # \. = dot
        # \| = pipe
        # , = comma
        # \- = dash
        # _ = underscore
        # \* = asterisk
        dirty_pattern = r"^[\s\.|,_*-]+|[\s\.|,_*-]+$"
        
        return re.sub(dirty_pattern, "", name).strip().upper()

    @staticmethod
    def _calculate_similarity(a: str, b: str) -> float:
        """Retorna ratio de similitud entre 0 y 1"""
        return difflib.SequenceMatcher(None, a, b).ratio()

    @staticmethod
    async def get_or_create_client_by_name(
        conn, 
        nombre_cliente: str, 
        mb_id: Optional[UUID] = None,
        initial_id_interno: Optional[str] = None
    ) -> Tuple[UUID, str, Optional[str]]:
        """
        Busca un cliente por nombre o ID con coincidencia INTELIGENTE.
        
        Strategy:
        1. ID Explícito (si user seleccionó dropdown)
        2. Coincidencia Exacta (ILIKE) -> Rápido
        3. Coincidencia Fuzzy (Normalización + Difflib) -> Lento pero seguro
        
        Args:
            conn: Conexión a BD
            nombre_cliente: Nombre ingresado
            mb_id: ID opcional seleccionado
            initial_id_interno: Si es nuevo, este será su ID congelado maestra.
            
        Returns:
            Tuple: (id, nombre_fiscal, id_interno_simulacion)
        """

        # Limpieza inicial de "errores de dedo"
        final_nombre = ClientService._sanitize_for_storage(nombre_cliente)
        
        # 1. ID Explícito
        if mb_id:
            # Recuperar id_interno si existe
            row = await conn.fetchrow("SELECT nombre_fiscal, id_interno_simulacion FROM tb_clientes WHERE id = $1", mb_id)
            if row:
                return mb_id, row['nombre_fiscal'], row['id_interno_simulacion']
            return mb_id, final_nombre, None
        
        # 2. Búsqueda Exacta (Rápida)
        existing_client = await conn.fetchrow(
            "SELECT id, nombre_fiscal, id_interno_simulacion FROM tb_clientes WHERE nombre_fiscal ILIKE $1", 
            final_nombre
        )
        if existing_client:
            return existing_client['id'], existing_client['nombre_fiscal'], existing_client['id_interno_simulacion']
            
        # 3. Búsqueda Fuzzy (Smart Match)
        if len(final_nombre) > 3:
            all_clients = await conn.fetch("SELECT id, nombre_fiscal, id_interno_simulacion FROM tb_clientes")
            
            normalized_input = ClientService._normalize_name(final_nombre)
            best_match = None
            highest_score = 0.0
            
            THRESHOLD = 0.88 
            
            for row in all_clients:
                db_name = row['nombre_fiscal']
                normalized_db = ClientService._normalize_name(db_name)
                
                if normalized_input == normalized_db and len(normalized_input) > 2:
                    score = 1.0
                else:
                    score = ClientService._calculate_similarity(normalized_input, normalized_db)
                
                if score > highest_score:
                    highest_score = score
                    best_match = row
                    
            if best_match and highest_score >= THRESHOLD:
                logger.info(f"SMART MATCH: '{final_nombre}' -> '{best_match['nombre_fiscal']}' (Score: {highest_score:.2f})")
                return best_match['id'], best_match['nombre_fiscal'], best_match['id_interno_simulacion']
        
        # 4. Si no hubo match, crear nuevo
        new_id = uuid4()
        
        # Si nos pasaron un ID interno inicial (porque es el primer proyecto), lo guardamos.
        # Si no, se guarda NULL (y se asignará después si fuera necesario, aunque el flujo principal lo asigna altiro)
        await conn.execute(
            "INSERT INTO tb_clientes (id, nombre_fiscal, id_interno_simulacion) VALUES ($1, $2, $3)",
            new_id, final_nombre, initial_id_interno
        )
        logger.info(f"Nuevo cliente creado: {final_nombre} ({new_id}) | ID Maestro: {initial_id_interno}")
        return new_id, final_nombre, initial_id_interno
