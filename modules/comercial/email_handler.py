from datetime import datetime
from uuid import UUID
from typing import List, Optional, Dict, Tuple
import logging
from fastapi import Request, UploadFile, HTTPException
from fastapi.templating import Jinja2Templates
from core.security import get_valid_graph_token
from .file_utils import validate_file_size

logger = logging.getLogger("ComercialModule")
templates = Jinja2Templates(directory="templates")

class EmailHandler:
    """Maneja el envío de correos del módulo comercial."""
    
    MAX_FILE_SIZE = 10 * 1024 * 1024
    
    async def procesar_y_enviar_notificacion(
        self,
        request: Request,
        conn,
        service,
        ms_auth,
        id_oportunidad: UUID,
        form_data: Dict,
        user_email: str
    ) -> Tuple[bool, Optional[dict]]:
        """
        Procesa formulario de correo y envía notificación.
        """
        access_token = await get_valid_graph_token(request)
        if not access_token:
            from fastapi import Response
            return (False, Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"}))
        row = await service.get_oportunidad_for_email(conn, id_oportunidad)
        
        if not row:
            return (False, templates.TemplateResponse(
                "comercial/partials/toasts/toast_error.html",
                {
                    "request": request,
                    "title": "Error",
                    "message": "Oportunidad no encontrada. Por favor intenta nuevamente."
                },
                status_code=404
            ))
        
        recipients_result = await self._procesar_destinatarios(
            conn,
            service,
            form_data.get("recipients_str", ""),
            form_data.get("fixed_to", []),
            form_data.get("fixed_cc", []),
            form_data.get("extra_cc", "")
        )
        
        recipients_list = recipients_result["to"]
        cc_list = recipients_result["cc"]
        bcc_list = recipients_result["bcc"]
        
        # Logging seguro (PII compliance): usar contadores en lugar de listas completas
        logger.info(
            f"Enviando correo OP {row['op_id_estandar']} | "
            f"TO: {len(recipients_list)} destinatarios | "
            f"CC: {len(cc_list)} | BCC: {len(bcc_list)}"
        )
        
        adjuntos_result = await self._procesar_adjuntos(
            request,
            conn,
            service,
            row,
            id_oportunidad,
            form_data.get("archivos_extra", [])
        )
        
        if not adjuntos_result["success"]:
            return (False, adjuntos_result["error_response"])
        
        adjuntos_procesados = adjuntos_result["attachments"]
        
        final_body = self._preparar_cuerpo_mensaje(
            form_data.get("body", ""),
            form_data.get("auto_message", "")
        )
        
        prioridad_envio = form_data.get("prioridad") or "normal"
        subject = form_data.get("subject", "")
        
        await service.update_oportunidad_prioridad(conn, id_oportunidad, prioridad_envio)
        
        envio_result = await self._enviar_con_hilos(
            conn,
            service,
            ms_auth,
            access_token,
            user_email,
            row,
            subject,
            final_body,
            recipients_list,
            cc_list,
            bcc_list,
            prioridad_envio,
            adjuntos_procesados,
            legacy_search_term=form_data.get("legacy_search_term")
        )
        
        if not envio_result["success"]:
            return (False, self._manejar_error_envio(request, envio_result["error"]))
        
        await service.update_email_status(conn, id_oportunidad)
        
        success_response = templates.TemplateResponse(
            "comercial/partials/messages/success_sent.html",
            {
                "request": request,
                "title": "Enviado Exitosamente",
                "message": "Regresando al tablero...",
                "redirect_url": "/comercial/ui"
            }
        )
        
        return (True, success_response)
    
    async def _procesar_destinatarios(
        self,
        conn,
        service,
        recipients_str: str,
        fixed_to: List[str],
        fixed_cc: List[str],
        extra_cc: str
    ) -> Dict:
        """
        Procesa y normaliza destinatarios TO, CC, BCC.
        Delega lógica de negocio al Service Layer.
        """
        return await service.get_email_recipients_context(
            conn,
            recipients_str,
            fixed_to,
            fixed_cc,
            extra_cc
        )
    
    async def _procesar_adjuntos(
        self,
        request: Request,
        conn,
        service,
        row: dict,
        id_oportunidad: UUID,
        archivos_extra: List[UploadFile]
    ) -> Dict:
        """Procesa archivos adjuntos incluyendo Excel multisitio."""
        adjuntos_procesados = []
        
        if (row.get('cantidad_sitios') or 0) > 1:
            excel_attachment = await service.generate_multisite_excel(
                conn,
                id_oportunidad,
                row.get('id_interno_simulacion')
            )
            if excel_attachment:
                adjuntos_procesados.append(excel_attachment)
        
        for archivo in archivos_extra:
            if archivo.filename:
                try:
                    # Validar tamaño y leer contenido en una sola operación
                    _, file_size, contenido = validate_file_size(archivo, max_size_mb=10, read_content=True)
                except HTTPException:
                    # La función ya maneja el logging
                    error_response = templates.TemplateResponse(
                        "comercial/partials/toasts/toast_error.html",
                        {
                            "request": request,
                            "title": "Archivo muy grande",
                            "message": "El archivo excede el tamaño máximo permitido de 10MB."
                        }
                    )
                    return {"success": False, "error_response": error_response}
                
                adjuntos_procesados.append({
                    "name": archivo.filename,
                    "content_bytes": contenido,
                    "contentType": archivo.content_type
                })
        
        return {"success": True, "attachments": adjuntos_procesados}
    
    def _preparar_cuerpo_mensaje(self, body: str, auto_message: str) -> str:
        """Concatena mensaje del usuario con mensaje automático."""
        final_body = body if body.strip() else ""
        if final_body:
            final_body += "<br><br>"
        final_body += auto_message
        return final_body
    
    async def _enviar_con_hilos(
        self,
        conn,
        service,
        ms_auth,
        access_token: str,
        user_email: str,
        row: dict,
        subject: str,
        body: str,
        recipients: List[str],
        cc: List[str],
        bcc: List[str],
        prioridad: str,
        attachments: List[dict],
        legacy_search_term: Optional[str] = None
    ) -> Dict:
        """
        Envía correo nuevo o responde a hilo existente.
        
        Delega la lógica de threading al Service Layer y se enfoca
        únicamente en la ejecución del envío de correo.
        
        Usa email del usuario autenticado como remitente.
        """
        # Delegar lógica de threading al Service Layer
        threading_context = await service.get_email_threading_context(
            conn, 
            row, 
            legacy_search_term
        )
        
        # Log del modo de envío
        logger.info(threading_context["log_message"])
        
        # Buscar hilo si hay search_key
        thread_id = None
        if threading_context["search_key"]:
            thread_id = ms_auth.find_thread_id(access_token, threading_context["search_key"])
            
            if thread_id:
                logger.info(
                    f"HILO ENCONTRADO | ID: {thread_id[:20]}... | "
                    f"Se responderá con nuevo título: '{subject}'"
                )
            else:
                logger.warning(
                    f"HILO NO ENCONTRADO | Búsqueda: '{search_key}' | "
                    f"Se enviará como correo nuevo"
                )
        
        if thread_id:
            ok, msg = await ms_auth.reply_with_new_subject(
                access_token=access_token,
                thread_id=thread_id,
                new_subject=subject,
                body=body,
                recipients=recipients,
                cc_recipients=cc,
                bcc_recipients=bcc,
                importance=prioridad.lower(),
                attachments=attachments
            )
            logger.info(f"Correo enviado como RESPUESTA en hilo existente")
        else:
            ok, msg = await ms_auth.send_email_with_attachments(
                access_token=access_token,
                from_email=user_email,
                subject=subject,
                body=body,
                recipients=recipients,
                cc_recipients=cc,
                bcc_recipients=bcc,
                importance=prioridad.lower(),
                attachments_files=attachments
            )
            logger.info(f"Correo enviado como NUEVO (sin hilo previo) desde {user_email}")
        
        return {"success": ok, "error": msg if not ok else None}
    
    def _manejar_error_envio(self, request: Request, error_msg: str) -> dict:
        """Maneja errores de envío de correo."""
        if "expired" in str(error_msg).lower() or "InvalidAuthenticationToken" in str(error_msg):
            logger.error("Sesión expirada durante envío de correo")
            request.session.clear()
            from fastapi import Response
            return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})
        
        logger.error(f"Fallo envio correo Graph: {error_msg}")
        return templates.TemplateResponse(
            "comercial/partials/toasts/toast_error.html",
            {
                "request": request,
                "title": "Error enviando correo",
                "message": error_msg
            },
            status_code=400
        )


def get_email_handler():
    """Retorna instancia de EmailHandler para inyección de dependencias."""
    return EmailHandler()
