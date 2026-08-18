"""Reglas compartidas para proveedores y expediente documental."""

import asyncio
import mimetypes
import posixpath
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from typing import Optional
from urllib.parse import unquote, urlparse
from uuid import UUID

from core.integrations.sharepoint import SharePointService
from core.microsoft import get_ms_auth

from .constants import (
    DOCUMENTO_CATEGORIAS,
    ESTATUS_DOC_PROXIMO,
    ESTATUS_DOC_SIN_DOCS,
    ESTATUS_DOC_VENCIDO,
    ESTATUS_DOC_VIGENTE,
    SHAREPOINT_CARPETAS_POR_CATEGORIA,
    SHAREPOINT_PROVEEDORES_ROOT,
    ZIP_CATEGORIA_DEFAULT,
)
from .db_service import ProveedoresDBService, get_proveedores_db_service


INVALID_FILENAME_CHARS = re.compile(r'[\x00-\x1f<>:"/\\|?*]+')


class DocumentoProveedorNoEncontrado(ValueError):
    """El documento solicitado no existe o no pertenece al proveedor."""


class DocumentoProveedorSinArchivo(ValueError):
    pass


class SharePointProveedorError(RuntimeError):
    pass


@dataclass(frozen=True)
class DocumentoArchivo:
    nombre_archivo: str
    media_type: str
    contenido: bytes | None = None
    redirect_url: str | None = None


class ProveedoresService:
    """Servicio compartido para Compras, Finanzas y futuros modulos."""

    def __init__(
        self,
        db: ProveedoresDBService,
        ms_auth=None,
        sharepoint_factory=None,
    ):
        self.db = db
        self.ms_auth = ms_auth
        self.sharepoint_factory = sharepoint_factory or SharePointService

    async def get_documentos_proveedor(self, conn, id_proveedor: UUID) -> list[dict]:
        return await self.db.get_documentos_proveedor(conn, id_proveedor)

    async def get_documentos_vigentes_proveedor(
        self,
        conn,
        id_proveedor: UUID,
    ) -> list[dict]:
        return await self.db.get_documentos_vigentes_proveedor(conn, id_proveedor)

    async def get_documento_metadata(
        self,
        conn,
        id_proveedor: UUID,
        doc_id: UUID,
    ) -> dict:
        documento = await self.db.get_documento_archivo(conn, id_proveedor, doc_id)
        if not documento:
            raise DocumentoProveedorNoEncontrado("Documento no encontrado")
        return documento

    async def get_documento_archivo(
        self,
        conn,
        id_proveedor: UUID,
        doc_id: UUID,
    ) -> DocumentoArchivo:
        documento = await self.get_documento_metadata(conn, id_proveedor, doc_id)
        return await self._descargar_documento(conn, documento)

    async def generar_zip_expediente(
        self,
        conn,
        id_proveedor: UUID,
    ) -> DocumentoArchivo:
        documentos = await self.get_documentos_vigentes_proveedor(conn, id_proveedor)
        if not documentos:
            proveedor = await self.db.get_proveedor_detalle(conn, id_proveedor)
            if not proveedor:
                raise DocumentoProveedorNoEncontrado("Proveedor no encontrado")
            raise DocumentoProveedorSinArchivo("No hay documentos vigentes")

        descargables = [doc for doc in documentos if doc.get("drive_item_id")]
        if not descargables:
            raise DocumentoProveedorSinArchivo("No hay documentos vigentes descargables")

        sharepoint = await self.get_sharepoint_service(conn)
        usados: set[str] = set()
        carpeta_proveedor = self.build_proveedor_folder(documentos[0])

        items = []
        for doc in descargables:
            categoria = DOCUMENTO_CATEGORIAS.get(
                doc.get("tipo_documento"),
                ZIP_CATEGORIA_DEFAULT,
            )
            nombre_archivo = self._resolve_filename(doc)
            zip_path = self.dedupe_zip_path(
                usados,
                "/".join(
                    [
                        self.sanitize_component(carpeta_proveedor, "Proveedor"),
                        self.sanitize_component(categoria, ZIP_CATEGORIA_DEFAULT),
                        self.sanitize_component(nombre_archivo, "documento"),
                    ]
                ),
            )
            items.append((doc["drive_item_id"], zip_path))

        zip_bytes = await self.descargar_y_zip(sharepoint, items)

        zip_name = f"{carpeta_proveedor}_expediente.zip"
        return DocumentoArchivo(
            nombre_archivo=self.sanitize_component(zip_name, "expediente.zip"),
            media_type="application/zip",
            contenido=zip_bytes,
        )

    async def descargar_y_zip(
        self,
        sharepoint: SharePointService,
        items: list[tuple[str, str]],
        *,
        max_concurrencia: int = 5,
    ) -> bytes:
        """Descarga N archivos de SharePoint en paralelo (acotado) y los empaqueta
        en un ZIP en memoria. Mecanismo generico compartido por cualquier feature
        de exportacion a ZIP (expediente de proveedor, comprobantes de Compras, etc.)
        — cada caller resuelve su propio agrupamiento/nombres de carpeta antes de
        llamar aqui.

        items: lista de (drive_item_id, zip_path) — zip_path ya debe venir
        sanitizado y dedupeado por el caller.
        """
        if not items:
            raise DocumentoProveedorSinArchivo("No hay archivos para incluir en el ZIP")

        sem = asyncio.Semaphore(max_concurrencia)

        async def _descargar(drive_item_id: str) -> bytes:
            async with sem:
                return await sharepoint.download_bytes_direct_by_item_id(drive_item_id)

        # httpx.HTTPError se deja propagar tal cual (no se envuelve en
        # SharePointProveedorError): cada router distingue 404 vs 502 via
        # _handle_sharepoint_error, y envolverlo aqui aplanaria esa distincion
        # a un generico 503 para todo caller de este helper.
        contenidos = await asyncio.gather(*[_descargar(item_id) for item_id, _path in items])

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for (_item_id, zip_path), contenido in zip(items, contenidos):
                zf.writestr(zip_path, contenido)
        return zip_buffer.getvalue()

    async def registrar_documento_proveedor(
        self,
        conn,
        id_proveedor: UUID,
        tipo_documento: str,
        tipo_persona: str,
        sharepoint_url: str,
        fecha_vencimiento=None,
        fecha_documento=None,
        subido_por: Optional[UUID] = None,
        notas: Optional[str] = None,
        id_documento_attachment: Optional[UUID] = None,
        nombre_archivo: Optional[str] = None,
        tipo_contenido: Optional[str] = None,
        tamano_bytes: Optional[int] = None,
        drive_item_id: Optional[str] = None,
        parent_drive_id: Optional[str] = None,
        folder_path: Optional[str] = None,
        periodo: Optional[str] = None,
        nombre_documento_personalizado: Optional[str] = None,
    ) -> dict:
        return await self.db.insert_documento_proveedor(
            conn,
            id_proveedor,
            tipo_documento,
            tipo_persona,
            sharepoint_url,
            fecha_vencimiento=fecha_vencimiento,
            fecha_documento=fecha_documento,
            subido_por=subido_por,
            notas=notas,
            id_documento_attachment=id_documento_attachment,
            nombre_archivo=nombre_archivo,
            tipo_contenido=tipo_contenido,
            tamano_bytes=tamano_bytes,
            drive_item_id=drive_item_id,
            parent_drive_id=parent_drive_id,
            folder_path=folder_path,
            periodo=periodo,
            nombre_documento_personalizado=nombre_documento_personalizado,
        )

    async def eliminar_documento_proveedor(self, conn, doc_id: UUID) -> bool:
        return await self.db.delete_documento_proveedor(conn, doc_id)

    async def get_proveedores_con_estatus_docs(self, conn) -> list[dict]:
        proveedores = await self.db.get_proveedores_con_estatus_docs(conn)
        for proveedor in proveedores:
            proveedor["estatus_docs"] = self._calcular_estatus_docs(proveedor)
        return proveedores

    async def get_proveedores_lista(
        self,
        conn,
        busqueda: str = "",
        solo_activos: bool = False,
        page: int = 1,
        per_page: int = 50,
    ) -> list[dict]:
        return await self.db.get_proveedores_lista(
            conn,
            busqueda=busqueda,
            solo_activos=solo_activos,
            page=page,
            per_page=per_page,
        )

    async def count_proveedores(
        self,
        conn,
        busqueda: str = "",
        solo_activos: bool = False,
    ) -> int:
        return await self.db.count_proveedores(
            conn,
            busqueda=busqueda,
            solo_activos=solo_activos,
        )

    async def get_proveedor_detalle(self, conn, id_proveedor: UUID) -> Optional[dict]:
        return await self.db.get_proveedor_detalle(conn, id_proveedor)

    def build_sharepoint_subcarpeta(
        self,
        proveedor: dict,
        tipo_documento: str,
    ) -> str:
        categoria = DOCUMENTO_CATEGORIAS.get(tipo_documento, ZIP_CATEGORIA_DEFAULT)
        carpeta_categoria = SHAREPOINT_CARPETAS_POR_CATEGORIA.get(
            categoria,
            SHAREPOINT_CARPETAS_POR_CATEGORIA[ZIP_CATEGORIA_DEFAULT],
        )
        return "/".join(
            [
                SHAREPOINT_PROVEEDORES_ROOT,
                self.sanitize_component(
                    self.build_proveedor_folder(proveedor),
                    "Proveedor",
                ),
                carpeta_categoria,
            ]
        )

    async def check_rfc_duplicado(
        self,
        conn,
        rfc: str,
        excluir_id: Optional[UUID] = None,
    ) -> bool:
        return await self.db.check_rfc_duplicado(conn, rfc, excluir_id=excluir_id)

    async def crear_proveedor(
        self,
        conn,
        rfc: str,
        razon_social: str,
        nombre_comercial: Optional[str],
    ) -> dict:
        return await self.db.insert_proveedor(conn, rfc, razon_social, nombre_comercial)

    async def actualizar_proveedor(
        self,
        conn,
        id_proveedor: UUID,
        rfc: str,
        razon_social: str,
        nombre_comercial: Optional[str],
    ) -> Optional[dict]:
        return await self.db.update_proveedor(
            conn,
            id_proveedor,
            rfc,
            razon_social,
            nombre_comercial,
        )

    async def toggle_proveedor_activo(self, conn, id_proveedor: UUID) -> Optional[dict]:
        return await self.db.toggle_proveedor_activo(conn, id_proveedor)

    def _calcular_estatus_docs(self, proveedor: dict) -> str:
        if (proveedor.get("total_docs") or 0) == 0:
            return ESTATUS_DOC_SIN_DOCS
        if (proveedor.get("docs_vencidos") or 0) > 0:
            return ESTATUS_DOC_VENCIDO
        if (proveedor.get("docs_proximos") or 0) > 0:
            return ESTATUS_DOC_PROXIMO
        return ESTATUS_DOC_VIGENTE

    async def _descargar_documento(self, conn, documento: dict) -> DocumentoArchivo:
        nombre_archivo = self._resolve_filename(documento)
        media_type = self._resolve_media_type(documento, nombre_archivo)
        drive_item_id = documento.get("drive_item_id")

        if not drive_item_id:
            sharepoint_url = documento.get("sharepoint_url")
            if sharepoint_url:
                return DocumentoArchivo(
                    nombre_archivo=nombre_archivo,
                    media_type=media_type,
                    redirect_url=sharepoint_url,
                )
            raise DocumentoProveedorSinArchivo("Documento sin archivo asociado")

        sharepoint = await self.get_sharepoint_service(conn)
        contenido = await sharepoint.download_bytes_direct_by_item_id(drive_item_id)
        return DocumentoArchivo(
            nombre_archivo=nombre_archivo,
            media_type=media_type,
            contenido=contenido,
        )

    async def get_sharepoint_service(self, conn) -> SharePointService:
        ms_auth = self.ms_auth or get_ms_auth()
        app_token = await ms_auth.get_application_token()
        if not app_token:
            raise SharePointProveedorError("No se pudo obtener token de SharePoint")

        sharepoint = self.sharepoint_factory(access_token=app_token)
        config = await sharepoint._resolve_config(conn)
        sharepoint.site_id = config.get("site_id")
        sharepoint.drive_id = config.get("drive_id")
        if not sharepoint.site_id and not sharepoint.drive_id:
            raise SharePointProveedorError("Configuracion de SharePoint incompleta")
        return sharepoint

    def _resolve_filename(self, documento: dict) -> str:
        nombre = (
            documento.get("nombre_archivo")
            or self._filename_from_url(documento.get("sharepoint_url"))
            or documento.get("nombre_documento_personalizado")
            or documento.get("tipo_documento")
            or "documento"
        )
        nombre = self.sanitize_component(str(nombre), "documento")
        if "." not in posixpath.basename(nombre):
            extension = mimetypes.guess_extension(
                self._resolve_media_type(documento, nombre)
            )
            if extension:
                nombre = f"{nombre}{extension}"
        return nombre

    def _resolve_media_type(self, documento: dict, nombre_archivo: str) -> str:
        media_type = (documento.get("tipo_contenido") or "").split(";")[0].strip().lower()
        if media_type:
            return media_type
        guessed, _ = mimetypes.guess_type(nombre_archivo)
        return guessed or "application/octet-stream"

    def _filename_from_url(self, sharepoint_url: str | None) -> str | None:
        if not sharepoint_url:
            return None
        path = urlparse(sharepoint_url).path
        filename = posixpath.basename(path)
        return unquote(filename) if filename else None

    def build_proveedor_folder(self, documento: dict) -> str:
        rfc = (documento.get("rfc") or "").strip().upper()
        razon_social = (
            documento.get("razon_social")
            or documento.get("nombre_comercial")
            or "Proveedor"
        )
        if rfc:
            return f"{rfc} - {razon_social}"

        id_proveedor = str(documento.get("id_proveedor") or "")[:8]
        suffix = f" - {id_proveedor}" if id_proveedor else ""
        return f"SIN_RFC - {razon_social}{suffix}"

    def sanitize_component(self, value: str, default: str) -> str:
        clean = INVALID_FILENAME_CHARS.sub("_", value or "").strip().strip(".")
        return clean or default

    def dedupe_zip_path(self, usados: set[str], path: str) -> str:
        if path not in usados:
            usados.add(path)
            return path

        folder, filename = posixpath.split(path)
        stem, dot, extension = filename.rpartition(".")
        if not dot:
            stem = filename
            extension = ""

        index = 2
        while True:
            candidate_name = f"{stem}_{index}.{extension}" if extension else f"{stem}_{index}"
            candidate = f"{folder}/{candidate_name}" if folder else candidate_name
            if candidate not in usados:
                usados.add(candidate)
                return candidate
            index += 1


def get_proveedores_service() -> ProveedoresService:
    return ProveedoresService(db=get_proveedores_db_service())
