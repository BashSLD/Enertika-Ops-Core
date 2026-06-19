"""
Service Layer para BOM (Lista de Materiales).
Logica de negocio, workflow de aprobaciones, versionado y exportacion Excel.
"""

import logging
from uuid import UUID
from typing import Optional, List, Set

import asyncpg
from jinja2 import TemplateError

from core.bom.db_service import BomDBService
from core.bom.schemas import EstatusBOM, AccionHistorial, TipoAprobacion
from core.config import settings
from core.notifications.service import get_notifications_service
from core.timezone import now_mx, today_mx
from core.config_service import ConfigService

logger = logging.getLogger("BOM.Service")

# Campos que puede editar cada area
CAMPOS_INGENIERIA = {'id_categoria', 'descripcion', 'cantidad', 'unidad_medida', 'precio_unitario', 'origen_precio', 'tipo_partida', 'moneda'}
CAMPOS_CONSTRUCCION = {'fecha_requerida', 'entregado', 'comentarios', 'cantidad_recibida'}
CAMPOS_COMPRAS = {
    'id_proveedor', 'tipo_entrega', 'fecha_estimada_entrega',
    'fecha_llegada_real', 'comentarios'
}

# Estados en los que NO se puede editar de ninguna forma
ESTATUS_BLOQUEADOS = {EstatusBOM.CANCELADO, EstatusBOM.APROBADO_FINAL}

# Estatus editables para agregar/eliminar items estructurales (ingenieria y construccion)
ESTATUS_EDITABLE_ING = set(EstatusBOM) - ESTATUS_BLOQUEADOS

# Campos especificos editables por construccion/compras en cualquier fase no bloqueada
ESTATUS_EDITABLE_CONST_COMPRAS = set(EstatusBOM) - ESTATUS_BLOQUEADOS

# Labels para historial
CAMPO_LABELS = {
    'id_categoria': 'Categoria',
    'descripcion': 'Descripcion',
    'cantidad': 'Cantidad',
    'unidad_medida': 'Unidad de medida',
    'fecha_requerida': 'Fecha requerida',
    'fecha_llegada_real': 'Fecha llegada real',
    'id_proveedor': 'Proveedor',
    'tipo_entrega': 'Tipo entrega',
    'fecha_estimada_entrega': 'Fecha estimada entrega',
    'comentarios': 'Comentarios',
    'entregado': 'Entregado',
    'precio_unitario': 'Precio unitario',
    'origen_precio': 'Origen precio',
    'cantidad_recibida': 'Cantidad recibida',
}


class BomService:
    """Logica de negocio para BOM."""

    def __init__(self):
        self.db = BomDBService()

    async def puede_crear_o_retomar_bom(
        self, conn, id_proyecto: UUID, user_id: Optional[UUID],
        ingeniero_asignado: Optional[dict] = None,
    ) -> bool:
        """Permite BOM solo a jefe de Ingenieria o ingeniero asignado al proyecto.

        Si el caller ya resolvio la asignacion de ingeniero_asignado (p.ej. para
        mostrar un mensaje), puede pasarla para evitar una consulta adicional.
        """
        if not user_id:
            return False
        if await self.db.usuario_tiene_rol_org(conn, user_id, "jefe_ingenieria"):
            return True
        if ingeniero_asignado is not None:
            return str(ingeniero_asignado["id_usuario"]) == str(user_id)
        return await self.db.usuario_tiene_asignacion_proyecto(
            conn, id_proyecto, user_id, "ingeniero_asignado", "INGENIERIA"
        )

    async def get_ingeniero_asignado(self, conn, id_proyecto: UUID) -> Optional[dict]:
        """Asignacion activa de ingeniero_asignado (INGENIERIA) del proyecto."""
        return await self.db.get_asignacion_proyecto(
            conn, id_proyecto, "ingeniero_asignado", "INGENIERIA"
        )

    async def _validar_retomar_bom_ingenieria(
        self, conn, id_proyecto: UUID, user_id: UUID
    ) -> None:
        if not await self.puede_crear_o_retomar_bom(conn, id_proyecto, user_id):
            raise ValueError(
                "Solo el jefe de Ingenieria o el ingeniero asignado pueden crear o retomar el BOM"
            )

    async def _validar_aprobador_bom(
        self, conn, user_id: UUID, user_role: str, rol_org: Optional[str],
        responsable_id: Optional[UUID], label: str, fallback_rol_org: str
    ) -> None:
        if not fallback_rol_org:
            raise ValueError(
                "_validar_aprobador_bom requiere fallback_rol_org: sin el, un BOM con "
                "responsable_id=None y gestion_solo_responsable=True quedaria sin validar"
            )
        if user_role == 'ADMIN':
            return
        director_bypass = await ConfigService.get_global_config(
            conn, 'bom.director_bypass_aprobaciones', True, bool
        )
        if rol_org == 'director' and director_bypass:
            return
        solo_responsable = await ConfigService.get_global_config(
            conn, 'bom.gestion_solo_responsable', True, bool
        )
        if solo_responsable and responsable_id and responsable_id != user_id:
            raise ValueError(f"Solo el {label} del proyecto puede ejecutar esta accion")
        if solo_responsable and responsable_id:
            return  # responsable_id=None cae al fallback de rol global
        if not await self.db.usuario_tiene_rol_org(conn, user_id, fallback_rol_org):
            raise ValueError(f"Solo el {label} puede ejecutar esta accion")

    # ─── CREAR BOM ──────────────────────────────────────────

    async def crear_bom(
        self, conn, id_proyecto: UUID, elaborado_por: UUID,
        responsable_ing: Optional[UUID] = None,
        jefe_construccion: Optional[UUID] = None,
        coordinador_obra: Optional[UUID] = None,
        notas: Optional[str] = None
    ) -> dict:
        """Crea un nuevo BOM resolviendo responsables desde reglas del proyecto."""
        # Verificar proyecto existe
        proyecto = await self.db.get_proyecto_info(conn, id_proyecto)
        if not proyecto:
            raise ValueError("Proyecto no encontrado")

        await self._validar_retomar_bom_ingenieria(conn, id_proyecto, elaborado_por)

        responsable = await self.db.get_responsable_proyecto_o_global(
            conn, id_proyecto, "jefe_ingenieria"
        )
        if not responsable:
            raise ValueError("No hay jefe de Ingenieria activo configurado")

        jefe_const = await self.db.get_responsable_proyecto_o_global(
            conn, id_proyecto, "jefe_construccion"
        )
        if not jefe_const:
            raise ValueError("No hay jefe de Construccion activo configurado")

        ingeniero = await self.db.get_asignacion_proyecto(
            conn, id_proyecto, "ingeniero_asignado", "INGENIERIA"
        )
        if not ingeniero:
            raise ValueError("Asigna un Ingeniero de Diseño al proyecto antes de crear el BOM")

        coordinador = await self.db.get_asignacion_proyecto(
            conn, id_proyecto, "coordinador_obra", "CONSTRUCCION"
        )

        # Verificar no hay BOM en BORRADOR
        borrador = await self.db.get_bom_borrador_by_proyecto(conn, id_proyecto)
        if borrador:
            raise ValueError(
                f"Ya existe un BOM en borrador (v{borrador['version']}). "
                "Edita el existente o eliminalo antes de crear uno nuevo."
            )

        # Obtener siguiente version
        max_version = await self.db.get_max_version(conn, id_proyecto)
        nueva_version = max_version + 1

        bom = await self.db.crear_bom(
            conn, id_proyecto, elaborado_por,
            responsable_ing=responsable["id_usuario"],
            jefe_construccion=jefe_const["id_usuario"],
            coordinador_obra=coordinador["id_usuario"] if coordinador else None,
            notas=notas,
            version=nueva_version
        )

        # Registrar en historial
        await self.db.registrar_historial(
            conn, bom['id_bom'], AccionHistorial.CREADO,
            nueva_version, elaborado_por
        )

        logger.info(
            "BOM creado: proyecto=%s, version=%d, por=%s",
            id_proyecto, nueva_version, elaborado_por
        )

        bom_creado = await self.db.get_bom_by_id(conn, bom['id_bom'])
        if not coordinador:
            await self._notify_bom(
                conn,
                bom_creado,
                jefe_const["id_usuario"],
                "FALTA_COORDINADOR_OBRA",
                por_user_id=elaborado_por,
                comentarios=(
                    "El BOM se creo sin coordinador de obra. "
                    "Asigna el coordinador desde Proyectos."
                ),
            )

        return bom_creado

    # ─── OBTENER BOM ────────────────────────────────────────

    async def get_bom_proyecto(self, conn, id_proyecto: UUID) -> Optional[dict]:
        """Obtiene el BOM mas reciente del proyecto."""
        return await self.db.get_bom_by_proyecto(conn, id_proyecto)

    async def get_bom(self, conn, id_bom: UUID) -> dict:
        """Obtiene un BOM por ID. Lanza error si no existe."""
        bom = await self.db.get_bom_by_id(conn, id_bom)
        if not bom:
            raise ValueError("BOM no encontrado")
        return bom

    # ─── ITEMS CRUD ─────────────────────────────────────────


    async def agregar_item(
        self, conn, id_bom: UUID, user_id: UUID,
        descripcion: str, cantidad, id_categoria: Optional[int] = None,
        unidad_medida: Optional[str] = None,
        comentarios: Optional[str] = None,
        precio_unitario=None,
        origen_precio: Optional[str] = 'MANUAL',
        id_material_ref: Optional[UUID] = None,
        id_material_interno: Optional[UUID] = None,
        tipo_partida: Optional[str] = 'MATERIAL',
        moneda: Optional[str] = 'MXN',
        area_editor: str = 'ingenieria'
    ) -> dict:
        """Agrega un item al BOM. Permite edicion segun area y estado."""
        bom = await self.get_bom(conn, id_bom)
        estatus = EstatusBOM(bom['estatus'])
        if estatus in ESTATUS_BLOQUEADOS:
            raise ValueError(f"El BOM esta en estado {estatus} y no permite modificaciones")

        if area_editor == 'ingenieria':
            await self._validar_retomar_bom_ingenieria(conn, bom['id_proyecto'], user_id)

        es_rol_bom = await self.es_bom_role(conn, bom, user_id)
        if not es_rol_bom:
            # Fallback: permisos originales por area_editor
            await self._validar_edicion_items(conn, id_bom, area_editor)

        from decimal import Decimal as _D
        if _D(str(cantidad)) <= 0:
            raise ValueError("La cantidad debe ser mayor a cero")
        if precio_unitario is not None and _D(str(precio_unitario)) < 0:
            raise ValueError("El precio unitario no puede ser negativo")

        orden = await self.db.get_next_orden(conn, id_bom)

        item = await self.db.agregar_item(
            conn, id_bom, descripcion, cantidad,
            id_categoria=id_categoria,
            unidad_medida=unidad_medida,
            comentarios=comentarios,
            orden=orden,
            precio_unitario=precio_unitario,
            origen_precio=origen_precio,
            id_material_ref=id_material_ref,
            id_material_interno=id_material_interno,
            tipo_partida=tipo_partida,
            moneda=moneda
        )

        await self.db.registrar_historial(
            conn, id_bom, AccionHistorial.AGREGADO,
            bom['version'], user_id,
            id_item=item['id_item'],
            campo_modificado='item',
            valor_nuevo=descripcion
        )

        return item

    async def editar_item(
        self, conn, id_item: UUID, user_id: UUID,
        area_editor: str, **campos
    ) -> dict:
        """
        Edita un item del BOM. Valida permisos segun area del editor.
        area_editor: 'ingenieria', 'construccion', 'compras'
        """
        item = await self.db.get_item_by_id(conn, id_item)
        if not item:
            raise ValueError("Item no encontrado")
        if not item.get('activo', True):
            raise ValueError("No se puede editar un item eliminado")
        if item.get('bloqueado'):
            raise ValueError("Este item fue completado en una version anterior del BOM y no se puede modificar")

        bom_estatus = EstatusBOM(item['bom_estatus'])
        es_catalogo = item.get('origen_precio') == 'CATALOGO'

        if area_editor == 'ingenieria':
            await self._validar_retomar_bom_ingenieria(conn, item['id_proyecto'], user_id)

        # Campos protegidos: items de catalogo no permiten cambiar descripcion,
        # precio, unidad ni origen para preservar integridad del analisis de costos
        campos_protegidos_catalogo = {
            'descripcion', 'precio_unitario', 'origen_precio',
            'id_material_ref', 'unidad_medida'
        }

        # Validar que campos correspondan al area del editor
        campos_filtrados = {}
        if area_editor == 'ingenieria':
            if bom_estatus not in ESTATUS_EDITABLE_ING:
                raise ValueError("El BOM no esta en estado editable para ingenieria")
            campos_filtrados = {k: v for k, v in campos.items() if k in CAMPOS_INGENIERIA}
            if 'precio_unitario' in campos_filtrados and campos_filtrados['precio_unitario'] is not None:
                from decimal import Decimal as _D
                if _D(str(campos_filtrados['precio_unitario'])) < 0:
                    raise ValueError("El precio unitario no puede ser negativo")
            # Items de catalogo: remover campos protegidos
            if es_catalogo:
                campos_filtrados = {
                    k: v for k, v in campos_filtrados.items()
                    if k not in campos_protegidos_catalogo
                }
        elif area_editor == 'construccion':
            if bom_estatus not in ESTATUS_EDITABLE_CONST_COMPRAS:
                raise ValueError("El BOM no esta en estado editable para construccion")
            campos_filtrados = {k: v for k, v in campos.items() if k in CAMPOS_CONSTRUCCION}
            # Recepcion parcial: auto-calcular entregado segun cantidad recibida
            if 'cantidad_recibida' in campos_filtrados:
                from decimal import Decimal
                cant_recibida = Decimal(str(campos_filtrados['cantidad_recibida']))
                cant_total = Decimal(str(item['cantidad']))
                if cant_recibida < 0:
                    raise ValueError("La cantidad recibida no puede ser negativa")
                if cant_recibida > cant_total:
                    raise ValueError("La cantidad recibida no puede exceder la cantidad total del item")
                if cant_recibida >= cant_total:
                    campos_filtrados['entregado'] = True
                    campos_filtrados['fecha_entrega_check'] = now_mx()
                else:
                    campos_filtrados['entregado'] = False
                    campos_filtrados['fecha_entrega_check'] = None
            # Marcar entregado manualmente (si no viene cantidad_recibida)
            elif 'entregado' in campos_filtrados and campos_filtrados['entregado']:
                campos_filtrados['fecha_entrega_check'] = now_mx()
            elif 'entregado' in campos_filtrados and not campos_filtrados['entregado']:
                campos_filtrados['fecha_entrega_check'] = None
        elif area_editor == 'compras':
            if bom_estatus not in ESTATUS_EDITABLE_CONST_COMPRAS:
                raise ValueError("El BOM no esta en estado editable para compras")
            campos_filtrados = {k: v for k, v in campos.items() if k in CAMPOS_COMPRAS}

        if not campos_filtrados:
            raise ValueError("No hay campos validos para actualizar")

        # Registrar cambios en historial
        for campo, valor_nuevo in campos_filtrados.items():
            valor_anterior = item.get(campo)
            if str(valor_anterior) != str(valor_nuevo):
                await self.db.registrar_historial(
                    conn, item['id_bom'], AccionHistorial.EDITADO,
                    item['bom_version'], user_id,
                    id_item=id_item,
                    campo_modificado=CAMPO_LABELS.get(campo, campo),
                    valor_anterior=str(valor_anterior) if valor_anterior is not None else None,
                    valor_nuevo=str(valor_nuevo) if valor_nuevo is not None else None
                )

        updated = await self.db.update_item(conn, id_item, **campos_filtrados)
        return updated

    async def eliminar_item(self, conn, id_item: UUID, user_id: UUID, area_editor: str = 'ingenieria') -> dict:
        """Soft delete de un item. Valida permisos segun area."""
        item = await self.db.get_item_by_id(conn, id_item)
        if not item:
            raise ValueError("Item no encontrado")
        if item.get('bloqueado'):
            raise ValueError("Este item fue completado en una version anterior del BOM y no se puede eliminar")

        bom = await self.get_bom(conn, item['id_bom'])
        estatus = EstatusBOM(bom['estatus'])
        if estatus in ESTATUS_BLOQUEADOS:
            raise ValueError(f"El BOM esta en estado {estatus} y no permite modificaciones")

        if area_editor == 'ingenieria':
            await self._validar_retomar_bom_ingenieria(conn, bom['id_proyecto'], user_id)

        es_rol_bom = await self.es_bom_role(conn, bom, user_id)
        if not es_rol_bom:
            await self._validar_edicion_items(conn, item['id_bom'], area_editor)

        deleted = await self.db.soft_delete_item(conn, id_item)

        await self.db.registrar_historial(
            conn, item['id_bom'], AccionHistorial.ELIMINADO,
            item['bom_version'], user_id,
            id_item=id_item,
            campo_modificado='item',
            valor_anterior=item.get('descripcion')
        )

        return deleted

    async def get_items(self, conn, id_bom: UUID) -> list:
        """Lista items activos del BOM, enriched with grupos and costo_mxn.

        Para items USD, el tipo de cambio se obtiene en este orden:
        1. TC del XML de la factura asociada (tb_materiales_historial.tipo_cambio_xml)
        2. Ultima tasa Banxico registrada (tb_tipo_cambio)
        3. Promedio 7 dias Banxico (fallback final)
        """
        items = await self.db.get_items_by_bom(conn, id_bom)
        if not items:
            return items
        grupos_map = await self.db.get_grupos_por_bom(conn, id_bom)

        usd_ids = [
            item['id_item'] for item in items
            if item.get('moneda') == 'USD' and item.get('precio_unitario')
        ]

        tc_from_xml = {}
        tc_banxico = None
        tc_promedio = None

        if usd_ids:
            tc_from_xml = await self.db.get_tc_from_linked_materials(conn, usd_ids)

            still_need = [iid for iid in usd_ids if str(iid) not in tc_from_xml]
            if still_need:
                from core.tipo_cambio.db_service import TipoCambioDBService
                tc_svc = TipoCambioDBService()
                tasa = await tc_svc.get_tasa_mas_reciente(conn)
                tc_banxico = float(tasa['tasa_mxn']) if tasa else None

                if not tc_banxico:
                    tc_promedio = await self.db.get_tasa_promedio(conn)

        for item in items:
            item['grupos'] = grupos_map.get(str(item['id_item']), [])
            moneda = item.get('moneda', 'MXN')
            if moneda == 'USD' and item.get('precio_unitario'):
                iid = str(item['id_item'])
                if iid in tc_from_xml:
                    tc = tc_from_xml[iid]
                elif tc_banxico:
                    tc = tc_banxico
                elif tc_promedio:
                    tc = tc_promedio
                else:
                    tc = None
                if tc:
                    item['costo_mxn'] = round(float(item['precio_unitario']) * tc, 2)

        # Enriquecer con gasto real desde materiales vinculados
        all_ids = [item['id_item'] for item in items]
        gasto_map = await self.db.get_gasto_real_por_item(conn, all_ids)
        for item in items:
            gasto = gasto_map.get(str(item['id_item']))
            if gasto is not None:
                item['gasto_real'] = round(gasto, 2)

        return items

    async def get_item(self, conn, id_item: UUID) -> dict:
        """Obtiene un item por ID, enriquecido con costo_mxn y gasto_real."""
        item = await self.db.get_item_by_id(conn, id_item)
        if not item:
            raise ValueError("Item no encontrado")
        # Enriquecer costo_mxn para items USD
        if item.get('moneda') == 'USD' and item.get('precio_unitario'):
            from core.tipo_cambio.db_service import TipoCambioDBService
            tc_svc = TipoCambioDBService()
            tasa = await tc_svc.get_tasa_mas_reciente(conn)
            tc = float(tasa['tasa_mxn']) if tasa else None
            if tc:
                item['costo_mxn'] = round(float(item['precio_unitario']) * tc, 2)
        # Enriquecer gasto_real
        gasto_map = await self.db.get_gasto_real_por_item(conn, [id_item])
        gasto = gasto_map.get(str(id_item))
        if gasto is not None:
            item['gasto_real'] = round(gasto, 2)
        return item

    # ─── WORKFLOW DE APROBACION ──────────────────────────────

    async def enviar_revision_ing(
        self, conn, id_bom: UUID, user_id: UUID
    ) -> dict:
        """Envia BOM a revision de responsable de ingenieria."""
        bom = await self.get_bom(conn, id_bom)
        await self._validar_retomar_bom_ingenieria(conn, bom['id_proyecto'], user_id)

        if not bom.get('responsable_ing'):
            raise ValueError("El BOM no tiene responsable de Ingenieria asignado. Configura el jefe de Ingenieria antes de enviar.")

        if EstatusBOM(bom['estatus']) != EstatusBOM.BORRADOR:
            raise ValueError("Solo se puede enviar a revision desde BORRADOR")

        # Verificar que tenga items
        items = await self.db.get_items_by_bom(conn, id_bom)
        if not items:
            raise ValueError("El BOM debe tener al menos un item")

        update_kwargs = {
            'fecha_envio_ing': now_mx()
        }

        updated = await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.EN_REVISION_ING, **update_kwargs
        )

        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.ENVIO_REVISION_ING,
            bom['version'], user_id
        )

        logger.info("BOM %s enviado a revision ing por %s", id_bom, user_id)
        bom_updated = await self.db.get_bom_by_id(conn, id_bom)
        await self._notify_bom(conn, bom_updated, bom_updated.get('responsable_ing'),
                               'ENVIADO_REVISION_ING', por_user_id=user_id)

        # Recordatorio si falta RC o coordinador de obra: notifica a director y RC/jefe_const
        asignaciones_const = await self.db.get_asignaciones_proyecto(
            conn, bom['id_proyecto'],
            ["responsable_construccion", "coordinador_obra"], "CONSTRUCCION"
        )
        if "responsable_construccion" not in asignaciones_const or "coordinador_obra" not in asignaciones_const:
            director = await self.db.get_director(conn)
            jefe_const = await self.db.get_responsable_proyecto_o_global(
                conn, bom['id_proyecto'], "jefe_construccion"
            )
            notificados: set[str] = set()
            if director:
                notificados.add(str(director['id_usuario']))
                await self._notify_bom(conn, bom_updated, director['id_usuario'],
                                       'FALTA_ASIGNACION_CONSTRUCCION', por_user_id=user_id)
            if jefe_const and str(jefe_const['id_usuario']) not in notificados:
                await self._notify_bom(conn, bom_updated, jefe_const['id_usuario'],
                                       'FALTA_ASIGNACION_CONSTRUCCION', por_user_id=user_id)

        return bom_updated

    async def aprobar_ing(
        self, conn, id_bom: UUID, user_id: UUID, user_role: str,
        rol_org: Optional[str] = None, comentarios: Optional[str] = None
    ) -> dict:
        """Aprueba BOM por responsable de ingenieria."""
        bom = await self.get_bom(conn, id_bom)
        await self._validar_aprobador_bom(
            conn, user_id, user_role, rol_org,
            bom.get('responsable_ing'), "Responsable de Ingenieria", "jefe_ingenieria"
        )

        if EstatusBOM(bom['estatus']) != EstatusBOM.EN_REVISION_ING:
            raise ValueError("El BOM debe estar EN_REVISION_ING para aprobar")

        await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.APROBADO_ING,
            fecha_aprobacion_ing=now_mx()
        )
        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.APROBACION_ING,
            bom['version'], user_id, comentarios=comentarios
        )
        logger.info("BOM %s aprobado por ing %s", id_bom, user_id)
        bom_updated = await self.db.get_bom_by_id(conn, id_bom)
        await self._notify_bom(conn, bom_updated, bom_updated.get('elaborado_por'),
                               'APROBADO_ING', por_user_id=user_id)
        return bom_updated

    async def rechazar_ing(
        self, conn, id_bom: UUID, user_id: UUID, user_role: str,
        rol_org: Optional[str] = None, comentarios: Optional[str] = None
    ) -> dict:
        """Rechaza BOM por responsable de ingenieria. Vuelve a BORRADOR."""
        if not comentarios or not comentarios.strip():
            raise ValueError("El motivo del rechazo es obligatorio")

        bom = await self.get_bom(conn, id_bom)
        await self._validar_aprobador_bom(
            conn, user_id, user_role, rol_org,
            bom.get('responsable_ing'), "Responsable de Ingenieria", "jefe_ingenieria"
        )

        if EstatusBOM(bom['estatus']) != EstatusBOM.EN_REVISION_ING:
            raise ValueError("El BOM debe estar EN_REVISION_ING para rechazar")

        await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.BORRADOR,
            fecha_envio_ing=None,
            fecha_aprobacion_ing=None
        )
        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.RECHAZO_ING,
            bom['version'], user_id, comentarios=comentarios
        )
        logger.info("BOM %s rechazado por ing %s: %s", id_bom, user_id, comentarios)
        bom_updated = await self.db.get_bom_by_id(conn, id_bom)
        await self._notify_bom(conn, bom_updated, bom_updated.get('elaborado_por'),
                               'RECHAZADO_ING', por_user_id=user_id, comentarios=comentarios)
        return bom_updated

    async def enviar_revision_const(
        self, conn, id_bom: UUID, user_id: UUID,
    ) -> dict:
        """Envia BOM aprobado por ing a revision de construccion."""
        bom = await self.get_bom(conn, id_bom)
        await self._validar_retomar_bom_ingenieria(conn, bom['id_proyecto'], user_id)

        if EstatusBOM(bom['estatus']) != EstatusBOM.APROBADO_ING:
            raise ValueError("El BOM debe estar APROBADO_ING para enviar a construccion")

        update_kwargs = {
            'fecha_envio_const': now_mx()
        }

        await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.EN_REVISION_CONST, **update_kwargs
        )

        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.ENVIO_REVISION_CONST,
            bom['version'], user_id
        )

        logger.info("BOM %s enviado a revision const por %s", id_bom, user_id)
        return await self.db.get_bom_by_id(conn, id_bom)

    async def aprobar_const(
        self, conn, id_bom: UUID, user_id: UUID, user_role: str,
        rol_org: Optional[str] = None, comentarios: Optional[str] = None
    ) -> dict:
        """Aprueba BOM por jefe de construccion. Estado final antes de compras."""
        bom = await self.get_bom(conn, id_bom)
        await self._validar_aprobador_bom(
            conn, user_id, user_role, rol_org,
            bom.get('jefe_construccion'), "Jefe de Construccion", "jefe_construccion"
        )

        if EstatusBOM(bom['estatus']) != EstatusBOM.EN_REVISION_CONST:
            raise ValueError("El BOM debe estar EN_REVISION_CONST para aprobar")

        await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.APROBADO_CONST,
            fecha_aprobacion_const=now_mx()
        )
        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.APROBACION_CONST,
            bom['version'], user_id, comentarios=comentarios
        )
        logger.info("BOM %s aprobado por const %s", id_bom, user_id)
        bom_updated = await self.db.get_bom_by_id(conn, id_bom)
        await self._notify_bom(conn, bom_updated, bom_updated.get('elaborado_por'),
                               'APROBADO_CONST', por_user_id=user_id)
        return bom_updated

    async def rechazar_const(
        self, conn, id_bom: UUID, user_id: UUID, user_role: str,
        rol_org: Optional[str] = None, comentarios: Optional[str] = None
    ) -> dict:
        """Rechaza BOM por construccion. Vuelve a APROBADO_ING."""
        if not comentarios or not comentarios.strip():
            raise ValueError("El motivo del rechazo es obligatorio")

        bom = await self.get_bom(conn, id_bom)
        await self._validar_aprobador_bom(
            conn, user_id, user_role, rol_org,
            bom.get('jefe_construccion'), "Jefe de Construccion", "jefe_construccion"
        )

        if EstatusBOM(bom['estatus']) != EstatusBOM.EN_REVISION_CONST:
            raise ValueError("El BOM debe estar EN_REVISION_CONST para rechazar")

        await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.APROBADO_ING,
            fecha_envio_const=None,
            fecha_aprobacion_const=None
        )
        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.RECHAZO_CONST,
            bom['version'], user_id, comentarios=comentarios
        )
        logger.info("BOM %s rechazado por const %s: %s", id_bom, user_id, comentarios)
        bom_updated = await self.db.get_bom_by_id(conn, id_bom)
        await self._notify_bom(conn, bom_updated, bom_updated.get('elaborado_por'),
                               'RECHAZADO_CONST', por_user_id=user_id, comentarios=comentarios)
        return bom_updated

    async def enviar_revision_obra(
        self, conn, id_bom: UUID, user_id: UUID
    ) -> dict:
        """Envia BOM aprobado por ing a revision del coordinador de obra."""
        bom = await self.get_bom(conn, id_bom)
        await self._validar_retomar_bom_ingenieria(conn, bom['id_proyecto'], user_id)

        if EstatusBOM(bom['estatus']) != EstatusBOM.APROBADO_ING:
            raise ValueError("El BOM debe estar APROBADO_ING para enviar a obra")

        await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.EN_REVISION_OBRA,
            fecha_envio_obra=now_mx()
        )
        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.ENVIO_REVISION_OBRA,
            bom['version'], user_id
        )
        logger.info("BOM %s enviado a revision obra por %s", id_bom, user_id)
        bom_updated = await self.db.get_bom_by_id(conn, id_bom)
        await self._notify_bom(conn, bom_updated, bom_updated.get('coordinador_obra'),
                               'ENVIADO_REVISION_OBRA', por_user_id=user_id)
        return bom_updated

    async def aprobar_revision_obra(
        self, conn, id_bom: UUID, user_id: UUID, user_role: str,
        rol_org: Optional[str] = None, comentarios: Optional[str] = None
    ) -> dict:
        """Aprueba BOM por coordinador de obra. Avanza automaticamente a EN_REVISION_CONST."""
        bom = await self.get_bom(conn, id_bom)
        await self._validar_aprobador_bom(
            conn, user_id, user_role, rol_org,
            bom.get('coordinador_obra'), "Coordinador de Obra", "jefe_construccion"
        )

        if EstatusBOM(bom['estatus']) != EstatusBOM.EN_REVISION_OBRA:
            raise ValueError("El BOM debe estar EN_REVISION_OBRA para aprobar")

        await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.EN_REVISION_CONST,
            fecha_aprobacion_obra=now_mx(),
            fecha_envio_const=now_mx()
        )
        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.APROBACION_OBRA,
            bom['version'], user_id, comentarios=comentarios
        )
        logger.info("BOM %s aprobado por obra %s, avanza a EN_REVISION_CONST", id_bom, user_id)
        bom_updated = await self.db.get_bom_by_id(conn, id_bom)
        await self._notify_bom(conn, bom_updated, bom_updated.get('jefe_construccion'),
                               'ENVIADO_REVISION_CONST', por_user_id=user_id)
        return bom_updated

    async def rechazar_obra(
        self, conn, id_bom: UUID, user_id: UUID, user_role: str,
        rol_org: Optional[str] = None, comentarios: Optional[str] = None
    ) -> dict:
        """Rechaza BOM por coordinador de obra. Vuelve a APROBADO_ING."""
        if not comentarios or not comentarios.strip():
            raise ValueError("El motivo del rechazo es obligatorio")

        bom = await self.get_bom(conn, id_bom)
        await self._validar_aprobador_bom(
            conn, user_id, user_role, rol_org,
            bom.get('coordinador_obra'), "Coordinador de Obra", "jefe_construccion"
        )

        if EstatusBOM(bom['estatus']) != EstatusBOM.EN_REVISION_OBRA:
            raise ValueError("El BOM debe estar EN_REVISION_OBRA para rechazar")

        await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.APROBADO_ING,
            fecha_envio_obra=None,
            fecha_aprobacion_obra=None
        )
        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.RECHAZO_OBRA,
            bom['version'], user_id, comentarios=comentarios
        )
        logger.info("BOM %s rechazado por obra %s: %s", id_bom, user_id, comentarios)
        bom_updated = await self.db.get_bom_by_id(conn, id_bom)
        await self._notify_bom(conn, bom_updated, bom_updated.get('elaborado_por'),
                               'RECHAZADO_OBRA', por_user_id=user_id, comentarios=comentarios)
        return bom_updated

    async def devolver_a_borrador(
        self, conn, id_bom: UUID, user_id: UUID,
        comentarios: Optional[str] = None
    ) -> dict:
        """Devuelve BOM de APROBADO_ING a BORRADOR para corregir tras rechazo de construccion."""
        bom = await self.get_bom(conn, id_bom)
        await self._validar_retomar_bom_ingenieria(conn, bom['id_proyecto'], user_id)

        if EstatusBOM(bom['estatus']) != EstatusBOM.APROBADO_ING:
            raise ValueError("Solo se puede devolver a borrador desde APROBADO_ING")

        await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.BORRADOR,
            fecha_envio_ing=None,
            fecha_aprobacion_ing=None,
            fecha_envio_const=None,
            fecha_aprobacion_const=None
        )

        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.DEVOLUCION_BORRADOR,
            bom['version'], user_id, comentarios=comentarios
        )

        logger.info("BOM %s devuelto a borrador por %s", id_bom, user_id)
        return await self.db.get_bom_by_id(conn, id_bom)

    async def cancelar_bom(
        self, conn, id_bom: UUID, user_id: UUID,
        comentarios: Optional[str] = None
    ) -> dict:
        """Cancela un BOM en BORRADOR."""
        bom = await self.get_bom(conn, id_bom)
        await self._validar_retomar_bom_ingenieria(conn, bom['id_proyecto'], user_id)

        if EstatusBOM(bom['estatus']) != EstatusBOM.BORRADOR:
            raise ValueError("Solo se puede cancelar un BOM en BORRADOR")

        await self.db.update_bom_estatus(conn, id_bom, EstatusBOM.CANCELADO)

        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.CANCELACION,
            bom['version'], user_id, comentarios=comentarios
        )

        logger.info("BOM %s cancelado por %s", id_bom, user_id)
        return await self.db.get_bom_by_id(conn, id_bom)

    async def get_ultimo_rechazo(self, conn, id_bom: UUID) -> Optional[dict]:
        """Obtiene el ultimo rechazo/devolucion del BOM."""
        return await self.db.get_ultimo_rechazo(conn, id_bom)

    async def solicitar_modificacion(
        self, conn, id_bom: UUID, user_id: UUID,
        comentarios: Optional[str] = None
    ) -> dict:
        """
        Solicita modificacion post-aprobacion.
        Crea nueva version copiando items y pone en BORRADOR.
        """
        bom = await self.get_bom(conn, id_bom)
        await self._validar_retomar_bom_ingenieria(conn, bom['id_proyecto'], user_id)

        ESTATUS_MODIFICABLE = {EstatusBOM.APROBADO_CONST, EstatusBOM.APROBADO_FINAL}
        if EstatusBOM(bom['estatus']) not in ESTATUS_MODIFICABLE:
            raise ValueError("Solo se puede solicitar modificacion de un BOM APROBADO_CONST o APROBADO_FINAL")

        # Registrar solicitud en version actual
        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.SOLICITUD_MODIFICACION,
            bom['version'], user_id, comentarios=comentarios
        )

        # Crear nueva version — re-resolver responsables frescos con fallback al BOM anterior
        nueva_version = bom['version'] + 1
        responsable = await self.db.get_responsable_proyecto_o_global(conn, bom['id_proyecto'], "jefe_ingenieria")
        jefe_const = await self.db.get_responsable_proyecto_o_global(conn, bom['id_proyecto'], "jefe_construccion")
        coordinador = await self.db.get_asignacion_proyecto(
            conn, bom['id_proyecto'], "coordinador_obra", "CONSTRUCCION"
        )
        nuevo_bom = await self.db.crear_bom(
            conn, bom['id_proyecto'], user_id,
            responsable_ing=responsable["id_usuario"] if responsable else bom.get('responsable_ing'),
            jefe_construccion=jefe_const["id_usuario"] if jefe_const else bom.get('jefe_construccion'),
            coordinador_obra=coordinador["id_usuario"] if coordinador else bom.get('coordinador_obra'),
            notas=f"Modificacion solicitada sobre v{bom['version']}. {comentarios or ''}".strip(),
            version=nueva_version
        )

        # Copiar items activos
        items_copiados = await self.db.copiar_items_a_nueva_version(
            conn, id_bom, nuevo_bom['id_bom']
        )

        await self.db.registrar_historial(
            conn, nuevo_bom['id_bom'], AccionHistorial.CREADO,
            nueva_version, user_id,
            campo_modificado='version',
            valor_anterior=str(bom['version']),
            valor_nuevo=str(nueva_version)
        )

        logger.info(
            "Nueva version BOM creada: proyecto=%s, v%d->v%d, %d items copiados",
            bom['id_proyecto'], bom['version'], nueva_version, items_copiados
        )

        return await self.db.get_bom_by_id(conn, nuevo_bom['id_bom'])

    # ─── HISTORIAL Y APROBACIONES ────────────────────────────

    async def get_historial(self, conn, id_bom: UUID) -> list:
        """Lista historial de cambios."""
        return await self.db.get_historial_by_bom(conn, id_bom)

    async def get_aprobaciones(self, conn, id_bom: UUID) -> list:
        """Lista aprobaciones/rechazos."""
        return await self.db.get_aprobaciones_by_bom(conn, id_bom)

    async def get_estadisticas(self, conn, id_bom: UUID) -> dict:
        """Estadisticas del BOM."""
        return await self.db.get_estadisticas_bom(conn, id_bom)

    # ─── PERMISOS BOM-ROLE ───────────────────────────────────

    async def get_titulares_que_representa(self, conn, user_id: UUID) -> Set[UUID]:
        """Retorna el user_id + los titulares cuya suplencia activa tiene este usuario."""
        titulares = await self.db.get_titulares_que_representa(conn, user_id)
        result = set(titulares)
        result.add(user_id)
        return result

    async def es_bom_role(self, conn, bom: dict, user_id: UUID) -> bool:
        """True si el usuario es (o representa via suplencia) alguno de los 3 roles del BOM."""
        if not bom:
            return False
        representados = await self.get_titulares_que_representa(conn, user_id)
        bom_roles = {
            bom.get('elaborado_por'),
            bom.get('responsable_ing'),
            bom.get('jefe_construccion'),
            bom.get('coordinador_obra'),
        } - {None}
        return bool(representados & bom_roles)

    # ─── GRUPOS BOM ─────────────────────────────────────────

    async def set_item_grupos(
        self, conn, id_item: UUID, user_id: UUID, grupo_ids: List[int]
    ) -> None:
        """Asigna grupos BOM a un item. Registra en historial."""
        item = await self.db.get_item_by_id(conn, id_item)
        if not item:
            raise ValueError("Item no encontrado")
        await self.db.set_item_grupos(conn, id_item, grupo_ids)
        await self.db.registrar_historial(
            conn, item['id_bom'], AccionHistorial.EDITADO,
            item['bom_version'], user_id,
            id_item=id_item,
            campo_modificado='grupos_bom',
            valor_nuevo=str(grupo_ids)
        )

    # ─── SUPLENCIAS ─────────────────────────────────────────

    async def get_suplencia_activa(self, conn, user_id: UUID) -> Optional[dict]:
        """Suplencia activa vigente del usuario (como titular)."""
        return await self.db.get_suplencia_activa_del_titular(conn, user_id)

    async def configurar_suplente(
        self, conn, titular_id: UUID, suplente_id: UUID, fecha_fin
    ) -> dict:
        """Configura suplente para el usuario. Valida que la fecha sea futura."""
        from datetime import date as date_type
        if isinstance(fecha_fin, str):
            fecha_fin = date_type.fromisoformat(fecha_fin)
        if fecha_fin < today_mx():
            raise ValueError("La fecha fin de la suplencia debe ser futura")
        suplente = await self.db.get_usuario_activo_basico(conn, suplente_id)
        if not suplente:
            raise ValueError("El usuario suplente no existe o no esta activo")
        return await self.db.crear_suplencia(conn, titular_id, suplente_id, fecha_fin)

    async def eliminar_suplencia(self, conn, titular_id: UUID) -> None:
        """Desactiva la suplencia activa del usuario."""
        await self.db.desactivar_suplencia(conn, titular_id)

    # ─── APROBADOR FINAL ────────────────────────────────────

    async def enviar_revision_final(
        self, conn, id_bom: UUID, user_id: UUID
    ) -> dict:
        """Envia BOM APROBADO_CONST a revision del aprobador final."""
        bom = await self.get_bom(conn, id_bom)
        if EstatusBOM(bom['estatus']) != EstatusBOM.APROBADO_CONST:
            raise ValueError("El BOM debe estar APROBADO_CONST para enviar al aprobador final")

        aprobador_id = await self.db.get_aprobador_final_id(conn)
        await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.EN_REVISION_FINAL,
            fecha_envio_final=now_mx()
        )
        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.ENVIO_REVISION_FINAL,
            bom['version'], user_id
        )
        logger.info("BOM %s enviado a revision final por %s", id_bom, user_id)
        bom_updated = await self.db.get_bom_by_id(conn, id_bom)
        await self._notify_bom(conn, bom_updated, aprobador_id,
                               'ENVIADO_REVISION_FINAL', por_user_id=user_id)
        return bom_updated

    async def aprobar_final(
        self, conn, id_bom: UUID, user_id: UUID,
        comentarios: Optional[str] = None
    ) -> dict:
        """Aprobacion final del BOM por el aprobador final."""
        bom = await self.get_bom(conn, id_bom)
        if EstatusBOM(bom['estatus']) != EstatusBOM.EN_REVISION_FINAL:
            raise ValueError("El BOM debe estar EN_REVISION_FINAL para aprobar")

        aprobador_id = await self.db.get_aprobador_final_id(conn)
        if not aprobador_id or str(user_id) != str(aprobador_id):
            raise ValueError("Solo el aprobador final designado puede ejecutar esta accion")

        await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.APROBADO_FINAL,
            fecha_aprobacion_final=now_mx()
        )
        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.APROBACION_FINAL,
            bom['version'], user_id, comentarios=comentarios
        )
        logger.info("BOM %s aprobado final por %s", id_bom, user_id)
        bom_updated = await self.db.get_bom_by_id(conn, id_bom)
        await self._notify_bom(conn, bom_updated, bom_updated.get('elaborado_por'),
                               'APROBADO_FINAL', por_user_id=user_id)
        return bom_updated

    async def rechazar_final(
        self, conn, id_bom: UUID, user_id: UUID,
        comentarios: Optional[str] = None
    ) -> dict:
        """Rechazo por aprobador final. Vuelve a APROBADO_CONST."""
        if not comentarios or not comentarios.strip():
            raise ValueError("El motivo del rechazo es obligatorio")

        bom = await self.get_bom(conn, id_bom)
        if EstatusBOM(bom['estatus']) != EstatusBOM.EN_REVISION_FINAL:
            raise ValueError("El BOM debe estar EN_REVISION_FINAL para rechazar")

        aprobador_id = await self.db.get_aprobador_final_id(conn)
        if not aprobador_id or str(user_id) != str(aprobador_id):
            raise ValueError("Solo el aprobador final designado puede ejecutar esta accion")

        await self.db.update_bom_estatus(conn, id_bom, EstatusBOM.APROBADO_CONST)
        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.RECHAZO_FINAL,
            bom['version'], user_id, comentarios=comentarios
        )
        logger.info("BOM %s rechazado final por %s: %s", id_bom, user_id, comentarios)
        bom_updated = await self.db.get_bom_by_id(conn, id_bom)
        await self._notify_bom(conn, bom_updated, bom_updated.get('elaborado_por'),
                               'RECHAZADO_FINAL', por_user_id=user_id, comentarios=comentarios)
        return bom_updated

    async def get_aprobador_final_id(self, conn) -> Optional[UUID]:
        return await self.db.get_aprobador_final_id(conn)

    # ─── NOTIFICACIONES ──────────────────────────────────────

    async def _broadcast_bom(self, conn, to_user_id, tipo: str, titulo: str, proyecto_nombre: str) -> None:
        notif_svc = get_notifications_service()
        notification_data = await notif_svc.create_notification(
            conn=conn,
            usuario_id=to_user_id,
            tipo=tipo,
            titulo=titulo,
            mensaje=f"Proyecto: {proyecto_nombre}",
            modulo_origen="bom",
        )
        await notif_svc.broadcast_to_user(conn, to_user_id, notification_data)

    async def _notify_bom(
        self, conn, bom: dict,
        to_user_id,
        evento: str,
        por_user_id=None,
        comentarios: Optional[str] = None
    ) -> None:
        """Envia email de notificacion de cambio de estado BOM. Fire-and-forget."""
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
                logger.warning("BOM notify: no DEFAULT sender email configurado")
                return

            por_nombre = None
            if por_user_id:
                por_nombre = await self.db.get_usuario_nombre(conn, por_user_id)

            html = notif._render_template('shared/emails/bom/bom_revision.html', {
                'bom': bom,
                'evento': evento,
                'por_nombre': por_nombre or 'Sistema',
                'comentarios': comentarios,
                'app_url': f"{settings.APP_BASE_URL}/bom/{bom.get('id_proyecto')}/ui",
            })

            subject_map = {
                'ENVIADO_REVISION_ING':   f"BOM {bom.get('proyecto_id_estandar', '')} - Revision requerida (Ingenieria)",
                'APROBADO_ING':           f"BOM {bom.get('proyecto_id_estandar', '')} - Aprobado por Ingenieria",
                'RECHAZADO_ING':          f"BOM {bom.get('proyecto_id_estandar', '')} - Devuelto por Ingenieria",
                'ENVIADO_REVISION_OBRA':  f"BOM {bom.get('proyecto_id_estandar', '')} - Revision requerida (Obra)",
                'RECHAZADO_OBRA':         f"BOM {bom.get('proyecto_id_estandar', '')} - Devuelto por Obra",
                'ENVIADO_REVISION_CONST': f"BOM {bom.get('proyecto_id_estandar', '')} - Revision requerida (Construccion)",
                'APROBADO_CONST':         f"BOM {bom.get('proyecto_id_estandar', '')} - Aprobado por Construccion",
                'RECHAZADO_CONST':        f"BOM {bom.get('proyecto_id_estandar', '')} - Devuelto por Construccion",
                'ENVIADO_REVISION_FINAL': f"BOM {bom.get('proyecto_id_estandar', '')} - Aprobacion final requerida",
                'APROBADO_FINAL':         f"BOM {bom.get('proyecto_id_estandar', '')} - Aprobado definitivamente",
                'RECHAZADO_FINAL':        f"BOM {bom.get('proyecto_id_estandar', '')} - Devuelto por Aprobador Final",
                'FALTA_COORDINADOR_OBRA': f"BOM {bom.get('proyecto_id_estandar', '')} - Asignar coordinador de obra",
                'FALTA_ASIGNACION_CONSTRUCCION': f"BOM {bom.get('proyecto_id_estandar', '')} - Falta equipo de Construccion",
            }
            subject = subject_map.get(evento, f"BOM {bom.get('proyecto_id_estandar', '')} - Actualizacion")

            await notif._send_email({to_email}, set(), subject, html, sender_email)
            logger.info("BOM notify enviada: evento=%s to_user=%s", evento, to_user_id)
            await self._broadcast_bom(conn, to_user_id, f"BOM_{evento}", subject, bom.get('proyecto_nombre', ''))
        except (asyncpg.PostgresError, KeyError, RuntimeError, TemplateError, TypeError, ValueError) as exc:
            logger.warning("BOM notify: error enviando email, evento=%s: %s", evento, exc)

    # ─── CATALOGOS ──────────────────────────────────────────

    async def get_catalogos(self, conn) -> dict:
        """Obtiene todos los catalogos necesarios para formularios."""
        tipos_entrega = await self.db.get_tipos_entrega(conn)
        categorias = await self.db.get_categorias_compra(conn)
        proveedores = await self.db.get_proveedores(conn)
        usuarios_ing_jefes = await self.db.get_usuarios_por_area(conn, 'ingenieria', solo_jefes=True)
        usuarios_ing = await self.db.get_usuarios_por_area(conn, 'ingenieria', solo_jefes=False)

        usuarios_const_jefes = await self.db.get_usuarios_por_area(conn, 'construccion', solo_jefes=True)
        usuarios_const = await self.db.get_usuarios_por_area(conn, 'construccion', solo_jefes=False)
        grupos_bom = await self.db.get_grupos_bom(conn)

        return {
            'tipos_entrega': tipos_entrega,
            'categorias': categorias,
            'proveedores': proveedores,
            'usuarios_ing': usuarios_ing,           # Lista completa (por si se requiere)
            'usuarios_ing_jefes': usuarios_ing_jefes, # Solo jefes (para Responsable de Ing)
            'usuarios_const': usuarios_const,       # Lista completa (para Coordinador de Obra)
            'usuarios_const_jefes': usuarios_const_jefes, # Solo jefes (para Jefe de Construccion)
            'grupos_bom': grupos_bom,
        }

    # ─── EXPORT EXCEL ────────────────────────────────────────

    async def export_to_excel(self, conn, id_bom: UUID) -> bytes:
        """Genera archivo Excel con los items del BOM."""
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter
        from io import BytesIO

        bom = await self.get_bom(conn, id_bom)
        items = await self.db.get_items_by_bom(conn, id_bom)

        wb = Workbook()
        ws = wb.active
        ws.title = "Lista de Materiales"

        # Estilos
        header_font = Font(bold=True, color="FFFFFF", size=11)
        header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        thin_border = Border(
            left=Side(style='thin'), right=Side(style='thin'),
            top=Side(style='thin'), bottom=Side(style='thin')
        )

        # Info cabecera BOM (filas 1-5)
        info_font = Font(bold=True, size=10)
        ws.cell(row=1, column=1, value="Proyecto:").font = info_font
        ws.cell(row=1, column=2, value=f"{bom.get('proyecto_id_estandar', '')} - {bom.get('proyecto_nombre', '')}")
        ws.cell(row=2, column=1, value="Version:").font = info_font
        ws.cell(row=2, column=2, value=bom.get('version', 1))
        ws.cell(row=3, column=1, value="Estatus:").font = info_font
        ws.cell(row=3, column=2, value=bom.get('estatus', ''))
        ws.cell(row=4, column=1, value="Elaborado por:").font = info_font
        ws.cell(row=4, column=2, value=bom.get('elaborado_por_nombre', ''))
        ws.cell(row=5, column=1, value="Responsable Ing:").font = info_font
        ws.cell(row=5, column=2, value=bom.get('responsable_ing_nombre', ''))

        # Headers de tabla (fila 7)
        headers_row = 7
        headers = [
            "#", "Categoria", "Descripcion", "Cantidad", "Unidad",
            "Precio Unitario", "Importe",
            "Fecha Requerida", "Fecha Llegada Real", "Proveedor",
            "Tipo Entrega", "Fecha Estimada Entrega", "Comentarios", "Entregado"
        ]

        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=headers_row, column=col_num, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border

        # Datos
        total_importe = 0
        for row_num, item in enumerate(items, headers_row + 1):
            precio = float(item.get('precio_unitario') or 0)
            cantidad = float(item.get('cantidad') or 0)
            importe = cantidad * precio
            total_importe += importe

            row_data = [
                row_num - headers_row,
                item.get('categoria_nombre', ''),
                item.get('descripcion', ''),
                item.get('cantidad', 0),
                item.get('unidad_medida', ''),
                float(precio) if precio else None,
                importe if precio else None,
                item['fecha_requerida'].strftime("%d/%m/%Y") if item.get('fecha_requerida') else '',
                item['fecha_llegada_real'].strftime("%d/%m/%Y") if item.get('fecha_llegada_real') else '',
                item.get('proveedor_nombre', ''),
                item.get('tipo_entrega', ''),
                item['fecha_estimada_entrega'].strftime("%d/%m/%Y") if item.get('fecha_estimada_entrega') else '',
                item.get('comentarios', ''),
                'Si' if item.get('entregado') else 'No',
            ]

            for col_num, value in enumerate(row_data, 1):
                cell = ws.cell(row=row_num, column=col_num, value=value)
                cell.border = thin_border
                if col_num == 4:
                    cell.number_format = '#,##0.0000'
                    cell.alignment = Alignment(horizontal="right")
                elif col_num in (6, 7):
                    cell.number_format = '$#,##0.00'
                    cell.alignment = Alignment(horizontal="right")

        # Fila de total
        if items:
            total_row = headers_row + len(items) + 1
            total_font = Font(bold=True, size=11)
            ws.cell(row=total_row, column=3, value="TOTAL").font = total_font
            ws.cell(row=total_row, column=3).border = thin_border
            cell_total = ws.cell(row=total_row, column=7, value=total_importe)
            cell_total.font = total_font
            cell_total.number_format = '$#,##0.00'
            cell_total.alignment = Alignment(horizontal="right")
            cell_total.border = thin_border

        # Anchos de columna
        column_widths = [5, 20, 40, 12, 10, 16, 16, 16, 16, 25, 16, 18, 30, 10]
        for i, width in enumerate(column_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = width

        ws.freeze_panes = f"A{headers_row + 1}"

        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()

    # ─── COTIZACIONES ────────────────────────────────────────

    async def listar_cotizaciones(self, conn, id_bom: UUID) -> List[dict]:
        cotizaciones = await self.db.get_cotizaciones_by_bom(conn, id_bom)
        if not cotizaciones:
            return cotizaciones

        cot_items_map = {}
        all_bom_item_ids = []
        for cot in cotizaciones:
            items = await self.db.get_items_cotizacion(conn, cot['id'])
            cot_items_map[str(cot['id'])] = items
            all_bom_item_ids.extend(i['bom_item_id'] for i in items)

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

        # RFQ: sin validación de precios
        tiene_precios = any(
            float(i.get('precio_unitario') or 0) > 0 for i in items_data
        )

        if tiene_precios:
            bom_ids_con_precio = [
                i['bom_item_id'] for i in items_data
                if float(i.get('precio_unitario') or 0) > 0
            ]
            bom_items_batch = await self.db.get_items_by_ids(conn, list(set(bom_ids_con_precio)))
            bom_items_map_cot = {str(bi['id_item']): bi for bi in bom_items_batch}

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

        estatus_inicial = 'BORRADOR'
        proveedor_nombre_db = nombre_proveedor
        proveedor_id_db = proveedor_id
        if es_rfq:
            estatus_inicial = 'BORRADOR'  # RFQ también es borrador pero sin proveedor
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

        updated = await self.db.actualizar_estatus_cotizacion(conn, cotizacion_id, 'SELECCIONADA')

        # Actualizar estatus_compra de los ítems cubiertos
        items = await self.db.get_items_cotizacion(conn, cotizacion_id)
        if items:
            item_ids = [i['bom_item_id'] for i in items]
            await self.db.actualizar_estatus_compra_items(conn, item_ids, 'COTIZADO')

            # Actualizar precio_unitario del BOM con el precio de la cotización
            # Solo items no protegidos (origen != CATALOGO)
            bom_ids = [i['bom_item_id'] for i in items]
            bom_items_sel = await self.db.get_items_by_ids(conn, bom_ids)
            bom_items_sel_map = {str(bi['id_item']): bi for bi in bom_items_sel}
            for it in items:
                bom_item = bom_items_sel_map.get(str(it['bom_item_id']))
                if bom_item and bom_item.get('origen_precio') != 'CATALOGO':
                    await self.db.update_item(
                        conn, it['bom_item_id'],
                        precio_unitario=it['precio_unitario']
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
            # Notificar al coordinador de obra
            coordinador_id = bom.get('coordinador_obra')
            if coordinador_id:
                aut_enriquecida = {**autorizacion, 'nombre_proveedor': cotizacion.get('nombre_proveedor')}
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

        # Actualizar estatus_compra de los ítems a AUTORIZADO
        items_cot = await self.db.get_items_cotizacion(conn, aut['cotizacion_id'])
        if items_cot:
            item_ids = [i['bom_item_id'] for i in items_cot]
            await self.db.actualizar_estatus_compra_items(conn, item_ids, 'AUTORIZADO')

        updated = await self.db.update_autorizacion_paso_finanzas(conn, autorizacion_id, user_id, nota)

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
        else:  # AUTORIZADO_DIRECCION
            paso = 'FINANZAS'
            es_finanzas = finanzas_role in ('editor', 'admin')
            if user_role != 'ADMIN' and not es_finanzas:
                raise ValueError("Solo usuarios del módulo Finanzas pueden rechazar en este paso.")

        updated = await self.db.rechazar_autorizacion_db(conn, autorizacion_id, user_id, motivo, paso)

        # Cotización vuelve a RECIBIDA
        await self.db.actualizar_estatus_cotizacion(conn, aut['cotizacion_id'], 'RECIBIDA')

        # Ítems vuelven a SIN_COTIZAR
        items_cot = await self.db.get_items_cotizacion(conn, aut['cotizacion_id'])
        if items_cot:
            item_ids = [i['bom_item_id'] for i in items_cot]
            await self.db.actualizar_estatus_compra_items(conn, item_ids, 'SIN_COTIZAR')

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

    # ─── HELPERS INTERNOS ────────────────────────────────────

    async def _validar_edicion_items(self, conn, id_bom: UUID, area_editor: str) -> dict:
        """Valida que el BOM estÃ© en estado editable para agregar/eliminar items segun el area."""
        bom = await self.get_bom(conn, id_bom)
        estatus = EstatusBOM(bom['estatus'])

        if area_editor == 'ingenieria':
            if estatus not in ESTATUS_EDITABLE_ING:
                raise ValueError(
                    f"El BOM esta en estado {estatus} y no permite edicion estructural por Ingenieria."
                )
        elif area_editor == 'construccion':
            if estatus not in ESTATUS_EDITABLE_CONST_COMPRAS:
                raise ValueError(
                    f"El BOM esta en estado {estatus} y no permite edicion estructural por Construccion."
                )
        else:
            if estatus not in ESTATUS_EDITABLE_ING:
                raise ValueError("Area de edicion no reconocida o estado invalido.")
        
        return bom

    # ─── TRAZABILIDAD BOM ↔ COMPRAS ──────────────────────────

    async def get_items_por_autorizacion(self, conn, autorizacion_id: UUID) -> list:
        """Obtiene los items BOM vinculados a una autorizacion de compra."""
        return await self.db.get_items_by_autorizacion(conn, autorizacion_id)

    async def get_autorizacion_por_bom_pago(self, conn, id_bom_pago: UUID) -> Optional[dict]:
        """Obtiene la autorizacion a partir del id_bom_pago de finanzas."""
        return await self.db.get_autorizacion_by_bom_pago(conn, id_bom_pago)

    def match_conceptos_a_items(
        self, conceptos: list, bom_items: list
    ) -> dict:
        """
        Empareja conceptos de CFDI con items del BOM usando similitud de texto.

        Estrategia:
        1. Match exacto por clave_prod_serv contra id_material_ref→clave_prod_serv
        2. Mejor similitud de descripcion (normalizada, case-insensitive)
        3. Se asigna cada concepto al item con mayor similitud > umbral 0.4

        Returns:
            dict {indice_concepto: UUID(id_bom_item) | None}
        """
        import re
        match_map = {}

        def normalizar(texto):
            if not texto:
                return ""
            return re.sub(r'\s+', ' ', str(texto).strip().upper())

        for idx, concepto in enumerate(conceptos):
            desc_concepto = normalizar(concepto.get('descripcion', ''))
            clave_concepto = concepto.get('clave_prod_serv', '').strip()

            best_item = None
            best_score = 0.0

            for item in bom_items:
                desc_item = normalizar(item.get('descripcion', ''))

                if clave_concepto and len(clave_concepto) >= 6:
                    if desc_concepto and desc_item:
                        palabras_concepto = set(desc_concepto.split())
                        palabras_item = set(desc_item.split())
                        comunes = palabras_concepto & palabras_item
                        score = len(comunes) / max(len(palabras_concepto), 1)
                    else:
                        score = 0.0
                else:
                    if desc_concepto and desc_item:
                        palabras_concepto = set(desc_concepto.split())
                        palabras_item = set(desc_item.split())
                        comunes = palabras_concepto & palabras_item
                        token_score = len(comunes) / max(len(palabras_concepto), 1) if palabras_concepto else 0

                        len_ratio = min(len(desc_concepto), len(desc_item)) / max(len(desc_concepto), len(desc_item), 1)
                        score = (token_score * 0.7) + (len_ratio * 0.3)
                    else:
                        score = 0.0

                if score > best_score:
                    best_score = score
                    best_item = item

            if best_score >= 0.4 and best_item:
                match_map[idx] = best_item['id_item']
            else:
                match_map[idx] = None

        return match_map

    async def actualizar_estatus_compra(
        self, conn, item_ids: list, nuevo_estatus: str
    ) -> None:
        """Actualiza estatus_compra de items BOM en lote."""
        from uuid import UUID
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


def get_bom_service():
    """Dependency injection para FastAPI."""
    return BomService()
