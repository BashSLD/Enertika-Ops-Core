"""
Service Layer para BOM (Lista de Materiales).
Logica de negocio, workflow de aprobaciones, versionado y exportacion Excel.
"""

import logging
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from uuid import UUID
from typing import Optional, List, Set

import asyncpg
import httpx
from jinja2 import TemplateError

from core.bom.compras_service import (
    BomComprasServiceMixin,
    ESTATUS_ITEM_CERRADO_COMPRA,
    ESTATUS_COMPRA_BLOQUEA_ADENDA,
    ESTATUS_ADENDA_APROBADA,
)
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
    'fecha_estimada_entrega', 'fecha_llegada_real', 'estatus_ejecucion'
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
TIPO_ITEM_BASE = "BASE"
TIPO_ITEM_REEMPLAZO = "REEMPLAZO"
TIPO_ITEM_FUERA_SCOPE = "FUERA_SCOPE"
ESTATUS_ADENDA_PENDIENTE_CONSTRUCCION = "PENDIENTE_CONSTRUCCION"
ESTATUS_ADENDA_PENDIENTE_INGENIERIA = "PENDIENTE_INGENIERIA"
ESTATUS_ADENDA_TERMINALES = {ESTATUS_ADENDA_APROBADA, "RECHAZADA", "CANCELADA"}
TIPOS_PROPUESTA_CAMBIO = {"OBRA", "CONSTRUCCION"}
ACCIONES_PROPUESTA_CAMBIO = {"AGREGAR", "EDITAR", "ELIMINAR"}
ESTATUS_PROPUESTA_CAMBIO = {EstatusBOM.EN_REVISION_OBRA, EstatusBOM.EN_REVISION_CONST}
ESTATUS_BASE_CONSTRUCCION_BLOQUEADA = {
    EstatusBOM.EN_REVISION_OBRA,
    EstatusBOM.EN_REVISION_CONST,
    EstatusBOM.APROBADO_CONST,
    EstatusBOM.EN_REVISION_FINAL,
}

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
    'grupos_bom': 'Grupo',
    'grupos_operativos': 'Grupo operativo',
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


class BomService(BomComprasServiceMixin):
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
            jefe_construccion=jefe_const["id_usuario"] if jefe_const else None,
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
        if (item.get("tipo_origen_item") or TIPO_ITEM_BASE) != TIPO_ITEM_BASE:
            return False
        precio = item.get("precio_unitario")
        if precio is None:
            return True
        try:
            return Decimal(str(precio)) <= 0
        except (InvalidOperation, TypeError, ValueError):
            return True

    @staticmethod
    def mensaje_item_sin_costo() -> str:
        return (
            "Item guardado sin presupuesto base. Ingenieria debe capturar el presupuesto "
            "antes de avanzar el BOM."
        )

    @staticmethod
    def mensaje_item_agregado(item: dict) -> str:
        return f"'{item['descripcion']}' se agrego al BOM"

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

    async def refrescar_costos_catalogo(self, conn, id_bom: UUID, user_id: UUID) -> dict:
        """Ingenieria sincroniza precio_unitario de items sin costo desde el catalogo
        interno (precio_referencia o factura XML vinculada mas reciente). Solo en BORRADOR."""
        bom = await self.get_bom(conn, id_bom)
        await self._validar_retomar_bom_ingenieria(conn, bom['id_proyecto'], user_id)
        if EstatusBOM(bom['estatus']) != EstatusBOM.BORRADOR:
            raise ValueError("Solo se pueden refrescar costos mientras el BOM esta en BORRADOR")

        async with conn.transaction():
            # Sin historial: esta accion solo corre en BORRADOR (linea 379), y los
            # cambios de item en BORRADOR ya no se auditan (solo interesa post-liberacion).
            sincronizados = await self.db.sincronizar_costos_catalogo(conn, id_bom)
        return {"sincronizados": len(sincronizados), "bom": bom}

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
        """Bloquea el primer envio si falta el responsable inmediato o el aprobador final.

        Coordinador de Obra y Jefe de Construccion no se validan aqui: se resuelven
        en vivo hasta el envio de Ingenieria a Obra (enviar_revision_obra), que es
        cuando realmente se necesitan.
        """
        problemas = []
        if not bom.get("responsable_ing"):
            problemas.append("falta responsable de Ingenieria")
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
        if (
            area_editor == "construccion"
            and estatus in ESTATUS_BASE_CONSTRUCCION_BLOQUEADA
        ):
            raise ValueError(self._mensaje_propuesta_requerida())

        if area_editor == 'ingenieria':
            await self._validar_retomar_bom_ingenieria(conn, bom['id_proyecto'], user_id)

        es_rol_bom = await self.es_bom_role(conn, bom, user_id)
        if not es_rol_bom:
            # Fallback: permisos originales por area_editor
            await self._validar_edicion_items(conn, id_bom, area_editor)

        if self._decimal_o_error(cantidad, "La cantidad debe ser mayor a cero") <= 0:
            raise ValueError("La cantidad debe ser mayor a cero")
        if (
            precio_unitario is not None
            and self._decimal_o_error(
                precio_unitario, "El precio unitario no puede ser negativo"
            ) < 0
        ):
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

        if estatus != EstatusBOM.BORRADOR:
            await self.db.registrar_historial(
                conn, id_bom, AccionHistorial.AGREGADO,
                bom['version'], user_id,
                id_item=item['id_item'],
                campo_modificado='item',
                valor_nuevo=descripcion
            )

        return item

    @staticmethod
    def _validar_motivo_adenda(motivo: Optional[str]) -> str:
        motivo_limpio = (motivo or "").strip()
        if not motivo_limpio:
            raise ValueError("El motivo de la adenda es obligatorio")
        return motivo_limpio

    @staticmethod
    def _decimal_o_error(valor, mensaje: str) -> Decimal:
        try:
            return Decimal(str(valor))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(mensaje) from None

    @staticmethod
    def _datos_item_adenda(**campos) -> dict:
        """Normaliza datos propuestos de adenda para guardarlos como JSON."""
        data = {}
        for key, value in campos.items():
            if value is None:
                data[key] = None
            elif isinstance(value, UUID):
                data[key] = str(value)
            else:
                data[key] = str(value) if key in {"cantidad", "precio_unitario"} else value
        return data

    @staticmethod
    def _datos_item_desde_adenda(datos: Optional[dict]) -> dict:
        """Convierte JSON de adenda al formato esperado por agregar_item."""
        if isinstance(datos, str):
            data = json.loads(datos or "{}")
        else:
            data = dict(datos or {})
        if data.get("cantidad") is not None:
            data["cantidad"] = BomService._decimal_o_error(
                data["cantidad"], "La cantidad debe ser mayor a cero"
            )
        if data.get("precio_unitario") not in (None, ""):
            data["precio_unitario"] = BomService._decimal_o_error(
                data["precio_unitario"], "El precio unitario no puede ser negativo"
            )
        else:
            data["precio_unitario"] = None
        for key in ("id_material_ref", "id_material_interno"):
            if data.get(key):
                data[key] = UUID(str(data[key]))
        return data

    async def _validar_bom_aprobado_final_para_adenda(
        self, conn, id_bom: UUID
    ) -> dict:
        bom = await self.get_bom(conn, id_bom)
        if EstatusBOM(bom["estatus"]) != EstatusBOM.APROBADO_FINAL:
            raise ValueError("Solo se pueden registrar adendas cuando el BOM esta aprobado final")
        return bom

    async def _validar_item_base_para_adenda(
        self, conn, id_item: UUID
    ) -> tuple[dict, dict]:
        item = await self.db.get_item_by_id(conn, id_item)
        if not item:
            raise ValueError("Item no encontrado")
        if not item.get("activo", True):
            raise ValueError("No se puede registrar una adenda sobre un item eliminado")
        if (item.get("tipo_origen_item") or TIPO_ITEM_BASE) != TIPO_ITEM_BASE:
            raise ValueError("Solo los items base pueden cerrarse o reemplazarse")
        if item.get("estatus_ejecucion") in ESTATUS_ITEM_CERRADO_COMPRA:
            raise ValueError("El item ya esta cerrado para compra")
        if item.get("estatus_compra") in ESTATUS_COMPRA_BLOQUEA_ADENDA:
            raise ValueError(
                "No se puede registrar una adenda sobre un item cotizado, autorizado, pagado o facturado"
            )
        bloqueo = await self.db.get_item_compra_bloqueante(conn, id_item)
        if bloqueo.get("tiene_cotizacion_seleccionada") or bloqueo.get("tiene_autorizacion_activa"):
            raise ValueError(
                "No se puede registrar una adenda mientras el item tenga cotizacion seleccionada o autorizacion activa"
            )
        bom = await self._validar_bom_aprobado_final_para_adenda(conn, item["id_bom"])
        return item, bom

    async def cerrar_item_sin_compra(
        self, conn, id_item: UUID, user_id: UUID, motivo: str
    ) -> dict:
        """Crea una adenda pendiente para cerrar un item base sin compra."""
        motivo = self._validar_motivo_adenda(motivo)
        item, bom = await self._validar_item_base_para_adenda(conn, id_item)

        async with conn.transaction():
            adenda = await self.db.crear_adenda(
                conn, item["id_bom"], "NO_ADQUIRIDO", motivo, user_id
            )
            await self.db.registrar_adenda_item(
                conn, adenda["id_adenda"], "NO_ADQUIRIDO", motivo,
                id_item_origen=id_item,
            )
            await self.db.registrar_historial(
                conn, item["id_bom"], AccionHistorial.EDITADO,
                bom["version"], user_id,
                id_item=id_item,
                campo_modificado="adenda",
                valor_nuevo="PENDIENTE_CONSTRUCCION",
            )

        return {**adenda, "id_bom": item["id_bom"]}

    async def crear_reemplazo_item(
        self, conn, id_item_origen: UUID, user_id: UUID,
        descripcion: str, cantidad, grupo_ids: List[int], motivo: str,
        id_categoria: Optional[int] = None,
        unidad_medida: Optional[str] = None,
        comentarios: Optional[str] = None,
        precio_unitario=None,
        origen_precio: Optional[str] = "MANUAL",
        id_material_ref: Optional[UUID] = None,
        id_material_interno: Optional[UUID] = None,
        tipo_partida: Optional[str] = "MATERIAL",
        moneda: Optional[str] = "MXN",
    ) -> dict:
        """Crea una adenda pendiente para sustituir un item base."""
        motivo = self._validar_motivo_adenda(motivo)
        descripcion = (descripcion or "").strip()
        if not descripcion:
            raise ValueError("La descripcion del reemplazo es obligatoria")
        if self._decimal_o_error(cantidad, "La cantidad debe ser mayor a cero") <= 0:
            raise ValueError("La cantidad debe ser mayor a cero")
        if (
            precio_unitario is not None
            and self._decimal_o_error(
                precio_unitario, "El precio unitario no puede ser negativo"
            ) < 0
        ):
            raise ValueError("El precio unitario no puede ser negativo")
        if not grupo_ids:
            raise ValueError("Selecciona al menos un grupo BOM")

        item_origen, bom = await self._validar_item_base_para_adenda(conn, id_item_origen)

        async with conn.transaction():
            adenda = await self.db.crear_adenda(
                conn, item_origen["id_bom"], "REEMPLAZO", motivo, user_id
            )
            await self.db.registrar_adenda_item(
                conn, adenda["id_adenda"], "REEMPLAZO", motivo,
                id_item_origen=id_item_origen,
                datos_item=self._datos_item_adenda(
                    descripcion=descripcion,
                    cantidad=cantidad,
                    id_categoria=id_categoria,
                    unidad_medida=unidad_medida,
                    comentarios=comentarios,
                    precio_unitario=precio_unitario,
                    origen_precio=origen_precio,
                    id_material_ref=id_material_ref,
                    id_material_interno=id_material_interno,
                    tipo_partida=tipo_partida,
                    moneda=moneda,
                ),
                grupo_ids=grupo_ids,
            )
            await self.db.registrar_historial(
                conn, item_origen["id_bom"], AccionHistorial.AGREGADO,
                bom["version"], user_id,
                id_item=id_item_origen,
                campo_modificado="adenda_reemplazo",
                valor_nuevo=descripcion,
            )

        return {**adenda, "id_bom": item_origen["id_bom"]}

    async def agregar_fuera_scope(
        self, conn, id_bom: UUID, user_id: UUID,
        descripcion: str, cantidad, grupo_ids: List[int], motivo: str,
        id_categoria: Optional[int] = None,
        unidad_medida: Optional[str] = None,
        comentarios: Optional[str] = None,
        precio_unitario=None,
        origen_precio: Optional[str] = "MANUAL",
        id_material_ref: Optional[UUID] = None,
        id_material_interno: Optional[UUID] = None,
        tipo_partida: Optional[str] = "MATERIAL",
        moneda: Optional[str] = "MXN",
    ) -> dict:
        """Crea una adenda pendiente para una linea fuera del alcance aprobado."""
        motivo = self._validar_motivo_adenda(motivo)
        descripcion = (descripcion or "").strip()
        if not descripcion:
            raise ValueError("La descripcion del item fuera de alcance es obligatoria")
        if self._decimal_o_error(cantidad, "La cantidad debe ser mayor a cero") <= 0:
            raise ValueError("La cantidad debe ser mayor a cero")
        if (
            precio_unitario is not None
            and self._decimal_o_error(
                precio_unitario, "El precio unitario no puede ser negativo"
            ) < 0
        ):
            raise ValueError("El precio unitario no puede ser negativo")
        if not grupo_ids:
            raise ValueError("Selecciona al menos un grupo BOM")

        bom = await self._validar_bom_aprobado_final_para_adenda(conn, id_bom)

        async with conn.transaction():
            adenda = await self.db.crear_adenda(
                conn, id_bom, "FUERA_SCOPE", motivo, user_id
            )
            await self.db.registrar_adenda_item(
                conn, adenda["id_adenda"], "FUERA_SCOPE", motivo,
                datos_item=self._datos_item_adenda(
                    descripcion=descripcion,
                    cantidad=cantidad,
                    id_categoria=id_categoria,
                    unidad_medida=unidad_medida,
                    comentarios=comentarios,
                    precio_unitario=precio_unitario,
                    origen_precio=origen_precio,
                    id_material_ref=id_material_ref,
                    id_material_interno=id_material_interno,
                    tipo_partida=tipo_partida,
                    moneda=moneda,
                ),
                grupo_ids=grupo_ids,
            )
            await self.db.registrar_historial(
                conn, id_bom, AccionHistorial.AGREGADO,
                bom["version"], user_id,
                campo_modificado="adenda_fuera_scope",
                valor_nuevo=descripcion,
            )

        return {**adenda, "id_bom": id_bom}

    async def get_adendas(self, conn, id_bom: UUID) -> list:
        """Lista adendas registradas para el BOM."""
        return await self.db.get_adendas_by_bom(conn, id_bom)

    async def get_item_grupos(self, conn, id_item: UUID) -> tuple[list, list]:
        grupos = await self.db.get_grupos_por_item(conn, id_item)
        grupos_operativos = await self.db.get_grupos_operativos_por_item(conn, id_item)
        return grupos, grupos_operativos

    async def get_item_grupos_base(self, conn, id_item: UUID) -> list:
        return await self.db.get_grupos_por_item(conn, id_item)

    async def get_adenda(self, conn, id_adenda: UUID) -> Optional[dict]:
        return await self.db.get_adenda_by_id(conn, id_adenda)

    async def get_adenda_comentarios(self, conn, id_adenda: UUID) -> list:
        """Lista comentarios de una adenda."""
        return await self.db.get_adenda_comentarios(conn, id_adenda)

    async def get_adenda_comentarios_by_bom(self, conn, id_bom: UUID) -> dict:
        """Lista comentarios de adendas agrupados por adenda."""
        return await self.db.get_adenda_comentarios_by_bom(conn, id_bom)

    async def get_jefe_ingenieria_label(self, conn) -> str:
        jefe = await self.db.get_usuario_activo_por_rol_org(conn, "jefe_ingenieria")
        return jefe["nombre"] if jefe else "el jefe de Ingeniería"

    @staticmethod
    def requiere_propuesta_construccion(bom: dict, area_editor: str) -> bool:
        return (
            area_editor == "construccion"
            and bom
            and bom.get("estatus") in ESTATUS_PROPUESTA_CAMBIO
        )

    @staticmethod
    def base_construccion_bloqueada(bom: dict, area_editor: str) -> bool:
        return (
            area_editor == "construccion"
            and bom
            and bom.get("estatus") in ESTATUS_BASE_CONSTRUCCION_BLOQUEADA
        )

    @staticmethod
    def _lineas_propuesta_json_safe(lineas: list) -> list:
        return json.loads(json.dumps(lineas, default=str))

    async def registrar_propuesta_auto(
        self, conn, id_bom: UUID, user_id: UUID, context: dict, motivo: str, lineas: list
    ) -> dict:
        return await self.crear_propuesta_cambio(
            conn, id_bom, user_id, None, motivo,
            self._lineas_propuesta_json_safe(lineas),
            context.get("role"), context.get("rol_organizacional"),
        )

    async def comentar_adenda(
        self, conn, id_adenda: UUID, user_id: UUID, comentario: str
    ) -> dict:
        """Agrega un comentario de workflow a una adenda."""
        comentario_limpio = (comentario or "").strip()
        if not comentario_limpio:
            raise ValueError("El comentario es obligatorio")
        adenda = await self.db.get_adenda_by_id(conn, id_adenda)
        if not adenda:
            raise ValueError("Adenda no encontrada")
        return await self.db.registrar_adenda_comentario(
            conn, id_adenda, comentario_limpio, user_id
        )

    async def _aplicar_adenda(self, conn, adenda: dict, user_id: UUID) -> None:
        """Aplica lineas de adenda aprobadas dentro de la transaccion activa."""
        lineas = await self.db.get_adenda_items(conn, adenda["id_adenda"])
        if not lineas:
            raise ValueError("La adenda no tiene lineas para aplicar")

        for linea in lineas:
            tipo_linea = linea["tipo_linea"]
            motivo = linea.get("motivo") or adenda["motivo"]

            if tipo_linea == "NO_ADQUIRIDO":
                id_item_origen = linea["id_item_origen"]
                await self._validar_item_base_para_adenda(conn, id_item_origen)
                await self.db.upsert_item_ejecucion(
                    conn, id_item_origen, updated_by=user_id,
                    estatus_ejecucion="NO_ADQUIRIDO",
                    comentarios_operativos=motivo,
                )
                await self.db.registrar_historial(
                    conn, adenda["id_bom_base"], AccionHistorial.EDITADO,
                    adenda["bom_version"], user_id,
                    id_item=id_item_origen,
                    campo_modificado="adenda",
                    valor_nuevo="NO_ADQUIRIDO",
                )
                continue

            datos = self._datos_item_desde_adenda(linea.get("datos_item"))
            orden = await self.db.get_next_orden(conn, adenda["id_bom_base"])
            tipo_origen = (
                TIPO_ITEM_REEMPLAZO
                if tipo_linea == "REEMPLAZO"
                else TIPO_ITEM_FUERA_SCOPE
            )
            id_item_origen = linea.get("id_item_origen")
            if tipo_linea == "REEMPLAZO":
                await self._validar_item_base_para_adenda(conn, id_item_origen)

            item = await self.db.agregar_item(
                conn,
                adenda["id_bom_base"],
                datos["descripcion"],
                datos["cantidad"],
                id_categoria=datos.get("id_categoria"),
                unidad_medida=datos.get("unidad_medida"),
                comentarios=datos.get("comentarios"),
                orden=orden,
                precio_unitario=datos.get("precio_unitario"),
                origen_precio=datos.get("origen_precio") or "MANUAL",
                id_material_ref=datos.get("id_material_ref"),
                id_material_interno=datos.get("id_material_interno"),
                tipo_partida=datos.get("tipo_partida") or "MATERIAL",
                moneda=datos.get("moneda") or "MXN",
                tipo_origen_item=tipo_origen,
                id_item_reemplazado=id_item_origen,
                motivo_adenda=motivo,
                creado_en_adenda=adenda["id_adenda"],
            )
            await self.db.set_item_grupos_operativos(
                conn, item["id_item"], list(linea.get("grupo_ids") or []), user_id
            )
            await self.db.vincular_adenda_item_bom(
                conn, linea["id_adenda_item"], item["id_item"]
            )

            if tipo_linea == "REEMPLAZO":
                await self.db.upsert_item_ejecucion(
                    conn, id_item_origen, updated_by=user_id,
                    estatus_ejecucion="REEMPLAZADO",
                    comentarios_operativos=motivo,
                )

            await self.db.registrar_historial(
                conn, adenda["id_bom_base"], AccionHistorial.AGREGADO,
                adenda["bom_version"], user_id,
                id_item=item["id_item"],
                campo_modificado=(
                    "adenda_reemplazo"
                    if tipo_linea == "REEMPLAZO"
                    else "adenda_fuera_scope"
                ),
                valor_nuevo=datos["descripcion"],
            )

    async def aprobar_adenda_construccion(
        self, conn, id_adenda: UUID, user_id: UUID, user_role: str,
        rol_org: Optional[str] = None, requiere_ingenieria: bool = False
    ) -> dict:
        """Aprueba una adenda por Construccion y la aplica si no requiere Ingenieria."""
        adenda = await self.db.get_adenda_by_id(conn, id_adenda)
        if not adenda:
            raise ValueError("Adenda no encontrada")
        if adenda["estatus"] != ESTATUS_ADENDA_PENDIENTE_CONSTRUCCION:
            raise ValueError("La adenda no esta pendiente de Construccion")
        if EstatusBOM(adenda["bom_estatus"]) != EstatusBOM.APROBADO_FINAL:
            raise ValueError("Solo se pueden aprobar adendas en BOM aprobado final")
        await self._validar_aprobador_bom(
            conn, user_id, user_role, rol_org,
            adenda.get("jefe_construccion"), "Jefe de Construccion", "jefe_construccion"
        )

        async with conn.transaction():
            if not requiere_ingenieria:
                await self._aplicar_adenda(conn, adenda, user_id)
            updated = await self.db.marcar_adenda_construccion(
                conn, id_adenda, user_id, requiere_ingenieria
            )
        return updated

    async def aprobar_adenda_ingenieria(
        self, conn, id_adenda: UUID, user_id: UUID, user_role: str,
        rol_org: Optional[str] = None
    ) -> dict:
        """Aprueba tecnicamente una adenda y aplica sus cambios."""
        adenda = await self.db.get_adenda_by_id(conn, id_adenda)
        if not adenda:
            raise ValueError("Adenda no encontrada")
        if adenda["estatus"] != ESTATUS_ADENDA_PENDIENTE_INGENIERIA:
            raise ValueError("La adenda no esta pendiente de Ingenieria")
        if EstatusBOM(adenda["bom_estatus"]) != EstatusBOM.APROBADO_FINAL:
            raise ValueError("Solo se pueden aprobar adendas en BOM aprobado final")
        await self._validar_aprobador_bom(
            conn, user_id, user_role, rol_org,
            adenda.get("responsable_ing"), "Responsable de Ingenieria", "jefe_ingenieria"
        )

        async with conn.transaction():
            await self._aplicar_adenda(conn, adenda, user_id)
            updated = await self.db.aprobar_adenda_ingenieria(conn, id_adenda, user_id)
        return updated

    async def rechazar_adenda(
        self, conn, id_adenda: UUID, user_id: UUID, user_role: str,
        rol_org: Optional[str], motivo_rechazo: str
    ) -> dict:
        """Rechaza una adenda pendiente sin mutar items."""
        motivo = (motivo_rechazo or "").strip()
        if not motivo:
            raise ValueError("El motivo de rechazo es obligatorio")
        adenda = await self.db.get_adenda_by_id(conn, id_adenda)
        if not adenda:
            raise ValueError("Adenda no encontrada")
        if adenda["estatus"] in ESTATUS_ADENDA_TERMINALES:
            raise ValueError("La adenda ya esta cerrada")
        if adenda["estatus"] == ESTATUS_ADENDA_PENDIENTE_CONSTRUCCION:
            await self._validar_aprobador_bom(
                conn, user_id, user_role, rol_org,
                adenda.get("jefe_construccion"), "Jefe de Construccion", "jefe_construccion"
            )
        elif adenda["estatus"] == ESTATUS_ADENDA_PENDIENTE_INGENIERIA:
            await self._validar_aprobador_bom(
                conn, user_id, user_role, rol_org,
                adenda.get("responsable_ing"), "Responsable de Ingenieria", "jefe_ingenieria"
            )
        else:
            raise ValueError("La adenda no esta pendiente de aprobacion")
        return await self.db.rechazar_adenda(conn, id_adenda, user_id, motivo)

    async def cancelar_adenda(
        self, conn, id_adenda: UUID, user_id: UUID, user_role: str,
        rol_org: Optional[str] = None
    ) -> dict:
        """Cancela una adenda pendiente de construccion sin mutar items."""
        adenda = await self.db.get_adenda_by_id(conn, id_adenda)
        if not adenda:
            raise ValueError("Adenda no encontrada")
        if adenda["estatus"] != ESTATUS_ADENDA_PENDIENTE_CONSTRUCCION:
            raise ValueError("Solo se pueden cancelar adendas pendientes de Construccion")
        await self._validar_aprobador_bom(
            conn, user_id, user_role, rol_org,
            adenda.get("jefe_construccion"), "Jefe de Construccion", "jefe_construccion"
        )
        return await self.db.cancelar_adenda(conn, id_adenda, user_id)

    @staticmethod
    def _normalizar_lineas_propuesta(lineas) -> list:
        if isinstance(lineas, str):
            lineas = json.loads(lineas or "[]")
        if not isinstance(lineas, list) or not lineas:
            raise ValueError("La propuesta debe incluir al menos una linea de cambio")
        for linea in lineas:
            if not isinstance(linea, dict):
                raise ValueError("Cada linea de propuesta debe ser un objeto")
            accion = (linea.get("accion") or "").upper()
            if accion not in ACCIONES_PROPUESTA_CAMBIO:
                raise ValueError("Accion de propuesta invalida")
            linea["accion"] = accion
            grupo_ids = linea.get("grupo_ids") or []
            if not isinstance(grupo_ids, list):
                raise ValueError("Los grupos de la propuesta deben enviarse como lista")
            linea["grupo_ids"] = [
                int(grupo_id)
                for grupo_id in grupo_ids
                if str(grupo_id).strip()
            ]
        return lineas

    @staticmethod
    def _tipo_propuesta_desde_estatus(estatus: EstatusBOM) -> tuple[str, str, str]:
        if estatus == EstatusBOM.EN_REVISION_OBRA:
            return "OBRA", "coordinador_obra", "Coordinador de Obra"
        if estatus == EstatusBOM.EN_REVISION_CONST:
            return "CONSTRUCCION", "jefe_construccion", "Jefe de Construccion"
        raise ValueError(
            "Solo se pueden registrar propuestas durante revision de Obra o Construccion"
        )

    @staticmethod
    def _mensaje_propuesta_requerida() -> str:
        return (
            "Los cambios de alcance de Construccion deben registrarse como propuesta "
            "para revision de Ingenieria"
        )

    async def crear_propuesta_cambio(
        self, conn, id_bom: UUID, user_id: UUID,
        tipo_solicitante: str, motivo: str, lineas,
        user_role: str = "USER", rol_org: Optional[str] = None
    ) -> dict:
        """Crea una propuesta pre-final sin mutar items base."""
        motivo_limpio = (motivo or "").strip()
        if not motivo_limpio:
            raise ValueError("El motivo de la propuesta es obligatorio")
        lineas_norm = self._normalizar_lineas_propuesta(lineas)

        bom = await self.get_bom(conn, id_bom)
        estatus = EstatusBOM(bom["estatus"])
        tipo, responsable_key, responsable_label = self._tipo_propuesta_desde_estatus(estatus)
        tipo_form = (tipo_solicitante or tipo).upper()
        if tipo_form not in TIPOS_PROPUESTA_CAMBIO:
            raise ValueError("Tipo de solicitante invalido")
        if tipo_form != tipo:
            raise ValueError("El tipo de solicitante no corresponde al estado actual del BOM")

        await self._validar_aprobador_bom(
            conn, user_id, user_role, rol_org,
            bom.get(responsable_key), responsable_label, responsable_key
        )

        return await self.db.crear_propuesta_cambio(
            conn, id_bom, tipo, motivo_limpio, lineas_norm, user_id
        )

    async def get_propuestas_cambio(self, conn, id_bom: UUID) -> list:
        """Lista propuestas pre-final del BOM."""
        return await self.db.get_propuestas_cambio_by_bom(conn, id_bom)

    async def _aplicar_lineas_propuesta(
        self, conn, propuesta: dict, lineas: list, user_id: UUID
    ) -> None:
        for linea in lineas:
            accion = linea["accion"]
            datos = linea.get("datos") or {}
            grupo_ids = list(linea.get("grupo_ids") or [])

            if accion == "AGREGAR":
                descripcion = (datos.get("descripcion") or "").strip()
                if not descripcion:
                    raise ValueError("La linea AGREGAR requiere descripcion")
                cantidad = datos.get("cantidad")
                if cantidad is None:
                    raise ValueError("La linea AGREGAR requiere cantidad")
                cantidad = self._decimal_o_error(
                    cantidad, "La cantidad debe ser mayor a cero"
                )
                if cantidad <= 0:
                    raise ValueError("La cantidad debe ser mayor a cero")
                precio_unitario = datos.get("precio_unitario")
                if precio_unitario not in (None, ""):
                    precio_unitario = self._decimal_o_error(
                        precio_unitario, "El precio unitario no puede ser negativo"
                    )
                    if precio_unitario < 0:
                        raise ValueError("El precio unitario no puede ser negativo")
                else:
                    precio_unitario = None
                id_categoria = datos.get("id_categoria")
                id_categoria = int(id_categoria) if id_categoria not in (None, "") else None
                id_material_ref = datos.get("id_material_ref")
                id_material_ref = UUID(str(id_material_ref)) if id_material_ref else None
                id_material_interno = datos.get("id_material_interno")
                id_material_interno = (
                    UUID(str(id_material_interno)) if id_material_interno else None
                )
                orden = await self.db.get_next_orden(conn, propuesta["id_bom"])
                item = await self.db.agregar_item(
                    conn,
                    propuesta["id_bom"],
                    descripcion,
                    cantidad,
                    id_categoria=id_categoria,
                    unidad_medida=datos.get("unidad_medida"),
                    comentarios=datos.get("comentarios"),
                    orden=orden,
                    precio_unitario=precio_unitario,
                    origen_precio=datos.get("origen_precio") or "MANUAL",
                    id_material_ref=id_material_ref,
                    id_material_interno=id_material_interno,
                    tipo_partida=datos.get("tipo_partida") or "MATERIAL",
                    moneda=datos.get("moneda") or "MXN",
                )
                if grupo_ids:
                    await self.db.set_item_grupos(conn, item["id_item"], grupo_ids)
                await self.db.registrar_historial(
                    conn, propuesta["id_bom"], AccionHistorial.AGREGADO,
                    propuesta["bom_version"], user_id,
                    id_item=item["id_item"],
                    campo_modificado="propuesta_cambio",
                    valor_nuevo=descripcion,
                )
                continue

            id_item = linea.get("id_item")
            if not id_item:
                raise ValueError(f"La linea {accion} requiere id_item")
            id_item = UUID(str(id_item))
            item = await self.db.get_item_by_id(conn, id_item)
            if not item or str(item["id_bom"]) != str(propuesta["id_bom"]):
                raise ValueError("La propuesta contiene un item invalido")

            if accion == "EDITAR":
                campos_base = {
                    key: value for key, value in datos.items()
                    if key in CAMPOS_INGENIERIA or key in CAMPOS_CONSTRUCCION_BASE
                }
                if "cantidad" in campos_base and campos_base["cantidad"] is not None:
                    campos_base["cantidad"] = self._decimal_o_error(
                        campos_base["cantidad"], "La cantidad debe ser mayor a cero"
                    )
                    if campos_base["cantidad"] <= 0:
                        raise ValueError("La cantidad debe ser mayor a cero")
                if (
                    "precio_unitario" in campos_base
                    and campos_base["precio_unitario"] is not None
                ):
                    campos_base["precio_unitario"] = self._decimal_o_error(
                        campos_base["precio_unitario"],
                        "El precio unitario no puede ser negativo",
                    )
                    if campos_base["precio_unitario"] < 0:
                        raise ValueError("El precio unitario no puede ser negativo")
                if "id_categoria" in campos_base:
                    id_categoria = campos_base["id_categoria"]
                    campos_base["id_categoria"] = (
                        int(id_categoria) if id_categoria not in (None, "") else None
                    )
                if campos_base:
                    await self.db.update_item(conn, id_item, **campos_base)
                if grupo_ids:
                    await self.db.set_item_grupos(conn, id_item, grupo_ids)
                await self.db.registrar_historial(
                    conn, propuesta["id_bom"], AccionHistorial.EDITADO,
                    propuesta["bom_version"], user_id,
                    id_item=id_item,
                    campo_modificado="propuesta_cambio",
                    valor_nuevo=json.dumps(datos, ensure_ascii=False, default=str),
                )
            elif accion == "ELIMINAR":
                await self.db.soft_delete_item(conn, id_item)
                await self.db.registrar_historial(
                    conn, propuesta["id_bom"], AccionHistorial.ELIMINADO,
                    propuesta["bom_version"], user_id,
                    id_item=id_item,
                    campo_modificado="propuesta_cambio",
                    valor_anterior=item.get("descripcion"),
                )

    async def aprobar_propuesta_cambio(
        self, conn, id_propuesta: UUID, user_id: UUID, user_role: str,
        rol_org: Optional[str] = None, lineas_revision=None,
        ingenieria_modifico: bool = False,
        comentario_revision: Optional[str] = None,
    ) -> dict:
        """Aprueba una propuesta pre-final y aplica sus lineas en transaccion."""
        propuesta = await self.db.get_propuesta_cambio_by_id(conn, id_propuesta)
        if not propuesta:
            raise ValueError("Propuesta no encontrada")
        if propuesta["estatus"] != "PENDIENTE_INGENIERIA":
            raise ValueError("La propuesta no esta pendiente de Ingenieria")
        await self._validar_aprobador_bom(
            conn, user_id, user_role, rol_org,
            propuesta.get("responsable_ing"), "Responsable de Ingenieria", "jefe_ingenieria"
        )
        lineas = self._normalizar_lineas_propuesta(
            lineas_revision if lineas_revision is not None else propuesta["lineas"]
        )

        if ingenieria_modifico:
            siguiente_estatus = EstatusBOM.EN_REVISION_ING
            campos_limpios = self._limpiar_fechas_flujo(
                "fecha_aprobacion_ing",
                "fecha_envio_obra",
                "fecha_aprobacion_obra",
                "fecha_envio_const",
                "fecha_aprobacion_const",
                "fecha_envio_final",
                "fecha_aprobacion_final",
            )
            campos_limpios["fecha_envio_ing"] = now_mx()
        elif propuesta["tipo_solicitante"] == "OBRA":
            siguiente_estatus = EstatusBOM.EN_REVISION_CONST
            campos_limpios = self._limpiar_fechas_flujo(
                "fecha_aprobacion_obra",
                "fecha_envio_const",
                "fecha_aprobacion_const",
                "fecha_envio_final",
                "fecha_aprobacion_final",
            )
            campos_limpios["fecha_envio_const"] = now_mx()
        else:
            siguiente_estatus = EstatusBOM.EN_REVISION_FINAL
            campos_limpios = self._limpiar_fechas_flujo(
                "fecha_envio_final",
                "fecha_aprobacion_final",
            )
            campos_limpios["fecha_envio_final"] = now_mx()

        async with conn.transaction():
            await self._aplicar_lineas_propuesta(conn, propuesta, lineas, user_id)
            updated = await self.db.actualizar_propuesta_cambio_revision(
                conn, id_propuesta, "APLICADA", user_id, comentario_revision
            )
            await self.db.update_bom_estatus(
                conn, propuesta["id_bom"], siguiente_estatus, **campos_limpios
            )
        return updated

    async def rechazar_propuesta_cambio(
        self, conn, id_propuesta: UUID, user_id: UUID, user_role: str,
        rol_org: Optional[str], comentario_revision: str
    ) -> dict:
        """Rechaza una propuesta pre-final sin aplicar cambios."""
        comentario = (comentario_revision or "").strip()
        if not comentario:
            raise ValueError("El motivo de rechazo es obligatorio")
        propuesta = await self.db.get_propuesta_cambio_by_id(conn, id_propuesta)
        if not propuesta:
            raise ValueError("Propuesta no encontrada")
        if propuesta["estatus"] != "PENDIENTE_INGENIERIA":
            raise ValueError("La propuesta no esta pendiente de Ingenieria")
        await self._validar_aprobador_bom(
            conn, user_id, user_role, rol_org,
            propuesta.get("responsable_ing"), "Responsable de Ingenieria", "jefe_ingenieria"
        )
        return await self.db.actualizar_propuesta_cambio_revision(
            conn, id_propuesta, "RECHAZADA", user_id, comentario
        )

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
                if self._decimal_o_error(
                    campos_base['precio_unitario'],
                    "El precio unitario no puede ser negativo",
                ) < 0:
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
            if (
                bom_estatus in ESTATUS_BASE_CONSTRUCCION_BLOQUEADA
                and any(k in CAMPOS_CONSTRUCCION_BASE for k in campos)
            ):
                raise ValueError(self._mensaje_propuesta_requerida())
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
                cant_recibida = self._decimal_o_error(
                    campos_ejecucion['cantidad_recibida'],
                    "La cantidad recibida no puede ser negativa",
                )
                cant_total = self._decimal_o_error(
                    item['cantidad'],
                    "La cantidad total del item no es valida",
                )
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
                if self._decimal_o_error(
                    campos_ejecucion['precio_real'],
                    "El precio unitario no puede ser negativo",
                ) < 0:
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
        if bom_estatus != EstatusBOM.BORRADOR:
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
            if bom_estatus in ESTATUS_BASE_CONSTRUCCION_BLOQUEADA:
                raise ValueError(self._mensaje_propuesta_requerida())
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
                        if (
                            area_editor == "construccion"
                            and EstatusBOM(item["bom_estatus"])
                            in ESTATUS_BASE_CONSTRUCCION_BLOQUEADA
                        ):
                            raise ValueError(self._mensaje_propuesta_requerida())
                        await self.set_item_grupos(
                            conn, id_item, user_id, grupo_ids, area_editor
                        )
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
        if (
            area_editor == "construccion"
            and estatus in ESTATUS_BASE_CONSTRUCCION_BLOQUEADA
        ):
            raise ValueError(self._mensaje_propuesta_requerida())

        if area_editor == 'ingenieria':
            await self._validar_retomar_bom_ingenieria(conn, bom['id_proyecto'], user_id)

        es_rol_bom = await self.es_bom_role(conn, bom, user_id)
        if not es_rol_bom:
            await self._validar_edicion_items(conn, item['id_bom'], area_editor)

        deleted = await self.db.soft_delete_item(conn, id_item)

        if estatus != EstatusBOM.BORRADOR:
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
        grupos_operativos_map = await self.db.get_grupos_operativos_por_bom(conn, id_bom)

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
                tc_banxico = Decimal(str(tasa['tasa_mxn'])) if tasa else None

                if not tc_banxico:
                    tc_promedio = await self.db.get_tasa_promedio(conn)

        for item in items:
            item['grupos'] = grupos_map.get(str(item['id_item']), [])
            item['grupos_operativos'] = grupos_operativos_map.get(str(item['id_item']), [])
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
                    item['costo_mxn'] = round(Decimal(str(item['precio_unitario'])) * tc, 2)
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
                    item['costo_real_mxn'] = round(Decimal(str(item['precio_real'])) * tc, 2)

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
            tc = Decimal(str(tasa['tasa_mxn'])) if tasa else None
            if tc:
                item['costo_mxn'] = round(Decimal(str(item['precio_unitario'])) * tc, 2)
        if item.get('moneda_real') == 'USD' and item.get('precio_real'):
            from core.tipo_cambio.db_service import TipoCambioDBService
            tc_svc = TipoCambioDBService()
            tasa = await tc_svc.get_tasa_mas_reciente(conn)
            tc = Decimal(str(tasa['tasa_mxn'])) if tasa else None
            if tc:
                item['costo_real_mxn'] = round(Decimal(str(item['precio_real'])) * tc, 2)
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
            facturado = Decimal(str(f["facturado_confirmado_mxn"]))
            facturado_sugerido = Decimal(str(f["facturado_sugerido_mxn"]))
            cat = {
                "categoria_id": f["categoria_id"],
                "categoria_nombre": f["categoria_nombre"],
                "presupuesto": Decimal(str(f["presupuesto_mxn"])),
                "real": Decimal(str(f.get("compra_real_mxn") or 0)),
                "real_base": Decimal(str(f.get("compra_real_base_mxn") or 0)),
                "reemplazos": Decimal(str(f.get("reemplazos_mxn") or 0)),
                "fuera_scope": Decimal(str(f.get("fuera_scope_mxn") or 0)),
                "no_adquirido": Decimal(str(f.get("no_adquirido_mxn") or 0)),
                "facturado": facturado,
                "facturado_sugerido": facturado_sugerido,
                "facturado_total_potencial": facturado + facturado_sugerido,
                "pagado": Decimal(str(f["pagado_mxn"])),
            }
            cat["dif_real"] = cat["presupuesto"] - cat["real"]
            cat["dif_facturado"] = cat["presupuesto"] - cat["facturado"]
            cat["dif_pagado"] = cat["presupuesto"] - cat["pagado"]
            grupo["categorias"].append(cat)

        secciones = []
        tot_presup = tot_fact = tot_pag = Decimal("0")
        tot_sugerido = Decimal("0")
        tot_real = Decimal("0")
        tot_real_base = Decimal("0")
        tot_reemplazos = Decimal("0")
        tot_fuera_scope = Decimal("0")
        tot_no_adquirido = Decimal("0")

        for grupo in sorted(por_grupo.values(), key=lambda g: (g["orden"], g["codigo"])):
            cats = grupo["categorias"]
            s_presup = sum(c["presupuesto"] for c in cats)
            s_real = sum(c["real"] for c in cats)
            s_real_base = sum(c["real_base"] for c in cats)
            s_reemplazos = sum(c["reemplazos"] for c in cats)
            s_fuera_scope = sum(c["fuera_scope"] for c in cats)
            s_no_adquirido = sum(c["no_adquirido"] for c in cats)
            s_fact = sum(c["facturado"] for c in cats)
            s_sug = sum(c["facturado_sugerido"] for c in cats)
            s_pag = sum(c["pagado"] for c in cats)
            secciones.append({
                "codigo": grupo["codigo"],
                "nombre": grupo["nombre"],
                "presupuesto": s_presup,
                "real": s_real,
                "real_base": s_real_base,
                "reemplazos": s_reemplazos,
                "fuera_scope": s_fuera_scope,
                "no_adquirido": s_no_adquirido,
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
            tot_real_base += s_real_base
            tot_reemplazos += s_reemplazos
            tot_fuera_scope += s_fuera_scope
            tot_no_adquirido += s_no_adquirido
            tot_fact += s_fact
            tot_sugerido += s_sug
            tot_pag += s_pag

        totales = {
            "presupuesto": tot_presup,
            "real": tot_real,
            "real_base": tot_real_base,
            "reemplazos": tot_reemplazos,
            "fuera_scope": tot_fuera_scope,
            "no_adquirido": tot_no_adquirido,
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
            if not divisor:
                return None
            return round(valor / Decimal(str(divisor)), 2)

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

        await self.db.update_bom_estatus(
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
            bom['version'], user_id, comentarios=comentarios,
            destino_rechazo=destino_rechazo
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

        # Coordinador de Obra y Jefe de Construccion se resuelven en vivo aqui (no se
        # confia en la foto tomada al crear el BOM) para detectar personal asignado
        # despues de la creacion, y se autocorrige tb_bom si cambiaron.
        coordinador = await self.db.get_asignacion_proyecto(
            conn, bom['id_proyecto'], "coordinador_obra", "CONSTRUCCION"
        )
        jefe_const = await self.db.get_responsable_proyecto_o_global(
            conn, bom['id_proyecto'], "jefe_construccion"
        )
        # Sin fallback a bom.get(...): si la asignacion en vivo no encuentra a nadie,
        # es porque el responsable original ya no esta activo en el proyecto y debe
        # bloquear, no reusar la foto obsoleta tomada al crear el BOM.
        coordinador_obra_id = coordinador["id_usuario"] if coordinador else None
        jefe_construccion_id = jefe_const["id_usuario"] if jefe_const else None

        problemas = []
        if not coordinador_obra_id:
            problemas.append("falta Coordinador de Obra")
        if not jefe_construccion_id:
            problemas.append("falta Jefe de Construccion")
        if problemas:
            raise ValueError(
                "No se puede enviar a Obra: " + "; ".join(problemas)
                + ". Solicita al Jefe de Construccion que lo asigne."
            )

        await self.db.update_bom_estatus(
            conn, id_bom, EstatusBOM.EN_REVISION_OBRA,
            fecha_envio_obra=now_mx(),
            coordinador_obra=coordinador_obra_id,
            jefe_construccion=jefe_construccion_id,
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
        self, conn, id_item: UUID, user_id: UUID, grupo_ids: List[int],
        area_editor: str = "ingenieria"
    ) -> None:
        """Asigna grupos base u operativos a un item segun estado del BOM."""
        if not grupo_ids:
            raise ValueError("Selecciona al menos un grupo BOM")
        item = await self.db.get_item_by_id(conn, id_item)
        if not item:
            raise ValueError("Item no encontrado")
        bom_estatus = EstatusBOM(item["bom_estatus"])
        auditar = bom_estatus != EstatusBOM.BORRADOR
        if bom_estatus == EstatusBOM.APROBADO_FINAL:
            if area_editor != "construccion":
                raise ValueError("Solo Construccion puede cambiar grupos operativos en aprobado final")
            grupos_anteriores = await self.db.get_grupos_operativos_por_item(conn, id_item) if auditar else None
            await self.db.set_item_grupos_operativos(conn, id_item, grupo_ids, user_id)
            campo_modificado = "grupos_operativos"
        else:
            if area_editor not in {"ingenieria", "construccion"}:
                raise ValueError("Sin permisos para asignar grupos BOM")
            if (
                area_editor == "construccion"
                and bom_estatus in ESTATUS_BASE_CONSTRUCCION_BLOQUEADA
            ):
                raise ValueError(self._mensaje_propuesta_requerida())
            grupos_anteriores = await self.db.get_grupos_por_item(conn, id_item) if auditar else None
            await self.db.set_item_grupos(conn, id_item, grupo_ids)
            campo_modificado = "grupos_bom"
        if auditar:
            catalogo_grupos = await self.db.get_grupos_bom(conn)
            codigos_por_id = {g['id']: g['codigo'] for g in catalogo_grupos}
            grupos_nuevos = [codigos_por_id.get(gid, str(gid)) for gid in grupo_ids]
            await self.db.registrar_historial(
                conn, item['id_bom'], AccionHistorial.EDITADO,
                item['bom_version'], user_id,
                id_item=id_item,
                campo_modificado=CAMPO_LABELS.get(campo_modificado, campo_modificado),
                valor_anterior=", ".join(grupos_anteriores) if grupos_anteriores else None,
                valor_nuevo=", ".join(grupos_nuevos)
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
            sse_activa = await ConfigService.get_global_config(
                conn, BOM_COSTOS_SSE_KEY, False, bool
            )
            hay_correo = bool(to_emails or cc_emails or bcc_emails)
            if not hay_correo and not sse_activa:
                raise ValueError(
                    "No hay ningun canal configurado para notificar a Compras. "
                    "Activa el aviso interno o captura al menos un correo en "
                    "Admin > Configuracion BOM > Costos pendientes."
                )

            sse_notificados = 0
            if sse_activa:
                sse_notificados = await self._broadcast_costos_pendientes(conn, bom, items)

            correo_enviado = False
            if hay_correo:
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
                sender = await notif._get_notification_sender(conn, "BOM")
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
                correo_enviado = await notif._send_email(
                    to_emails,
                    cc_emails,
                    subject,
                    html,
                    sender["email"],
                    bcc_emails=bcc_emails,
                )
                if not correo_enviado:
                    logger.warning(
                        "BOM costos pendientes: correo no enviado (revisar destinatarios TO) bom=%s",
                        id_bom,
                    )

            if not correo_enviado and not sse_notificados:
                raise ValueError("No se pudo notificar a Compras por ningun canal.")

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
                "correo_enviado": correo_enviado,
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
        items = await self.get_items(conn, id_bom)

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
            "Precio Unitario", "Importe", "Costo Real", "Estado",
            "Fecha Requerida", "Fecha Llegada Real", "Recepcion", "Proveedor",
            "Tipo Entrega", "Fecha Estimada Entrega", "Comentarios", "Entregado"
        ]

        ESTADO_LABELS = {
            'FACTURADO': 'Facturado', 'PAGADO': 'Pagado',
            'AUTORIZADO': 'Autorizado', 'COTIZADO': 'Cotizado',
        }

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

            precio_real = item.get('precio_real')
            if precio_real is not None:
                importe_real = item.get('importe_real')
                costo_real = float(importe_real) if importe_real is not None else float(precio_real) * cantidad
            else:
                gasto_real = item.get('gasto_real')
                costo_real = float(gasto_real) if gasto_real is not None else None

            cantidad_recibida = float(item.get('cantidad_recibida') or 0)
            pct_recepcion = (cantidad_recibida / cantidad * 100) if cantidad else 0

            row_data = [
                row_num - headers_row,
                item.get('categoria_nombre', ''),
                item.get('descripcion', ''),
                item.get('cantidad', 0),
                item.get('unidad_medida', ''),
                float(precio) if precio else None,
                importe if precio else None,
                costo_real,
                ESTADO_LABELS.get(item.get('estatus_compra'), 'Pendiente'),
                item['fecha_requerida'].strftime("%d/%m/%Y") if item.get('fecha_requerida') else '',
                item['fecha_llegada_real'].strftime("%d/%m/%Y") if item.get('fecha_llegada_real') else '',
                f"{min(pct_recepcion, 100):.0f}%" if pct_recepcion > 0 else '',
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
                elif col_num in (6, 7, 8):
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
        column_widths = [5, 20, 40, 12, 10, 16, 16, 16, 14, 16, 16, 12, 25, 16, 18, 30, 10]
        for i, width in enumerate(column_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = width

        ws.freeze_panes = f"A{headers_row + 1}"

        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()

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

    # ========================================
    # DB PROXIES (router -> service -> db)
    # ========================================

    async def get_proyecto_info(self, conn, id_proyecto: UUID) -> Optional[dict]:
        return await self.db.get_proyecto_info(conn, id_proyecto)

    async def get_all_bom_versions(self, conn, id_proyecto: UUID) -> List[dict]:
        return await self.db.get_all_bom_versions(conn, id_proyecto)

    async def restaurar_item(self, conn, id_item: UUID) -> dict:
        return await self.db.restaurar_item(conn, id_item)

    async def buscar_materiales_para_bom(self, conn, query: str, **kwargs) -> dict:
        return await self.db.buscar_materiales_para_bom(conn, query, **kwargs)

    async def get_materiales_recientes(self, conn, limite: int = 10, offset: int = 0) -> dict:
        return await self.db.get_materiales_recientes(conn, limite=limite, offset=offset)

    async def get_usuarios_por_area(self, conn, module_slug: str, solo_jefes: bool = False) -> List[dict]:
        return await self.db.get_usuarios_por_area(conn, module_slug, solo_jefes=solo_jefes)

    async def get_bom_by_id(self, conn, id_bom: UUID) -> Optional[dict]:
        return await self.db.get_bom_by_id(conn, id_bom)

    async def get_cotizacion_by_id(self, conn, cotizacion_id: UUID) -> Optional[dict]:
        return await self.db.get_cotizacion_by_id(conn, cotizacion_id)

    async def get_items_by_ids(self, conn, item_ids: List[UUID]) -> List[dict]:
        return await self.db.get_items_by_ids(conn, item_ids)

    async def get_items_cotizacion(self, conn, cotizacion_id: UUID) -> List[dict]:
        return await self.db.get_items_cotizacion(conn, cotizacion_id)

    async def actualizar_pdf_cotizacion(self, conn, cotizacion_id: UUID, pdf_url: str) -> Optional[dict]:
        updated = await self.db.actualizar_pdf_cotizacion(conn, cotizacion_id, pdf_url)
        if not updated:
            cotizacion = await self.db.get_cotizacion_by_id(conn, cotizacion_id)
            if not cotizacion:
                raise ValueError("Cotización no encontrada.")
            raise ValueError(f"La cotización está en estatus {cotizacion['estatus']} y no puede modificarse.")
        return updated


def get_bom_service():
    """Dependency injection para FastAPI."""
    return BomService()
