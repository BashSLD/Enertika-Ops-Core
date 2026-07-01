"""
BOM – Compras: cotizaciones, RFQ, autorizaciones Fase D, conciliacion y match.
Mixin incluido en BomService; los metodos usan self.db, self.get_bom y self._broadcast_bom.
"""

import logging
import re
from uuid import UUID
from typing import Optional, List

import asyncpg
from jinja2 import TemplateError

from core.bom.schemas import EstatusBOM
from core.config import settings

logger = logging.getLogger("BOM.Service")

ESTATUS_ITEM_CERRADO_COMPRA = {"NO_ADQUIRIDO", "REEMPLAZADO", "CERRADO"}
ESTATUS_COMPRA_BLOQUEA_ADENDA = {"COTIZADO", "AUTORIZADO", "PAGADO", "FACTURADO"}
ESTATUS_ADENDA_APROBADA = "APROBADA"


class BomComprasServiceMixin:
    """Cotizaciones, RFQ, autorizaciones Fase D, conciliacion y match."""

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
        self, conn, cotizacion_id: UUID, nuevo_estatus: str
    ) -> None:
        """Obtiene ítems de una cotización y actualiza su estatus_compra en lote."""
        items = await self.db.get_items_cotizacion(conn, cotizacion_id)
        if items:
            item_ids = [i['bom_item_id'] for i in items]
            await self.db.actualizar_estatus_compra_items(conn, item_ids, nuevo_estatus)

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
                    if float(it['precio_unitario']) > float(bom_item['precio_unitario']):
                        tiene_sobrecosto = True
                        break
            cot['tiene_sobrecosto'] = tiene_sobrecosto

        return cotizaciones

    async def crear_cotizacion(
        self, conn, id_bom: UUID, proveedor_id: Optional[UUID],
        nombre_proveedor: Optional[str], moneda: str,
        items_data: list, iva_pct: float, notas: Optional[str],
        creado_por: UUID,
        es_rfq: bool = False,
        rfq_origen_id: Optional[UUID] = None,
        subtotal_externo: Optional[float] = None
    ) -> dict:
        """
        Crea una cotización con sus ítems.
        items_data: lista de dicts con bom_item_id, precio_unitario (opcional), cantidad.

        Modos:
        - RFQ (es_rfq=True): sin proveedor ni precios. Solo selecciona items.
        - Simplificado (subtotal_externo): precio se distribuye proporcionalmente.
        - Completo: cada item tiene precio_unitario individual.
        Valida sobrecosto si hay precios individuales.
        """
        bom = await self.get_bom(conn, id_bom)
        ESTATUS_COTIZABLE = {EstatusBOM.APROBADO_CONST, EstatusBOM.EN_REVISION_FINAL, EstatusBOM.APROBADO_FINAL}
        if EstatusBOM(bom['estatus']) not in ESTATUS_COTIZABLE:
            raise ValueError("Solo se pueden crear cotizaciones en BOMs aprobados por Construccion.")

        if not items_data:
            raise ValueError("Debes seleccionar al menos un item para cotizar.")

        item_ids = list(dict.fromkeys(i["bom_item_id"] for i in items_data))
        bom_items_batch = await self.db.get_items_by_ids(conn, item_ids)
        bom_items_map_cot = {str(bi["id_item"]): bi for bi in bom_items_batch}
        if len(bom_items_map_cot) != len(item_ids):
            raise ValueError("La cotizacion contiene items invalidos o inactivos")
        self._validar_items_cotizables(bom_items_batch, "cotizar")

        # RFQ: sin validación de precios
        tiene_precios = any(
            float(i.get('precio_unitario') or 0) > 0 for i in items_data
        )

        if tiene_precios:
            sobrecostos = []
            for i in items_data:
                pu = float(i.get('precio_unitario') or 0)
                if pu <= 0:
                    continue
                bom_item = bom_items_map_cot.get(str(i['bom_item_id']))
                if bom_item and bom_item.get('precio_unitario'):
                    precio_bom = float(bom_item['precio_unitario'])
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
            subtotal = round(subtotal_externo, 2)
            # Distribuir proporcionalmente entre items
            total_cantidad = sum(float(i.get('cantidad', 1)) for i in items_data)
            for i in items_data:
                prop = float(i.get('cantidad', 1)) / total_cantidad if total_cantidad > 0 else 1.0 / len(items_data)
                if 'precio_unitario' not in i or not i['precio_unitario']:
                    cantidad_item = float(i.get('cantidad') or 1)
                    i['precio_unitario'] = round(subtotal * prop / cantidad_item, 4)
        elif tiene_precios:
            subtotal = sum(
                float(i.get('precio_unitario') or 0) * float(i.get('cantidad') or 0)
                for i in items_data
            )
        else:
            subtotal = 0

        iva = round(subtotal * iva_pct / 100, 2)
        total = round(subtotal + iva, 2)

        proveedor_nombre_db = nombre_proveedor
        proveedor_id_db = proveedor_id
        if es_rfq:
            proveedor_nombre_db = None
            proveedor_id_db = None

        cotizacion = await self.db.crear_cotizacion(
            conn, id_bom, proveedor_id_db, proveedor_nombre_db, moneda,
            round(subtotal, 2), iva, total, notas, creado_por,
            es_rfq=es_rfq, rfq_origen_id=rfq_origen_id
        )

        # Preparar ítems con subtotal_linea
        items_insert = []
        for i in items_data:
            pu = float(i.get('precio_unitario') or 0)
            cant = float(i.get('cantidad') or 0)
            items_insert.append({
                'bom_item_id': i['bom_item_id'],
                'precio_unitario': pu if pu > 0 else None,
                'cantidad': cant,
                'moneda': moneda,
                'subtotal_linea': round(pu * cant, 2) if pu > 0 else 0,
            })
        await self.db.agregar_items_cotizacion(conn, cotizacion['id'], items_insert)

        logger.info(
            "Cotización %s creada (rfq=%s) para BOM %s por usuario %s",
            cotizacion['id'], es_rfq, id_bom, creado_por
        )
        return cotizacion

    async def seleccionar_cotizacion(
        self, conn, cotizacion_id: UUID, user_id: UUID
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
        if not cotizacion.get('total') or float(cotizacion['total']) <= 0:
            raise ValueError("La cotización no tiene un total válido.")

        bom = await self.db.get_bom_by_id(conn, cotizacion['bom_id'])
        if not bom or EstatusBOM(bom['estatus']) != EstatusBOM.APROBADO_FINAL:
            raise ValueError("El BOM debe estar en estatus APROBADO_FINAL para autorizar la compra.")

        items = await self.db.get_items_cotizacion(conn, cotizacion_id)
        if items:
            item_ids = [i["bom_item_id"] for i in items]
            bom_items = await self.db.get_items_by_ids(conn, list(dict.fromkeys(item_ids)))
            bom_items_map = {str(i["id_item"]): i for i in bom_items}
            if len(bom_items_map) != len(set(str(i) for i in item_ids)):
                raise ValueError("La cotizacion contiene items invalidos o inactivos")
            self._validar_items_cotizables(bom_items, "seleccionar cotizaciones con")

        _notify_args = None
        async with conn.transaction():
            updated = await self.db.actualizar_estatus_cotizacion(conn, cotizacion_id, 'SELECCIONADA')

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
                    await self.db.upsert_item_ejecucion(
                        conn,
                        it['bom_item_id'],
                        updated_by=user_id,
                        **campos_reales,
                    )

            # Crear autorización de compra (Fase D) si no existe ya
            existente = await self.db.get_autorizacion_by_cotizacion(conn, cotizacion_id)
            if not existente:
                bom = await self.db.get_bom_by_id(conn, cotizacion['bom_id'])
                tc = await self.db.get_tipo_cambio_vigente(conn)
                autorizacion = await self.db.crear_autorizacion(
                    conn,
                    cotizacion_id=cotizacion_id,
                    bom_id=cotizacion['bom_id'],
                    proyecto_id=bom['id_proyecto'],
                    monto_total=cotizacion['total'],
                    moneda=cotizacion['moneda'],
                    tipo_cambio_snapshot=tc['tasa_mxn'] if tc else None,
                    creado_por=user_id,
                )
                coordinador_id = bom.get('coordinador_obra')
                if coordinador_id:
                    _notify_args = (
                        {**autorizacion, 'nombre_proveedor': cotizacion.get('nombre_proveedor')},
                        bom,
                        coordinador_id,
                    )

        # Notificar fuera de la transacción (fire-and-forget)
        if _notify_args:
            aut_enriquecida, bom, coordinador_id = _notify_args
            await self._notify_autorizacion(
                conn, aut_enriquecida, bom,
                to_user_id=coordinador_id,
                evento='PENDIENTE_OBRA',
                por_user_id=user_id,
            )

        logger.info("Cotización %s seleccionada por usuario %s", cotizacion_id, user_id)
        return updated

    # ─── AUTORIZACIONES (Fase D) ────────────────────────────

    async def listar_autorizaciones(self, conn, bom_id: UUID) -> list:
        return await self.db.get_autorizaciones_by_bom(conn, bom_id)

    async def aprobar_obra(
        self, conn, autorizacion_id: UUID, user_id: UUID, nota: Optional[str], user_role: str
    ) -> dict:
        """Aprueba paso 1 (Coordinador de Obra). Valida que sea el coordinador o ADMIN."""
        aut = await self.db.get_autorizacion_by_id(conn, autorizacion_id)
        if not aut:
            raise ValueError("Autorización no encontrada.")
        if aut['estatus'] != 'PENDIENTE':
            raise ValueError(f"La autorización está en estatus {aut['estatus']} y no puede aprobarse en este paso.")

        bom = await self.db.get_bom_by_id(conn, aut['bom_id'])

        # Fase D no usa _validar_aprobador_bom: opera sobre la autorizacion (no sobre roles
        # de revision del BOM), no tiene bypass de Director (Direccion tiene su propio paso
        # en Fase D), y el fallback es NULL-check en coordinador_obra, no rol_org global.
        if user_role != 'ADMIN':
            coordinador_obra = bom.get('coordinador_obra')
            if coordinador_obra:
                if coordinador_obra != user_id:
                    raise ValueError("Solo el coordinador de obra del proyecto puede aprobar este paso.")
            else:
                es_jefe_const = await self.db.usuario_tiene_rol_org(conn, user_id, "jefe_construccion")
                if not es_jefe_const:
                    raise ValueError("No hay coordinador de obra asignado. Solo el jefe de Construccion puede aprobar este paso.")

        updated = await self.db.update_autorizacion_paso_obra(conn, autorizacion_id, user_id, nota)

        # Notificar al Director
        director = await self.db.get_director(conn)
        if director:
            await self._notify_autorizacion(
                conn, {**aut, **updated}, bom,
                to_user_id=director['id_usuario'],
                evento='PENDIENTE_DIRECCION',
                por_user_id=user_id,
                nota=nota,
            )

        logger.info("Autorización %s aprobada (obra) por usuario %s", autorizacion_id, user_id)
        return updated

    async def aprobar_direccion(
        self, conn, autorizacion_id: UUID, user_id: UUID, nota: Optional[str], user_role: str, rol_org: Optional[str]
    ) -> dict:
        """Aprueba paso 2 (Director). Valida rol_organizacional = 'director' o ADMIN."""
        aut = await self.db.get_autorizacion_by_id(conn, autorizacion_id)
        if not aut:
            raise ValueError("Autorización no encontrada.")
        if aut['estatus'] != 'AUTORIZADO_OBRA':
            raise ValueError(f"La autorización está en estatus {aut['estatus']} y no puede aprobarse en este paso.")

        if user_role != 'ADMIN' and rol_org != 'director':
            raise ValueError("Solo el Director puede aprobar este paso.")

        updated = await self.db.update_autorizacion_paso_direccion(conn, autorizacion_id, user_id, nota)

        # Notificar al creador de la autorización (Compras) como proxy hasta Fase E
        bom = await self.db.get_bom_by_id(conn, aut['bom_id'])
        if aut.get('creado_por'):
            await self._notify_autorizacion(
                conn, {**aut, **updated}, bom,
                to_user_id=aut['creado_por'],
                evento='PENDIENTE_FINANZAS',
                por_user_id=user_id,
                nota=nota,
            )

        logger.info("Autorización %s aprobada (dirección) por usuario %s", autorizacion_id, user_id)
        return updated

    async def aprobar_finanzas(
        self, conn, autorizacion_id: UUID, user_id: UUID, nota: Optional[str],
        user_role: str, finanzas_role: Optional[str] = None
    ) -> dict:
        """Aprueba paso 3 (Finanzas). Requiere ADMIN o rol finanzas editor+."""
        aut = await self.db.get_autorizacion_by_id(conn, autorizacion_id)
        if not aut:
            raise ValueError("Autorización no encontrada.")
        if aut['estatus'] != 'AUTORIZADO_DIRECCION':
            raise ValueError(f"La autorización está en estatus {aut['estatus']} y no puede aprobarse en este paso.")

        es_finanzas = finanzas_role in ('editor', 'admin')
        if user_role != 'ADMIN' and not es_finanzas:
            raise ValueError("Solo usuarios del módulo Finanzas pueden aprobar este paso.")

        await self._actualizar_estatus_items_cotizacion(conn, aut['cotizacion_id'], 'AUTORIZADO')

        updated = await self.db.update_autorizacion_paso_finanzas(conn, autorizacion_id, user_id, nota)

        bom = await self.db.get_bom_by_id(conn, aut['bom_id'])
        if aut.get('creado_por'):
            await self._notify_autorizacion(
                conn, {**aut, **updated}, bom,
                to_user_id=aut['creado_por'],
                evento='AUTORIZADO_FINANZAS',
                por_user_id=user_id,
                nota=nota,
            )

        logger.info("Autorización %s aprobada (finanzas) por usuario %s", autorizacion_id, user_id)
        return updated

    async def rechazar_autorizacion(
        self, conn, autorizacion_id: UUID, user_id: UUID, motivo: str,
        user_role: str, rol_org: Optional[str], finanzas_role: Optional[str] = None
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
            if user_role != 'ADMIN':
                bom = await self.db.get_bom_by_id(conn, aut['bom_id'])
                coordinador_obra = bom.get('coordinador_obra')
                if coordinador_obra:
                    if coordinador_obra != user_id:
                        raise ValueError("Solo el coordinador de obra puede rechazar en este paso.")
                else:
                    es_jefe_const = await self.db.usuario_tiene_rol_org(conn, user_id, "jefe_construccion")
                    if not es_jefe_const:
                        raise ValueError("No hay coordinador de obra asignado. Solo el jefe de Construccion puede rechazar en este paso.")
        elif estatus == 'AUTORIZADO_OBRA':
            paso = 'DIRECCION'
            if user_role != 'ADMIN' and rol_org != 'director':
                raise ValueError("Solo el Director puede rechazar en este paso.")
        elif estatus == 'AUTORIZADO_DIRECCION':
            paso = 'FINANZAS'
            es_finanzas = finanzas_role in ('editor', 'admin')
            if user_role != 'ADMIN' and not es_finanzas:
                raise ValueError("Solo usuarios del módulo Finanzas pueden rechazar en este paso.")
        else:
            raise ValueError(f"La autorización no puede rechazarse en estatus {estatus}.")

        updated = await self.db.rechazar_autorizacion_db(conn, autorizacion_id, user_id, motivo, paso)

        # Cotización vuelve a RECIBIDA
        await self.db.actualizar_estatus_cotizacion(conn, aut['cotizacion_id'], 'RECIBIDA')

        # Ítems vuelven a SIN_COTIZAR
        await self._actualizar_estatus_items_cotizacion(conn, aut['cotizacion_id'], 'SIN_COTIZAR')

        # Notificar al creador de la autorización (Compras)
        bom = await self.db.get_bom_by_id(conn, aut['bom_id'])
        if aut.get('creado_por'):
            await self._notify_autorizacion(
                conn, {**aut, **updated}, bom,
                to_user_id=aut['creado_por'],
                evento='RECHAZADO',
                por_user_id=user_id,
                nota=motivo,
            )

        logger.info("Autorización %s rechazada en paso %s por usuario %s", autorizacion_id, paso, user_id)
        return updated

    async def _notify_autorizacion(
        self, conn, autorizacion: dict, bom: dict,
        to_user_id, evento: str,
        por_user_id=None, nota: Optional[str] = None
    ) -> None:
        """Envía email de notificación de cambio en autorización. Fire-and-forget."""
        if not to_user_id:
            return
        try:
            from core.workflow.notification_service import NotificationService
            notif = NotificationService()

            to_email = await self.db.get_usuario_email(conn, to_user_id)
            if not to_email:
                return

            sender_email = await self.db.get_sender_email(conn, 'DEFAULT')
            if not sender_email:
                return

            por_nombre = None
            if por_user_id:
                por_nombre = await self.db.get_usuario_nombre(conn, por_user_id)

            html = notif._render_template('shared/emails/bom/bom_autorizacion.html', {
                'autorizacion': autorizacion,
                'bom': bom,
                'evento': evento,
                'por_nombre': por_nombre or 'Sistema',
                'nota': nota,
                'app_url': f"{settings.APP_BASE_URL}/bom/{bom.get('id_proyecto')}/ui",
            })

            subject_map = {
                'PENDIENTE_OBRA':      f"Autorización BOM {bom.get('proyecto_id_estandar', '')} - Requiere aprobación de Obra",
                'PENDIENTE_DIRECCION': f"Autorización BOM {bom.get('proyecto_id_estandar', '')} - Requiere aprobación de Dirección",
                'PENDIENTE_FINANZAS':  f"Autorización BOM {bom.get('proyecto_id_estandar', '')} - Requiere aprobación de Finanzas",
                'RECHAZADO':           f"Autorización BOM {bom.get('proyecto_id_estandar', '')} - Rechazada",
                'AUTORIZADO_FINANZAS': f"Autorización BOM {bom.get('proyecto_id_estandar', '')} - Aprobada completamente",
            }
            subject = subject_map.get(evento, f"Autorización BOM {bom.get('proyecto_id_estandar', '')} - Actualización")

            await notif._send_email({to_email}, set(), subject, html, sender_email)
            logger.info("Autorizacion notify: evento=%s to_user=%s", evento, to_user_id)
            await self._broadcast_bom(conn, to_user_id, f"BOM_AUT_{evento}", subject, bom.get('proyecto_nombre', ''))
        except (asyncpg.PostgresError, KeyError, RuntimeError, TemplateError, TypeError, ValueError) as exc:
            logger.warning("Autorizacion notify: error enviando email, evento=%s: %s", evento, exc)

    async def rechazar_cotizacion(
        self, conn, cotizacion_id: UUID, user_id: UUID
    ) -> dict:
        cotizacion = await self.db.get_cotizacion_by_id(conn, cotizacion_id)
        if not cotizacion:
            raise ValueError("Cotización no encontrada.")
        if cotizacion['estatus'] in ('SELECCIONADA', 'RECHAZADA'):
            raise ValueError(f"La cotización está en estatus {cotizacion['estatus']}.")

        updated = await self.db.actualizar_estatus_cotizacion(conn, cotizacion_id, 'RECHAZADA')
        logger.info("Cotización %s rechazada por usuario %s", cotizacion_id, user_id)
        return updated

    async def solicitar_aclaracion_cotizacion(
        self, conn, cotizacion_id: UUID, user_id: UUID, motivo: str
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
        updated = await self.db.devolver_cotizacion_borrador(conn, cotizacion_id, motivo)
        logger.info(
            "Cotización %s devuelta a borrador por %s: %s",
            cotizacion_id, user_id, motivo[:80]
        )
        return updated

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
        return {"conceptos": conceptos, "items": items}

    async def confirmar_match_concepto(
        self, conn, historial_id: UUID, id_bom_item: Optional[UUID]
    ) -> Optional[dict]:
        """Confirma (o desasigna) el match concepto->item declarado por un humano.

        Al asignar, marca el item como FACTURADO (coherente con el auto-link del flujo XML).
        Desasignar no revierte el estatus del item (decision conservadora de B3b).
        Ambas escrituras van en una transaccion: si falla la marca de estatus no queda
        el concepto ligado sin el item en FACTURADO.
        """
        async with conn.transaction():
            result = await self.db.confirmar_match_concepto(conn, historial_id, id_bom_item)
            if result and id_bom_item is not None:
                await self.db.update_items_estatus_compra(conn, [id_bom_item], 'FACTURADO')
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
        await self.db.update_items_estatus_compra(conn, uuid_ids, nuevo_estatus)

    # ─── COMPARATIVA RFQ (Gap 7d) ───────────────────────────

    async def get_rfqs(self, conn, id_bom: UUID) -> list:
        return await self.db.get_rfqs_by_bom(conn, id_bom)

    async def get_rfq_responses(self, conn, rfq_id: UUID) -> list:
        return await self.db.get_rfq_responses(conn, rfq_id)

    async def bulk_asignar_items(
        self, conn, cotizacion_id: UUID, item_ids: list,
        precio_unitario: float = None, moneda: str = "MXN"
    ) -> None:
        """Asigna items a una cotización de proveedor (reemplaza items existentes)."""
        cotizacion = await self.db.get_cotizacion_by_id(conn, cotizacion_id)
        if not cotizacion:
            raise ValueError("Cotización no encontrada.")
        if cotizacion['estatus'] in ('SELECCIONADA', 'RECHAZADA'):
            raise ValueError(f"La cotización está en estatus {cotizacion['estatus']} y no puede modificarse.")
        if item_ids:
            bom_items = await self.db.get_items_by_ids(conn, [UUID(str(iid)) for iid in item_ids])
            self._validar_items_cotizables(bom_items, "asignar en bulk a cotizaciones de")
        items = [
            {
                'bom_item_id': UUID(str(iid)),
                'precio_unitario': precio_unitario,
                'cantidad': 1,
                'moneda': moneda,
                'subtotal_linea': precio_unitario if precio_unitario else 0
            }
            for iid in item_ids
        ]
        await self.db.bulk_replace_cotizacion_items(conn, cotizacion_id, items)

    async def get_proveedores_buscar(self, conn, q: str) -> List[dict]:
        return await self.db.get_proveedores_buscar(conn, q)
