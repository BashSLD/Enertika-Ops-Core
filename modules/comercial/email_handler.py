from datetime import datetime
from uuid import UUID
from typing import List, Optional, Dict, Tuple
import logging
from fastapi import Request, UploadFile, HTTPException
from fastapi.templating import Jinja2Templates
from core.security import get_valid_graph_token

logger = logging.getLogger("ComercialModule")
templates = Jinja2Templates(directory="templates")

class EmailHandler:
    """Maneja el envío de correos del módulo comercial."""
    
    MAX_TOTAL_FILE_SIZE = 35 * 1024 * 1024  # 35 MB (límite total de adjuntos)
    
    async def procesar_y_enviar_notificacion(
        self,
        request: Request,
        conn,
        service,
        ms_auth,
        id_oportunidad: UUID,
        form_data: Dict,

        user_email: str,
        user_context: dict
    ) -> Tuple[bool, Optional[dict]]:
        """
        Procesa formulario de correo y envía notificación.
        """
        access_token = await get_valid_graph_token(request)
        if not access_token:
            from fastapi import Response
            return (False, Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"}))
        row = await service.get_oportunidad_for_email(conn, id_oportunidad, user_context)
        
        if not row:
            return (False, templates.TemplateResponse(
                request, "comercial/partials/toasts/toast_error.html",
                {                    "title": "Error",
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
            form_data.get("archivos_extra", []),
            user_context
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
        
        await service.update_oportunidad_prioridad(conn, id_oportunidad, prioridad_envio, user_context)
        
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
        
        await service.update_email_status(conn, id_oportunidad, user_context)
        
        success_response = templates.TemplateResponse(
            request, "comercial/partials/messages/success_sent.html",
            {                "title": "Enviado Exitosamente",
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
        archivos_extra: List[UploadFile],
        user_context: dict
    ) -> Dict:
        """Procesa archivos adjuntos incluyendo Excel multisitio."""
        adjuntos_procesados = []
        
        if service.is_originally_multisite(row):
            excel_attachment = await service.generate_multisite_excel(
                conn,
                id_oportunidad,
                row.get('id_interno_simulacion'),
                user_context
            )
            if excel_attachment:
                adjuntos_procesados.append(excel_attachment)
        
        for archivo in archivos_extra:
            if archivo.filename:
                contenido = await archivo.read()
                await archivo.seek(0)
                
                adjuntos_procesados.append({
                    "name": archivo.filename,
                    "content_bytes": contenido,
                    "contentType": archivo.content_type
                })
        
        # Validar tamaño total de todos los adjuntos (35 MB máximo)
        total_size = sum(len(a["content_bytes"]) for a in adjuntos_procesados)
        if total_size > self.MAX_TOTAL_FILE_SIZE:
            total_mb = total_size / (1024 * 1024)
            logger.warning(
                f"Adjuntos rechazados: total {total_mb:.1f}MB excede "
                f"límite de {self.MAX_TOTAL_FILE_SIZE // (1024 * 1024)}MB"
            )
            return {
                "success": False,
                "error_response": templates.TemplateResponse(
                    request, "comercial/partials/toasts/toast_error.html",
                    {                        "title": "Adjuntos exceden límite",
                        "message": f"El tamaño total de adjuntos ({total_mb:.1f}MB) "
                                   f"excede el máximo permitido de 35MB."
                    }
                )
            }
        
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
            candidatos_ids = await ms_auth.find_thread_candidates(access_token, threading_context["search_key"])
            
            for cid in candidatos_ids:
                logger.info(
                    f"PROBANDO HILO CANDIDATO | ID: {cid[:20]}... | "
                    f"Se responderá con nuevo título: '{subject}'"
                )
                ok, msg = await ms_auth.reply_with_new_subject(
                    access_token=access_token,
                    from_email=user_email,
                    thread_id=cid,
                    new_subject=subject,
                    body=body,
                    recipients=recipients,
                    cc_recipients=cc,
                    bcc_recipients=bcc,
                    importance=prioridad.lower(),
                    attachments=attachments
                )
                if ok:
                    thread_id = cid
                    logger.info(f"Correo enviado como RESPUESTA en hilo existente (ID: {cid[:20]}...)")
                    break
                else:
                    logger.warning(f"Error respondiendo a candidato {cid[:20]}...: {msg}. Probando siguiente...")
            
            if not thread_id and candidatos_ids:
                logger.warning(
                    f"TODOS LOS HILOS CANDIDATOS FALLARON | Búsqueda: '{threading_context.get('search_key')}' | "
                    f"Se enviará como correo nuevo"
                )
            elif not candidatos_ids:
                logger.warning(
                    f"HILO NO ENCONTRADO | Búsqueda: '{threading_context.get('search_key')}' | "
                    f"Se enviará como correo nuevo"
                )
        
        # --- SEGURIDAD: Bloquear envío si es Modo Homologación y falló la búsqueda ---
        if legacy_search_term and not thread_id:
             error_msg = f"Error: No se encontró un hilo válido para '{legacy_search_term}' o falló la respuesta a todos los candidatos. El envío ha sido bloqueado por seguridad."
             logger.error(error_msg)
             # Retornamos error explícito en lugar de enviar correo nuevo "roto"
             return {"success": False, "error": error_msg}
        
        # Si thread_id tiene valor, ya se envió exitosamente en el ciclo for.
        if thread_id:
            return {"success": True, "error": None}

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
        if ok:
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
            request,
            "comercial/partials/toasts/toast_error.html",
            {
                "title": "Error enviando correo",
                "message": error_msg
            }
        )


def get_email_handler():
    """Retorna instancia de EmailHandler para inyección de dependencias."""
    return EmailHandler()
