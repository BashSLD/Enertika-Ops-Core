# Archivo: core/materials/matcher.py
"""
Matcher automatico: vincula conceptos de facturas XML (tb_materiales_historial)
con items del catalogo interno (tb_cat_materiales), por niveles de confianza
CLAVE_SAT -> MEMORIA -> TEXTO.

Adaptado del matcher factura<->BOM (core/bom/compras_service.py::match_conceptos_a_items),
pero vive aqui (no en core/bom) porque la direccion de import establecida en el
repo es core/bom -> core/materials, nunca al reves.

Ver _Planes_Activos/._BOOM/39-plan-vinculacion-catalogo-interno-xml.md.
"""

import re
from typing import Optional


def _normalizar(texto: Optional[str]) -> str:
    if not texto:
        return ""
    return re.sub(r'\s+', ' ', str(texto).strip().upper())


def _score_texto(desc_concepto: str, desc_interno: str) -> float:
    if not desc_concepto or not desc_interno:
        return 0.0
    palabras_concepto = set(desc_concepto.split())
    palabras_interno = set(desc_interno.split())
    comunes = palabras_concepto & palabras_interno
    token_score = len(comunes) / max(len(palabras_concepto), 1)
    len_ratio = min(len(desc_concepto), len(desc_interno)) / max(
        len(desc_concepto), len(desc_interno), 1
    )
    return (token_score * 0.7) + (len_ratio * 0.3)


def match_conceptos_a_internos(
    conceptos: list, catalogo_interno: list, memoria_map: Optional[dict] = None
) -> dict:
    """
    Empareja conceptos de factura XML (ya filtrados a producto) con items del
    catalogo interno, por niveles de confianza.

    Estrategia (en orden de prioridad):
    1. ALTA - CLAVE_SAT: concepto.clave_prod_serv == interno.clave_prod_serv,
       solo si el match es unico (clave ambigua entre varios internos no se
       auto-aplica). Bloqueado en la practica hasta que el catalogo interno
       tenga clave_prod_serv poblada -- se activa solo via backfill organico
       (ver aplicar_matches_interno_alta en service.py).
    2. ALTA - MEMORIA: memoria_map[clave_prod_serv] (id_material_interno
       aprendido de vinculos HUMANO/ALTA previos para ese proveedor+clave).
    3. BAJA - TEXTO: similitud difusa descripcion_proveedor vs
       descripcion_norm (mismo criterio de token+longitud que el matcher
       factura-BOM, umbral 0.4).
    4. Sin match -> None.

    Args:
        catalogo_interno: lista de dicts {id, clave_prod_serv, descripcion_norm}
            de items activos (una sola query por factura, no por concepto).
        memoria_map: dict opcional {clave_prod_serv: id_material_interno}.

    Returns:
        dict {indice_concepto: {'id_material_interno': UUID, 'confianza': str,
        'origen': str, 'clave_prod_serv': str|None} | None}.
        confianza: 'ALTA'|'BAJA'; origen: 'CLAVE_SAT'|'MEMORIA'|'TEXTO'.
    """
    memoria_map = memoria_map or {}
    match_map = {}

    # Indice por clave SAT construido una sola vez (O(M)) en vez de re-escanear
    # todo el catalogo por cada concepto (O(N*M)) solo para el chequeo de unicidad.
    por_clave_sat: dict = {}
    for it in catalogo_interno:
        clave_it = (it.get('clave_prod_serv') or '').strip()
        if clave_it:
            por_clave_sat.setdefault(clave_it, []).append(it)

    for idx, concepto in enumerate(conceptos):
        desc_concepto = _normalizar(concepto.get('descripcion', ''))
        clave_concepto = (concepto.get('clave_prod_serv') or '').strip()

        # 1. ALTA - CLAVE_SAT (solo si el match es unico entre los internos)
        if clave_concepto and len(clave_concepto) >= 6:
            candidatos = por_clave_sat.get(clave_concepto, [])
            if len(candidatos) == 1:
                match_map[idx] = {
                    'id_material_interno': candidatos[0]['id'],
                    'confianza': 'ALTA', 'origen': 'CLAVE_SAT',
                    'clave_prod_serv': clave_concepto,
                }
                continue

        # 2. ALTA - memoria proveedor-producto
        material_recordado = memoria_map.get(clave_concepto) if clave_concepto else None
        if material_recordado:
            match_map[idx] = {
                'id_material_interno': material_recordado,
                'confianza': 'ALTA', 'origen': 'MEMORIA',
                'clave_prod_serv': clave_concepto,
            }
            continue

        # 3. BAJA - similitud de texto (fallback)
        best_item, best_score = None, 0.0
        for it in catalogo_interno:
            score = _score_texto(desc_concepto, _normalizar(it.get('descripcion_norm', '')))
            if score > best_score:
                best_score, best_item = score, it

        if best_item and best_score >= 0.4:
            match_map[idx] = {
                'id_material_interno': best_item['id'],
                'confianza': 'BAJA', 'origen': 'TEXTO',
                'clave_prod_serv': clave_concepto or None,
            }
        else:
            match_map[idx] = None

    return match_map
