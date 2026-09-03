"""
BOM – Compras: cotizaciones, RFQ, autorizaciones Fase D, conciliacion y match.
Mixin incluido en BomService; los metodos usan self.db y self.get_bom.
"""

import asyncio
import logging
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import UUID
from typing import Optional, List

import asyncpg

from core.bom.pdf_cotizacion_extractor import extraer_costos_cotizacion
from core.bom.schemas import EstatusBOM, EstatusCotizacionAprobacion
from core.config import settings
from core.timezone import today_mx

logger = logging.getLogger("BOM.Service")

ESTATUS_COTIZABLE = {EstatusBOM.APROBADO_CONST, EstatusBOM.EN_REVISION_FINAL, EstatusBOM.APROBADO_FINAL}
ESTATUS_ITEM_CERRADO_COMPRA = {"NO_ADQUIRIDO", "REEMPLAZADO", "CERRADO"}
# Bloqueo de adenda (Ingenieria/Construccion editando un item ya comprometido en
# compra) -- unico call site: service.py _validar_item_base_para_adenda. Incluye
# PARCIALMENTE_COTIZADO: ya hay dinero/proveedor comprometido en la parte
# cubierta, aunque el remanente si puede volver a cotizarse (ver constante
# ESTATUS_COMPRA_CERRADO_COTIZACION, usada para esa elegibilidad).
ESTATUS_COMPRA_BLOQUEA_ADENDA = {
    "COTIZADO", "AUTORIZADO", "PAGADO", "FACTURADO", "PARCIALMENTE_COTIZADO",
}
# Estatus terminales de compra donde ya no puede quedar remanente real por
# cotizar (a diferencia de PARCIALMENTE_COTIZADO/COTIZADO, que si pueden tener
# cantidad_pendiente > 0 mientras la cotizacion que los cubre no se autoriza).
# Derivado de ESTATUS_COMPRA_BLOQUEA_ADENDA (nunca a mano) para que un futuro
# estatus nuevo no pueda quedar agregado a uno de los dos sets y no al otro.
ESTATUS_COMPRA_CERRADO_COTIZACION = ESTATUS_COMPRA_BLOQUEA_ADENDA - {"PARCIALMENTE_COTIZADO"}
ESTATUS_ADENDA_APROBADA = "APROBADA"


def cantidad_pendiente_item(item: dict) -> Decimal:
    """Cantidad del item BOM aun sin cubrir por ninguna cotizacion adjudicada."""
    cantidad = Decimal(str(item.get("cantidad") or 0))
    cubierta = Decimal(str(item.get("cantidad_cubierta") or 0))
    return cantidad - cubierta


def item_disponible_cotizacion(item: dict) -> bool:
    """True si el item BOM todavia puede entrar a una cotizacion o RFQ nueva."""
    estatus_compra = item.get("estatus_compra", "SIN_COTIZAR")
    estatus_ejecucion = item.get("estatus_ejecucion")
    return (
        estatus_compra not in ESTATUS_COMPRA_CERRADO_COTIZACION
        and cantidad_pendiente_item(item) > 0
        and estatus_ejecucion not in ESTATUS_ITEM_CERRADO_COMPRA
    )


class BomComprasServiceMixin:
    """Cotizaciones, RFQ, autorizaciones Fase D, conciliacion y match."""

    @staticmethod
    def _es_cabeza_cotizable(bom: dict) -> bool:
        """Mantiene Compras en la oficial mientras otra version esta en retrabajo."""
        estado = EstatusBOM(bom["estatus"])
        if estado == EstatusBOM.APROBADO_FINAL:
            return bool(bom.get("es_cabeza_oficial"))
        return bool(bom.get("es_cabeza_trabajo", True))

    @staticmethod
    def _validar_content_type_pdf(file) -> None:
        content_type = (getattr(file, "content_type", None) or "").split(";")[0].strip().lower()
        if content_type != "application/pdf":
            raise ValueError("El archivo debe ser un PDF")

    async def _relock_bom_cotizable_o_raise(
        self, conn, id_bom: UUID, bom_esperado: dict,
        bom_lock_version_esperado: Optional[int] = None,
    ) -> dict:
        """Re-bloquea el BOM dentro de la transaccion y valida que sigue en el
        mismo estado que se vio en el fetch temprano (cierra la ventana de
        carrera entre validar y escribir). Compartido por crear_cotizacion y
        editar_cotizacion."""
        bom_bloqueado = await self.db.get_bom_for_update(conn, id_bom)
        if (
            not bom_bloqueado
            or bom_bloqueado["estatus"] != bom_esperado["estatus"]
            or not self._es_cabeza_cotizable(bom_bloqueado)
            or (
                bom_lock_version_esperado is not None
                and bom_bloqueado["lock_version"] != bom_lock_version_esperado
            )
        ):
            raise ValueError("El BOM cambio desde que abriste la cotizacion; recarga el paquete")
        return bom_bloqueado

    async def resolver_bom_cotizable(self, conn, id_paquete: UUID) -> dict:
        """Resuelve, a partir del paquete, el BOM relevante para Compras hoy: la
        cabeza de trabajo, salvo que haya retrabajo en curso y la nueva version
        aun no llegue a un estatus cotizable (BORRADOR/EN_REVISION_*), en cuyo
        caso Compras se queda en la cabeza oficial — misma regla que valida
        `_es_cabeza_cotizable`."""
        bom = await self.get_bom_cabeza_trabajo(conn, id_paquete)
        if EstatusBOM(bom["estatus"]) not in ESTATUS_COTIZABLE:
            oficial = await self.get_bom_cabeza_oficial(conn, id_paquete)
            if oficial:
                return oficial
        return bom

    @staticmethod
    def _raise_si_items(items: list, mensaje: str) -> None:
        if not items:
            return
        nombres = ", ".join(
            (i.get("descripcion") or "Item sin descripcion")[:60] for i in items[:3]
        )
        raise ValueError(f"{mensaje}: {nombres}")

    def _raise_si_excede_pendiente(
        self, items_con_cantidad: list, items_map: dict, mensaje: str,
    ) -> None:
        """items_con_cantidad: lista de (item_data, cantidad_solicitada: Decimal).
        items_map: dict id_item (str) -> fila de bom_item (con cantidad/cantidad_cubierta).
        Levanta ValueError con `mensaje` si algun item excede su remanente
        pendiente. Compartido por _calcular_items_cotizacion (validacion al
        crear/editar) y seleccionar_cotizacion (revalidacion bajo lock antes
        de adjudicar) -- mismo predicado, dos momentos distintos del flujo."""
        excedidos = [
            items_map[str(it["bom_item_id"])]
            for it, cantidad in items_con_cantidad
            if cantidad > cantidad_pendiente_item(items_map[str(it["bom_item_id"])])
        ]
        self._raise_si_items(excedidos, mensaje)

    async def _validar_items_cotizables(
        self, conn, bom_items: list, accion: str,
        cotizacion_id_excluir: Optional[UUID] = None,
        verificar_cotizacion_activa: bool = True,
    ) -> None:
        """Valida que ningún item esté cerrado, en adenda pendiente, en un estatus
        terminal de compra sin remanente, o con otra cotizacion activa
        compitiendo por el mismo remanente parcial (decision de negocio
        2026-08-27: solo 1 cotizacion BORRADOR/RECIBIDA a la vez por remanente).

        `cotizacion_id_excluir`: la cotizacion que se esta creando/editando/
        adjudicando no debe autobloquearse por sus propios items.

        `verificar_cotizacion_activa=False`: omite la consulta de "otra
        cotizacion activa" -- cada flujo llama a este metodo dos veces (pre-check
        sin lock, luego re-check con lock dentro de la transaccion); esa consulta
        solo es autoritativa en el segundo paso, así que el primero la salta para
        no duplicar el round trip.
        """
        self._raise_si_items(
            [i for i in bom_items if i.get("estatus_ejecucion") in ESTATUS_ITEM_CERRADO_COMPRA],
            f"No se pueden {accion} items cerrados o reemplazados",
        )
        self._raise_si_items(
            [
                i for i in bom_items
                if i.get("creado_en_adenda") and i.get("adenda_estatus") != ESTATUS_ADENDA_APROBADA
            ],
            f"No se pueden {accion} items de adendas pendientes de aprobacion",
        )
        self._raise_si_items(
            [
                i for i in bom_items
                if i.get("estatus_compra") in ESTATUS_COMPRA_CERRADO_COTIZACION
                or cantidad_pendiente_item(i) <= 0
            ],
            f"No se pueden {accion} items ya cotizados, autorizados, pagados o facturados en otra cotizacion",
        )
        parciales = [i for i in bom_items if i.get("estatus_compra") == "PARCIALMENTE_COTIZADO"]
        if parciales and verificar_cotizacion_activa:
            ids_bloqueados = set(await self.db.get_items_con_cotizacion_activa(
                conn, [i["id_item"] for i in parciales], cotizacion_id_excluir,
            ))
            self._raise_si_items(
                [i for i in parciales if i["id_item"] in ids_bloqueados],
                f"No se pueden {accion} items que ya tienen otra cotización pendiente cubriendo su remanente",
            )

    async def _actualizar_estatus_items_cotizacion(
        self, conn, cotizacion_id: UUID, nuevo_estatus: str,
        item_ids: Optional[list] = None,
    ) -> None:
        """Actualiza estatus_compra en lote para los items de una cotización.

        Si `item_ids` no viene, los obtiene de la cotización (round trip extra);
        pasarlo evita re-consultar cuando el caller ya los tiene cargados.
        """
        if item_ids is None:
            items = await self.db.get_items_cotizacion(conn, cotizacion_id)
            item_ids = [i['bom_item_id'] for i in items]
        if item_ids:
            await self._actualizar_estatus_items_por_ids(
                conn, item_ids, nuevo_estatus
            )

    async def _autorizar_items_cotizacion(
        self, conn, cotizacion_id: UUID, item_ids: Optional[list] = None,
    ) -> None:
        """Avanza Fase D: promueve a AUTORIZADO solo los items de la cotizacion
        totalmente cubiertos; el remanente sin cubrir se queda en
        PARCIALMENTE_COTIZADO (ver autorizar_items_cotizacion_por_cobertura) para
        no bloquear una nueva cotizacion sobre ese remanente."""
        if item_ids is None:
            items = await self.db.get_items_cotizacion(conn, cotizacion_id)
            item_ids = [i['bom_item_id'] for i in items]
        if not item_ids:
            return

        async def resolver(bloqueados):
            ids = [b["id_item"] for b in bloqueados]
            return await self.db.autorizar_items_cotizacion_por_cobertura(conn, ids)

        await self._mutar_estatus_compra_items(conn, item_ids, resolver)

    async def _mutar_estatus_compra_items(
        self, conn, item_ids: list[UUID], resolver, updated_by: Optional[UUID] = None,
    ) -> list[dict]:
        """Lock exacto por item + mirror del estatus_compra resultante hacia
        estatus_ejecucion -- mecanismo compartido por
        _actualizar_estatus_items_por_ids (estatus uniforme para todo el lote)
        y _ajustar_cantidad_cubierta_items (estatus derivado por item de su
        propio delta de cantidad_cubierta); ambos solo difieren en como se
        calcula el estatus_compra de cada item.

        `resolver(bloqueados) -> list[dict]`: recibe los items ya bloqueados
        (con ejecucion_lock_version) y debe escribir su estatus_compra en BD,
        devolviendo por cada uno {"id_item", "estatus_compra"} para el mirror.
        """
        ids = sorted(set(item_ids), key=str)
        if not ids:
            return []
        bloqueados = await self.db.lock_items_context_by_ids(conn, ids)
        if len(bloqueados) != len(ids):
            raise ValueError("Uno de los items cambió; recarga el paquete")
        locks_ejecucion = {
            str(item["id_item"]): int(item.get("ejecucion_lock_version") or 0)
            for item in bloqueados
        }
        resultados = await resolver(bloqueados)

        filas = [
            (
                r["id_item"],
                "PENDIENTE" if r["estatus_compra"] == "SIN_COTIZAR" else r["estatus_compra"],
                updated_by,
                locks_ejecucion[str(r["id_item"])],
            )
            for r in resultados
        ]
        logrados = set(await self.db.actualizar_estatus_ejecucion_batch(conn, filas))
        faltantes = {r["id_item"] for r in resultados} - logrados
        if faltantes:
            raise ValueError("La ejecución de un item cambió; recarga el paquete")
        return resultados

    async def _actualizar_estatus_items_por_ids(
        self, conn, item_ids: list[UUID], nuevo_estatus: str,
        updated_by: Optional[UUID] = None,
    ) -> None:
        """Serializa el espejo legacy y la ejecución con el lock exacto de cada ítem."""
        async def resolver(bloqueados):
            ids = [b["id_item"] for b in bloqueados]
            await self.db.actualizar_estatus_compra_items(conn, ids, nuevo_estatus)
            return [{"id_item": i, "estatus_compra": nuevo_estatus} for i in ids]

        await self._mutar_estatus_compra_items(conn, item_ids, resolver, updated_by)

    async def _ajustar_cantidad_cubierta_items(
        self, conn, ajustes: dict, updated_by: Optional[UUID] = None,
    ) -> None:
        """Ajusta cantidad_cubierta por item (delta positivo al adjudicar,
        negativo al liberar) y deriva el estatus_compra resultante por item
        (en vez de uno uniforme para todo el lote).

        `ajustes`: dict {bom_item_id: Decimal(delta)}.
        """
        async def resolver(bloqueados):
            return await self.db.ajustar_cantidad_cubierta_items(
                conn, [(b["id_item"], ajustes[b["id_item"]]) for b in bloqueados]
            )

        await self._mutar_estatus_compra_items(conn, list(ajustes.keys()), resolver, updated_by)

    # ─── COTIZACIONES ────────────────────────────────────────

    async def listar_cotizaciones(self, conn, id_bom: UUID) -> List[dict]:
        cotizaciones = await self.db.get_cotizaciones_by_bom(conn, id_bom)
        if not cotizaciones:
            return cotizaciones

        cot_ids = [cot['id'] for cot in cotizaciones]
        all_cot_items = await self.db.get_items_by_cotizacion_ids(conn, cot_ids)
        cot_items_map: dict = {}
        all_bom_item_ids = []
        for it in all_cot_items:
            key = str(it['cotizacion_id'])
            cot_items_map.setdefault(key, []).append(it)
            all_bom_item_ids.append(it['bom_item_id'])

        bom_items_map = {}
        if all_bom_item_ids:
            bom_items = await self.db.get_items_by_ids(conn, list(set(all_bom_item_ids)))
            bom_items_map = {str(bi['id_item']): bi for bi in bom_items}

        for cot in cotizaciones:
            tiene_sobrecosto = False
            for it in cot_items_map.get(str(cot['id']), []):
                bom_item = bom_items_map.get(str(it['bom_item_id']))
                if bom_item and bom_item.get('precio_unitario') and it.get('precio_unitario'):
                    if Decimal(str(it['precio_unitario'])) > Decimal(str(bom_item['precio_unitario'])):
                        tiene_sobrecosto = True
                        break
            cot['tiene_sobrecosto'] = tiene_sobrecosto
            subtotal = cot.get('subtotal')
            iva = cot.get('iva')
            cot['iva_pct'] = (
                round(float(iva) / float(subtotal) * 100, 2)
                if subtotal and float(subtotal) > 0 and iva is not None
                else 16
            )

        return cotizaciones

    @staticmethod
    def _validar_sobrecosto(items_data: list, bom_items_map: dict, notas: Optional[str]) -> None:
        """Exige justificacion en `notas` si algun item se cotiza por encima del
        precio_unitario estimado en el BOM. Compartido por _calcular_items_cotizacion
        (Fase C, crear/editar cotizacion) y _actualizar_costos_vigencia (gate de
        vigencia, Camino 2 -- 2026-09-02)."""
        sobrecostos = []
        for i in items_data:
            pu = Decimal(str(i.get('precio_unitario') or 0))
            if pu <= 0:
                continue
            bom_item = bom_items_map.get(str(i['bom_item_id']))
            if bom_item and bom_item.get('precio_unitario'):
                precio_bom = Decimal(str(bom_item['precio_unitario']))
                if pu > precio_bom:
                    sobrecostos.append({
                        'item_id': str(i['bom_item_id']),
                        'descripcion': bom_item.get('descripcion', '')[:60],
                        'precio_bom': precio_bom,
                        'precio_cotizado': pu,
                        'diferencia_pct': round((pu - precio_bom) / precio_bom * 100, 1),
                    })
        if sobrecostos and not (notas and notas.strip()):
            items_str = ', '.join(
                f"{s['descripcion']} (+{s['diferencia_pct']}%)"
                for s in sobrecostos[:3]
            )
            raise ValueError(
                f"Se detectaron {len(sobrecostos)} items con precio mayor al estimado: {items_str}. "
                "Debes agregar una justificacion en el campo de notas."
            )

    async def _calcular_items_cotizacion(
        self, conn, id_bom: UUID, items_data: list, moneda: str,
        iva_pct: float, notas: Optional[str],
        subtotal_externo: Optional[float] = None,
        cotizacion_id_excluir: Optional[UUID] = None,
    ) -> tuple:
        """Valida items_data contra el BOM y calcula items_insert/subtotal/iva/total.

        Compartido por crear_cotizacion y editar_cotizacion: misma validacion de
        sobrecosto/cotizabilidad y mismo calculo de subtotal (precios individuales
        o distribucion proporcional en modo simplificado).
        Retorna (items_insert, item_ids, subtotal, iva, total).
        """
        if not items_data:
            raise ValueError("Debes seleccionar al menos un item para cotizar.")
        try:
            cantidades = [
                Decimal(str(item.get("cantidad") or 0)) for item in items_data
            ]
        except (ArithmeticError, TypeError, ValueError):
            raise ValueError("La cantidad cotizada no es valida") from None
        if any(cantidad <= 0 for cantidad in cantidades):
            raise ValueError("La cantidad cotizada de cada item debe ser mayor a cero")

        item_ids = list(dict.fromkeys(i["bom_item_id"] for i in items_data))
        bom_items_batch = await self.db.get_items_by_ids(conn, item_ids)
        bom_items_map_cot = {str(bi["id_item"]): bi for bi in bom_items_batch}
        if len(bom_items_map_cot) != len(item_ids):
            raise ValueError("La cotizacion contiene items invalidos o inactivos")
        if any(str(item.get("id_bom")) != str(id_bom) for item in bom_items_batch):
            raise ValueError("La cotizacion no puede mezclar items de otro paquete BOM")
        await self._validar_items_cotizables(
            conn, bom_items_batch, "cotizar", cotizacion_id_excluir,
            verificar_cotizacion_activa=False,
        )
        self._raise_si_excede_pendiente(
            list(zip(items_data, cantidades)), bom_items_map_cot,
            "La cantidad cotizada supera el remanente pendiente de los items",
        )

        precios = [
            Decimal(str(i["precio_unitario"]))
            if i.get("precio_unitario") is not None else None
            for i in items_data
        ]
        tiene_precios = any(precio is not None and precio > 0 for precio in precios)
        if subtotal_externo is None and any(
            precio is None or precio <= 0 for precio in precios
        ):
            raise ValueError(
                "Captura un precio mayor a cero para cada item de la cotización"
            )

        if tiene_precios:
            self._validar_sobrecosto(items_data, bom_items_map_cot, notas)

        # Calcular subtotal: suma de precios individuales o subtotal_externo
        if subtotal_externo is not None:
            subtotal = round(Decimal(str(subtotal_externo)), 2)
            if subtotal <= 0:
                raise ValueError("El subtotal de la cotización debe ser mayor a cero")
            # Distribuir proporcionalmente entre items
            total_cantidad = sum(Decimal(str(i.get('cantidad', 1))) for i in items_data)
            for i in items_data:
                if total_cantidad > 0:
                    prop = Decimal(str(i.get('cantidad', 1))) / total_cantidad
                else:
                    prop = Decimal("1") / len(items_data)
                if 'precio_unitario' not in i or not i['precio_unitario']:
                    cantidad_item = Decimal(str(i.get('cantidad') or 1))
                    i['precio_unitario'] = round(subtotal * prop / cantidad_item, 4)
        elif tiene_precios:
            subtotal = sum(
                Decimal(str(i.get('precio_unitario') or 0)) * Decimal(str(i.get('cantidad') or 0))
                for i in items_data
            )
        else:
            subtotal = Decimal("0")

        iva = round(subtotal * Decimal(str(iva_pct)) / Decimal("100"), 2)
        total = round(subtotal + iva, 2)

        # Preparar ítems con subtotal_linea
        items_insert = []
        for i in items_data:
            pu = Decimal(str(i.get('precio_unitario') or 0))
            cant = Decimal(str(i.get('cantidad') or 0))
            items_insert.append({
                'bom_item_id': i['bom_item_id'],
                'precio_unitario': pu if pu > 0 else None,
                'cantidad': cant,
                'moneda': moneda,
                'subtotal_linea': round(pu * cant, 2) if pu > 0 else None,
            })
        return items_insert, item_ids, round(subtotal, 2), iva, total

    @staticmethod
    def _validar_proveedor_moneda(
        proveedor_id: Optional[UUID], nombre_proveedor: Optional[str], moneda: str,
    ) -> str:
        """Valida proveedor y moneda, compartido por crear_cotizacion y editar_cotizacion.

        Retorna la moneda normalizada (strip + uppercase).
        """
        if not proveedor_id and not (nombre_proveedor or "").strip():
            raise ValueError("Indica el proveedor que cotizó.")
        moneda = (moneda or "").strip().upper()
        if moneda not in {"MXN", "USD"}:
            raise ValueError("La moneda de la cotizacion debe ser MXN o USD")
        return moneda

    async def crear_cotizacion(
        self, conn, id_bom: UUID, proveedor_id: Optional[UUID],
        nombre_proveedor: Optional[str], moneda: str,
        items_data: list, iva_pct: float, notas: Optional[str],
        creado_por: UUID,
        subtotal_externo: Optional[float] = None,
        bom_lock_version_esperado: Optional[int] = None,
        rfq_id: Optional[UUID] = None,
        folio_proveedor: Optional[str] = None,
    ) -> dict:
        """
        Crea una cotización con sus ítems.
        items_data: lista de dicts con bom_item_id, precio_unitario (opcional), cantidad.

        Modos:
        - Simplificado (subtotal_externo): precio se distribuye proporcionalmente.
        - Completo: cada item tiene precio_unitario individual.
        Valida sobrecosto si hay precios individuales.
        rfq_id (opcional, doc 35): liga esta cotización real como respuesta a un RFQ del mismo BOM.
        """
        bom = await self.get_bom(conn, id_bom)
        if EstatusBOM(bom['estatus']) not in ESTATUS_COTIZABLE:
            raise ValueError("Solo se pueden crear cotizaciones en BOMs aprobados por Construccion.")
        if bom_lock_version_esperado is None:
            raise ValueError("El BOM cambio; recarga el paquete antes de cotizar")
        moneda = self._validar_proveedor_moneda(proveedor_id, nombre_proveedor, moneda)
        if rfq_id:
            rfq = await self.db.get_rfq_by_id(conn, rfq_id)
            if not rfq or str(rfq["bom_id"]) != str(id_bom):
                raise ValueError("El RFQ no pertenece a este BOM")

        items_insert, item_ids, subtotal, iva, total = await self._calcular_items_cotizacion(
            conn, id_bom, items_data, moneda, iva_pct, notas, subtotal_externo,
        )

        async with conn.transaction():
            await self._relock_bom_cotizable_o_raise(conn, id_bom, bom, bom_lock_version_esperado)
            items_bloqueados = await self.db.lock_items_context_by_ids(
                conn, sorted(item_ids, key=str)
            )
            if len(items_bloqueados) != len(item_ids) or any(
                str(item.get("id_bom")) != str(id_bom)
                for item in items_bloqueados
            ):
                raise ValueError(
                    "La cotizacion contiene items invalidos o de otro paquete BOM"
                )
            await self._validar_items_cotizables(conn, items_bloqueados, "cotizar")
            cotizacion = await self.db.crear_cotizacion(
                conn, id_bom, proveedor_id, nombre_proveedor, moneda,
                subtotal, iva, total, notas, creado_por,
                rfq_id=rfq_id,
                modo_simplificado=subtotal_externo is not None,
                folio_proveedor=folio_proveedor,
            )
            await self.db.agregar_items_cotizacion(
                conn, cotizacion['id'], id_bom, items_insert
            )

        logger.info(
            "Cotización %s creada para BOM %s por usuario %s",
            cotizacion['id'], id_bom, creado_por
        )
        return cotizacion

    async def editar_cotizacion(
        self, conn, cotizacion_id: UUID, proveedor_id: Optional[UUID],
        nombre_proveedor: Optional[str], moneda: str,
        items_data: list, iva_pct: float, notas: Optional[str],
        editado_por: UUID,
        subtotal_externo: Optional[float] = None,
        lock_version_esperado: Optional[int] = None,
        folio_proveedor: Optional[str] = None,
    ) -> dict:
        """Edita una cotización existente (proveedor, moneda, items, notas).

        Solo permitido en BORRADOR/RECIBIDA -- una vez SELECCIONADA ya disparó
        autorizacion de compra y/o aprobacion de Direccion, y RECHAZADA es terminal.
        Reemplaza los items por completo (mismo calculo/validacion que crear_cotizacion).
        """
        cotizacion = await self.db.get_cotizacion_by_id(conn, cotizacion_id)
        if not cotizacion:
            raise ValueError("Cotización no encontrada")
        if cotizacion["estatus"] not in ("BORRADOR", "RECIBIDA"):
            raise ValueError("Solo se pueden editar cotizaciones en BORRADOR o RECIBIDA")
        if lock_version_esperado is None:
            raise ValueError("La cotizacion cambio; recarga la pestaña")
        moneda = self._validar_proveedor_moneda(proveedor_id, nombre_proveedor, moneda)

        id_bom = cotizacion["bom_id"]
        bom = await self.get_bom(conn, id_bom)
        if EstatusBOM(bom['estatus']) not in ESTATUS_COTIZABLE or not self._es_cabeza_cotizable(bom):
            raise ValueError("El BOM ya no admite cotizaciones; recarga el paquete")

        items_insert, item_ids, subtotal, iva, total = await self._calcular_items_cotizacion(
            conn, id_bom, items_data, moneda, iva_pct, notas, subtotal_externo,
            cotizacion_id_excluir=cotizacion_id,
        )

        async with conn.transaction():
            await self._relock_bom_cotizable_o_raise(conn, id_bom, bom)
            items_bloqueados = await self.db.lock_items_context_by_ids(
                conn, sorted(item_ids, key=str)
            )
            if len(items_bloqueados) != len(item_ids) or any(
                str(item.get("id_bom")) != str(id_bom)
                for item in items_bloqueados
            ):
                raise ValueError(
                    "La cotizacion contiene items invalidos o de otro paquete BOM"
                )
            await self._validar_items_cotizables(
                conn, items_bloqueados, "cotizar", cotizacion_id
            )
            actualizado = await self.db.actualizar_cotizacion(
                conn, cotizacion_id, proveedor_id, nombre_proveedor, moneda,
                subtotal, iva, total, notas, lock_version_esperado,
                modo_simplificado=subtotal_externo is not None,
                folio_proveedor=folio_proveedor,
            )
            if not actualizado:
                raise ValueError("La cotizacion cambio; recarga la pestaña")
            await self.db.bulk_replace_cotizacion_items(
                conn, cotizacion_id, id_bom, items_insert
            )

        logger.info(
            "Cotización %s editada por usuario %s", cotizacion_id, editado_por
        )
        return actualizado

    async def seleccionar_cotizacion(
        self, conn, cotizacion_id: UUID, user_id: UUID,
        lock_version_esperado: Optional[int] = None,
    ) -> dict:
        """
        Marca una cotización como SELECCIONADA, actualiza estatus_compra de ítems
        y crea la autorización de compra (Fase D) notificando al coordinador de obra.
        """
        cotizacion = await self.db.get_cotizacion_by_id(conn, cotizacion_id)
        if not cotizacion:
            raise ValueError("Cotización no encontrada.")
        if cotizacion['estatus'] not in ('BORRADOR', 'RECIBIDA'):
            raise ValueError(f"La cotización está en estatus {cotizacion['estatus']} y no puede seleccionarse.")
        if not cotizacion.get('pdf_url'):
            raise ValueError("La cotización no tiene PDF cargado. Sube el PDF antes de seleccionarla.")
        if not cotizacion.get('proveedor_id') and not (cotizacion.get('nombre_proveedor') or '').strip():
            raise ValueError("La cotización no tiene proveedor capturado. Captura el proveedor antes de adjudicarla.")
        if not cotizacion.get('total') or Decimal(str(cotizacion['total'])) <= 0:
            raise ValueError("La cotización no tiene un total válido.")

        bom = await self.db.get_bom_by_id(conn, cotizacion['bom_id'])
        if (
            not bom
            or EstatusBOM(bom['estatus']) != EstatusBOM.APROBADO_FINAL
            or not bom.get("es_cabeza_oficial")
        ):
            raise ValueError("El BOM debe estar en estatus APROBADO_FINAL para autorizar la compra.")
        if lock_version_esperado is None:
            raise ValueError("La cotizacion cambio; recarga la pestaña")

        items = await self.db.get_items_cotizacion(conn, cotizacion_id)
        if items:
            item_ids = [i["bom_item_id"] for i in items]
            bom_items = await self.db.get_items_by_ids(conn, list(dict.fromkeys(item_ids)))
            bom_items_map = {str(i["id_item"]): i for i in bom_items}
            if len(bom_items_map) != len(set(str(i) for i in item_ids)):
                raise ValueError("La cotizacion contiene items invalidos o inactivos")
            if any(
                str(item.get("id_bom")) != str(cotizacion["bom_id"])
                for item in bom_items
            ):
                raise ValueError("La cotizacion contiene items de otro paquete BOM")
            await self._validar_items_cotizables(
                conn, bom_items, "seleccionar cotizaciones con", cotizacion_id,
                verificar_cotizacion_activa=False,
            )

        async with conn.transaction():
            bom_bloqueado = await self.db.get_bom_for_update(conn, cotizacion['bom_id'])
            if (
                not bom_bloqueado
                or bom_bloqueado["estatus"] != "APROBADO_FINAL"
                or not bom_bloqueado.get("es_cabeza_oficial")
                or bom_bloqueado.get("estado_paquete") != "ACTIVO"
            ):
                raise ValueError("El BOM ya no es la cabeza oficial activa")
            cotizacion_bloqueada = await self.db.get_cotizacion_for_update(
                conn, cotizacion_id
            )
            if (
                not cotizacion_bloqueada
                or cotizacion_bloqueada["estatus"] != cotizacion["estatus"]
                or cotizacion_bloqueada["lock_version"] != lock_version_esperado
            ):
                raise ValueError("La cotizacion ya cambio; recarga la pestaña")
            if items:
                bloqueados = await self.db.lock_items_context_by_ids(
                    conn, sorted(item_ids, key=str)
                )
                if len(bloqueados) != len(set(item_ids)):
                    raise ValueError("La cotizacion contiene items invalidos")
                await self._validar_items_cotizables(
                    conn, bloqueados, "seleccionar cotizaciones con", cotizacion_id
                )
                # Recheck bajo lock: _validar_items_cotizables solo confirma que
                # queda remanente > 0, no que la cantidad de ESTA cotizacion siga
                # cabiendo en el remanente actual. Sin esto, dos cotizaciones que
                # individualmente cupieron al crearse (remanente aun no tocado en
                # ese momento) pueden violar tb_bom_items_cantidad_cubierta_check
                # si ambas se seleccionan (la segunda ve el remanente ya reducido
                # por la primera, recien liberado el lock de fila).
                bloqueados_map = {str(it["id_item"]): it for it in bloqueados}
                self._raise_si_excede_pendiente(
                    [(it, Decimal(str(it["cantidad"]))) for it in items], bloqueados_map,
                    "La cantidad de esta cotizacion ya no cabe en el remanente pendiente "
                    "(otra cotizacion cubrio parte del remanente mientras tanto)",
                )
                locks_ejecucion = {
                    str(item["id_item"]): int(
                        item.get("ejecucion_lock_version") or 0
                    )
                    for item in bloqueados
                }
            updated = await self.db.actualizar_estatus_cotizacion(
                conn, cotizacion_id, 'SELECCIONADA', cotizacion["estatus"],
                lock_version_esperado,
            )
            if not updated:
                raise ValueError("La cotizacion ya cambio; recarga la pestaña")

            # TC del proyecto, resuelto una sola vez: lo usa la bitácora de items
            # (congelado por ítem si es USD) y la autorización más abajo (si aplica).
            tc_resuelto = None
            if cotizacion['moneda'] == 'USD':
                tc_resuelto = await self.resolver_tipo_cambio(conn, bom['id_proyecto'])

            # Actualizar estatus_compra de los ítems cubiertos: incrementa
            # cantidad_cubierta por lo que esta cotizacion adjudica y deriva
            # COTIZADO (remanente agotado) o PARCIALMENTE_COTIZADO (queda
            # remanente) por item, en vez de fijar COTIZADO a secas.
            if items:
                item_ids = [i['bom_item_id'] for i in items]
                # items ya cargados arriba — llamada directa para evitar re-fetch en _actualizar_estatus_items_cotizacion
                resultados = await self.db.ajustar_cantidad_cubierta_items(
                    conn,
                    [
                        (it['bom_item_id'], Decimal(str(it['cantidad'])))
                        for it in items
                    ],
                )
                estatus_resultante = {
                    str(r['id_item']): r['estatus_compra'] for r in resultados
                }

                # Registrar costo/proveedor reales sin mutar el presupuesto base.
                for it in items:
                    campos_reales = {
                        'id_proveedor_real': cotizacion.get('proveedor_id'),
                        'moneda_real': it.get('moneda') or cotizacion.get('moneda'),
                        'estatus_ejecucion': estatus_resultante[str(it['bom_item_id'])],
                    }
                    if it.get('precio_unitario') is not None:
                        campos_reales['precio_real'] = it.get('precio_unitario')
                    ejecucion = await self.db.upsert_item_ejecucion(
                        conn,
                        it['bom_item_id'],
                        updated_by=user_id,
                        lock_version_esperado=locks_ejecucion[
                            str(it['bom_item_id'])
                        ],
                        **campos_reales,
                    )
                    if not ejecucion:
                        raise ValueError(
                            "La ejecución de un ítem cambió; recarga la cotización"
                        )

                # Bitácora de precios: solo si el proveedor está catalogado
                # (id_proveedor NOT NULL en tb_materiales_historial) -- una
                # cotización con solo nombre libre de proveedor no puede
                # alimentar esta bitácora.
                if cotizacion.get('proveedor_id'):
                    tc_usd = tc_resuelto["tasa"] if tc_resuelto else None
                    await self.db.guardar_historial_cotizacion(
                        conn, cotizacion['proveedor_id'],
                        today_mx(), user_id, items, tc_usd,
                    )

                # Refresco de costo del catálogo interno: independiente de si el
                # proveedor está catalogado, solo depende de que el ítem tenga
                # material interno vinculado. Misma autoridad que editar el
                # catálogo a mano (MaterialsService.actualizar_interno).
                registros_catalogo = [
                    {
                        'id': it['id_material_interno'],
                        'precio_referencia': it['precio_unitario'],
                        'moneda': it.get('moneda') or 'MXN',
                        'actualizado_por': user_id,
                    }
                    for it in items
                    if it.get('id_material_interno') and it.get('precio_unitario')
                ]
                if registros_catalogo:
                    await self.materials.actualizar_precios_referencia_bulk(
                        conn, registros_catalogo
                    )

            # Crear autorización de compra (Fase D) si no existe ya; si quedó
            # RECHAZADA de un ciclo anterior, reabrirla a PENDIENTE (nuevo ciclo)
            existente = await self.db.get_autorizacion_by_cotizacion(conn, cotizacion_id)
            if not existente or existente.get('estatus') == 'RECHAZADO':
                bom = await self.db.get_bom_by_id(conn, cotizacion['bom_id'])
                tc_valor = None
                if cotizacion['moneda'] == 'USD':
                    if not tc_resuelto["tasa"]:
                        raise ValueError(
                            "No hay tipo de cambio vigente para autorizar la cotizacion"
                        )
                    tc_valor = tc_resuelto["tasa"]
                if existente:
                    await self.db.reabrir_autorizacion_db(
                        conn, existente['id'], cotizacion['total'],
                        cotizacion['moneda'], tc_valor, user_id,
                        existente["lock_version"],
                    )
                else:
                    await self.db.crear_autorizacion(
                        conn,
                        cotizacion_id=cotizacion_id,
                        bom_id=cotizacion['bom_id'],
                        proyecto_id=bom['id_proyecto'],
                        monto_total=cotizacion['total'],
                        moneda=cotizacion['moneda'],
                        tipo_cambio_snapshot=tc_valor,
                        creado_por=user_id,
                    )
            await self.db.registrar_evento_outbox(
                conn,
                f"COTIZACION:{cotizacion_id}:{updated['lock_version']}:SELECCIONADA",
                "COTIZACION_SELECCIONADA", bom["id_proyecto"], user_id,
                {"id_cotizacion": str(cotizacion_id), "estatus": "SELECCIONADA"},
                id_paquete=bom.get("id_paquete"), id_bom=cotizacion["bom_id"],
                id_documento=cotizacion_id,
            )

        logger.info("Cotización %s seleccionada por usuario %s", cotizacion_id, user_id)
        return updated

    # ─── AUTORIZACIONES (Fase D) ────────────────────────────

    async def _adjuntar_items_a_autorizaciones(self, conn, autorizaciones: list) -> list:
        """Batch de items de cotizacion para una lista de autorizaciones (evita N+1).
        Comun a listar_autorizaciones (por-BOM) y listar_pendientes_popup_coordinador
        (cross-BOM)."""
        if not autorizaciones:
            return autorizaciones
        cotizacion_ids = [aut["cotizacion_id"] for aut in autorizaciones]
        items = await self.db.get_items_by_cotizacion_ids(conn, cotizacion_ids)
        items_por_cotizacion = defaultdict(list)
        for item in items:
            items_por_cotizacion[item["cotizacion_id"]].append(item)
        for aut in autorizaciones:
            aut["items"] = items_por_cotizacion.get(aut["cotizacion_id"], [])
        return autorizaciones

    async def listar_autorizaciones(self, conn, bom_id: UUID) -> list:
        autorizaciones = await self.db.get_autorizaciones_by_bom(conn, bom_id)
        return await self._adjuntar_items_a_autorizaciones(conn, autorizaciones)

    async def listar_pendientes_popup_coordinador(
        self, conn, user_id: UUID, rol_organizacional: Optional[str],
    ) -> list:
        """Autorizaciones de Obra pendientes que el usuario (titular o suplente)
        puede aprobar, para el banner de pendientes al entrar a la app
        (PLAN_popup_pendientes_autorizacion_obra.md §1/§2). Una sola resolucion
        de titulares + una query cross-BOM -- nunca por-BOM. Sin
        _adjuntar_items_a_autorizaciones: el banner simplificado (2026-09-02) ya
        no muestra items/PDF/monto, solo proveedor + proyecto/BOM, para no
        duplicar el detalle que ya vive en /bom/obra/autorizaciones."""
        representados = list(await self.get_titulares_que_representa(conn, user_id))
        return await self.db.get_autorizaciones_pendientes_por_coordinador(
            conn, representados, rol_organizacional,
        )

    async def listar_autorizaciones_obra_coordinador(
        self, conn, user_id: UUID, rol_organizacional: Optional[str],
        limit: int = 20, offset: int = 0, id_proyecto: Optional[UUID] = None,
    ) -> tuple[list, int]:
        """Variante paginada de listar_pendientes_popup_coordinador para la tabla
        cross-proyecto de "Mis Autorizaciones": a diferencia del popup, NO adjunta
        items (_adjuntar_items_a_autorizaciones) porque la tabla no los muestra y
        ningun endpoint de aprobar/rechazar los lee. Devuelve (autorizaciones, total).

        `id_proyecto`: cuando se pasa (entrada desde el indicador de pendientes de
        un proyecto especifico), la query deja de filtrar por `representados` y
        trae TODO lo pendiente de ese proyecto -- un visitante que no es el
        coordinador de ese BOM (ej. Direccion) debe poder VER quien es el
        coordinador asignado en vez de recibir una tabla vacia indistinguible de
        "sin pendientes". `puede_actuar` marca por fila si el usuario actual
        puede aprobar/rechazar esa autorizacion especifica (mismo predicado que
        el gate real, calculado aqui sin queries extra); el template usa esta
        bandera para mostrar Aprobar/Rechazar o el nombre del coordinador."""
        representados = list(await self.get_titulares_que_representa(conn, user_id))
        autorizaciones = await self.db.get_autorizaciones_pendientes_por_coordinador(
            conn, representados, rol_organizacional, limit=limit, offset=offset,
            id_proyecto=id_proyecto,
        )
        total = await self.db.contar_autorizaciones_pendientes_por_coordinador(
            conn, representados, rol_organizacional, id_proyecto=id_proyecto,
        )
        representados_set = set(representados)
        for aut in autorizaciones:
            aut["puede_actuar"] = self.es_coordinador_obra(
                aut.get("coordinador_obra"), representados_set, rol_organizacional,
            )
        return autorizaciones, total

    async def get_proyectos_con_rol_bom(
        self, conn, proyecto_ids: List[UUID], user_id: UUID,
    ) -> set:
        """Proyectos donde el usuario (o algun titular que representa via
        suplencia activa) tiene rol de BOM -- gate para el acceso a
        "Configurar suplente" desde el menu de proyectos/ui."""
        if not proyecto_ids:
            return set()
        representados = await self.get_titulares_que_representa(conn, user_id)
        return await self.db.get_proyectos_con_rol_bom(conn, proyecto_ids, list(representados))

    async def get_conteo_pendientes_por_proyecto(
        self, conn, proyecto_ids: List[UUID],
    ) -> dict:
        """Conteo de pendientes de BOM por proyecto, para el indicador de
        proyectos/ui: {proyecto_id: {"compras_obra": n, "cotizaciones_direccion": n}}.
        Dos queries independientes (una por tipo) combinadas en memoria -- no hay
        un solo agregado compartido porque cada tipo cuenta contra una tabla y un
        estatus distintos."""
        if not proyecto_ids:
            return {}
        conteo_obra = await self.db.get_conteo_autorizaciones_pendientes_por_proyecto(
            conn, proyecto_ids,
        )
        conteo_direccion = await self.db.get_conteo_cotizaciones_pendientes_direccion_por_proyecto(
            conn, proyecto_ids,
        )
        resultado = {}
        for proyecto_id in set(conteo_obra) | set(conteo_direccion):
            resultado[proyecto_id] = {
                "compras_obra": conteo_obra.get(proyecto_id, 0),
                "cotizaciones_direccion": conteo_direccion.get(proyecto_id, 0),
            }
        return resultado

    def _exigir_coordinador_obra(
        self, coordinador_obra: Optional[UUID], representados: set,
        rol_organizacional: Optional[str], accion: str,
    ) -> None:
        """Levanta ValueError si el usuario no es el coordinador de obra
        (titular o suplente) ni el jefe de Construccion (autoridad permanente,
        no solo fallback -- ver BomService.es_coordinador_obra()). `accion` es
        el verbo infinitivo del paso (ej. "aprobar", "rechazar"), usado para
        armar el mensaje. Un solo mensaje: con jefe_construccion siempre
        elegible, ya no hay una rama "sin coordinador asignado" distinta."""
        if self.es_coordinador_obra(coordinador_obra, representados, rol_organizacional):
            return
        raise ValueError(
            f"Solo el coordinador de obra del proyecto, su suplente, o el jefe "
            f"de Construccion pueden {accion} este paso."
        )

    async def aprobar_obra(
        self, conn, autorizacion_id: UUID, user_id: UUID, nota: Optional[str],
        user_role: str, lock_version_esperado: Optional[int] = None,
        rol_organizacional: Optional[str] = None,
    ) -> dict:
        """Aprueba paso 1 el controlador de Obra o su suplente activo."""
        aut = await self.db.get_autorizacion_by_id(conn, autorizacion_id)
        if not aut:
            raise ValueError("Autorización no encontrada.")
        if aut['estatus'] != 'PENDIENTE':
            raise ValueError(f"La autorización está en estatus {aut['estatus']} y no puede aprobarse en este paso.")

        bom = await self.db.get_bom_by_id(conn, aut['bom_id'])

        # Fase D no usa _validar_aprobador_bom: opera sobre la autorizacion (no sobre roles
        # de revision del BOM), no tiene bypass de Director (Direccion tiene su propio paso
        # en Fase D), y el fallback es NULL-check en coordinador_obra, no rol_org global.
        representados = await self.get_titulares_que_representa(conn, user_id)
        coordinador_obra = bom.get('coordinador_obra')
        self._exigir_coordinador_obra(coordinador_obra, representados, rol_organizacional, "aprobar")

        if lock_version_esperado is None:
            raise ValueError("La autorizacion cambio; recarga la pestaña")
        async with conn.transaction():
            bloqueada = await self.db.get_autorizacion_for_update(conn, autorizacion_id)
            if (
                not bloqueada or bloqueada["estatus"] != "PENDIENTE"
                or bloqueada["lock_version"] != lock_version_esperado
            ):
                raise ValueError("La autorizacion ya cambio; recarga la pestaña")
            updated = await self.db.update_autorizacion_paso_obra(
                conn, autorizacion_id, user_id, nota, lock_version_esperado
            )
            if not updated:
                raise ValueError("La autorizacion ya cambio; recarga la pestaña")
            await self.db.registrar_evento_outbox(
                conn, f"AUTORIZACION:{autorizacion_id}:{updated['lock_version']}:OBRA",
                "AUTORIZACION_OBRA", aut["proyecto_id"], user_id,
                {"id_autorizacion": str(autorizacion_id), "estatus": updated["estatus"]},
                id_paquete=bom.get("id_paquete"), id_bom=aut["bom_id"],
                id_documento=autorizacion_id,
            )

        logger.info("Autorización %s aprobada (obra) por usuario %s", autorizacion_id, user_id)
        return updated

    async def aprobar_finanzas(
        self, conn, autorizacion_id: UUID, user_id: UUID, nota: Optional[str],
        user_role: str, finanzas_role: Optional[str] = None,
        lock_version_esperado: Optional[int] = None,
    ) -> dict:
        """Aprueba paso 3. Requiere rol del modulo Finanzas editor o admin."""
        aut = await self.db.get_autorizacion_by_id(conn, autorizacion_id)
        if not aut:
            raise ValueError("Autorización no encontrada.")
        if aut['estatus'] != 'AUTORIZADO_DIRECCION':
            raise ValueError(f"La autorización está en estatus {aut['estatus']} y no puede aprobarse en este paso.")

        es_finanzas = finanzas_role in ('editor', 'admin')
        if not es_finanzas:
            raise ValueError("Solo usuarios del módulo Finanzas pueden aprobar este paso.")

        bom = await self.db.get_bom_by_id(conn, aut['bom_id'])
        if lock_version_esperado is None:
            raise ValueError("La autorizacion cambio; recarga la pestaña")
        async with conn.transaction():
            bloqueada = await self.db.get_autorizacion_for_update(conn, autorizacion_id)
            if (
                not bloqueada or bloqueada["estatus"] != "AUTORIZADO_DIRECCION"
                or bloqueada["lock_version"] != lock_version_esperado
            ):
                raise ValueError("La autorizacion ya cambio; recarga la pestaña")
            updated = await self._avanzar_paso_finanzas(
                conn, autorizacion_id, aut['cotizacion_id'], user_id, nota,
                lock_version_esperado, aut["proyecto_id"], bom.get("id_paquete"),
                aut["bom_id"],
            )
        logger.info("Autorización %s aprobada (finanzas) por usuario %s", autorizacion_id, user_id)
        return updated

    async def _avanzar_paso_finanzas(
        self, conn, autorizacion_id: UUID, cotizacion_id: UUID,
        user_id: UUID, nota: Optional[str], lock_version_actual: int,
        proyecto_id: UUID, id_paquete: Optional[UUID], id_bom: UUID,
        auto_avance: bool = False,
    ) -> dict:
        """
        Avanza AUTORIZADO_DIRECCION -> AUTORIZADO_FINANZAS: actualiza la
        autorizacion, marca los items de la cotizacion AUTORIZADO y registra el
        evento outbox. Paso compartido por `aprobar_finanzas()` (clic manual,
        sigue disponible sin usarse) y por el autoavance desde Direccion
        (decision de negocio 2026-08-19: Finanzas ya no aprueba, solo paga y
        adjunta comprobante — ver memory/bom_gate_finanzas_deshabilitado.md).
        `auto_avance=True` marca en el payload del evento outbox que el actor
        (`user_id`) es quien aprobo Direccion, no un usuario de Finanzas real
        — evita que un futuro consumidor del evento atribuya mal la accion.
        """
        updated = await self.db.update_autorizacion_paso_finanzas(
            conn, autorizacion_id, user_id, nota, lock_version_actual,
        )
        if not updated:
            raise ValueError("La autorizacion ya cambio; recarga la pestaña")
        await self._autorizar_items_cotizacion(conn, cotizacion_id)
        await self.db.registrar_evento_outbox(
            conn, f"AUTORIZACION:{autorizacion_id}:{updated['lock_version']}:FINANZAS",
            "AUTORIZACION_FINANZAS", proyecto_id, user_id,
            {
                "id_autorizacion": str(autorizacion_id),
                "estatus": updated["estatus"],
                "auto_avance": auto_avance,
            },
            id_paquete=id_paquete, id_bom=id_bom, id_documento=autorizacion_id,
        )
        return updated

    async def rechazar_autorizacion(
        self, conn, autorizacion_id: UUID, user_id: UUID, motivo: str,
        user_role: str, rol_org: Optional[str], finanzas_role: Optional[str] = None,
        lock_version_esperado: Optional[int] = None,
    ) -> dict:
        """Rechaza la autorización en el paso actual. Cotización vuelve a RECIBIDA."""
        aut = await self.db.get_autorizacion_by_id(conn, autorizacion_id)
        if not aut:
            raise ValueError("Autorización no encontrada.")

        estatus = aut['estatus']
        if estatus in ('AUTORIZADO_FINANZAS', 'RECHAZADO'):
            raise ValueError(f"La autorización ya está en estatus {estatus}.")

        # El lock_version se valida ANTES de determinar el paso/permiso: si otra
        # pestaña ya avanzo la autorizacion (ej. Obra aprobo mientras esta pestaña
        # seguia en PENDIENTE), el estatus fresco ya corresponde al paso siguiente
        # y el chequeo de permiso de ESE paso (ej. _require_direccion_titular)
        # dispara con un mensaje de permisos que no describe el problema real.
        if lock_version_esperado is None or aut['lock_version'] != lock_version_esperado:
            raise ValueError(
                "Esta autorización ya fue actualizada por otro paso o usuario; recarga la página."
            )

        # Determinar paso y validar permisos
        if estatus == 'PENDIENTE':
            paso = 'OBRA'
            bom = await self.db.get_bom_by_id(conn, aut['bom_id'])
            representados = await self.get_titulares_que_representa(conn, user_id)
            coordinador_obra = bom.get('coordinador_obra')
            self._exigir_coordinador_obra(coordinador_obra, representados, rol_org, "rechazar")
        elif estatus == 'AUTORIZADO_OBRA':
            paso = 'DIRECCION'
            await self._require_direccion_titular(conn, user_id, "rechazar")
            # Si Compras ya solicito la aprobacion documental (tb_bom_cotizacion_
            # aprobaciones), este atajo generico debe ceder el paso a
            # rechazar_cotizacion_direccion: ese es el unico camino que resuelve
            # tambien la aprobacion (PENDIENTE_DIRECCION -> RECHAZADA) ademas de
            # la autorizacion -- seguir por aqui la dejaria huerfana para siempre.
            if await self.db.get_cotizacion_aprobacion_activa(conn, aut['cotizacion_id']):
                raise ValueError(
                    "Compras ya solicitó la aprobación de esta cotización; "
                    "recházala desde la tab Cotizaciones."
                )
        elif estatus == 'AUTORIZADO_DIRECCION':
            paso = 'FINANZAS'
            es_finanzas = finanzas_role in ('editor', 'admin')
            if not es_finanzas:
                raise ValueError("Solo usuarios del módulo Finanzas pueden rechazar en este paso.")
        else:
            raise ValueError(f"La autorización no puede rechazarse en estatus {estatus}.")

        bom = await self.db.get_bom_by_id(conn, aut['bom_id'])
        async with conn.transaction():
            bloqueada = await self.db.get_autorizacion_for_update(conn, autorizacion_id)
            if (
                not bloqueada or bloqueada["estatus"] != estatus
                or bloqueada["lock_version"] != lock_version_esperado
            ):
                raise ValueError("La autorizacion ya cambio; recarga la pestaña")
            updated = await self.db.rechazar_autorizacion_db(
                conn, autorizacion_id, user_id, motivo, paso, estatus,
                lock_version_esperado,
            )
            if not updated:
                raise ValueError("La autorizacion ya cambio; recarga la pestaña")
            await self._liberar_cotizacion_rechazada(conn, aut['cotizacion_id'])
            await self.db.registrar_evento_outbox(
                conn,
                f"AUTORIZACION:{autorizacion_id}:{updated['lock_version']}:RECHAZADA",
                "AUTORIZACION_RECHAZADA", aut["proyecto_id"], user_id,
                {"id_autorizacion": str(autorizacion_id), "estatus": "RECHAZADO"},
                id_paquete=bom.get("id_paquete"), id_bom=aut["bom_id"],
                id_documento=autorizacion_id,
            )

        # Cotización vuelve a RECIBIDA e ítems a SIN_COTIZAR
        # La liberacion de la cotizacion ya ocurrio dentro de la transaccion.

        logger.info("Autorización %s rechazada en paso %s por usuario %s", autorizacion_id, paso, user_id)
        return updated

    # ─── APROBACIONES DE COTIZACION (post-BOM) ──────────────

    async def get_cotizacion_aprobaciones_direccion(
        self, conn, estatus: Optional[str] = None,
        id_proyecto: Optional[UUID] = None,
        nombre_proveedor: Optional[str] = None,
    ) -> list:
        """Dashboard de Direccion: pendientes/aprobadas/rechazadas de todos los proyectos."""
        return await self.db.get_cotizacion_aprobaciones_direccion(
            conn, estatus=estatus, id_proyecto=id_proyecto, nombre_proveedor=nombre_proveedor,
        )

    async def _liberar_cotizacion_rechazada(
        self, conn, cotizacion_id: UUID,
        resetear_estatus_cotizacion: bool = True,
        items: Optional[list] = None,
    ) -> None:
        """Libera los items de una cotización tras un rechazo o reemplazo,
        decrementando cantidad_cubierta exactamente por lo que esta cotizacion
        cubria (no resetea a SIN_COTIZAR a ciegas: si otra cotizacion previa ya
        adjudico una parte del mismo item, el item vuelve a PARCIALMENTE_COTIZADO
        en vez de perder esa cobertura).

        Por defecto regresa `tb_bom_cotizaciones.estatus` a RECIBIDA (rechazo
        normal, ## 7.3). `reemplazar_cotizacion_proveedor` pasa
        `resetear_estatus_cotizacion=False`: su CHECK no admite un valor de
        reemplazo, la cotización se conserva SELECCIONADA como evidencia
        histórica (## 7.4).

        `items`: items de la cotizacion ya cargados (con `cantidad`) si el
        caller los tiene a mano -- evita re-consultar `get_items_cotizacion`.
        """
        if resetear_estatus_cotizacion:
            cotizacion = await self.db.get_cotizacion_for_update(conn, cotizacion_id)
            if not cotizacion:
                raise ValueError("Cotizacion no encontrada")
            actualizada = await self.db.actualizar_estatus_cotizacion(
                conn, cotizacion_id, 'RECIBIDA', cotizacion["estatus"],
                cotizacion["lock_version"],
            )
            if not actualizada:
                raise ValueError("La cotizacion cambio; recarga la pestaña")
        if items is None:
            items = await self.db.get_items_cotizacion(conn, cotizacion_id)
        if not items:
            return
        ajustes = {
            it['bom_item_id']: -Decimal(str(it['cantidad'])) for it in items
        }
        await self._ajustar_cantidad_cubierta_items(conn, ajustes)

    async def solicitar_aprobacion_cotizacion(
        self, conn, cotizacion_id: UUID, user_id: UUID,
        comentarios: Optional[str] = None,
        cotizacion_lock_version_esperado: Optional[int] = None,
        autorizacion_lock_version_esperado: Optional[int] = None,
        reemplaza_aprobacion_id: Optional[UUID] = None,
        vigente: bool = True,
        motivo_no_vigente: Optional[str] = None,
    ) -> dict:
        """
        Crea la aprobacion documental de Direccion (tb_bom_cotizacion_aprobaciones)
        para una cotizacion. Precondiciones (plan ## 7.2 / ## 8.1 / ## 9.3): cotizacion
        real (no RFQ) con PDF y total, SELECCIONADA, BOM en APROBADO_FINAL y
        autorizacion Fase D ya aprobada por Obra.

        Si `reemplaza_aprobacion_id` viene (## 7.4), liga esta cotizacion como la
        sucesora de una aprobacion REEMPLAZADA del mismo BOM sin sucesor aun.

        Punto A del gate de vigencia (plan standby/vigencia 2026-08-28): Compras
        debe confirmar `vigente` en la misma solicitud. Si `vigente=False`, no se
        crea aprobacion alguna -- se rechaza la autorizacion Fase D directamente
        (RECHAZO_VIGENCIA) via `_rechazar_por_vigencia`. Si `vigente=True`, procede
        como hoy -- si el precio cambio, la cotizacion se edita aparte antes de
        llegar a este paso (BORRADOR/RECIBIDA), no desde este gate.
        """
        if not vigente and (not motivo_no_vigente or not motivo_no_vigente.strip()):
            raise ValueError("El motivo es obligatorio cuando la cotización ya no está vigente.")
        cotizacion = await self.db.get_cotizacion_by_id(conn, cotizacion_id)
        if not cotizacion:
            raise ValueError("Cotización no encontrada.")
        if not cotizacion.get('pdf_url'):
            raise ValueError("La cotización no tiene PDF cargado. Sube el PDF antes de solicitar aprobación.")
        if not cotizacion.get('total') or Decimal(str(cotizacion['total'])) <= 0:
            raise ValueError("La cotización no tiene un total válido.")
        if cotizacion['estatus'] != 'SELECCIONADA':
            raise ValueError("La cotización debe estar seleccionada antes de solicitar aprobación de Dirección.")

        bom = await self.db.get_bom_by_id(conn, cotizacion['bom_id'])
        if not bom or EstatusBOM(bom['estatus']) != EstatusBOM.APROBADO_FINAL:
            raise ValueError("El BOM debe estar en estatus APROBADO_FINAL para solicitar aprobación.")

        autorizacion = await self.db.get_autorizacion_by_cotizacion(conn, cotizacion_id)
        if not autorizacion or autorizacion['estatus'] != 'AUTORIZADO_OBRA':
            raise ValueError("La autorización de compra debe estar aprobada por Obra antes de solicitar aprobación de Dirección.")

        if cotizacion_lock_version_esperado is None or autorizacion_lock_version_esperado is None:
            raise ValueError("La cotización o autorización cambió; recarga la pestaña.")

        async with conn.transaction():
            paquete_bloqueado = await self.db.get_paquete_for_update(conn, bom["id_paquete"])
            bom_bloqueado = await self.db.get_bom_for_update(conn, cotizacion["bom_id"])
            cotizacion_bloqueada = await self.db.get_cotizacion_for_update(conn, cotizacion_id)
            autorizacion_bloqueada = await self.db.get_autorizacion_for_update(
                conn, autorizacion["id"]
            )
            if (
                not paquete_bloqueado
                or paquete_bloqueado["estado_paquete"] != "ACTIVO"
                or not bom_bloqueado
                or bom_bloqueado["id_paquete"] != paquete_bloqueado["id_paquete"]
                or not cotizacion_bloqueada
                or cotizacion_bloqueada["estatus"] != "SELECCIONADA"
                or cotizacion_bloqueada["lock_version"] != cotizacion_lock_version_esperado
                or not autorizacion_bloqueada
                or autorizacion_bloqueada["estatus"] != "AUTORIZADO_OBRA"
                or autorizacion_bloqueada["lock_version"] != autorizacion_lock_version_esperado
            ):
                raise ValueError("La cotización o autorización cambió; recarga la pestaña.")
            existente = await self.db.get_cotizacion_aprobacion_activa(conn, cotizacion_id)
            if existente:
                raise ValueError(
                    "La cotización ya tiene una aprobación de Dirección pendiente o aprobada."
                )

            if not vigente:
                rechazada = await self._rechazar_por_vigencia(
                    conn, autorizacion_bloqueada, cotizacion_id, user_id,
                    motivo_no_vigente.strip(), bom,
                )
                logger.info(
                    "Cotización %s marcada NO vigente al solicitar aprobación (usuario %s)",
                    cotizacion_id, user_id,
                )
                return rechazada

            reemplazada = None
            if reemplaza_aprobacion_id:
                reemplazada = await self.db.get_cotizacion_aprobacion_for_update(
                    conn, reemplaza_aprobacion_id
                )
                if (
                    not reemplazada
                    or str(reemplazada["bom_id"]) != str(cotizacion["bom_id"])
                    or reemplazada["estatus"] != EstatusCotizacionAprobacion.REEMPLAZADA
                ):
                    raise ValueError(
                        "La cotización reemplazada no es válida para ligar como sucesora."
                    )
                # Nota: sin constraint unico en aprobacion_reemplazada_id, dos
                # solicitudes concurrentes podrian ligarse al mismo predecesor
                # (solo afecta el enlace historico, no el estado de items/pagos).
            try:
                aprobacion = await self.db.crear_cotizacion_aprobacion(
                    conn, cotizacion_id, cotizacion['bom_id'], bom['id_proyecto'],
                    user_id, comentarios,
                    cotizacion_reemplazada_id=(
                        reemplazada["cotizacion_id"] if reemplazada else None
                    ),
                    aprobacion_reemplazada_id=reemplaza_aprobacion_id,
                )
            except asyncpg.UniqueViolationError:
                raise ValueError(
                    "La cotización ya tiene una aprobación de Dirección pendiente o aprobada."
                )
            await self.db.registrar_evento_outbox(
                conn,
                f"COTIZACION_APROBACION:{aprobacion['id']}:0:SOLICITADA",
                "COTIZACION_APROBACION_SOLICITADA", bom["id_proyecto"], user_id,
                {
                    "id_cotizacion": str(cotizacion_id),
                    "id_aprobacion": str(aprobacion["id"]),
                    "estatus": aprobacion["estatus"],
                },
                id_paquete=bom["id_paquete"], id_bom=cotizacion["bom_id"],
                id_documento=aprobacion["id"],
            )
        logger.info(
            "Aprobación de cotización %s solicitada (aprobación %s) por usuario %s",
            cotizacion_id, aprobacion['id'], user_id
        )
        return aprobacion

    async def _require_direccion_titular(
        self, conn, user_id: UUID, accion: str,
    ) -> UUID:
        """Aprobador de Direccion vigente (titular o suplente activo) o ValueError.

        Extraido de la validacion duplicada en aprobar_cotizacion_direccion y
        rechazar_cotizacion_direccion (Gap #6) para que standby/confirmacion de
        vigencia no agreguen una tercera copia divergente.
        """
        aprobador_direccion = await self.db.get_aprobador_final_id(conn)
        representados = await self.get_titulares_que_representa(conn, user_id)
        if not aprobador_direccion or aprobador_direccion not in representados:
            raise ValueError(
                f"Solo el aprobador de Dirección o su suplente puede {accion} cotizaciones."
            )
        return aprobador_direccion

    async def _rechazar_por_vigencia(
        self, conn, autorizacion: dict, cotizacion_id: UUID, user_id: UUID,
        motivo: str, bom: dict,
    ) -> dict:
        """Camino "no vigente" compartido por el Punto A (solicitar_aprobacion_cotizacion)
        y el Punto B (confirmar_vigencia_reactivacion): rechaza explicitamente la
        autorizacion Fase D (paso RECHAZO_VIGENCIA) antes de liberar los items, para
        que no quede huerfana en AUTORIZADO_OBRA (Gap #4) -- el estatus_esperado se
        toma de la fila ya bloqueada por el caller, no del valor pre-lock.

        Notifica a Compras (via el evento AUTORIZACION_RECHAZADA existente, que ya
        resuelve autorizacion.creado_por) y, por marcar 'motivo_paso':'RECHAZO_VIGENCIA'
        en el payload, tambien a Obra (jefe_construccion) -- decision de negocio
        2026-08-28: el rechazo por vigencia invalida su AUTORIZADO_OBRA previo y debe
        saber que la cotizacion se recotizara desde cero (whitelist en db_service.py).
        """
        rechazada = await self.db.rechazar_autorizacion_db(
            conn, autorizacion['id'], user_id, motivo, 'RECHAZO_VIGENCIA',
            autorizacion['estatus'], autorizacion['lock_version'],
        )
        if not rechazada:
            raise ValueError("La autorización cambió; recarga la pestaña.")
        await self._liberar_cotizacion_rechazada(conn, cotizacion_id)
        await self.db.registrar_evento_outbox(
            conn,
            f"AUTORIZACION:{autorizacion['id']}:{rechazada['lock_version']}:RECHAZADA",
            "AUTORIZACION_RECHAZADA", rechazada["proyecto_id"], user_id,
            {
                "id_autorizacion": str(autorizacion['id']),
                "estatus": "RECHAZADO",
                "motivo_paso": "RECHAZO_VIGENCIA",
                "motivo": motivo,
            },
            id_paquete=bom.get("id_paquete"), id_bom=rechazada["bom_id"],
            id_documento=autorizacion['id'],
        )
        return rechazada

    async def _actualizar_costos_vigencia(
        self, conn, cotizacion_id: UUID, user_id: UUID,
        items_data: list, iva_pct: float, motivo: str,
        notas: Optional[str] = None, nuevo_pdf_url: Optional[str] = None,
        cotizacion_lock_version_esperado: Optional[int] = None,
        autorizacion_lock_version_esperado: Optional[int] = None,
    ) -> dict:
        """Camino 2 del gate de vigencia (decision de negocio 2026-09-02): cuando
        Compras marca una cotizacion como "no vigente" porque cambio el costo
        (mismos items, sin cambios de alcance), corrige precio_unitario por item
        y recalcula subtotal/iva/total de la cotizacion SELECCIONADA -- sin
        reabrir su detalle completo (a diferencia de Camino 1, "liberar y
        recotizar", que regresa la cotizacion a RECIBIDA via
        _rechazar_por_vigencia) y sin que Obra vuelva a aprobar: el alcance de
        Obra es validar que los items cotizados sean correctos, no el costo, asi
        que solo aplica si la autorizacion ya esta AUTORIZADO_OBRA. El caller
        (actualizar_costos_y_solicitar_aprobacion / _y_confirmar_vigencia)
        encadena hacia el flujo normal de aprobacion de Direccion con
        vigente=True una vez aplicado este ajuste.

        Sincroniza tb_bom_autorizaciones.monto_total en la misma transaccion --
        el CONSTRAINT TRIGGER DEFERRED trg_bom_validar_autorizacion_cotizacion
        exige que coincida con el total de la cotizacion."""
        if not motivo or not motivo.strip():
            raise ValueError("El motivo es obligatorio cuando la cotización ya no está vigente.")
        if cotizacion_lock_version_esperado is None or autorizacion_lock_version_esperado is None:
            raise ValueError("La cotización o autorización cambió; recarga la pestaña.")

        cotizacion = await self.db.get_cotizacion_by_id(conn, cotizacion_id)
        if not cotizacion or cotizacion['estatus'] != 'SELECCIONADA':
            raise ValueError("La cotización debe estar seleccionada para actualizar su costo.")
        autorizacion = await self.db.get_autorizacion_by_cotizacion(conn, cotizacion_id)
        if not autorizacion or autorizacion['estatus'] != 'AUTORIZADO_OBRA':
            raise ValueError("Solo puedes actualizar el costo si Obra ya aprobó esta cotización.")
        bom = await self.db.get_bom_by_id(conn, cotizacion['bom_id'])

        items_existentes = await self.db.get_items_cotizacion(conn, cotizacion_id)
        ids_existentes = {str(it['bom_item_id']) for it in items_existentes}
        ids_nuevos = {str(i['bom_item_id']) for i in items_data}
        if ids_existentes != ids_nuevos:
            raise ValueError(
                "Solo puedes actualizar el costo de los items existentes; "
                "para agregar o quitar items, libera la cotización y recotiza."
            )
        precios = {str(i['bom_item_id']): Decimal(str(i['precio_unitario'])) for i in items_data}
        if any(p <= 0 for p in precios.values()):
            raise ValueError("Captura un precio mayor a cero para cada item.")

        bom_items = await self.db.get_items_by_ids(
            conn, [it['bom_item_id'] for it in items_existentes]
        )
        bom_items_map = {str(bi['id_item']): bi for bi in bom_items}
        items_calculo = [
            {
                'bom_item_id': it['bom_item_id'],
                'precio_unitario': precios[str(it['bom_item_id'])],
                'cantidad': Decimal(str(it['cantidad'])),
            }
            for it in items_existentes
        ]
        self._validar_sobrecosto(items_calculo, bom_items_map, notas)

        subtotal = sum(i['precio_unitario'] * i['cantidad'] for i in items_calculo)
        iva = round(subtotal * Decimal(str(iva_pct)) / Decimal("100"), 2)
        total = round(subtotal + iva, 2)
        subtotal = round(subtotal, 2)

        async with conn.transaction():
            cotizacion_bloqueada = await self.db.get_cotizacion_for_update(conn, cotizacion_id)
            autorizacion_bloqueada = await self.db.get_autorizacion_for_update(conn, autorizacion['id'])
            if (
                not cotizacion_bloqueada
                or cotizacion_bloqueada['estatus'] != 'SELECCIONADA'
                or cotizacion_bloqueada['lock_version'] != cotizacion_lock_version_esperado
                or not autorizacion_bloqueada
                or autorizacion_bloqueada['estatus'] != 'AUTORIZADO_OBRA'
                or autorizacion_bloqueada['lock_version'] != autorizacion_lock_version_esperado
            ):
                raise ValueError("La cotización o autorización cambió; recarga la pestaña.")

            await self.db.actualizar_items_precio_cotizacion(
                conn, cotizacion_id,
                [
                    {
                        'bom_item_id': i['bom_item_id'],
                        'precio_unitario': i['precio_unitario'],
                        'subtotal_linea': round(i['precio_unitario'] * i['cantidad'], 2),
                    }
                    for i in items_calculo
                ],
            )
            cot_actualizada = await self.db.actualizar_totales_pdf_cotizacion_seleccionada(
                conn, cotizacion_id, subtotal, iva, total, nuevo_pdf_url,
                cotizacion_lock_version_esperado,
            )
            if not cot_actualizada:
                raise ValueError("La cotización cambió; recarga la pestaña.")
            aut_sincronizada = await self.db.sincronizar_monto_autorizacion_db(
                conn, autorizacion['id'], total, autorizacion_lock_version_esperado,
            )
            if not aut_sincronizada:
                raise ValueError("La autorización cambió; recarga la pestaña.")
            await self.db.registrar_evento_outbox(
                conn,
                f"COTIZACION:{cotizacion_id}:{cot_actualizada['lock_version']}:COSTO_ACTUALIZADO_VIGENCIA",
                "COTIZACION_COSTO_ACTUALIZADO_VIGENCIA", bom["id_proyecto"], user_id,
                {
                    "id_cotizacion": str(cotizacion_id),
                    "motivo": motivo.strip(),
                    "total_anterior": str(cotizacion['total']),
                    "total_nuevo": str(total),
                },
                id_paquete=bom.get("id_paquete"), id_bom=cotizacion["bom_id"],
                id_documento=cotizacion_id,
            )

        logger.info(
            "Costo de cotización %s actualizado por vigencia (usuario %s): total %s -> %s",
            cotizacion_id, user_id, cotizacion['total'], total,
        )
        return {**cot_actualizada, "autorizacion_lock_version": aut_sincronizada['lock_version']}

    async def actualizar_costos_y_solicitar_aprobacion(
        self, conn, cotizacion_id: UUID, user_id: UUID,
        items_data: list, iva_pct: float, motivo: str,
        notas: Optional[str] = None, nuevo_pdf_url: Optional[str] = None,
        cotizacion_lock_version_esperado: Optional[int] = None,
        autorizacion_lock_version_esperado: Optional[int] = None,
    ) -> dict:
        """Punto A, Camino 2: actualiza costo/PDF y encadena a
        solicitar_aprobacion_cotizacion(vigente=True) con los locks frescos.
        Ambos pasos comparten una sola transaccion externa -- _actualizar_costos_vigencia
        y solicitar_aprobacion_cotizacion abren cada uno su propio `async with
        conn.transaction()`, que asyncpg anida como SAVEPOINT bajo esta; si el
        segundo paso falla, se revierte el ajuste de costo/PDF del primero en
        vez de dejar la cotizacion repreciada sin una aprobacion en curso."""
        async with conn.transaction():
            actualizada = await self._actualizar_costos_vigencia(
                conn, cotizacion_id, user_id, items_data, iva_pct, motivo,
                notas, nuevo_pdf_url,
                cotizacion_lock_version_esperado, autorizacion_lock_version_esperado,
            )
            return await self.solicitar_aprobacion_cotizacion(
                conn, cotizacion_id, user_id,
                cotizacion_lock_version_esperado=actualizada['lock_version'],
                autorizacion_lock_version_esperado=actualizada['autorizacion_lock_version'],
                vigente=True,
            )

    async def actualizar_costos_y_confirmar_vigencia(
        self, conn, cotizacion_id: UUID, user_id: UUID,
        items_data: list, iva_pct: float, motivo: str,
        notas: Optional[str] = None, nuevo_pdf_url: Optional[str] = None,
        cotizacion_lock_version_esperado: Optional[int] = None,
        aprobacion_lock_version_esperado: Optional[int] = None,
        autorizacion_lock_version_esperado: Optional[int] = None,
    ) -> dict:
        """Punto B, Camino 2: actualiza costo/PDF y encadena a
        confirmar_vigencia_reactivacion(vigente=True) con el lock de autorizacion
        fresco (el de aprobacion no cambia con este ajuste). Misma transaccion
        externa que actualizar_costos_y_solicitar_aprobacion -- ver su docstring."""
        async with conn.transaction():
            actualizada = await self._actualizar_costos_vigencia(
                conn, cotizacion_id, user_id, items_data, iva_pct, motivo,
                notas, nuevo_pdf_url,
                cotizacion_lock_version_esperado, autorizacion_lock_version_esperado,
            )
            return await self.confirmar_vigencia_reactivacion(
                conn, cotizacion_id, user_id, vigente=True,
                aprobacion_lock_version_esperado=aprobacion_lock_version_esperado,
                autorizacion_lock_version_esperado=actualizada['autorizacion_lock_version'],
            )

    async def aprobar_cotizacion_direccion(
        self, conn, cotizacion_id: UUID, user_id: UUID,
        user_role: str, rol_org: Optional[str],
        comentarios: Optional[str] = None,
        aprobacion_lock_version_esperado: Optional[int] = None,
        autorizacion_lock_version_esperado: Optional[int] = None,
    ) -> dict:
        """
        Direccion aprueba la cotizacion (aprobacion documental). Requiere la
        autorizacion Fase D en AUTORIZADO_OBRA (guard duro: si cambio por la
        superficie standalone, se rechaza la operacion); la avanza en la misma
        transaccion y notifica a Finanzas despues del commit (## 8.5).
        """
        aprobacion = await self.db.get_cotizacion_aprobacion_activa(conn, cotizacion_id)
        if not aprobacion or aprobacion['estatus'] != EstatusCotizacionAprobacion.PENDIENTE_DIRECCION:
            raise ValueError("La cotización no tiene una aprobación pendiente de Dirección.")

        await self._require_direccion_titular(conn, user_id, "aprobar")

        if aprobacion_lock_version_esperado is None or autorizacion_lock_version_esperado is None:
            raise ValueError("La aprobación o autorización cambió; recarga la pestaña.")
        async with conn.transaction():
            autorizacion = await self.db.get_autorizacion_by_cotizacion(conn, cotizacion_id)
            if not autorizacion or autorizacion['estatus'] != 'AUTORIZADO_OBRA':
                raise ValueError(
                    "La autorización de compra ya no está aprobada por Obra; "
                    "resuélvela en la pestaña Autorizaciones antes de aprobar la cotización."
                )

            bom = await self.db.get_bom_by_id(conn, aprobacion["bom_id"])
            paquete_bloqueado = await self.db.get_paquete_for_update(conn, bom["id_paquete"])
            await self.db.get_bom_for_update(conn, aprobacion["bom_id"])
            await self.db.get_cotizacion_for_update(conn, cotizacion_id)
            autorizacion_bloqueada = await self.db.get_autorizacion_for_update(
                conn, autorizacion["id"]
            )
            aprobacion_bloqueada = await self.db.get_cotizacion_aprobacion_for_update(
                conn, aprobacion["id"]
            )
            if (
                not paquete_bloqueado
                or paquete_bloqueado["estado_paquete"] != "ACTIVO"
                or not aprobacion_bloqueada
                or aprobacion_bloqueada["estatus"] != "PENDIENTE_DIRECCION"
                or aprobacion_bloqueada["lock_version"] != aprobacion_lock_version_esperado
                or not autorizacion_bloqueada
                or autorizacion_bloqueada["estatus"] != "AUTORIZADO_OBRA"
                or autorizacion_bloqueada["lock_version"] != autorizacion_lock_version_esperado
            ):
                raise ValueError("La aprobacion o autorizacion cambio; recarga la pestaña")
            updated = await self.db.aprobar_cotizacion_aprobacion_db(
                conn, aprobacion['id'], user_id, comentarios,
                aprobacion_lock_version_esperado,
            )
            if not updated:
                raise ValueError("La aprobación ya no está pendiente de Dirección.")

            aut_updated = await self.db.update_autorizacion_paso_direccion(
                conn, autorizacion['id'], user_id, comentarios,
                autorizacion_lock_version_esperado,
            )
            if not aut_updated:
                raise ValueError("La autorizacion cambio; recarga la pestaña")
            await self.db.registrar_evento_outbox(
                conn,
                f"COTIZACION_APROBACION:{updated['id']}:{updated['lock_version']}:APROBADA",
                "COTIZACION_APROBACION_APROBADA", updated["proyecto_id"], user_id,
                {
                    "id_cotizacion": str(cotizacion_id),
                    "id_aprobacion": str(updated["id"]),
                    "id_autorizacion": str(aut_updated["id"]),
                    "estatus": updated["estatus"],
                },
                id_paquete=bom["id_paquete"], id_bom=updated["bom_id"],
                id_documento=updated["id"],
            )
            await self._avanzar_paso_finanzas(
                conn, autorizacion["id"], cotizacion_id, user_id, comentarios,
                aut_updated["lock_version"], updated["proyecto_id"],
                bom["id_paquete"], updated["bom_id"], auto_avance=True,
            )

        logger.info("Cotización %s aprobada por Dirección (usuario %s)", cotizacion_id, user_id)
        return updated

    async def rechazar_cotizacion_direccion(
        self, conn, cotizacion_id: UUID, user_id: UUID, motivo: str,
        user_role: str, rol_org: Optional[str],
        aprobacion_lock_version_esperado: Optional[int] = None,
        autorizacion_lock_version_esperado: Optional[int] = None,
    ) -> dict:
        """
        Direccion rechaza la cotizacion con motivo obligatorio. Requiere la
        autorizacion Fase D en PENDIENTE o AUTORIZADO_OBRA (guard duro simetrico
        al de aprobar). Cancela en cascada la autorizacion (paso
        'RECHAZO_COTIZACION'), libera los items a SIN_COTIZAR para permitir
        reemplazo (## 7.3) y notifica al creador (Compras) despues del commit.
        """
        if not motivo or not motivo.strip():
            raise ValueError("El motivo de rechazo es obligatorio.")

        aprobacion = await self.db.get_cotizacion_aprobacion_activa(conn, cotizacion_id)
        if not aprobacion or aprobacion['estatus'] != EstatusCotizacionAprobacion.PENDIENTE_DIRECCION:
            raise ValueError("La cotización no tiene una aprobación pendiente de Dirección.")

        await self._require_direccion_titular(conn, user_id, "rechazar")

        if aprobacion_lock_version_esperado is None or autorizacion_lock_version_esperado is None:
            raise ValueError("La aprobación o autorización cambió; recarga la pestaña.")
        async with conn.transaction():
            autorizacion = await self.db.get_autorizacion_by_cotizacion(conn, cotizacion_id)
            if not autorizacion or autorizacion['estatus'] not in ('PENDIENTE', 'AUTORIZADO_OBRA'):
                raise ValueError(
                    "La autorización de compra ya avanzó o no existe; "
                    "resuélvela en la pestaña Autorizaciones antes de rechazar la cotización."
                )

            bom = await self.db.get_bom_by_id(conn, aprobacion["bom_id"])
            paquete_bloqueado = await self.db.get_paquete_for_update(conn, bom["id_paquete"])
            await self.db.get_bom_for_update(conn, aprobacion["bom_id"])
            await self.db.get_cotizacion_for_update(conn, cotizacion_id)
            autorizacion_bloqueada = await self.db.get_autorizacion_for_update(
                conn, autorizacion["id"]
            )
            aprobacion_bloqueada = await self.db.get_cotizacion_aprobacion_for_update(
                conn, aprobacion["id"]
            )
            if (
                not paquete_bloqueado
                or paquete_bloqueado["estado_paquete"] != "ACTIVO"
                or not aprobacion_bloqueada
                or aprobacion_bloqueada["estatus"] != "PENDIENTE_DIRECCION"
                or aprobacion_bloqueada["lock_version"] != aprobacion_lock_version_esperado
                or not autorizacion_bloqueada
                or autorizacion_bloqueada["estatus"] != autorizacion["estatus"]
                or autorizacion_bloqueada["lock_version"] != autorizacion_lock_version_esperado
            ):
                raise ValueError("La aprobacion o autorizacion cambio; recarga la pestaña")
            updated = await self.db.rechazar_cotizacion_aprobacion_db(
                conn, aprobacion['id'], user_id, motivo,
                aprobacion_lock_version_esperado,
            )
            if not updated:
                raise ValueError("La aprobación ya no está pendiente de Dirección.")

            rechazada = await self.db.rechazar_autorizacion_db(
                conn, autorizacion['id'], user_id, motivo, 'RECHAZO_COTIZACION',
                autorizacion["estatus"], autorizacion_lock_version_esperado,
            )
            if not rechazada:
                raise ValueError("La autorizacion cambio; recarga la pestaña")
            await self._liberar_cotizacion_rechazada(conn, cotizacion_id)
            await self.db.registrar_evento_outbox(
                conn,
                f"COTIZACION_APROBACION:{updated['id']}:{updated['lock_version']}:RECHAZADA",
                "COTIZACION_APROBACION_RECHAZADA", updated["proyecto_id"], user_id,
                {
                    "id_cotizacion": str(cotizacion_id),
                    "id_aprobacion": str(updated["id"]),
                    "id_autorizacion": str(rechazada["id"]),
                    "estatus": updated["estatus"],
                    "motivo": motivo,
                },
                id_paquete=bom["id_paquete"], id_bom=updated["bom_id"],
                id_documento=updated["id"],
            )

        logger.info(
            "Cotización %s rechazada por Dirección (usuario %s): %s",
            cotizacion_id, user_id, motivo[:80]
        )
        return updated

    async def _standby_o_reprogramar(
        self, conn, cotizacion_id: UUID, user_id: UUID,
        motivo: str, fecha_recordatorio: date,
        aprobacion_lock_version_esperado: Optional[int],
        *, estatus_esperado: str, accion_label: str, db_write,
    ) -> dict:
        """Implementacion compartida de standby_cotizacion_direccion y
        reprogramar_standby_direccion: misma validacion y patron de lock: solo
        cambia el estatus de origen esperado y la funcion CAS a invocar (Gap #9:
        cada CAS sigue siendo literal por transicion a nivel SQL, no
        parametrizada -- lo que se comparte aqui es la orquestacion, no el SQL)."""
        if not motivo or not motivo.strip():
            raise ValueError("El motivo del standby es obligatorio.")
        if not fecha_recordatorio:
            raise ValueError("La fecha de recordatorio es obligatoria.")
        if fecha_recordatorio < today_mx():
            raise ValueError("La fecha de recordatorio no puede ser en el pasado.")
        await self._require_direccion_titular(conn, user_id, accion_label)

        es_standby_nuevo = estatus_esperado == EstatusCotizacionAprobacion.PENDIENTE_DIRECCION
        error_no_elegible = (
            "La cotización no tiene una aprobación pendiente de Dirección."
            if es_standby_nuevo else "La cotización no está en standby."
        )
        aprobacion = await self.db.get_cotizacion_aprobacion_activa(conn, cotizacion_id)
        if not aprobacion or aprobacion['estatus'] != estatus_esperado:
            raise ValueError(error_no_elegible)
        if aprobacion_lock_version_esperado is None:
            raise ValueError("La aprobación cambió; recarga la pestaña.")

        bom = await self.db.get_bom_by_id(conn, aprobacion["bom_id"])
        async with conn.transaction():
            paquete_bloqueado = await self.db.get_paquete_for_update(conn, bom["id_paquete"])
            aprobacion_bloqueada = await self.db.get_cotizacion_aprobacion_for_update(
                conn, aprobacion["id"]
            )
            if (
                not paquete_bloqueado
                or paquete_bloqueado["estado_paquete"] != "ACTIVO"
                or not aprobacion_bloqueada
                or aprobacion_bloqueada["estatus"] != estatus_esperado
                or aprobacion_bloqueada["lock_version"] != aprobacion_lock_version_esperado
            ):
                raise ValueError("La aprobación cambió; recarga la pestaña.")
            updated = await db_write(
                conn, aprobacion["id"], motivo.strip(), fecha_recordatorio,
                aprobacion_lock_version_esperado,
            )
            if not updated:
                raise ValueError(error_no_elegible)

        return updated

    async def standby_cotizacion_direccion(
        self, conn, cotizacion_id: UUID, user_id: UUID,
        motivo: str, fecha_recordatorio: date,
        aprobacion_lock_version_esperado: Optional[int] = None,
    ) -> dict:
        """
        Direccion pone en espera ("standby") una cotizacion pendiente de su
        aprobacion, con motivo y fecha de recordatorio obligatorios (tercera
        opcion junto a aprobar/rechazar). No toca tb_bom_autorizaciones: la Fase D
        queda intacta en AUTORIZADO_OBRA mientras dure la espera.
        """
        updated = await self._standby_o_reprogramar(
            conn, cotizacion_id, user_id, motivo, fecha_recordatorio,
            aprobacion_lock_version_esperado,
            estatus_esperado=EstatusCotizacionAprobacion.PENDIENTE_DIRECCION,
            accion_label="poner en standby",
            db_write=self.db.poner_en_standby_db,
        )
        logger.info(
            "Cotización %s puesta en standby por Dirección (usuario %s), recordatorio %s",
            cotizacion_id, user_id, fecha_recordatorio,
        )
        return updated

    async def reprogramar_standby_direccion(
        self, conn, cotizacion_id: UUID, user_id: UUID,
        motivo: str, fecha_recordatorio: date,
        aprobacion_lock_version_esperado: Optional[int] = None,
    ) -> dict:
        """Reprograma un standby ya activo (nuevo motivo/fecha), sin salir de
        EN_STANDBY. Mismo patron de lock que standby_cotizacion_direccion."""
        updated = await self._standby_o_reprogramar(
            conn, cotizacion_id, user_id, motivo, fecha_recordatorio,
            aprobacion_lock_version_esperado,
            estatus_esperado=EstatusCotizacionAprobacion.EN_STANDBY,
            accion_label="reprogramar el standby de",
            db_write=self.db.reprogramar_standby_db,
        )
        logger.info(
            "Standby de cotización %s reprogramado (usuario %s), nuevo recordatorio %s",
            cotizacion_id, user_id, fecha_recordatorio,
        )
        return updated

    async def confirmar_vigencia_reactivacion(
        self, conn, cotizacion_id: UUID, user_id: UUID,
        vigente: bool, motivo: Optional[str] = None,
        aprobacion_lock_version_esperado: Optional[int] = None,
        autorizacion_lock_version_esperado: Optional[int] = None,
    ) -> dict:
        """
        Punto B del gate de vigencia: Compras confirma si la cotizacion sigue
        vigente tras la reactivacion del standby (PENDIENTE_VIGENCIA_COMPRAS,
        disparada por el worker). Mismo ciclo vigente/no-vigente que el Punto A
        (`solicitar_aprobacion_cotizacion`): si vigente, regresa a
        PENDIENTE_DIRECCION; si no, rechaza la autorizacion Fase D via
        `_rechazar_por_vigencia` y cierra esta aprobacion como RECHAZADA.
        """
        if not vigente and (not motivo or not motivo.strip()):
            raise ValueError("El motivo es obligatorio cuando la cotización ya no está vigente.")

        aprobacion = await self.db.get_cotizacion_aprobacion_activa(conn, cotizacion_id)
        if not aprobacion or aprobacion['estatus'] != EstatusCotizacionAprobacion.PENDIENTE_VIGENCIA_COMPRAS:
            raise ValueError("La cotización no está pendiente de confirmación de vigencia.")

        autorizacion = await self.db.get_autorizacion_by_cotizacion(conn, cotizacion_id)
        if not autorizacion or autorizacion['estatus'] != 'AUTORIZADO_OBRA':
            raise ValueError(
                "La autorización de compra ya no está aprobada por Obra; "
                "resuélvela en la pestaña Autorizaciones."
            )
        if aprobacion_lock_version_esperado is None or autorizacion_lock_version_esperado is None:
            raise ValueError("La aprobación o autorización cambió; recarga la pestaña.")

        bom = await self.db.get_bom_by_id(conn, aprobacion["bom_id"])
        async with conn.transaction():
            paquete_bloqueado = await self.db.get_paquete_for_update(conn, bom["id_paquete"])
            autorizacion_bloqueada = await self.db.get_autorizacion_for_update(
                conn, autorizacion["id"]
            )
            aprobacion_bloqueada = await self.db.get_cotizacion_aprobacion_for_update(
                conn, aprobacion["id"]
            )
            if (
                not paquete_bloqueado
                or paquete_bloqueado["estado_paquete"] != "ACTIVO"
                or not aprobacion_bloqueada
                or aprobacion_bloqueada["estatus"] != "PENDIENTE_VIGENCIA_COMPRAS"
                or aprobacion_bloqueada["lock_version"] != aprobacion_lock_version_esperado
                or not autorizacion_bloqueada
                or autorizacion_bloqueada["lock_version"] != autorizacion_lock_version_esperado
            ):
                raise ValueError("La aprobación o autorización cambió; recarga la pestaña.")

            # Gap #10: replicar bajo lock el guard bloqueado_por_pago de
            # reemplazar_cotizacion_proveedor -- chequeo especifico ANTES del
            # generico "estatus != AUTORIZADO_OBRA" para que la carrera
            # (pago registrado justo entre la pre-lectura y este lock) de un
            # mensaje claro en vez de la staleness generica. Hoy se cumple "por
            # construccion" que un pago nunca llega antes de una aprobacion
            # APROBADA, pero un standby sin tope de dias pudo dejar este
            # registro vivo mucho tiempo -- no hay invariante de BD que lo
            # garantice.
            if autorizacion_bloqueada["estatus"] in ("PAGADO", "PAGO_PARCIAL"):
                raise ValueError(
                    "No se puede confirmar vigencia: la cotización ya tiene pago registrado."
                )
            if autorizacion_bloqueada["estatus"] != "AUTORIZADO_OBRA":
                raise ValueError("La aprobación o autorización cambió; recarga la pestaña.")

            if not vigente:
                await self._rechazar_por_vigencia(
                    conn, autorizacion_bloqueada, cotizacion_id, user_id,
                    motivo.strip(), bom,
                )
                rechazada_aprob = await self.db.rechazar_cotizacion_aprobacion_vigencia_db(
                    conn, aprobacion["id"], user_id, motivo.strip(),
                    aprobacion_lock_version_esperado,
                )
                if not rechazada_aprob:
                    raise ValueError("La aprobación cambió; recarga la pestaña.")
                logger.info(
                    "Cotización %s marcada NO vigente en reactivación de standby (usuario %s)",
                    cotizacion_id, user_id,
                )
                return rechazada_aprob

            reactivada = await self.db.confirmar_vigencia_reactiva_direccion_db(
                conn, aprobacion["id"], aprobacion_lock_version_esperado,
            )
            if not reactivada:
                raise ValueError("La aprobación cambió; recarga la pestaña.")
            await self.db.registrar_evento_outbox(
                conn,
                f"COTIZACION_APROBACION:{reactivada['id']}:{reactivada['lock_version']}:REACTIVADA",
                "COTIZACION_APROBACION_SOLICITADA", reactivada["proyecto_id"], user_id,
                {
                    "id_cotizacion": str(cotizacion_id),
                    "id_aprobacion": str(reactivada["id"]),
                    "estatus": reactivada["estatus"],
                    "reactivada_desde_standby": True,
                },
                id_paquete=bom["id_paquete"], id_bom=reactivada["bom_id"],
                id_documento=reactivada["id"],
            )

        logger.info(
            "Cotización %s vigencia confirmada, regresa a Dirección (usuario %s)",
            cotizacion_id, user_id,
        )
        return reactivada

    async def reemplazar_cotizacion_proveedor(
        self, conn, cotizacion_id: UUID, motivo: str, user_id: UUID,
        user_role: str, rol_org: Optional[str],
        aprobacion_lock_version_esperado: Optional[int] = None,
        autorizacion_lock_version_esperado: Optional[int] = None,
        es_override: bool = False,
        cancelar_definitivo: bool = False,
    ) -> dict:
        """
        Reemplaza una cotizacion ya aprobada por Direccion porque el proveedor
        ya no puede cumplir (plan ## 7.4). No edita la cotizacion original (queda
        como evidencia historica; su CHECK de estatus no admite un valor de
        reemplazo): cancela la autorizacion Fase D asociada (paso
        'REEMPLAZO_PROVEEDOR'), libera sus items a SIN_COTIZAR para que puedan
        recotizarse, y marca la aprobacion como REEMPLAZADA (o
        CANCELADA_PROVEEDOR si `cancelar_definitivo`, sin cotizacion sucesora
        planeada).

        Bloqueado si ya hay pago (autorizacion en PAGADO/PAGO_PARCIAL) o algun
        item ya FACTURADO, salvo `es_override` con ADMIN o Direccion (decision
        de negocio 2026-07-01, plan ## 7.4).
        """
        if not motivo or not motivo.strip():
            raise ValueError("El motivo del reemplazo es obligatorio.")

        aprobacion = await self.db.get_cotizacion_aprobacion_activa(conn, cotizacion_id)
        if aprobacion and aprobacion['estatus'] in (
            EstatusCotizacionAprobacion.EN_STANDBY,
            EstatusCotizacionAprobacion.PENDIENTE_VIGENCIA_COMPRAS,
        ):
            raise ValueError(
                "La cotización está en standby de Dirección; resuelve el standby "
                "antes de reemplazar al proveedor."
            )
        if not aprobacion or aprobacion['estatus'] != EstatusCotizacionAprobacion.APROBADA:
            raise ValueError("Solo se puede reemplazar una cotización ya aprobada por Dirección.")

        autorizacion = await self.db.get_autorizacion_by_cotizacion(conn, cotizacion_id)
        if not autorizacion:
            raise ValueError("La cotización no tiene una autorización de compra asociada.")

        es_admin_o_director = user_role == "ADMIN" or rol_org == "director"
        bloqueado_por_pago = autorizacion['estatus'] in ('PAGADO', 'PAGO_PARCIAL')

        # El estatus de facturacion de los items solo se valida bajo lock (mas
        # abajo, en la transaccion): un pre-check aqui nunca es la fuente de
        # verdad (siempre se re-verifica bajo lock) y duplicaria la consulta.
        if bloqueado_por_pago and not (es_override and es_admin_o_director):
            raise ValueError(
                "No se puede reemplazar: la cotización ya tiene pago registrado. "
                "Solo ADMIN o Dirección pueden autorizar una excepción."
            )

        items_cot = await self.db.get_items_cotizacion(conn, cotizacion_id)
        item_ids = [i['bom_item_id'] for i in items_cot]

        if aprobacion_lock_version_esperado is None or autorizacion_lock_version_esperado is None:
            raise ValueError(
                "Faltan datos del formulario (lock_version de la cotización o su "
                "autorización); recarga la pestaña e intenta de nuevo."
            )

        nuevo_estatus = (
            EstatusCotizacionAprobacion.CANCELADA_PROVEEDOR if cancelar_definitivo
            else EstatusCotizacionAprobacion.REEMPLAZADA
        )

        bom = await self.db.get_bom_by_id(conn, aprobacion["bom_id"])
        async with conn.transaction():
            paquete_bloqueado = await self.db.get_paquete_for_update(conn, bom["id_paquete"])
            aprobacion_bloqueada = await self.db.get_cotizacion_aprobacion_for_update(
                conn, aprobacion["id"]
            )
            autorizacion_bloqueada = await self.db.get_autorizacion_for_update(
                conn, autorizacion["id"]
            )
            if (
                not paquete_bloqueado
                or paquete_bloqueado["estado_paquete"] != "ACTIVO"
                or not aprobacion_bloqueada
                or aprobacion_bloqueada["estatus"] != "APROBADA"
                or aprobacion_bloqueada["lock_version"] != aprobacion_lock_version_esperado
                or not autorizacion_bloqueada
                or autorizacion_bloqueada["estatus"] != autorizacion["estatus"]
                or autorizacion_bloqueada["lock_version"] != autorizacion_lock_version_esperado
            ):
                raise ValueError("La cotización o autorización cambió; recarga la pestaña.")

            bloqueado_por_pago_actual = autorizacion_bloqueada["estatus"] in ('PAGADO', 'PAGO_PARCIAL')
            bloqueado_por_factura_actual = False
            if item_ids:
                bom_items_actuales = await self.db.get_items_by_ids(conn, item_ids)
                bloqueado_por_factura_actual = any(
                    i.get('estatus_compra') == 'FACTURADO' for i in bom_items_actuales
                )
            if (bloqueado_por_pago_actual or bloqueado_por_factura_actual) and not (
                es_override and es_admin_o_director
            ):
                causa = (
                    "ya tiene pago registrado" if bloqueado_por_pago_actual
                    else "tiene ítems ya facturados/conciliados"
                )
                raise ValueError(
                    f"No se puede reemplazar: la cotización {causa}. "
                    "Solo ADMIN o Dirección pueden autorizar una excepción."
                )

            rechazada = await self.db.rechazar_autorizacion_db(
                conn, autorizacion['id'], user_id, motivo, 'REEMPLAZO_PROVEEDOR',
                autorizacion['estatus'], autorizacion_lock_version_esperado,
            )
            if not rechazada:
                raise ValueError("La autorización cambió; recarga la pestaña.")

            await self._liberar_cotizacion_rechazada(
                conn, cotizacion_id,
                resetear_estatus_cotizacion=False, items=items_cot,
            )

            updated = await self.db.marcar_cotizacion_aprobacion_reemplazada(
                conn, aprobacion['id'], nuevo_estatus.value, motivo,
                aprobacion_lock_version_esperado,
            )
            if not updated:
                raise ValueError("La aprobación cambió; recarga la pestaña.")

            await self.db.registrar_evento_outbox(
                conn,
                f"COTIZACION_APROBACION:{updated['id']}:{updated['lock_version']}:REEMPLAZO",
                "COTIZACION_APROBACION_REEMPLAZADA", updated["proyecto_id"], user_id,
                {
                    "id_cotizacion": str(cotizacion_id),
                    "id_aprobacion": str(updated["id"]),
                    "id_autorizacion": str(rechazada["id"]),
                    "estatus": updated["estatus"],
                    "motivo": motivo,
                    "override_admin_direccion": bool(es_override and es_admin_o_director),
                },
                id_paquete=bom["id_paquete"], id_bom=updated["bom_id"],
                id_documento=updated["id"],
            )

        logger.info(
            "Cotización %s reemplazada (aprobación %s -> %s) por usuario %s: %s",
            cotizacion_id, aprobacion['id'], nuevo_estatus.value, user_id, motivo[:80]
        )
        return updated

    async def rechazar_cotizacion(
        self, conn, cotizacion_id: UUID, user_id: UUID,
        lock_version_esperado: Optional[int] = None,
    ) -> dict:
        cotizacion = await self.db.get_cotizacion_by_id(conn, cotizacion_id)
        if not cotizacion:
            raise ValueError("Cotización no encontrada.")
        if cotizacion['estatus'] in ('SELECCIONADA', 'RECHAZADA'):
            raise ValueError(f"La cotización está en estatus {cotizacion['estatus']}.")

        if lock_version_esperado is None:
            raise ValueError("La cotizacion cambio; recarga la pestaña")
        bom = await self.db.get_bom_by_id(conn, cotizacion["bom_id"])
        async with conn.transaction():
            bloqueada = await self.db.get_cotizacion_for_update(conn, cotizacion_id)
            if (
                not bloqueada or bloqueada["estatus"] != cotizacion["estatus"]
                or bloqueada["lock_version"] != lock_version_esperado
            ):
                raise ValueError("La cotizacion ya cambio; recarga la pestaña")
            updated = await self.db.actualizar_estatus_cotizacion(
                conn, cotizacion_id, 'RECHAZADA', cotizacion["estatus"],
                lock_version_esperado,
            )
            if not updated:
                raise ValueError("La cotizacion ya cambio; recarga la pestaña")
            await self.db.registrar_evento_outbox(
                conn,
                f"COTIZACION:{cotizacion_id}:{updated['lock_version']}:RECHAZADA",
                "COTIZACION_RECHAZADA", bom["id_proyecto"], user_id,
                {"id_cotizacion": str(cotizacion_id), "estatus": "RECHAZADA"},
                id_paquete=bom.get("id_paquete"), id_bom=cotizacion["bom_id"],
                id_documento=cotizacion_id,
            )
        logger.info("Cotización %s rechazada por usuario %s", cotizacion_id, user_id)
        return updated

    async def solicitar_aclaracion_cotizacion(
        self, conn, cotizacion_id: UUID, user_id: UUID, motivo: str,
        lock_version_esperado: Optional[int] = None,
    ) -> dict:
        """Devuelve una cotización a BORRADOR con motivo (feedback de aprobador)."""
        if not motivo or not motivo.strip():
            raise ValueError("El motivo de la aclaracion es obligatorio")
        cotizacion = await self.db.get_cotizacion_by_id(conn, cotizacion_id)
        if not cotizacion:
            raise ValueError("Cotización no encontrada.")
        if cotizacion['estatus'] not in ('RECIBIDA', 'BORRADOR'):
            raise ValueError(
                f"La cotización está en estatus {cotizacion['estatus']} y no puede devolverse."
            )
        if lock_version_esperado is None:
            raise ValueError("La cotizacion cambio; recarga la pestaña")
        async with conn.transaction():
            bloqueada = await self.db.get_cotizacion_for_update(conn, cotizacion_id)
            if (
                not bloqueada or bloqueada["estatus"] != cotizacion["estatus"]
                or bloqueada["lock_version"] != lock_version_esperado
            ):
                raise ValueError("La cotizacion ya cambio; recarga la pestaña")
            updated = await self.db.devolver_cotizacion_borrador(
                conn, cotizacion_id, motivo, cotizacion["estatus"],
                lock_version_esperado,
            )
            if not updated:
                raise ValueError("La cotizacion ya cambio; recarga la pestaña")
        logger.info(
            "Cotización %s devuelta a borrador por %s: %s",
            cotizacion_id, user_id, motivo[:80]
        )
        return updated

    async def _subir_pdf_sharepoint_o_raise(
        self, conn, file, user_id: UUID, cotizacion_id: UUID,
    ) -> dict:
        """Sube un PDF de cotizacion a SharePoint (categoria/origen/relacion fijos
        de este dominio) y valida que el upload haya devuelto url_sharepoint.

        El upload a SharePoint (round-trip de red) se hace fuera de la
        transaccion de negocio para no mantener una conexion del pool abierta
        durante esa llamada externa (mismo criterio que
        FinanzasService.registrar_pago). Compartido por subir_pdf_cotizacion
        (Fase C) y el gate de vigencia Puntos A/B en compras_router.py -- antes
        cada uno reimplementaba esta misma llamada."""
        from modules.compras.service import ComprasService

        upload_result = await ComprasService().subir_pdf_mensual(
            conn, file, categoria='bom/cotizaciones',
            origen_slug='cotizacion_bom', user_id=user_id,
            id_bom_cotizacion=cotizacion_id,
        )
        if not upload_result or not upload_result.get('url_sharepoint'):
            raise ValueError("No se pudo subir el PDF a SharePoint")
        return upload_result

    async def _con_cleanup_pdf_huerfano(self, conn, upload_result: Optional[dict], coro):
        """Await `coro`; si levanta ValueError (CAS de lock_version/estatus
        fallido) o asyncpg.PostgresError (la transaccion no se aplico), borra el
        PDF que `upload_result` ya subio a SharePoint para que no quede
        huerfano ligado a la cotizacion, y relanza. Compartido por
        subir_pdf_cotizacion y el gate de vigencia Puntos A/B."""
        try:
            return await coro
        except (ValueError, asyncpg.PostgresError):
            if upload_result:
                doc_id = upload_result.get('id_documento_attachment')
                if doc_id:
                    await self.db.eliminar_attachment_huerfano(conn, doc_id)
            raise

    async def subir_pdf_cotizacion(
        self, conn, cotizacion_id: UUID, file, user_id: UUID,
        lock_version_esperado: Optional[int] = None,
    ) -> dict:
        """Sube el PDF de una cotizacion a SharePoint y actualiza pdf_url (estatus -> RECIBIDA)."""
        if lock_version_esperado is None:
            raise ValueError("La cotizacion cambio; recarga la pestaña")
        cotizacion = await self.db.get_cotizacion_by_id(conn, cotizacion_id)
        if not cotizacion:
            raise ValueError("Cotización no encontrada.")
        aprobacion = await self.db.get_cotizacion_aprobacion_activa(conn, cotizacion_id)
        if aprobacion and aprobacion['estatus'] == 'APROBADA':
            raise ValueError(
                "La cotización ya fue aprobada por Dirección y no puede modificarse."
            )
        self._validar_content_type_pdf(file)

        upload_result = await self._subir_pdf_sharepoint_o_raise(conn, file, user_id, cotizacion_id)
        return await self._con_cleanup_pdf_huerfano(
            conn, upload_result,
            self.actualizar_pdf_cotizacion(
                conn, cotizacion_id, upload_result['url_sharepoint'], lock_version_esperado
            ),
        )

    async def extraer_costos_pdf_cotizacion(self, file) -> dict:
        """Extrae precios candidatos de un PDF de cotizacion de proveedor para
        asistir la captura manual (core/bom/pdf_cotizacion_extractor.py).

        No hace match automatico contra items del BOM ni persiste nada -- es
        solo lectura, para mostrar candidatos en el modal. El PDF se sube a
        SharePoint aparte (subir_pdf_cotizacion) al guardar la cotizacion.
        """
        self._validar_content_type_pdf(file)
        content = await file.read()
        max_size_mb = settings.PDF_MAX_UPLOAD_SIZE_MB
        if len(content) / (1024 * 1024) > max_size_mb:
            raise ValueError(f"El PDF supera el tamaño máximo permitido ({max_size_mb}MB)")
        return await asyncio.to_thread(
            extraer_costos_cotizacion, content, file.filename or "cotizacion.pdf"
        )

    async def get_pdf_cotizacion_bytes(
        self, conn, cotizacion_id: UUID, doc_id: Optional[UUID] = None,
    ) -> tuple:
        """Descarga el PDF (mas reciente o uno especifico) para preview inline.

        Retorna (nombre_archivo, media_type, contenido_bytes).
        """
        documento = await self.db.get_pdf_attachment_cotizacion(conn, cotizacion_id, doc_id)
        if not documento:
            raise ValueError("La cotización no tiene PDF cargado")

        nombre_archivo = documento.get('nombre_archivo') or 'cotizacion.pdf'
        media_type = (documento.get('tipo_contenido') or 'application/pdf').split(';')[0].strip()
        drive_item_id = documento.get('drive_item_id')
        if not drive_item_id:
            raise ValueError("El PDF no tiene archivo descargable asociado")

        from core.integrations.sharepoint import SharePointService
        from core.microsoft import get_ms_auth

        ms_auth = get_ms_auth()
        app_token = await ms_auth.get_application_token()
        if not app_token:
            raise RuntimeError("No se pudo obtener token de SharePoint")
        sharepoint = SharePointService(access_token=app_token)
        config = await sharepoint._resolve_config(conn)
        sharepoint.site_id = config.get("site_id")
        sharepoint.drive_id = config.get("drive_id")
        contenido = await sharepoint.download_bytes_direct_by_item_id(drive_item_id)
        return nombre_archivo, media_type, contenido

    # ─── TRAZABILIDAD BOM ↔ COMPRAS ──────────────────────────

    async def get_items_por_autorizacion(self, conn, autorizacion_id: UUID) -> list:
        """Obtiene los items BOM vinculados a una autorizacion de compra."""
        return await self.db.get_items_by_autorizacion(conn, autorizacion_id)

    async def get_conciliacion(self, conn, autorizacion_id: UUID) -> dict:
        """Datos para la UI de conciliacion factura<->item BOM de una autorizacion.

        Devuelve las dos columnas: `conceptos` (CFDI con su match actual) e `items`
        (items del BOM de la cotizacion, candidatos a asignar).
        """
        conceptos = await self.db.get_conceptos_conciliacion(conn, autorizacion_id)
        items = await self.db.get_items_by_autorizacion(conn, autorizacion_id)
        for item in items:
            grupo_ids = item.get("grupo_ids") or []
            grupo_labels = item.get("grupo_labels") or []
            item["grupos_conciliacion"] = [
                {"id": grupo_id, "label": label}
                for grupo_id, label in zip(grupo_ids, grupo_labels)
            ]
        return {"conceptos": conceptos, "items": items}

    async def confirmar_match_concepto(
        self, conn, historial_id: UUID, id_bom_item: Optional[UUID],
        id_bom_item_anterior: Optional[UUID],
        lock_version_esperado: Optional[int] = None,
        id_grupo: Optional[int] = None,
    ) -> Optional[dict]:
        """Confirma (o desasigna) el match concepto->item declarado por un humano.

        Al asignar, marca el item como FACTURADO (coherente con el auto-link del flujo XML).
        Desasignar no revierte el estatus del item (decision conservadora de B3b).
        Ambas escrituras van en una transaccion: si falla la marca de estatus no queda
        el concepto ligado sin el item en FACTURADO.
        """
        if lock_version_esperado is None:
            raise ValueError("El concepto cambió; recarga la conciliación.")
        async with conn.transaction():
            result = await self.db.confirmar_match_concepto(
                conn, historial_id, id_bom_item, id_bom_item_anterior,
                lock_version_esperado, id_grupo,
            )
            if not result:
                raise ValueError("El concepto cambio; recarga la conciliacion")
            if result and id_bom_item is not None:
                await self._actualizar_estatus_items_por_ids(
                    conn, [id_bom_item], 'FACTURADO'
                )
        return result

    async def get_autorizacion_por_bom_pago(self, conn, id_bom_pago: UUID) -> Optional[dict]:
        """Obtiene la autorizacion a partir del id_bom_pago de finanzas."""
        return await self.db.get_autorizacion_by_bom_pago(conn, id_bom_pago)

    async def get_memoria_match_proveedor(
        self, conn, id_proveedor: UUID, claves: list
    ) -> dict:
        """Memoria proveedor-producto (clave SAT -> id_material_ref) del historial confirmado."""
        return await self.db.get_memoria_match_proveedor(conn, id_proveedor, claves)

    def match_conceptos_a_items(
        self, conceptos: list, bom_items: list, memoria_map: dict = None
    ) -> dict:
        """
        Empareja conceptos de CFDI con items del BOM por niveles de confianza.

        Estrategia (en orden de prioridad):
        1. ALTA - clave SAT exacta: concepto.clave_prod_serv == item.material_clave
           (clave del material interno via id_material_ref). Si varios items comparten
           clave, desempata por cercania de monto contra la linea de cotizacion.
        2. ALTA - memoria proveedor-producto: memoria_map[clave] (id_material_ref aprendido
           del historial) coincide con item.id_material_ref. Mas especifico que el monto.
        3. ALTA - ancla de cotizacion: importe ~= coti_subtotal (la linea que Compras
           declaro al cotizar). Si es match unico, alta confianza.
        4. BAJA - texto: solapamiento de descripcion normalizada, umbral 0.4 (fallback).
        5. Sin match -> None.

        Args:
            memoria_map: dict opcional {clave_prod_serv: id_material_ref} de
                get_memoria_match_proveedor. Si None, se omite el nivel MEMORIA.

        Returns:
            dict {indice_concepto: {'id_item': UUID, 'confianza': str, 'origen': str} | None}
            confianza: 'ALTA' | 'BAJA' ; origen: 'CLAVE_SAT' | 'MEMORIA' | 'COTIZACION' | 'TEXTO'.
        """
        memoria_map = memoria_map or {}

        def normalizar(texto):
            if not texto:
                return ""
            return re.sub(r'\s+', ' ', str(texto).strip().upper())

        def to_float(valor):
            try:
                return float(valor) if valor is not None else None
            except (TypeError, ValueError):
                return None

        def monto_cercano(a, b, rel=0.01, abs_tol=1.0):
            if a is None or b is None or b == 0:
                return False
            return abs(a - b) <= max(abs_tol, abs(b) * rel)

        def score_texto(desc_concepto, desc_item):
            if not desc_concepto or not desc_item:
                return 0.0
            palabras_concepto = set(desc_concepto.split())
            palabras_item = set(desc_item.split())
            comunes = palabras_concepto & palabras_item
            token_score = len(comunes) / max(len(palabras_concepto), 1)
            len_ratio = min(len(desc_concepto), len(desc_item)) / max(
                len(desc_concepto), len(desc_item), 1
            )
            return (token_score * 0.7) + (len_ratio * 0.3)

        match_map = {}
        used_item_ids: set = set()

        for idx, concepto in enumerate(conceptos):
            desc_concepto = normalizar(concepto.get('descripcion', ''))
            clave_concepto = (concepto.get('clave_prod_serv') or '').strip()
            importe_concepto = to_float(concepto.get('importe'))

            available = [i for i in bom_items if str(i['id_item']) not in used_item_ids]

            # 1. ALTA - clave SAT exacta (con desempate por monto si hay empate)
            candidatos_clave = [
                item for item in available
                if clave_concepto and len(clave_concepto) >= 6
                and (item.get('material_clave') or '').strip() == clave_concepto
            ]
            if candidatos_clave:
                mejor = min(
                    candidatos_clave,
                    key=lambda it: abs(
                        (importe_concepto or 0) - (to_float(it.get('coti_subtotal')) or 0)
                    ),
                )
                match_map[idx] = {
                    'id_item': mejor['id_item'], 'confianza': 'ALTA', 'origen': 'CLAVE_SAT',
                }
                used_item_ids.add(str(mejor['id_item']))
                continue

            # 2. ALTA - memoria proveedor-producto: material aprendido para esta clave
            material_recordado = memoria_map.get(clave_concepto) if clave_concepto else None
            if material_recordado:
                candidatos_mem = [
                    item for item in available
                    if item.get('id_material_ref') == material_recordado
                ]
                if candidatos_mem:
                    mejor = min(
                        candidatos_mem,
                        key=lambda it: abs(
                            (importe_concepto or 0) - (to_float(it.get('coti_subtotal')) or 0)
                        ),
                    )
                    match_map[idx] = {
                        'id_item': mejor['id_item'], 'confianza': 'ALTA', 'origen': 'MEMORIA',
                    }
                    used_item_ids.add(str(mejor['id_item']))
                    continue

            # 3. ALTA - ancla de cotizacion: monto ~= subtotal de la linea declarada
            candidatos_monto = [
                item for item in available
                if monto_cercano(importe_concepto, to_float(item.get('coti_subtotal')))
            ]
            if len(candidatos_monto) == 1:
                match_map[idx] = {
                    'id_item': candidatos_monto[0]['id_item'],
                    'confianza': 'ALTA', 'origen': 'COTIZACION',
                }
                used_item_ids.add(str(candidatos_monto[0]['id_item']))
                continue
            if len(candidatos_monto) > 1:
                # Empate de montos: desempata por texto entre los candidatos
                mejor = max(
                    candidatos_monto,
                    key=lambda it: score_texto(desc_concepto, normalizar(it.get('descripcion', ''))),
                )
                match_map[idx] = {
                    'id_item': mejor['id_item'], 'confianza': 'ALTA', 'origen': 'COTIZACION',
                }
                used_item_ids.add(str(mejor['id_item']))
                continue

            # 4. BAJA - similitud de texto (fallback)
            best_item, best_score = None, 0.0
            for item in available:
                score = score_texto(desc_concepto, normalizar(item.get('descripcion', '')))
                if score > best_score:
                    best_score, best_item = score, item

            if best_item and best_score >= 0.4:
                match_map[idx] = {
                    'id_item': best_item['id_item'], 'confianza': 'BAJA', 'origen': 'TEXTO',
                }
                used_item_ids.add(str(best_item['id_item']))
            else:
                match_map[idx] = None

        return match_map

    async def actualizar_estatus_compra(
        self, conn, item_ids: list, nuevo_estatus: str
    ) -> None:
        """Actualiza estatus_compra de items BOM en lote."""
        uuid_ids = [UUID(str(i)) for i in item_ids]
        await self._actualizar_estatus_items_por_ids(
            conn, uuid_ids, nuevo_estatus
        )

    # ─── RFQ (doc 35) ────────────────────────────────────────

    async def _siguiente_nombre_rfq_disponible(self, conn, base_nombre: str) -> str:
        """base_nombre si esta libre; si no, el siguiente sufijo '-N' disponible.

        Solo aplica al nombre autogenerado -- uno capturado a mano nunca pasa por
        aqui y puede repetirse a proposito.
        """
        existentes = await self.db.get_rfq_nombres_similares(conn, base_nombre)
        if not existentes:
            return base_nombre
        max_sufijo = 1
        for n in existentes:
            if n == base_nombre:
                continue
            sufijo = n[len(base_nombre) + 1:]
            if sufijo.isdigit():
                max_sufijo = max(max_sufijo, int(sufijo))
        return f"{base_nombre}-{max_sufijo + 1}"

    async def crear_rfq(
        self, conn, id_bom: UUID, item_ids: list, creado_por: UUID,
        notas: Optional[str] = None, nombre: Optional[str] = None,
    ) -> dict:
        """Crea un RFQ (sin proveedor ni precios) con los items seleccionados.

        No bloquea items ni cambia su estatus_compra/estatus_ejecucion -- instruccion
        explicita del usuario: seleccionar items para un RFQ es solo para generar el PDF,
        nunca debe crear un candado que impida a Ingenieria/Construccion seguir editando.
        """
        bom = await self.get_bom(conn, id_bom)
        if EstatusBOM(bom['estatus']) not in ESTATUS_COTIZABLE:
            raise ValueError("Solo se pueden crear RFQ en BOMs aprobados por Construccion.")
        if not item_ids:
            raise ValueError("Selecciona al menos un item para el RFQ.")

        item_ids_unicos = list(dict.fromkeys(item_ids))
        items_bd = await self.db.get_items_by_ids(conn, item_ids_unicos)
        if len(items_bd) != len(item_ids_unicos):
            raise ValueError("El RFQ contiene items invalidos o inactivos")
        if any(str(i.get("id_bom")) != str(id_bom) for i in items_bd):
            raise ValueError("El RFQ no puede mezclar items de otro paquete BOM")

        items_disponibles = [i for i in items_bd if item_disponible_cotizacion(i)]
        if not items_disponibles:
            raise ValueError(
                "Todos los items seleccionados ya están autorizados, pagados o facturados"
            )

        items_insert = [
            {"bom_item_id": i["id_item"], "cantidad": cantidad_pendiente_item(i)}
            for i in items_disponibles
        ]
        async with conn.transaction():
            if not nombre:
                proyecto_id_estandar = bom.get('proyecto_id_estandar') or 'SIN-ID'
                base_nombre = f"RFQ_{proyecto_id_estandar}_{today_mx().strftime('%y%m%d')}"
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", base_nombre)
                nombre = await self._siguiente_nombre_rfq_disponible(conn, base_nombre)
            rfq = await self.db.crear_rfq(conn, id_bom, creado_por, notas, nombre)
            await self.db.agregar_items_rfq(conn, rfq['id'], items_insert)
            await self.db.registrar_historial_rfq(
                conn, rfq['id'], creado_por, 'CREADO',
                {"total_items": len(items_insert)},
            )
        logger.info(
            "RFQ %s creado para BOM %s con %d items por %s",
            rfq['id'], id_bom, len(items_insert), creado_por
        )
        return {**rfq, "total_items": len(items_insert)}

    async def renombrar_rfq(
        self, conn, rfq_id: UUID, nombre: str, lock_version_esperado: Optional[int] = None,
    ) -> dict:
        if not nombre or not nombre.strip():
            raise ValueError("El nombre no puede estar vacío")
        if not await self.db.get_rfq_by_id(conn, rfq_id):
            raise ValueError("RFQ no encontrado")
        if lock_version_esperado is None:
            raise ValueError("El RFQ cambio; recarga la pestaña")

        actualizado = await self.db.renombrar_rfq(conn, rfq_id, nombre.strip(), lock_version_esperado)
        if not actualizado:
            if await self.db.rfq_tiene_pago_asignado(conn, rfq_id):
                raise ValueError(
                    "Este RFQ ya tiene un pago asignado y los pagos se concilian por su "
                    "nombre; ya no puede renombrarse"
                )
            raise ValueError("El RFQ cambio; recarga la pestaña")
        return actualizado

    async def agregar_item_rfq(
        self, conn, rfq_id: UUID, bom_item_id: UUID, cantidad,
        unidad_override: Optional[str], user_id: UUID,
        lock_version_esperado: Optional[int] = None,
    ) -> dict:
        rfq = await self.db.get_rfq_by_id(conn, rfq_id)
        if not rfq:
            raise ValueError("RFQ no encontrado")
        if lock_version_esperado is None:
            raise ValueError("El RFQ cambio; recarga la pestaña")
        items_bd = await self.db.get_items_by_ids(conn, [bom_item_id])
        if not items_bd or str(items_bd[0].get("id_bom")) != str(rfq["bom_id"]):
            raise ValueError("El item no pertenece a este BOM")
        if not item_disponible_cotizacion(items_bd[0]):
            raise ValueError(
                "Este item ya está autorizado, pagado o facturado y no puede agregarse al RFQ"
            )
        cantidad_decimal = Decimal(str(cantidad))
        cantidad_pendiente = cantidad_pendiente_item(items_bd[0])
        if cantidad_decimal > cantidad_pendiente:
            raise ValueError(
                f"La cantidad no puede superar el remanente pendiente del item ({cantidad_pendiente})"
            )
        async with conn.transaction():
            actualizado = await self.db.incrementar_lock_rfq(conn, rfq_id, lock_version_esperado)
            if not actualizado:
                raise ValueError("El RFQ cambio; recarga la pestaña")
            insertados = await self.db.agregar_items_rfq(conn, rfq_id, [{
                "bom_item_id": bom_item_id,
                "cantidad": cantidad_decimal,
                "unidad_override": (unidad_override or "").strip() or None,
            }])
            if not insertados:
                raise ValueError("El item ya está en este RFQ")
            await self.db.registrar_historial_rfq(
                conn, rfq_id, user_id, 'ITEM_AGREGADO', {"bom_item_id": str(bom_item_id)},
            )
        return actualizado

    async def quitar_item_rfq(
        self, conn, rfq_id: UUID, bom_item_id: UUID, user_id: UUID,
        lock_version_esperado: Optional[int] = None,
    ) -> dict:
        rfq = await self.db.get_rfq_by_id(conn, rfq_id)
        if not rfq:
            raise ValueError("RFQ no encontrado")
        if lock_version_esperado is None:
            raise ValueError("El RFQ cambio; recarga la pestaña")
        async with conn.transaction():
            actualizado = await self.db.incrementar_lock_rfq(conn, rfq_id, lock_version_esperado)
            if not actualizado:
                raise ValueError("El RFQ cambio; recarga la pestaña")
            eliminados = await self.db.quitar_item_rfq(conn, rfq_id, bom_item_id)
            if not eliminados:
                raise ValueError("El item no esta en este RFQ")
            await self.db.registrar_historial_rfq(
                conn, rfq_id, user_id, 'ITEM_QUITADO', {"bom_item_id": str(bom_item_id)},
            )
        return actualizado

    async def actualizar_unidad_item_rfq(
        self, conn, rfq_id: UUID, bom_item_id: UUID, unidad_override: Optional[str],
        user_id: UUID, lock_version_esperado: Optional[int] = None,
    ) -> dict:
        rfq = await self.db.get_rfq_by_id(conn, rfq_id)
        if not rfq:
            raise ValueError("RFQ no encontrado")
        if lock_version_esperado is None:
            raise ValueError("El RFQ cambio; recarga la pestaña")
        unidad_override = (unidad_override or "").strip() or None
        async with conn.transaction():
            actualizado = await self.db.incrementar_lock_rfq(conn, rfq_id, lock_version_esperado)
            if not actualizado:
                raise ValueError("El RFQ cambio; recarga la pestaña")
            afectados = await self.db.actualizar_unidad_item_rfq(
                conn, rfq_id, bom_item_id, unidad_override,
            )
            if not afectados:
                raise ValueError("El item no esta en este RFQ")
            await self.db.registrar_historial_rfq(
                conn, rfq_id, user_id, 'ITEM_UNIDAD_ACTUALIZADA',
                {"bom_item_id": str(bom_item_id), "unidad_override": unidad_override},
            )
        return actualizado

    async def listar_historial_rfq(self, conn, rfq_id: UUID) -> list:
        return await self.db.get_historial_rfq(conn, rfq_id)

    async def generar_pdf_rfq(self, conn, rfq_id: UUID, user_id: UUID) -> tuple:
        """Genera el PDF neutro del RFQ (sin datos de proveedor) con membrete de Enertika.
        Retorna (pdf_bytes, filename).
        """
        rfq = await self.db.get_rfq_by_id(conn, rfq_id)
        if not rfq:
            raise ValueError("RFQ no encontrado")
        items = await self.db.get_items_rfq(conn, rfq_id)
        if not items:
            raise ValueError("El RFQ no tiene items; agrega al menos uno antes de generar el PDF")
        bom = await self.db.get_bom_by_id(conn, rfq["bom_id"])
        proyecto = (
            await self.get_proyecto_info(conn, bom["id_proyecto"])
            if bom and bom.get("id_proyecto") else None
        )
        from core.cfdi.db_service import get_cfdi_db_service
        empresa = await get_cfdi_db_service().get_config_empresa(conn)

        from core.pdf_service.service import get_pdf_service
        pdf_service = get_pdf_service()
        pdf_bytes = await pdf_service.generate(
            "bom/rfq.html",
            {
                "rfq": rfq,
                "items": items,
                "proyecto": proyecto,
                "empresa": empresa,
            },
        )
        proyecto_codigo = (proyecto or {}).get("proyecto_id_estandar") or str(rfq_id)[:8]
        filename = pdf_service.generate_filename("RFQ", proyecto_codigo)
        await self.db.registrar_historial_rfq(conn, rfq_id, user_id, 'PDF_GENERADO')
        return pdf_bytes, filename

    # ─── COMPARATIVA RFQ (Gap 7d) ───────────────────────────

    async def get_rfqs(self, conn, id_bom: UUID) -> list:
        return await self.db.get_rfqs_by_bom(conn, id_bom)

    async def get_rfqs_cross_proyecto(self, conn) -> list:
        return await self.db.get_rfqs_cross_proyecto(conn)

    async def get_items_rfq(self, conn, rfq_id: UUID) -> list:
        return await self.db.get_items_rfq(conn, rfq_id)

    async def get_rfq_responses(self, conn, rfq_id: UUID) -> list:
        return await self.db.get_rfq_responses(conn, rfq_id)

    async def bulk_asignar_items(
        self, conn, cotizacion_id: UUID, item_ids: list,
        precio_unitario: float = None, moneda: str = "MXN",
        lock_version_esperado: Optional[int] = None,
    ) -> None:
        """Asigna items a una cotización de proveedor (reemplaza items existentes)."""
        cotizacion = await self.db.get_cotizacion_by_id(conn, cotizacion_id)
        if not cotizacion:
            raise ValueError("Cotización no encontrada.")
        if cotizacion['estatus'] in ('SELECCIONADA', 'RECHAZADA'):
            raise ValueError(f"La cotización está en estatus {cotizacion['estatus']} y no puede modificarse.")
        if lock_version_esperado is None:
            raise ValueError("La cotizacion cambio; recarga la comparativa")
        item_ids = list(dict.fromkeys(UUID(str(iid)) for iid in item_ids))
        if item_ids:
            bom_items = await self.db.get_items_by_ids(conn, item_ids)
            if len(bom_items) != len(item_ids) or any(
                str(item.get("id_bom")) != str(cotizacion["bom_id"])
                for item in bom_items
            ):
                raise ValueError("No se pueden asignar items de otro paquete BOM")
            await self._validar_items_cotizables(
                conn, bom_items, "asignar en bulk a cotizaciones de", cotizacion_id,
                verificar_cotizacion_activa=False,
            )
        moneda_cotizacion = (cotizacion.get("moneda") or "").strip().upper()
        if moneda_cotizacion not in {"MXN", "USD"}:
            raise ValueError("La cotización no tiene una moneda válida")
        precio_bulk = (
            Decimal(str(precio_unitario))
            if precio_unitario is not None else None
        )
        items = [
            {
                'bom_item_id': iid,
                'precio_unitario': precio_bulk,
                'cantidad': 1,
                'moneda': moneda_cotizacion,
                'subtotal_linea': (
                    precio_bulk if precio_bulk and precio_bulk > 0 else None
                ),
            }
            for iid in item_ids
        ]
        async with conn.transaction():
            bom = await self.db.get_bom_for_update(conn, cotizacion["bom_id"])
            if not bom or not self._es_cabeza_cotizable(bom):
                raise ValueError("El BOM de la cotizacion ya no es la version vigente")
            bloqueada = await self.db.get_cotizacion_for_update(conn, cotizacion_id)
            if (
                not bloqueada
                or bloqueada["estatus"] != cotizacion["estatus"]
                or bloqueada["lock_version"] != lock_version_esperado
            ):
                raise ValueError("La cotizacion cambio; recarga la comparativa")
            if item_ids:
                bloqueados = await self.db.lock_items_context_by_ids(
                    conn, sorted(item_ids, key=str)
                )
                if len(bloqueados) != len(item_ids) or any(
                    str(item.get("id_bom")) != str(cotizacion["bom_id"])
                    for item in bloqueados
                ):
                    raise ValueError("No se pueden asignar items de otro paquete BOM")
                await self._validar_items_cotizables(
                    conn, bloqueados, "asignar en bulk a cotizaciones de", cotizacion_id
                )
            await self.db.bulk_replace_cotizacion_items(
                conn, cotizacion_id, cotizacion["bom_id"], items
            )
            actualizada = await self.db.incrementar_lock_cotizacion_cas(
                conn, cotizacion_id, cotizacion["estatus"], lock_version_esperado
            )
            if not actualizada:
                raise ValueError("La cotizacion cambio; recarga la comparativa")

    async def get_proveedores_buscar(self, conn, q: str) -> List[dict]:
        return await self.db.get_proveedores_buscar(conn, q)
