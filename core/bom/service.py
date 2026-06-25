"""
Service Layer para BOM (Lista de Materiales).
Logica de negocio, workflow de aprobaciones, versionado y exportacion Excel.
"""

import logging
from collections import defaultdict
from uuid import UUID
from typing import Optional, List, Set

import asyncpg
import httpx
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
CAMPOS_CONSTRUCCION_BASE = {'fecha_requerida'}
CAMPOS_CONSTRUCCION_EJECUCION = {
    'entregado', 'comentarios', 'comentarios_operativos', 'cantidad_recibida',
    'fecha_llegada_real', 'estatus_ejecucion'
}
CAMPOS_CONSTRUCCION = CAMPOS_CONSTRUCCION_BASE | CAMPOS_CONSTRUCCION_EJECUCION
CAMPOS_COMPRAS = {
    'id_proveedor', 'tipo_entrega', 'fecha_estimada_entrega',
    'fecha_llegada_real', 'comentarios', 'comentarios_operativos',
    'precio_unitario', 'precio_real', 'origen_precio', 'moneda',
    'moneda_real', 'estatus_ejecucion'
}

# Campos editables en lote: los de edicion individual menos los que varian por
# item. Derivado de los sets por area para que el bulk sea siempre un subconjunto
# del individual (evita drift al agregar/quitar campos).
_CAMPOS_BULK_EXCLUIDOS = {'descripcion', 'cantidad', 'cantidad_recibida'}
CAMPOS_BULK = {
    'ingenieria': CAMPOS_INGENIERIA - _CAMPOS_BULK_EXCLUIDOS,
    'construccion': CAMPOS_CONSTRUCCION - _CAMPOS_BULK_EXCLUIDOS,
    'compras': CAMPOS_COMPRAS - _CAMPOS_BULK_EXCLUIDOS,
}

# Estados en los que NO se puede editar de ninguna forma
ESTATUS_BLOQUEADOS = {EstatusBOM.CANCELADO, EstatusBOM.APROBADO_FINAL}
ESTATUS_BLOQUEADOS_EJECUCION = {EstatusBOM.CANCELADO}

# Fechas de cabecera que representan el recorrido completo de aprobaciones.
FECHAS_FLUJO_BOM = (
    "fecha_envio_ing",
    "fecha_aprobacion_ing",
    "fecha_envio_obra",
    "fecha_aprobacion_obra",
    "fecha_envio_const",
    "fecha_aprobacion_const",
    "fecha_envio_final",
    "fecha_aprobacion_final",
)

# Estatus editables para agregar/eliminar items estructurales (ingenieria y construccion)
ESTATUS_EDITABLE_ING = set(EstatusBOM) - ESTATUS_BLOQUEADOS

# Campos especificos editables por construccion/compras en cualquier fase no cancelada
ESTATUS_EDITABLE_CONST_COMPRAS = set(EstatusBOM) - ESTATUS_BLOQUEADOS_EJECUCION

# Labels para historial
CAMPO_LABELS = {
    'id_categoria': 'Categoria',
    'descripcion': 'Descripcion',
    'cantidad': 'Cantidad',
    'unidad_medida': 'Unidad de medida',
    'fecha_requerida': 'Fecha requerida',
    'fecha_llegada_real': 'Fecha llegada real',
    'id_proveedor': 'Proveedor',
    'id_proveedor_real': 'Proveedor real',
    'tipo_entrega': 'Tipo entrega',
    'fecha_estimada_entrega': 'Fecha estimada entrega',
    'comentarios': 'Comentarios',
    'entregado': 'Entregado',
    'precio_unitario': 'Presupuesto unitario',
    'precio_real': 'Costo real',
    'moneda_real': 'Moneda real',
    'origen_precio': 'Origen precio',
    'cantidad_recibida': 'Cantidad recibida',
    'estatus_ejecucion': 'Estatus ejecucion',
    'comentarios_operativos': 'Comentarios operativos',
}

BOM_COSTOS_EVENTO = "BOM_ITEMS_SIN_COSTO"
BOM_COSTOS_REGLAS_MODULOS = {"BOM"}
BOM_COSTOS_ASUNTO_KEY = "bom.costos_notificacion_asunto"
BOM_COSTOS_TEMPLATE_KEY = "bom.costos_notificacion_template"
BOM_COSTOS_SSE_KEY = "bom.costos_notificacion_sse_activa"
BOM_COSTOS_DEFAULT_ASUNTO = "BOM {proyecto_id} - Items sin presupuesto base"
BOM_COSTOS_DEFAULT_TEMPLATE = (
    "El ingeniero ingreso {total_items} item(s) para el BOM del proyecto "
    "{proyecto_id} sin presupuesto base. Ingresa para actualizar el/los item(s)."
)


class BomService:
    """Logica de negocio para BOM."""

    def __init__(self):
        self.db = BomDBService()

    @staticmethod
    def _limpiar_fechas_flujo(*campos: str) -> dict:
        campos_limpieza = campos or FECHAS_FLUJO_BOM
        return {campo: None for campo in campos_limpieza}

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
        responsable_id: Optional[UUID], label: str, fallback_rol_org: str,
        representados: Optional[Set[UUID]] = None
    ) -> None:
        if not fallback_rol_org:
            raise ValueError(
                "_validar_aprobador_bom requiere fallback_rol_org: sin el, un BOM con "
                "responsable_id=None y gestion_solo_responsable=True quedaria sin validar"
            )
        if user_role == 'ADMIN':
            return
        solo_responsable = await ConfigService.get_global_config(
            conn, 'bom.gestion_solo_responsable', True, bool
        )
        if solo_responsable and responsable_id:
            # El titular del rol o su suplente activo pueden ejecutar la accion
            if representados is None:
                representados = await self.get_titulares_que_representa(conn, user_id)
            if responsable_id not in representados:
                raise ValueError(
                    f"Solo el {label} del proyecto (o su suplente) puede ejecutar esta accion"
                )
            return  # responsable_id=None cae al fallback de rol global
        if not await self.db.usuario_tiene_rol_org(conn, user_id, fallback_rol_org):
            raise ValueError(f"Solo el {label} puede ejecutar esta accion")

    async def puede_aprobar_bom(
        self, conn, user_id: UUID, user_role: str, rol_org: Optional[str],
        responsable_id: Optional[UUID], fallback_rol_org: str,
        representados: Optional[Set[UUID]] = None
    ) -> bool:
        """Version booleana de _validar_aprobador_bom para la UI (no lanza).

        Permite que el template oculte botones que el service rechazaria, usando
        exactamente la misma logica (ADMIN, propiedad, suplencia y fallback de rol
        global). Acepta `representados` precalculado para no repetir la consulta de
        suplencias dentro del mismo render.
        """
        try:
            await self._validar_aprobador_bom(
                conn, user_id, user_role, rol_org, responsable_id, "",
                fallback_rol_org, representados=representados
            )
            return True
        except ValueError:
            return False

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

    @staticmethod
    def item_sin_costo(item: dict) -> bool:
        """True si el item activo no tiene costo util para presupuesto."""
        if not item.get("activo", True):
            return False
        precio = item.get("precio_unitario")
        if precio is None:
            return True
        try:
            return float(precio) <= 0
        except (TypeError, ValueError):
            return True

    @staticmethod
    def mensaje_item_sin_costo() -> str:
        return (
            "Item guardado sin presupuesto base. Ingenieria debe capturar el presupuesto "
            "antes de avanzar el BOM."
        )

    @staticmethod
    def _format_template(template: str, context: dict) -> str:
        return template.format_map(defaultdict(str, context))

    @staticmethod
    def _resumen_costos_pendientes(items: list[dict], limit: int = 5) -> str:
        previews = [
            str(item.get("descripcion") or "Item sin descripcion")
            for item in items[:limit]
        ]
        suffix = f" y {len(items) - limit} mas" if len(items) > limit else ""
        return "; ".join(previews) + suffix

    def _build_costos_pendientes_error(self, items: list[dict]) -> str:
        detalle = self._resumen_costos_pendientes(items)
        return (
            f"No se puede avanzar el BOM: hay {len(items)} item(s) sin presupuesto base. "
            "Captura el presupuesto base antes de continuar. "
            f"Pendientes: {detalle}."
        )

    async def get_items_sin_costo(self, conn, id_bom: UUID) -> list[dict]:
        """Lista items activos sin costo asignado."""
        return await self.db.get_items_sin_costo_bom(conn, id_bom)

    async def validar_sin_costos_pendientes(self, conn, id_bom: UUID) -> None:
        """Bloquea avances del workflow si quedan items activos sin costo."""
        items_sin_costo = await self.get_items_sin_costo(conn, id_bom)
        if items_sin_costo:
            raise ValueError(self._build_costos_pendientes_error(items_sin_costo))

    async def _get_aprobador_final_direccion_id(self, conn) -> UUID:
        aprobador_id = await self.db.get_aprobador_final_id(conn)
        if not aprobador_id:
            raise ValueError("Configura un aprobador final de Dirección antes de avanzar el BOM")
        if not await self.db.usuario_tiene_rol_org(conn, aprobador_id, "director"):
            raise ValueError("El aprobador final del BOM debe ser un usuario activo de Dirección")
        return aprobador_id

    async def configurar_aprobador_final(self, conn, user_id: Optional[UUID]) -> None:
        if user_id and not await self.db.usuario_tiene_rol_org(conn, user_id, "director"):
            raise ValueError("El aprobador final debe ser un usuario activo de Dirección")
        await self.db.set_aprobador_final_id(conn, user_id)

    async def validar_responsables_workflow_bom(self, conn, bom: dict) -> None:
        """Bloquea el primer envio si el workflow completo no tiene responsables."""
        problemas = []
        if not bom.get("responsable_ing"):
            problemas.append("falta responsable de Ingenieria")
        if not bom.get("coordinador_obra"):
            problemas.append("falta Coordinador de Obra")
        if not bom.get("jefe_construccion"):
            problemas.append("falta Jefe de Construccion")
        try:
            await self._get_aprobador_final_direccion_id(conn)
        except ValueError as exc:
            problemas.append(str(exc))

        if problemas:
            raise ValueError(
                "No se puede enviar el BOM a revision: " + "; ".join(problemas)
            )

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

        # Campos protegidos: items de catalogo no permiten cambiar identidad tecnica.
        # El costo si queda editable para resolver items sin presupuesto.
        campos_protegidos_catalogo = {
            'descripcion', 'id_material_ref', 'unidad_medida'
        }

        # Validar que campos correspondan al area del editor y separar base vs ejecucion.
        campos_base = {}
        campos_ejecucion = {}
        if area_editor == 'ingenieria':
            if bom_estatus not in ESTATUS_EDITABLE_ING:
                raise ValueError("El BOM no esta en estado editable para ingenieria")
            campos_base = {k: v for k, v in campos.items() if k in CAMPOS_INGENIERIA}
            if 'precio_unitario' in campos_base and campos_base['precio_unitario'] is not None:
                from decimal import Decimal as _D
                if _D(str(campos_base['precio_unitario'])) < 0:
                    raise ValueError("El precio unitario no puede ser negativo")
            # Items de catalogo: remover campos protegidos
            if es_catalogo:
                campos_base = {
                    k: v for k, v in campos_base.items()
                    if k not in campos_protegidos_catalogo
                }
        elif area_editor == 'construccion':
            if bom_estatus not in ESTATUS_EDITABLE_CONST_COMPRAS:
                raise ValueError("El BOM no esta en estado editable para construccion")
            puede_actualizar_base_construccion = bom_estatus not in ESTATUS_BLOQUEADOS
            if puede_actualizar_base_construccion:
                campos_base = {
                    k: v for k, v in campos.items()
                    if k in CAMPOS_CONSTRUCCION_BASE
                }
            campos_ejecucion = {
                k: v for k, v in campos.items()
                if k in CAMPOS_CONSTRUCCION_EJECUCION
            }
            if 'comentarios' in campos_ejecucion:
                campos_ejecucion['comentarios_operativos'] = campos_ejecucion.pop('comentarios')
            # Recepcion parcial: auto-calcular entregado segun cantidad recibida
            if 'cantidad_recibida' in campos_ejecucion:
                from decimal import Decimal
                cant_recibida = Decimal(str(campos_ejecucion['cantidad_recibida']))
                cant_total = Decimal(str(item['cantidad']))
                if cant_recibida < 0:
                    raise ValueError("La cantidad recibida no puede ser negativa")
                if cant_recibida > cant_total:
                    raise ValueError("La cantidad recibida no puede exceder la cantidad total del item")
                if cant_recibida >= cant_total:
                    campos_ejecucion.setdefault('estatus_ejecucion', 'RECIBIDO_TOTAL')
                    if puede_actualizar_base_construccion:
                        campos_base['entregado'] = True
                        campos_base['fecha_entrega_check'] = now_mx()
                elif cant_recibida > 0:
                    campos_ejecucion.setdefault('estatus_ejecucion', 'RECIBIDO_PARCIAL')
                    if puede_actualizar_base_construccion:
                        campos_base['entregado'] = False
                        campos_base['fecha_entrega_check'] = None
                else:
                    if puede_actualizar_base_construccion:
                        campos_base['entregado'] = False
                        campos_base['fecha_entrega_check'] = None
            # Marcar entregado manualmente (si no viene cantidad_recibida)
            elif 'entregado' in campos_ejecucion and campos_ejecucion['entregado']:
                campos_ejecucion['cantidad_recibida'] = item['cantidad']
                campos_ejecucion.setdefault('estatus_ejecucion', 'RECIBIDO_TOTAL')
                if puede_actualizar_base_construccion:
                    campos_base['entregado'] = True
                    campos_base['fecha_entrega_check'] = now_mx()
            elif 'entregado' in campos_ejecucion and not campos_ejecucion['entregado']:
                campos_ejecucion['cantidad_recibida'] = 0
                if puede_actualizar_base_construccion:
                    campos_base['entregado'] = False
                    campos_base['fecha_entrega_check'] = None
            campos_ejecucion.pop('entregado', None)
        elif area_editor == 'compras':
            if bom_estatus not in ESTATUS_EDITABLE_CONST_COMPRAS:
                raise ValueError("El BOM no esta en estado editable para compras")
            campos_compras = {k: v for k, v in campos.items() if k in CAMPOS_COMPRAS}
            mapping = {
                'id_proveedor': 'id_proveedor_real',
                'precio_unitario': 'precio_real',
                'moneda': 'moneda_real',
                'comentarios': 'comentarios_operativos',
            }
            campos_ejecucion = {
                mapping.get(k, k): v for k, v in campos_compras.items()
                if k not in {'origen_precio'}
            }
            if 'precio_real' in campos_ejecucion and campos_ejecucion['precio_real'] is not None:
                from decimal import Decimal as _D
                if _D(str(campos_ejecucion['precio_real'])) < 0:
                    raise ValueError("El precio unitario no puede ser negativo")
                campos_ejecucion.setdefault('estatus_ejecucion', 'COTIZADO')
        else:
            raise ValueError("Sin permisos para editar items del BOM")

        if not campos_base and not campos_ejecucion:
            raise ValueError("No hay campos validos para actualizar")

        # Registrar cambios en historial
        historial_campos = []
        historial_campos.extend((campo, campo, valor) for campo, valor in campos_base.items())
        ejecucion_public_keys = {
            'id_proveedor_real': 'id_proveedor',
            'precio_real': 'precio_real',
            'moneda_real': 'moneda_real',
            'cantidad_recibida': 'cantidad_recibida',
            'fecha_estimada_entrega': 'fecha_estimada_entrega',
            'fecha_llegada_real': 'fecha_llegada_real',
            'tipo_entrega': 'tipo_entrega',
            'estatus_ejecucion': 'estatus_ejecucion',
            'comentarios_operativos': 'comentarios_operativos',
        }
        historial_campos.extend(
            (campo, ejecucion_public_keys.get(campo, campo), valor)
            for campo, valor in campos_ejecucion.items()
        )
        for campo_hist, campo_actual, valor_nuevo in historial_campos:
            valor_anterior = item.get(campo_actual)
            if str(valor_anterior) != str(valor_nuevo):
                await self.db.registrar_historial(
                    conn, item['id_bom'], AccionHistorial.EDITADO,
                    item['bom_version'], user_id,
                    id_item=id_item,
                    campo_modificado=CAMPO_LABELS.get(campo_hist, campo_hist),
                    valor_anterior=str(valor_anterior) if valor_anterior is not None else None,
                    valor_nuevo=str(valor_nuevo) if valor_nuevo is not None else None
                )

        if campos_base:
            await self.db.update_item(conn, id_item, **campos_base)
        if campos_ejecucion:
            await self.db.upsert_item_ejecucion(
                conn, id_item, updated_by=user_id, **campos_ejecucion
            )
        return await self.db.get_item_by_id(conn, id_item)

    async def _validar_item_bulk(
        self, conn, item: Optional[dict], id_bom: UUID, user_id: UUID,
        area_editor: str, permisos_ing_cache: dict
    ) -> None:
        """Valida que un item pueda editarse dentro de una operacion bulk."""
        if not item:
            raise ValueError("Item no encontrado")
        if str(item.get('id_bom')) != str(id_bom):
            raise ValueError("El item no pertenece a este BOM")
        if not item.get('activo', True):
            raise ValueError("No se puede editar un item eliminado")
        if item.get('bloqueado'):
            raise ValueError("Este item fue completado en una version anterior del BOM y no se puede modificar")

        bom_estatus = EstatusBOM(item['bom_estatus'])
        if area_editor == 'ingenieria':
            id_proyecto = item['id_proyecto']
            cache_key = str(id_proyecto)
            if cache_key not in permisos_ing_cache:
                try:
                    await self._validar_retomar_bom_ingenieria(conn, id_proyecto, user_id)
                    permisos_ing_cache[cache_key] = None
                except ValueError as exc:
                    permisos_ing_cache[cache_key] = str(exc)
            if permisos_ing_cache[cache_key]:
                raise ValueError(permisos_ing_cache[cache_key])
            if bom_estatus not in ESTATUS_EDITABLE_ING:
                raise ValueError("El BOM no esta en estado editable para ingenieria")
        elif area_editor == 'construccion':
            if bom_estatus not in ESTATUS_EDITABLE_CONST_COMPRAS:
                raise ValueError("El BOM no esta en estado editable para construccion")
        elif area_editor == 'compras':
            if bom_estatus not in ESTATUS_EDITABLE_CONST_COMPRAS:
                raise ValueError("El BOM no esta en estado editable para compras")
        else:
            raise ValueError("Sin permisos para editar items del BOM")

    async def editar_items_bulk(
        self, conn, id_bom: UUID, item_ids: List[UUID], user_id: UUID,
        area_editor: str, campo: str,
        valor=None, grupo_ids: Optional[List[int]] = None,
    ) -> dict:
        """Aplica un mismo cambio a varios items del BOM.

        Reutiliza editar_item/set_item_grupos por item, heredando validacion,
        proteccion de catalogo e historial. Captura ValueError por item y
        continua, devolviendo cuantos se actualizaron y cuales se omitieron
        (decision: aplicar a los validos, reportar el resto).

        campo == 'grupos' reemplaza la clasificacion tecnica con grupo_ids.
        """
        if area_editor not in ('ingenieria', 'construccion', 'compras'):
            raise ValueError("Sin permisos para editar items del BOM")
        if not item_ids:
            raise ValueError("No hay items seleccionados")
        item_ids = list(dict.fromkeys(item_ids))

        es_grupos = campo == 'grupos'
        if es_grupos:
            if area_editor not in ('ingenieria', 'construccion'):
                raise ValueError("Solo Ingenieria y Construccion pueden cambiar grupos")
            if not grupo_ids:
                raise ValueError("Selecciona al menos un grupo BOM")
        elif campo not in CAMPOS_BULK.get(area_editor, set()):
            raise ValueError("Campo no editable en lote para tu area")

        items_context = await self.db.get_items_context_by_ids(conn, item_ids)
        items_por_id = {str(item['id_item']): item for item in items_context}
        permisos_ing_cache = {}
        actualizados = 0
        omitidos = []
        # Transaccion unica: los items omitidos por ValueError no escriben nada
        # (se validan antes de tocar BD), y un PostgresError a mitad del lote
        # revierte todo en vez de dejar items a medio aplicar.
        async with conn.transaction():
            for id_item in item_ids:
                try:
                    item = items_por_id.get(str(id_item))
                    await self._validar_item_bulk(
                        conn, item, id_bom, user_id, area_editor, permisos_ing_cache
                    )
                    if es_grupos:
                        if EstatusBOM(item['bom_estatus']) == EstatusBOM.APROBADO_FINAL:
                            raise ValueError("El BOM aprobado final no permite cambiar grupos")
                        await self.set_item_grupos(conn, id_item, user_id, grupo_ids)
                    else:
                        await self.editar_item(conn, id_item, user_id, area_editor, **{campo: valor})
                    actualizados += 1
                except ValueError as e:
                    omitidos.append({'id_item': id_item, 'motivo': str(e)})
        return {'actualizados': actualizados, 'omitidos': omitidos}

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
            if (
                (item.get('moneda') == 'USD' and item.get('precio_unitario'))
                or (item.get('moneda_real') == 'USD' and item.get('precio_real'))
            )
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
            moneda_real = item.get('moneda_real')
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
            if moneda_real == 'USD' and item.get('precio_real'):
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
                    item['costo_real_mxn'] = round(float(item['precio_real']) * tc, 2)

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
        if item.get('moneda_real') == 'USD' and item.get('precio_real'):
            from core.tipo_cambio.db_service import TipoCambioDBService
            tc_svc = TipoCambioDBService()
            tasa = await tc_svc.get_tasa_mas_reciente(conn)
            tc = float(tasa['tasa_mxn']) if tasa else None
            if tc:
                item['costo_real_mxn'] = round(float(item['precio_real']) * tc, 2)
        # Enriquecer gasto_real
        gasto_map = await self.db.get_gasto_real_por_item(conn, [id_item])
        gasto = gasto_map.get(str(id_item))
        if gasto is not None:
            item['gasto_real'] = round(gasto, 2)
        return item

    # ─── RESUMEN DE COMPRA ───────────────────────────────────

    async def get_resumen_compra(self, conn, id_bom: UUID) -> dict:
        """Arma el comparativo Presupuesto vs Facturado vs Pagado del BOM.

        Agrupa las categorias por grupo BOM (rollup en memoria), calcula totales,
        desviaciones (presupuesto - facturado / - pagado) y métricas normalizadas
        (MXN por modulo FV y por kWp). Solo agregacion; no escribe nada.
        """
        filas = await self.db.get_resumen_compra(conn, id_bom)
        divisores = await self.db.get_divisores_bom(conn, id_bom)

        por_grupo: dict[str, dict] = {}
        for f in filas:
            grupo_codigo = f["grupo_codigo"] or "SIN_CLASIFICAR"
            grupo = por_grupo.setdefault(grupo_codigo, {
                "codigo": grupo_codigo,
                "nombre": f["grupo_nombre"] or "Sin clasificar",
                "orden": int(f["grupo_orden"] or 999),
                "categorias": [],
            })
            facturado = float(f["facturado_confirmado_mxn"])
            facturado_sugerido = float(f["facturado_sugerido_mxn"])
            cat = {
                "categoria_id": f["categoria_id"],
                "categoria_nombre": f["categoria_nombre"],
                "presupuesto": float(f["presupuesto_mxn"]),
                "real": float(f.get("compra_real_mxn") or 0),
                "facturado": facturado,
                "facturado_sugerido": facturado_sugerido,
                "facturado_total_potencial": facturado + facturado_sugerido,
                "pagado": float(f["pagado_mxn"]),
            }
            cat["dif_real"] = cat["presupuesto"] - cat["real"]
            cat["dif_facturado"] = cat["presupuesto"] - cat["facturado"]
            cat["dif_pagado"] = cat["presupuesto"] - cat["pagado"]
            grupo["categorias"].append(cat)

        secciones = []
        tot_presup = tot_fact = tot_pag = 0.0
        tot_sugerido = 0.0
        tot_real = 0.0

        for grupo in sorted(por_grupo.values(), key=lambda g: (g["orden"], g["codigo"])):
            cats = grupo["categorias"]
            s_presup = sum(c["presupuesto"] for c in cats)
            s_real = sum(c["real"] for c in cats)
            s_fact = sum(c["facturado"] for c in cats)
            s_sug = sum(c["facturado_sugerido"] for c in cats)
            s_pag = sum(c["pagado"] for c in cats)
            secciones.append({
                "codigo": grupo["codigo"],
                "nombre": grupo["nombre"],
                "presupuesto": s_presup,
                "real": s_real,
                "facturado": s_fact,
                "facturado_sugerido": s_sug,
                "facturado_total_potencial": s_fact + s_sug,
                "pagado": s_pag,
                "dif_real": s_presup - s_real,
                "dif_facturado": s_presup - s_fact,
                "dif_pagado": s_presup - s_pag,
                "categorias": cats,
            })
            tot_presup += s_presup
            tot_real += s_real
            tot_fact += s_fact
            tot_sugerido += s_sug
            tot_pag += s_pag

        totales = {
            "presupuesto": tot_presup,
            "real": tot_real,
            "facturado": tot_fact,
            "facturado_sugerido": tot_sugerido,
            "facturado_total_potencial": tot_fact + tot_sugerido,
            "pagado": tot_pag,
            "dif_real": tot_presup - tot_real,
            "dif_facturado": tot_presup - tot_fact,
            "dif_pagado": tot_presup - tot_pag,
        }

        modulos = divisores["modulos_fv"]
        kwp = divisores["kwp"]

        def _por(divisor, valor):
            return round(valor / divisor, 2) if divisor else None

        metricas = {
            "modulos_fv": modulos,
            "kwp": kwp,
            "presup_por_modulo": _por(modulos, tot_presup),
            "real_por_modulo": _por(modulos, tot_real),
            "facturado_por_modulo": _por(modulos, tot_fact),
            "sugerido_por_modulo": _por(modulos, tot_sugerido),
            "presup_por_kwp": _por(kwp, tot_presup),
            "real_por_kwp": _por(kwp, tot_real),
            "facturado_por_kwp": _por(kwp, tot_fact),
            "sugerido_por_kwp": _por(kwp, tot_sugerido),
        }

        return {
            "secciones": secciones,
            "totales": totales,
            "metricas": metricas,
            "sin_datos": not secciones,
        }

    # ─── WORKFLOW DE APROBACION ──────────────────────────────

    async def enviar_revision_ing(
        self, conn, id_bom: UUID, user_id: UUID
    ) -> dict:
        """Envia BOM a revision de responsable de ingenieria."""
        bom = await self.get_bom(conn, id_bom)
        await self._validar_retomar_bom_ingenieria(conn, bom['id_proyecto'], user_id)

        if EstatusBOM(bom['estatus']) != EstatusBOM.BORRADOR:
            raise ValueError("Solo se puede enviar a revision desde BORRADOR")
        await self.validar_responsables_workflow_bom(conn, bom)

        # Verificar que tenga items
        items = await self.db.get_items_by_bom(conn, id_bom)
        if not items:
            raise ValueError("El BOM debe tener al menos un item")
        await self.validar_sin_costos_pendientes(conn, id_bom)

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
        await self.validar_sin_costos_pendientes(conn, id_bom)

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
        await self.validar_sin_costos_pendientes(conn, id_bom)

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
        rol_org: Optional[str] = None, comentarios: Optional[str] = None,
        destino_rechazo: Optional[str] = None
    ) -> dict:
        """Rechaza BOM por construccion. Vuelve a Obra o a Borrador."""
        if not comentarios or not comentarios.strip():
            raise ValueError("El motivo del rechazo es obligatorio")
        if destino_rechazo not in {"obra", "ingenieria"}:
            raise ValueError("Destino de rechazo invalido")

        bom = await self.get_bom(conn, id_bom)
        await self._validar_aprobador_bom(
            conn, user_id, user_role, rol_org,
            bom.get('jefe_construccion'), "Jefe de Construccion", "jefe_construccion"
        )

        if EstatusBOM(bom['estatus']) != EstatusBOM.EN_REVISION_CONST:
            raise ValueError("El BOM debe estar EN_REVISION_CONST para rechazar")

        if destino_rechazo == "obra":
            nuevo_estatus = EstatusBOM.EN_REVISION_OBRA
            campos_limpios = self._limpiar_fechas_flujo(
                "fecha_aprobacion_obra",
                "fecha_envio_const",
                "fecha_aprobacion_const",
                "fecha_envio_final",
                "fecha_aprobacion_final",
            )
            notify_to = bom.get('coordinador_obra')
        else:
            nuevo_estatus = EstatusBOM.BORRADOR
            campos_limpios = self._limpiar_fechas_flujo()
            notify_to = bom.get('elaborado_por')

        await self.db.update_bom_estatus(conn, id_bom, nuevo_estatus, **campos_limpios)
        await self.db.registrar_aprobacion(
            conn, id_bom, TipoAprobacion.RECHAZO_CONST,
            bom['version'], user_id, comentarios=comentarios
        )
        logger.info(
            "BOM %s rechazado por const %s hacia %s: %s",
            id_bom, user_id, destino_rechazo, comentarios
        )
        bom_updated = await self.db.get_bom_by_id(conn, id_bom)
        await self._notify_bom(conn, bom_updated, notify_to,
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
        await self.validar_sin_costos_pendientes(conn, id_bom)

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
        await self.validar_sin_costos_pendientes(conn, id_bom)

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
        """Rechaza BOM por coordinador de obra. Vuelve a BORRADOR."""
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
            conn, id_bom, EstatusBOM.BORRADOR,
            **self._limpiar_fechas_flujo()
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

    async def es_bom_role(
        self, conn, bom: dict, user_id: UUID,
        representados: Optional[Set[UUID]] = None
    ) -> bool:
        """True si el usuario es (o representa via suplencia) alguno de los 3 roles del BOM."""
        if not bom:
            return False
        if representados is None:
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
        if not grupo_ids:
            raise ValueError("Selecciona al menos un grupo BOM")
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
        self, conn, id_bom: UUID, user_id: UUID, user_role: str,
        rol_org: Optional[str] = None
    ) -> dict:
        """Envia BOM APROBADO_CONST a revision del aprobador final."""
        bom = await self.get_bom(conn, id_bom)
        await self._validar_aprobador_bom(
            conn, user_id, user_role, rol_org,
            bom.get('jefe_construccion'), "Jefe de Construccion", "jefe_construccion"
        )

        if EstatusBOM(bom['estatus']) != EstatusBOM.APROBADO_CONST:
            raise ValueError("El BOM debe estar APROBADO_CONST para enviar al aprobador final")
        await self.validar_sin_costos_pendientes(conn, id_bom)

        aprobador_id = await self._get_aprobador_final_direccion_id(conn)
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
        await self.validar_sin_costos_pendientes(conn, id_bom)

        aprobador_id = await self._get_aprobador_final_direccion_id(conn)
        if str(user_id) != str(aprobador_id):
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
        """Rechazo por aprobador final. Vuelve a BORRADOR."""
        if not comentarios or not comentarios.strip():
            raise ValueError("El motivo del rechazo es obligatorio")

        bom = await self.get_bom(conn, id_bom)
        if EstatusBOM(bom['estatus']) != EstatusBOM.EN_REVISION_FINAL:
            raise ValueError("El BOM debe estar EN_REVISION_FINAL para rechazar")

        aprobador_id = await self._get_aprobador_final_direccion_id(conn)
        if str(user_id) != str(aprobador_id):
            raise ValueError("Solo el aprobador final designado puede ejecutar esta accion")

        await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.BORRADOR,
            **self._limpiar_fechas_flujo()
        )
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

    async def notificar_items_sin_costo_compras(
        self, conn, id_bom: UUID, user_id: UUID
    ) -> dict:
        """Envia a Compras la lista consolidada de items del BOM sin costo."""
        bom = await self.get_bom(conn, id_bom)
        items = await self.get_items_sin_costo(conn, id_bom)
        if not items:
            raise ValueError("No hay items sin presupuesto base para notificar.")

        try:
            from core.workflow.notification_service import NotificationService
            notif = NotificationService()

            to_emails = await notif._get_emails_for_event(
                conn, BOM_COSTOS_EVENTO, "TO", BOM_COSTOS_REGLAS_MODULOS
            )
            cc_emails = await notif._get_emails_for_event(
                conn, BOM_COSTOS_EVENTO, "CC", BOM_COSTOS_REGLAS_MODULOS
            )
            bcc_emails = await notif._get_emails_for_event(
                conn, BOM_COSTOS_EVENTO, "CCO", BOM_COSTOS_REGLAS_MODULOS
            )
            if not to_emails:
                raise ValueError(
                    "Faltan correos para notificar a Compras. Configura al menos "
                    "un destinatario principal en Admin > Configuracion BOM > "
                    "Costos pendientes."
                )

            sender = await notif._get_notification_sender(conn, "BOM")
            por_nombre = await self.db.get_usuario_nombre(conn, user_id)
            proyecto_id = bom.get("proyecto_id_estandar") or str(bom.get("id_proyecto"))
            format_ctx = {
                "bom": bom,
                "items": items,
                "total_items": len(items),
                "proyecto_id": proyecto_id,
                "proyecto_nombre": bom.get("proyecto_nombre") or "",
                "version": bom.get("version", ""),
                "por_nombre": por_nombre or "Sistema",
                "app_url": f"{settings.APP_BASE_URL}/bom/{bom.get('id_proyecto')}/ui",
            }

            subject_template = await ConfigService.get_global_config(
                conn, BOM_COSTOS_ASUNTO_KEY, BOM_COSTOS_DEFAULT_ASUNTO, str
            )
            body_template = await ConfigService.get_global_config(
                conn, BOM_COSTOS_TEMPLATE_KEY, BOM_COSTOS_DEFAULT_TEMPLATE, str
            )
            subject = self._format_template(subject_template, format_ctx).strip()
            mensaje = self._format_template(body_template, format_ctx).strip()
            if not subject:
                subject = self._format_template(BOM_COSTOS_DEFAULT_ASUNTO, format_ctx)
            if not mensaje:
                mensaje = self._format_template(BOM_COSTOS_DEFAULT_TEMPLATE, format_ctx)

            html = notif._render_template("shared/emails/bom/items_sin_costo.html", {
                **format_ctx,
                "mensaje": mensaje,
            })
            sent = await notif._send_email(
                to_emails,
                cc_emails,
                subject,
                html,
                sender["email"],
                bcc_emails=bcc_emails,
            )
            if not sent:
                raise ValueError("No se pudo enviar la notificacion a Compras.")

            sse_notificados = 0
            sse_activa = await ConfigService.get_global_config(
                conn, BOM_COSTOS_SSE_KEY, False, bool
            )
            if sse_activa:
                sse_notificados = await self._broadcast_costos_pendientes(conn, bom, items)

            logger.info(
                "BOM costos pendientes notificados: bom=%s items=%d to=%d cc=%d cco=%d sse=%d por=%s",
                id_bom, len(items), len(to_emails), len(cc_emails), len(bcc_emails),
                sse_notificados, user_id,
            )
            return {
                "items_sin_costo": len(items),
                "destinatarios": len(to_emails),
                "cc": len(cc_emails),
                "cco": len(bcc_emails),
                "sse": sse_notificados,
            }
        except ValueError:
            raise
        except (TemplateError, httpx.HTTPError, RuntimeError, TypeError, KeyError) as exc:
            logger.warning("BOM costos pendientes: error notificando compras: %s", exc)
            raise ValueError("No se pudo enviar la notificacion a Compras.") from exc

    async def _broadcast_costos_pendientes(self, conn, bom: dict, items: list[dict]) -> int:
        """Crea aviso SSE para usuarios activos de Compras usando un tipo permitido."""
        usuarios_compras = await self.db.get_usuarios_por_area(conn, "compras", solo_jefes=False)
        if not usuarios_compras:
            return 0

        notif_svc = get_notifications_service()
        titulo = f"BOM {bom.get('proyecto_id_estandar', '')} - Items sin presupuesto"
        mensaje = f"{len(items)} item(s) sin presupuesto pendiente(s) de actualizar."
        count = 0
        for usuario in usuarios_compras:
            usuario_id = usuario.get("id_usuario")
            if not usuario_id:
                continue
            notification_data = await notif_svc.create_notification(
                conn=conn,
                usuario_id=usuario_id,
                tipo="CAMBIO_ESTATUS",
                titulo=titulo,
                mensaje=mensaje,
                id_oportunidad=bom.get("id_oportunidad"),
                modulo_origen="bom",
            )
            await notif_svc.broadcast_to_user(conn, usuario_id, notification_data)
            count += 1
        return count

    async def _broadcast_bom(self, conn, to_user_id, tipo: str, titulo: str, proyecto_nombre: str) -> None:
        notif_svc = get_notifications_service()
        tipo_notificacion = (
            tipo
            if tipo in {"ASIGNACION", "CAMBIO_ESTATUS", "NUEVO_COMENTARIO"}
            else "CAMBIO_ESTATUS"
        )
        notification_data = await notif_svc.create_notification(
            conn=conn,
            usuario_id=to_user_id,
            tipo=tipo_notificacion,
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
        import re
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
            if a is None or b is None:
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

        for idx, concepto in enumerate(conceptos):
            desc_concepto = normalizar(concepto.get('descripcion', ''))
            clave_concepto = (concepto.get('clave_prod_serv') or '').strip()
            importe_concepto = to_float(concepto.get('importe'))

            # 1. ALTA - clave SAT exacta (con desempate por monto si hay empate)
            candidatos_clave = [
                item for item in bom_items
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
                continue

            # 2. ALTA - memoria proveedor-producto: material aprendido para esta clave
            material_recordado = memoria_map.get(clave_concepto) if clave_concepto else None
            if material_recordado:
                candidatos_mem = [
                    item for item in bom_items
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
                    continue

            # 3. ALTA - ancla de cotizacion: monto ~= subtotal de la linea declarada
            candidatos_monto = [
                item for item in bom_items
                if monto_cercano(importe_concepto, to_float(item.get('coti_subtotal')))
            ]
            if len(candidatos_monto) == 1:
                match_map[idx] = {
                    'id_item': candidatos_monto[0]['id_item'],
                    'confianza': 'ALTA', 'origen': 'COTIZACION',
                }
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
                continue

            # 4. BAJA - similitud de texto (fallback)
            best_item, best_score = None, 0.0
            for item in bom_items:
                score = score_texto(desc_concepto, normalizar(item.get('descripcion', '')))
                if score > best_score:
                    best_score, best_item = score, item

            if best_item and best_score >= 0.4:
                match_map[idx] = {
                    'id_item': best_item['id_item'], 'confianza': 'BAJA', 'origen': 'TEXTO',
                }
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
