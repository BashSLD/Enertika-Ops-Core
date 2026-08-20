"""
BOM – Compras: cotizaciones, RFQ, autorizaciones Fase D, conciliacion y match.
Mixin incluido en BomService; los metodos usan self.db y self.get_bom.
"""

import logging
import re
from decimal import Decimal
from uuid import UUID
from typing import Optional, List

import asyncpg

from core.bom.schemas import EstatusBOM, EstatusCotizacionAprobacion
from core.timezone import today_mx

logger = logging.getLogger("BOM.Service")

ESTATUS_COTIZABLE = {EstatusBOM.APROBADO_CONST, EstatusBOM.EN_REVISION_FINAL, EstatusBOM.APROBADO_FINAL}
ESTATUS_ITEM_CERRADO_COMPRA = {"NO_ADQUIRIDO", "REEMPLAZADO", "CERRADO"}
ESTATUS_COMPRA_BLOQUEA_ADENDA = {"COTIZADO", "AUTORIZADO", "PAGADO", "FACTURADO"}
ESTATUS_ADENDA_APROBADA = "APROBADA"


def item_disponible_cotizacion(item: dict) -> bool:
    """True si el item BOM todavia puede entrar a una cotizacion o RFQ nueva."""
    estatus_compra = item.get("estatus_compra", "SIN_COTIZAR")
    estatus_ejecucion = item.get("estatus_ejecucion")
    return (
        estatus_compra not in ESTATUS_COMPRA_BLOQUEA_ADENDA
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

    async def resolver_bom_cotizable(self, conn, id_paquete: UUID) -> dict:
        """Resuelve, a partir del paquete, el BOM relevante para Compras hoy: la
        cabeza de trabajo, salvo que haya retrabajo en curso tras APROBADO_FINAL
        (una nueva version en BORRADOR/revision), en cuyo caso Compras se queda
        en la cabeza oficial — misma regla que valida `_es_cabeza_cotizable`."""
        bom = await self.get_bom_cabeza_trabajo(conn, id_paquete)
        if EstatusBOM(bom["estatus"]) != EstatusBOM.APROBADO_FINAL:
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

    def _validar_items_cotizables(self, bom_items: list, accion: str) -> None:
        """Valida que ningún item esté cerrado, en adenda pendiente, o ya comprometido en otra cotizacion."""
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
            [i for i in bom_items if i.get("estatus_compra") in ESTATUS_COMPRA_BLOQUEA_ADENDA],
            f"No se pueden {accion} items ya cotizados, autorizados, pagados o facturados en otra cotizacion",
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

    async def _actualizar_estatus_items_por_ids(
        self, conn, item_ids: list[UUID], nuevo_estatus: str,
        updated_by: Optional[UUID] = None,
    ) -> None:
        """Serializa el espejo legacy y la ejecución con el lock exacto de cada ítem."""
        ids = sorted(set(item_ids), key=str)
        if not ids:
            return
        bloqueados = await self.db.lock_items_context_by_ids(conn, ids)
        if len(bloqueados) != len(ids):
            raise ValueError("Uno de los items cambió; recarga el paquete")
        locks_ejecucion = {
            str(item["id_item"]): int(item.get("ejecucion_lock_version") or 0)
            for item in bloqueados
        }
        await self.db.actualizar_estatus_compra_items(conn, ids, nuevo_estatus)
        estado_ejecucion = (
            "PENDIENTE" if nuevo_estatus == "SIN_COTIZAR" else nuevo_estatus
        )
        for item_id in ids:
            ejecucion = await self.db.upsert_item_ejecucion(
                conn,
                item_id,
                updated_by=updated_by,
                lock_version_esperado=locks_ejecucion[str(item_id)],
                estatus_ejecucion=estado_ejecucion,
            )
            if not ejecucion:
                raise ValueError(
                    "La ejecución de un item cambió; recarga el paquete"
                )

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

        return cotizaciones

    async def crear_cotizacion(
        self, conn, id_bom: UUID, proveedor_id: Optional[UUID],
        nombre_proveedor: Optional[str], moneda: str,
        items_data: list, iva_pct: float, notas: Optional[str],
        creado_por: UUID,
        subtotal_externo: Optional[float] = None,
        bom_lock_version_esperado: Optional[int] = None,
        rfq_id: Optional[UUID] = None,
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
        moneda = (moneda or "").strip().upper()
        if moneda not in {"MXN", "USD"}:
            raise ValueError("La moneda de la cotizacion debe ser MXN o USD")
        if rfq_id:
            rfq = await self.db.get_rfq_by_id(conn, rfq_id)
            if not rfq or str(rfq["bom_id"]) != str(id_bom):
                raise ValueError("El RFQ no pertenece a este BOM")

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
        self._validar_items_cotizables(bom_items_batch, "cotizar")

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
            sobrecostos = []
            for i in items_data:
                pu = Decimal(str(i.get('precio_unitario') or 0))
                if pu <= 0:
                    continue
                bom_item = bom_items_map_cot.get(str(i['bom_item_id']))
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
        async with conn.transaction():
            bom_bloqueado = await self.db.get_bom_for_update(conn, id_bom)
            if (
                not bom_bloqueado
                or bom_bloqueado["lock_version"] != bom_lock_version_esperado
                or bom_bloqueado["estatus"] != bom["estatus"]
                or not self._es_cabeza_cotizable(bom_bloqueado)
            ):
                raise ValueError(
                    "El BOM cambio desde que abriste la cotizacion; recarga el paquete"
                )
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
            self._validar_items_cotizables(items_bloqueados, "cotizar")
            cotizacion = await self.db.crear_cotizacion(
                conn, id_bom, proveedor_id, nombre_proveedor, moneda,
                round(subtotal, 2), iva, total, notas, creado_por,
                rfq_id=rfq_id,
            )
            await self.db.agregar_items_cotizacion(
                conn, cotizacion['id'], id_bom, items_insert
            )

        logger.info(
            "Cotización %s creada para BOM %s por usuario %s",
            cotizacion['id'], id_bom, creado_por
        )
        return cotizacion

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
            self._validar_items_cotizables(bom_items, "seleccionar cotizaciones con")

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
                self._validar_items_cotizables(bloqueados, "seleccionar cotizaciones con")
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

            # Actualizar estatus_compra de los ítems cubiertos
            if items:
                item_ids = [i['bom_item_id'] for i in items]
                # items ya cargados arriba — llamada directa para evitar re-fetch en _actualizar_estatus_items_cotizacion
                await self.db.actualizar_estatus_compra_items(conn, item_ids, 'COTIZADO')

                # Registrar costo/proveedor reales sin mutar el presupuesto base.
                for it in items:
                    campos_reales = {
                        'id_proveedor_real': cotizacion.get('proveedor_id'),
                        'moneda_real': it.get('moneda') or cotizacion.get('moneda'),
                        'estatus_ejecucion': 'COTIZADO',
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

            # Crear autorización de compra (Fase D) si no existe ya; si quedó
            # RECHAZADA de un ciclo anterior, reabrirla a PENDIENTE (nuevo ciclo)
            existente = await self.db.get_autorizacion_by_cotizacion(conn, cotizacion_id)
            if not existente or existente.get('estatus') == 'RECHAZADO':
                bom = await self.db.get_bom_by_id(conn, cotizacion['bom_id'])
                tc_valor = None
                if cotizacion['moneda'] == 'USD':
                    resuelto = await self.resolver_tipo_cambio(conn, bom['id_proyecto'])
                    if not resuelto["tasa"]:
                        raise ValueError(
                            "No hay tipo de cambio vigente para autorizar la cotizacion"
                        )
                    tc_valor = resuelto["tasa"]
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

    async def listar_autorizaciones(self, conn, bom_id: UUID) -> list:
        return await self.db.get_autorizaciones_by_bom(conn, bom_id)

    async def aprobar_obra(
        self, conn, autorizacion_id: UUID, user_id: UUID, nota: Optional[str],
        user_role: str, lock_version_esperado: Optional[int] = None,
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
        if coordinador_obra:
            if coordinador_obra not in representados:
                raise ValueError(
                    "Solo el coordinador de obra del proyecto o su suplente puede aprobar este paso."
                )
        elif not await self.db.usuario_tiene_rol_org(
            conn, user_id, "jefe_construccion"
        ):
            raise ValueError(
                "No hay coordinador de obra asignado. Solo el jefe de Construccion puede aprobar este paso."
            )

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

    async def aprobar_direccion(
        self, conn, autorizacion_id: UUID, user_id: UUID, nota: Optional[str],
        user_role: str, rol_org: Optional[str],
        lock_version_esperado: Optional[int] = None,
    ) -> dict:
        """Aprueba paso 2 el aprobador de Dirección o su suplente activo."""
        aut = await self.db.get_autorizacion_by_id(conn, autorizacion_id)
        if not aut:
            raise ValueError("Autorización no encontrada.")
        if aut['estatus'] != 'AUTORIZADO_OBRA':
            raise ValueError(f"La autorización está en estatus {aut['estatus']} y no puede aprobarse en este paso.")

        aprobador_direccion = await self.db.get_aprobador_final_id(conn)
        representados = await self.get_titulares_que_representa(conn, user_id)
        if not aprobador_direccion or aprobador_direccion not in representados:
            raise ValueError("Solo el aprobador de Direccion o su suplente puede aprobar este paso.")

        if lock_version_esperado is None:
            raise ValueError("La autorizacion cambio; recarga la pestaña")
        bom = await self.db.get_bom_by_id(conn, aut["bom_id"])
        async with conn.transaction():
            bloqueada = await self.db.get_autorizacion_for_update(conn, autorizacion_id)
            if (
                not bloqueada or bloqueada["estatus"] != "AUTORIZADO_OBRA"
                or bloqueada["lock_version"] != lock_version_esperado
            ):
                raise ValueError("La autorizacion ya cambio; recarga la pestaña")
            updated_direccion = await self.db.update_autorizacion_paso_direccion(
                conn, autorizacion_id, user_id, nota, lock_version_esperado
            )
            if not updated_direccion:
                raise ValueError("La autorizacion ya cambio; recarga la pestaña")
            await self.db.registrar_evento_outbox(
                conn,
                f"AUTORIZACION:{autorizacion_id}:{updated_direccion['lock_version']}:DIRECCION",
                "AUTORIZACION_DIRECCION", aut["proyecto_id"], user_id,
                {"id_autorizacion": str(autorizacion_id), "estatus": updated_direccion["estatus"]},
                id_paquete=bom.get("id_paquete"), id_bom=aut["bom_id"],
                id_documento=autorizacion_id,
            )
            updated = await self._avanzar_paso_finanzas(
                conn, autorizacion_id, aut["cotizacion_id"], user_id, nota,
                updated_direccion["lock_version"], aut["proyecto_id"], bom.get("id_paquete"),
                aut["bom_id"], auto_avance=True,
            )

        logger.info("Autorización %s aprobada (dirección→finanzas) por usuario %s", autorizacion_id, user_id)
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
        await self._actualizar_estatus_items_cotizacion(conn, cotizacion_id, 'AUTORIZADO')
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

        # Determinar paso y validar permisos
        if estatus == 'PENDIENTE':
            paso = 'OBRA'
            bom = await self.db.get_bom_by_id(conn, aut['bom_id'])
            representados = await self.get_titulares_que_representa(conn, user_id)
            coordinador_obra = bom.get('coordinador_obra')
            if coordinador_obra:
                if coordinador_obra not in representados:
                    raise ValueError(
                        "Solo el coordinador de obra o su suplente puede rechazar en este paso."
                    )
            elif not await self.db.usuario_tiene_rol_org(
                conn, user_id, "jefe_construccion"
            ):
                raise ValueError(
                    "No hay coordinador de obra asignado. Solo el jefe de Construccion puede rechazar en este paso."
                )
        elif estatus == 'AUTORIZADO_OBRA':
            paso = 'DIRECCION'
            aprobador_direccion = await self.db.get_aprobador_final_id(conn)
            representados = await self.get_titulares_que_representa(conn, user_id)
            if not aprobador_direccion or aprobador_direccion not in representados:
                raise ValueError(
                    "Solo el aprobador de Direccion o su suplente puede rechazar en este paso."
                )
        elif estatus == 'AUTORIZADO_DIRECCION':
            paso = 'FINANZAS'
            es_finanzas = finanzas_role in ('editor', 'admin')
            if not es_finanzas:
                raise ValueError("Solo usuarios del módulo Finanzas pueden rechazar en este paso.")
        else:
            raise ValueError(f"La autorización no puede rechazarse en estatus {estatus}.")

        bom = await self.db.get_bom_by_id(conn, aut['bom_id'])
        if lock_version_esperado is None:
            raise ValueError("La autorizacion cambio; recarga la pestaña")
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
        item_ids: Optional[list] = None,
    ) -> None:
        """Libera los items de una cotización a SIN_COTIZAR tras un rechazo o reemplazo.

        Por defecto regresa `tb_bom_cotizaciones.estatus` a RECIBIDA (rechazo
        normal, ## 7.3). `reemplazar_cotizacion_proveedor` pasa
        `resetear_estatus_cotizacion=False`: su CHECK no admite un valor de
        reemplazo, la cotización se conserva SELECCIONADA como evidencia
        histórica (## 7.4).
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
        await self._actualizar_estatus_items_cotizacion(
            conn, cotizacion_id, 'SIN_COTIZAR', item_ids=item_ids
        )

    async def solicitar_aprobacion_cotizacion(
        self, conn, cotizacion_id: UUID, user_id: UUID,
        comentarios: Optional[str] = None,
        cotizacion_lock_version_esperado: Optional[int] = None,
        autorizacion_lock_version_esperado: Optional[int] = None,
        reemplaza_aprobacion_id: Optional[UUID] = None,
    ) -> dict:
        """
        Crea la aprobacion documental de Direccion (tb_bom_cotizacion_aprobaciones)
        para una cotizacion. Precondiciones (plan ## 7.2 / ## 8.1 / ## 9.3): cotizacion
        real (no RFQ) con PDF y total, SELECCIONADA, BOM en APROBADO_FINAL y
        autorizacion Fase D ya aprobada por Obra.

        Si `reemplaza_aprobacion_id` viene (## 7.4), liga esta cotizacion como la
        sucesora de una aprobacion REEMPLAZADA del mismo BOM sin sucesor aun.
        """
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
        aprobador_direccion = await self.db.get_aprobador_final_id(conn)
        representados = await self.get_titulares_que_representa(conn, user_id)
        if not aprobador_direccion or aprobador_direccion not in representados:
            raise ValueError(
                "Solo el aprobador de Dirección o su suplente puede aprobar cotizaciones."
            )

        aprobacion = await self.db.get_cotizacion_aprobacion_activa(conn, cotizacion_id)
        if not aprobacion or aprobacion['estatus'] != EstatusCotizacionAprobacion.PENDIENTE_DIRECCION:
            raise ValueError("La cotización no tiene una aprobación pendiente de Dirección.")

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
        aprobador_direccion = await self.db.get_aprobador_final_id(conn)
        representados = await self.get_titulares_que_representa(conn, user_id)
        if not aprobador_direccion or aprobador_direccion not in representados:
            raise ValueError(
                "Solo el aprobador de Dirección o su suplente puede rechazar cotizaciones."
            )

        aprobacion = await self.db.get_cotizacion_aprobacion_activa(conn, cotizacion_id)
        if not aprobacion or aprobacion['estatus'] != EstatusCotizacionAprobacion.PENDIENTE_DIRECCION:
            raise ValueError("La cotización no tiene una aprobación pendiente de Dirección.")

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
                resetear_estatus_cotizacion=False, item_ids=item_ids,
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
        content_type = (getattr(file, "content_type", None) or "").split(";")[0].strip().lower()
        if content_type != "application/pdf":
            raise ValueError("El archivo debe ser un PDF")

        from modules.compras.service import ComprasService

        # El upload a SharePoint (round-trip de red) se hace fuera de la
        # transaccion para no mantener una conexion del pool abierta durante
        # esa llamada externa (mismo criterio que FinanzasService.registrar_pago).
        # Si el CAS de abajo falla, se borra el attachment recien creado para
        # que no quede huerfano y termine sirviendose por error en el preview.
        upload_result = await ComprasService().subir_pdf_mensual(
            conn, file, categoria='bom/cotizaciones',
            origen_slug='cotizacion_bom', user_id=user_id,
            id_bom_cotizacion=cotizacion_id,
        )
        if not upload_result or not upload_result.get('url_sharepoint'):
            raise ValueError("No se pudo subir el PDF a SharePoint")

        try:
            return await self.actualizar_pdf_cotizacion(
                conn, cotizacion_id, upload_result['url_sharepoint'], lock_version_esperado
            )
        except ValueError:
            doc_id = upload_result.get('id_documento_attachment')
            if doc_id:
                await self.db.eliminar_attachment_huerfano(conn, doc_id)
            raise

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

        if not nombre:
            proyecto_id_estandar = bom.get('proyecto_id_estandar') or 'SIN-ID'
            base_nombre = f"RFQ_{proyecto_id_estandar}_{today_mx().strftime('%y%m%d')}"
            nombre = await self._siguiente_nombre_rfq_disponible(conn, base_nombre)

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
            {"bom_item_id": i["id_item"], "cantidad": Decimal(str(i["cantidad"]))}
            for i in items_disponibles
        ]
        async with conn.transaction():
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
        rfq = await self.db.get_rfq_by_id(conn, rfq_id)
        if not rfq:
            raise ValueError("RFQ no encontrado")
        if not nombre or not nombre.strip():
            raise ValueError("El nombre no puede estar vacío")
        if lock_version_esperado is None:
            raise ValueError("El RFQ cambio; recarga la pestaña")
        actualizado = await self.db.renombrar_rfq(conn, rfq_id, nombre.strip(), lock_version_esperado)
        if not actualizado:
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
        async with conn.transaction():
            actualizado = await self.db.incrementar_lock_rfq(conn, rfq_id, lock_version_esperado)
            if not actualizado:
                raise ValueError("El RFQ cambio; recarga la pestaña")
            insertados = await self.db.agregar_items_rfq(conn, rfq_id, [{
                "bom_item_id": bom_item_id,
                "cantidad": Decimal(str(cantidad)),
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
            self._validar_items_cotizables(bom_items, "asignar en bulk a cotizaciones de")
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
                self._validar_items_cotizables(
                    bloqueados, "asignar en bulk a cotizaciones de"
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
