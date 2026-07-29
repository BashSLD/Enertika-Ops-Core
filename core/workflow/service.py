from typing import Any, List, Optional
from uuid import UUID, uuid4
import asyncio
import logging
import time

from core.database import DB_REPORT_ERRORS
from core.integrations.sharepoint import SharePointService
from core.microsoft import MicrosoftAuth
from core.permissions import ROLE_HIERARCHY, user_has_module_access
from core.timezone import now_mx

from .constants import MODULE_TO_DEPT
from .db_service import WorkflowDBService, get_workflow_db_service
from .notification_service import get_notification_service

logger = logging.getLogger("WorkflowCore")


class WorkflowService:
    """
    Servicio centralizado para gestion de flujo de trabajo y comunicaciones.
    Usado por: Simulacion, Comercial, Ingenieria, etc.
    """

    def __init__(self, db: WorkflowDBService | None = None):
        self.db = db or get_workflow_db_service()
        self.ms_auth = MicrosoftAuth()
        self.notification_service = get_notification_service()

    def get_department_slug(self, module: str) -> str:
        department = MODULE_TO_DEPT.get(module)
        if not department:
            raise ValueError(f"Modulo '{module}' no valido")
        return department

    async def build_comentarios_modal_context(
        self,
        conn,
        id_oportunidad: UUID,
        module: str,
        user_context: dict,
    ) -> dict:
        department_slug = self.get_department_slug(module)
        op = await self.get_oportunidad_basic_info(conn, id_oportunidad)
        if not op:
            raise LookupError("Oportunidad no encontrada")

        comentarios = await self.get_historial(conn, id_oportunidad)
        can_comment = user_has_module_access(module, user_context, min_role="editor")

        logger.info(
            "[COMENTARIOS MODAL] Mostrando %s comentarios. Usuario puede comentar: %s",
            len(comentarios),
            can_comment,
        )

        return {
            "id_oportunidad": id_oportunidad,
            "module_slug": module,
            "department_slug": department_slug,
            "can_comment": can_comment,
            "op_info": op,
            "comentarios": comentarios,
            "context": user_context,
        }

    async def create_comentario_and_get_historial(
        self,
        conn,
        user_context: dict,
        id_oportunidad: UUID,
        comentario: str,
        module: str,
        file_uploads: Optional[List[Any]] = None,
        sharepoint_token: Optional[str] = None,
    ) -> List[dict]:
        department_slug = self.get_department_slug(module)
        if not user_has_module_access(module, user_context, min_role="editor"):
            logger.warning(
                "[CREATE COMENTARIO] Usuario %s sin permisos de editor en %s",
                user_context.get("user_name"),
                module,
            )
            raise PermissionError(f"No tienes permisos para comentar en el modulo {module}")

        uploads = file_uploads or []
        clean_comment = comentario.strip()
        if clean_comment or uploads:
            await self.add_comentario(
                conn,
                user_context,
                id_oportunidad,
                clean_comment,
                departamento_slug=department_slug,
                modulo_origen=module,
                file_uploads=uploads,
                sharepoint_token=sharepoint_token,
            )
            logger.info("[CREATE COMENTARIO] Comentario creado exitosamente")
        else:
            logger.warning("[CREATE COMENTARIO] Comentario vacio recibido, ignorado")

        return await self.get_historial(conn, id_oportunidad)

    async def add_comentario(
        self,
        conn,
        user_context: dict,
        id_oportunidad: UUID,
        comentario: str,
        departamento_slug: str,
        modulo_origen: str,
        file_uploads: Optional[List[Any]] = None,
        sharepoint_token: Optional[str] = None,
    ) -> dict:
        user_id = user_context.get("user_db_id")
        user_name = user_context.get("user_name", "Usuario Sistema")
        user_email = user_context.get("user_email") or user_context.get("email")

        if not user_email:
            logger.error("[COMENTARIO] Usuario sin email en contexto: %s", user_context)
            raise RuntimeError(
                "Error de sesion: no se pudo obtener el email del usuario. "
                "Por favor, cierre sesion y vuelva a iniciar."
            )

        logger.info("[COMENTARIO] Iniciando add_comentario para %s por %s", id_oportunidad, user_name)

        new_id = uuid4()
        now = now_mx()

        await self.db.insert_comentario(
            conn,
            {
                "id": new_id,
                "id_oportunidad": id_oportunidad,
                "usuario_id": user_id,
                "usuario_nombre": user_name,
                "usuario_email": user_email,
                "comentario": comentario,
                "departamento_origen": departamento_slug,
                "modulo_origen": modulo_origen,
                "fecha_comentario": now,
            },
        )
        logger.info("[COMENTARIO] INSERT exitoso para %s", new_id)

        attachments_data = []
        uploads = file_uploads or []
        if uploads and sharepoint_token:
            attachments_data = await self._procesar_adjuntos_comentario(
                conn,
                uploads,
                id_oportunidad,
                new_id,
                user_id,
            )

        asyncio.create_task(
            self._notificar_comentario(
                id_oportunidad,
                comentario,
                user_context,
                departamento_slug,
            )
        )

        return {
            "id": new_id,
            "usuario_nombre": user_name,
            "comentario": comentario,
            "fecha": now,
            "departamento": departamento_slug,
            "adjuntos": attachments_data,
        }

    async def _procesar_adjuntos_comentario(
        self,
        conn,
        file_uploads: List[Any],
        id_oportunidad: UUID,
        id_comentario: UUID,
        user_id: UUID,
    ) -> List[dict]:
        logger.info("[COMENTARIO] Procesando %s adjuntos.", len(file_uploads))
        attachments_data = []

        try:
            config_map = await self.db.get_attachment_config(conn)
            max_size_mb = int(config_map.get("MAX_UPLOAD_SIZE_MB", "10"))
            base_folder = config_map.get("SHAREPOINT_BASE_FOLDER", "").strip().strip("/")
            op_estandar = await self.db.get_oportunidad_estandar(conn, id_oportunidad)

            if not op_estandar:
                logger.warning(
                    "[COMENTARIO] No se pudo subir adjunto: op_id_estandar es NULL para %s",
                    id_oportunidad,
                )
                return attachments_data

            relative_path = f"comentario/{op_estandar}"
            folder_path = f"{base_folder}/{relative_path}" if base_folder else relative_path

            app_token = await self.ms_auth.get_application_token()
            sharepoint = SharePointService(access_token=app_token)

            for file_obj in file_uploads:
                try:
                    file_obj.file.seek(0, 2)
                    file_size = file_obj.file.tell()
                    file_obj.file.seek(0)

                    file_size_mb = file_size / (1024 * 1024)
                    if file_size_mb > max_size_mb:
                        logger.warning(
                            "[COMENTARIO] Archivo %s excede limite: %s bytes",
                            file_obj.filename,
                            file_size,
                        )
                        continue

                    original_name = file_obj.filename
                    file_obj.filename = f"{int(time.time())}_{original_name}"
                    logger.info("[COMENTARIO] Subiendo archivo: %s a %s", file_obj.filename, folder_path)

                    upload_result = await sharepoint.upload_file(conn, file_obj, folder_path)
                    doc_id = uuid4()
                    parent_ref = upload_result.get("parentReference", {})

                    await self.db.insert_document_attachment(
                        conn,
                        {
                            "id_documento": doc_id,
                            "nombre_archivo": upload_result["name"],
                            "url_sharepoint": upload_result["webUrl"],
                            "drive_item_id": upload_result["id"],
                            "parent_drive_id": parent_ref.get("driveId"),
                            "tipo_contenido": file_obj.content_type,
                            "tamano_bytes": upload_result["size"],
                            "id_comentario": id_comentario,
                            "id_oportunidad": id_oportunidad,
                            "subido_por_id": user_id,
                        },
                    )

                    attachments_data.append({
                        "nombre": upload_result["name"],
                        "url": upload_result["webUrl"],
                    })
                    logger.info("[COMENTARIO] Adjunto registrado: %s", upload_result["name"])
                except (OSError, KeyError, RuntimeError, ValueError) as exc:
                    logger.error(
                        "[COMENTARIO] Error subiendo archivo individual %s: %s",
                        getattr(file_obj, "filename", "(sin nombre)"),
                        exc,
                    )
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("[COMENTARIO] Fallo general en proceso de adjuntos: %s", exc)

        return attachments_data

    async def get_historial(
        self,
        conn,
        id_oportunidad: UUID,
        limit: Optional[int] = None,
    ) -> List[dict]:
        rows = await self.db.get_historial_rows(conn, id_oportunidad, limit)

        grouped = {}
        order = []
        for row in rows:
            comment_id = row["id"]
            if comment_id not in grouped:
                grouped[comment_id] = {
                    "id": comment_id,
                    "usuario_nombre": row["usuario_nombre"],
                    "usuario_email": row["usuario_email"],
                    "comentario": row["comentario"],
                    "departamento_origen": row["departamento_origen"],
                    "modulo_origen": row["modulo_origen"],
                    "fecha_comentario": row["fecha_comentario"],
                    "comentario_op_estandar": row["comentario_op_estandar"],
                    "adjuntos": [],
                }
                order.append(comment_id)

            if row["adjunto_url"]:
                grouped[comment_id]["adjuntos"].append({
                    "nombre": row["adjunto_nombre"],
                    "url": row["adjunto_url"],
                })

        return [grouped[comment_id] for comment_id in order]

    async def get_detalle_oportunidad(self, conn, id_oportunidad: UUID) -> Optional[dict]:
        return await self.db.get_detalle_oportunidad(conn, id_oportunidad)

    async def get_oportunidad_basic_info(self, conn, id_oportunidad: UUID) -> Optional[dict]:
        return await self.db.get_oportunidad_basic_info(conn, id_oportunidad)

    async def build_detalle_oportunidad_context(
        self,
        conn,
        id_oportunidad: UUID,
        source_module: str,
        user_context: dict,
        read_only: bool = False,
    ) -> dict:
        op = await self.get_detalle_oportunidad(conn, id_oportunidad)
        if not op:
            raise LookupError("Oportunidad no encontrada")

        if read_only:
            can_edit_comercial = False
            can_close_sale = False
            can_reassign = False
        else:
            can_edit_comercial = user_has_module_access("comercial", user_context, min_role="editor")
            can_close_sale = self._can_close_sale(user_context)

            user_id = user_context.get("user_db_id")
            responsable_id = op.get("responsable_comercial_id") or op.get("creado_por_id")
            is_owner = str(responsable_id or "") == str(user_id or "")
            _status = (op.get("status_global") or "").lower()
            can_reassign = (is_owner or can_close_sale) and _status not in ("ganada", "cancelado", "perdido")

        es_ultimo_del_grupo = True
        if can_close_sale and (op.get("status_global") or "").lower() == "entregado":
            es_ultimo_del_grupo = await self.db.es_ultimo_del_grupo(conn, id_oportunidad)

        sitios = []
        if can_close_sale and op.get("cantidad_sitios", 1) > 1:
            sitios = await self.db.get_sitios_oportunidad(conn, id_oportunidad)

        sitios_ganados_detalle = []
        if (op.get("status_global") or "").lower() == "ganada":
            sitios_ganados_detalle = await self.db.get_sitios_ganados_detalle(conn, id_oportunidad)

        sitios_ganados_total = len(sitios_ganados_detalle)
        sitios_con_proyecto_total = sum(
            1 for sitio in sitios_ganados_detalle if sitio["tiene_proyecto"]
        )
        historial_responsables = await self.db.get_historial_responsables(conn, id_oportunidad)

        return {
            "op": op,
            "can_edit_comercial": can_edit_comercial,
            "can_close_sale": can_close_sale,
            "es_ultimo_del_grupo": es_ultimo_del_grupo,
            "can_reassign": can_reassign,
            "sitios": sitios,
            "show_solicitar_actions": source_module == "comercial",
            "tiene_proyecto": sitios_con_proyecto_total > 0,
            "proyectos_completos": (
                sitios_ganados_total > 0
                and sitios_con_proyecto_total >= sitios_ganados_total
            ),
            "sitios_ganados_total": sitios_ganados_total,
            "sitios_con_proyecto_total": sitios_con_proyecto_total,
            "sitios_ganados_detalle": sitios_ganados_detalle,
            "notificacion_ganada_at": op.get("notificacion_ganada_at"),
            "historial_responsables": historial_responsables,
        }

    @staticmethod
    def _can_close_sale(user_context: dict) -> bool:
        context_role = user_context.get("role")
        comercial_role = user_context.get("module_roles", {}).get("comercial", "")

        if context_role == "ADMIN":
            return True
        if comercial_role == "admin":
            return True
        if context_role == "MANAGER":
            user_level = ROLE_HIERARCHY.get(comercial_role, 0)
            editor_level = ROLE_HIERARCHY.get("editor", 0)
            return user_level >= editor_level
        return False

    async def _notificar_comentario(
        self,
        id_oportunidad: UUID,
        comentario: str,
        sender_ctx: dict,
        depto: str,
    ):
        try:
            from core.database import get_db_pool
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                await self.notification_service.notify_new_comment(
                    conn=conn,
                    id_oportunidad=id_oportunidad,
                    comentario=comentario,
                    sender_ctx=sender_ctx,
                    departamento=depto.upper(),
                )
        except DB_REPORT_ERRORS as exc:
            logger.error(
                "[NOTIFY] Error de BD notificando comentario %s: %s",
                id_oportunidad,
                exc,
                exc_info=True,
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            logger.error(
                "[NOTIFY] Fallo en notificacion de comentario %s: %s",
                id_oportunidad,
                exc,
                exc_info=True,
            )


def get_workflow_service():
    """Helper para inyeccion de dependencias."""
    return WorkflowService()
