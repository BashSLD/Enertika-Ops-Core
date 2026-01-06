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
    
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    
    async def procesar_y_enviar_notificacion(
        self,
        request: Request,
        conn,
        service,
        ms_auth,
        id_oportunidad: UUID,
        form_data: Dict
    ) -> Tuple[bool, Optional[dict]]:
        """
        Procesa formulario de correo y envía notificación.
        
        Args:
            request: FastAPI Request object
            conn: Database connection
            service: ComercialService instance
            ms_auth: MicrosoftAuth instance  
            id_oportunidad: UUID de la oportunidad
            form_data: Dict con campos del formulario
                - recipients_str: str (Chips de TO)
                - fixed_to: List[str] (Hidden fixed TOs)
                - fixed_cc: List[str] (Hidden fixed CCs)
                - extra_cc: str (Input manual CC)
                - subject: str
                - body: str (Mensaje adicional)
                - auto_message: str (Mensaje automático)
                - prioridad: str
                - archivos_extra: List[UploadFile]
                
        Returns:
            tuple: (success, result_template_or_error)
                - success: bool - True si envío exitoso
                - result_template_or_error: dict con template response o None
        """
        # 1. Validar token de Microsoft Graph
        access_token = await get_valid_graph_token(request)
        if not access_token:
            from fastapi import Response
            return (False, Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"}))
        
        # 2. Recuperar info de la oportunidad
        row = await conn.fetchrow(
            "SELECT * FROM tb_oportunidades WHERE id_oportunidad = $1", 
            id_oportunidad
        )
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
        
        # 3. Procesar destinatarios
        recipients_result = await self._procesar_destinatarios(
            conn,
            form_data.get("recipients_str", ""),
            form_data.get("fixed_to", []),
            form_data.get("fixed_cc", []),
            form_data.get("extra_cc", "")
        )
        
        recipients_list = recipients_result["to"]
        cc_list = recipients_result["cc"]
        bcc_list = recipients_result["bcc"]
        
        logger.info(
            f"Enviando correo OP {row['op_id_estandar']} | "
            f"TO: {recipients_list} | CC: {cc_list} | BCC: {bcc_list}"
        )
        
        # 4. Procesar adjuntos
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
        
        # 5. Preparar cuerpo del mensaje
        final_body = self._preparar_cuerpo_mensaje(
            form_data.get("body", ""),
            form_data.get("auto_message", "")
        )
        
        # 6. Enviar correo (con o sin hilo)
        # CAMBIO IMPORTANTE: Usamos la prioridad del FORMULARIO, no de la BD
        # Esto permite al usuario cambiar la prioridad al enviar seguimientos
        prioridad_envio = form_data.get("prioridad") or "normal"
        subject = form_data.get("subject", "")
        
        # Actualizar prioridad en BD si cambió
        await conn.execute(
            "UPDATE tb_oportunidades SET prioridad = $1 WHERE id_oportunidad = $2",
            prioridad_envio,
            id_oportunidad
        )
        logger.info(f"Prioridad actualizada a '{prioridad_envio}' para OP {row.get('op_id_estandar')}")
        
        envio_result = await self._enviar_con_hilos(
            conn,
            ms_auth,
            access_token,
            row,
            subject,
            final_body,
            recipients_list,
            cc_list,
            bcc_list,
            prioridad_envio,
            adjuntos_procesados,
            legacy_search_term=form_data.get("legacy_search_term")  # PUENTE: Término legacy para homologación
        )
        
        if not envio_result["success"]:
            return (False, self._manejar_error_envio(request, envio_result["error"]))
        
        # 7. Marcar como enviado y retornar éxito

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
        recipients_str: str,
        fixed_to: List[str],
        fixed_cc: List[str],
        extra_cc: str
    ) -> Dict:
        """Procesa y normaliza destinatarios TO, CC, BCC."""
        # Procesar TO
        final_to = set()
        
        # Chips manuales
        if recipients_str:
            raw_list = recipients_str.replace(",", ";").split(";")
            for email in raw_list:
                if email.strip():
                    final_to.add(email.strip())
        
        # Fixed rules
        for email in fixed_to:
            if email.strip():
                final_to.add(email.strip())
        
        # Procesar CC
        final_cc = set()
        
        # Fixed rules
        for email in fixed_cc:
            if email.strip():
                final_cc.add(email.strip())
        
        # Manual input
        if extra_cc:
            raw_cc = extra_cc.replace(",", ";").split(";")
            for email in raw_cc:
                if email.strip():
                    final_cc.add(email.strip())
        
        # Procesar BCC (solo defaults)
        final_bcc = set()
        defaults = await conn.fetchrow("SELECT * FROM tb_email_defaults ORDER BY id LIMIT 1")
        if defaults:
            def_cco = (defaults['default_cco'] or "").upper().replace(",", ";").split(";")
            for email in def_cco:
                if email.strip():
                    final_bcc.add(email.strip())
        
        return {
            "to": list(final_to),
            "cc": list(final_cc),
            "bcc": list(final_bcc)
        }
    
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
        
        # Generar Excel multisitio automáticamente
        if (row.get('cantidad_sitios') or 0) > 1:
            excel_attachment = await service.generate_multisite_excel(
                conn,
                id_oportunidad,
                row.get('id_interno_simulacion')
            )
            if excel_attachment:
                adjuntos_procesados.append(excel_attachment)
        
        # Procesar archivos extra
        for archivo in archivos_extra:
            if archivo.filename:
                # Validar tamaño
                archivo.file.seek(0, 2)
                file_size = archivo.file.tell()
                await archivo.seek(0)
                
                if file_size > self.MAX_FILE_SIZE:
                    logger.warning(
                        f"Archivo rechazado (excede 10MB): {archivo.filename} ({file_size} bytes)"
                    )
                    error_response = templates.TemplateResponse(
                        "comercial/partials/toasts/toast_error.html",
                        {
                            "request": request,
                            "title": "Archivo muy grande",
                            "message": "El archivo excede el tamaño máximo permitido de 10MB."
                        }
                    )
                    return {"success": False, "error_response": error_response}
                
                contenido = await archivo.read()
                await archivo.seek(0)
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
        ms_auth,
        access_token: str,
        row: dict,
        subject: str,
        body: str,
        recipients: List[str],
        cc: List[str],
        bcc: List[str],
        prioridad: str,
        attachments: List[dict],
        legacy_search_term: Optional[str] = None  # NUEVO: Término legacy para homologación
    ) -> Dict:
        """
        Endía correo nuevo o responde a hilo existente.
        
        Lógica HÍBRIDA de búsqueda de hilos (por prioridad):
        1. Si existe legacy_search_term: HOMOLOGACIÓN (busca hilo viejo con datos nuevos)
        2. Si tiene parent_id: SEGUIMIENTO NORMAL (busca por título del padre)
        3. Caso contrario: ENVÍO INICIAL (nuevo, sin hilo previo)
        
        Siempre envía con el asunto ACTUAL (nuevo).
        """
        
        # --- LÓGICA DE DECISIÓN INTELIGENTE ---
        search_key = None
        modo = "NUEVO"  # Por defecto
        
        if legacy_search_term:
            # CASO 1: HOMOLOGACIÓN (Prioridad máxima)
            # El usuario quiere responder a un hilo antiguo pero con un formulario nuevo
            search_key = legacy_search_term
            modo = "HOMOLOGACIÓN"
            logger.info(
                f"MODO HOMOLOGACIÓN activado para '{row.get('op_id_estandar')}' | "
                f"Buscando hilo por término legacy: '{search_key}'"
            )
        elif row.get('parent_id'):
            # CASO 2: SEGUIMIENTO NORMAL
            # Es un seguimiento estándar: buscar por título del padre
            search_key = await conn.fetchval(
                "SELECT titulo_proyecto FROM tb_oportunidades WHERE id_oportunidad = $1",
                row['parent_id']
            )
            modo = "SEGUIMIENTO"
            logger.info(
                f"SEGUIMIENTO NORMAL detectado para '{row.get('op_id_estandar')}' | "
                f"Buscando hilo del padre: '{search_key}'"
            )
        else:
            # CASO 3: ENVÍO INICIAL
            # No buscar hilo previo
            logger.info(
                f"ENVÍO INICIAL para '{row.get('op_id_estandar')}' | "
                f"No se buscará hilo previo"
            )
        
        # Buscar hilo existente (solo si es seguimiento)
        thread_id = None
        if search_key:
            thread_id = ms_auth.find_thread_id(access_token, search_key)
            
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
        
        # Enviar correo
        if thread_id:
            # Responder a hilo existente
            ok, msg = ms_auth.reply_with_new_subject(
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
            # Enviar correo nuevo
            ok, msg = ms_auth.send_email_with_attachments(
                access_token=access_token,
                subject=subject,
                body=body,
                recipients=recipients,
                cc_recipients=cc,
                bcc_recipients=bcc,
                importance=prioridad.lower(),
                attachments_files=attachments
            )
            logger.info(f"Correo enviado como NUEVO (sin hilo previo)")
        
        return {"success": ok, "error": msg if not ok else None}
    
    def _manejar_error_envio(self, request: Request, error_msg: str) -> dict:
        """Maneja errores de envío de correo."""
        # Detectar token expirado
        if "expired" in str(error_msg).lower() or "InvalidAuthenticationToken" in str(error_msg):
            logger.error("Sesión expirada durante envío de correo")
            request.session.clear()
            from fastapi import Response
            return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})
        
        # Otro error
        logger.error(f"Fallo envio correo Graph: {error_msg}")
        return templates.TemplateResponse(
            "comercial/partials/toasts/toast_error.html",
            {
                "request": request,
                "title": "Error enviando correo",
                "message": error_msg
            },
            status_code=200
        )


# Helper para inyección de dependencias
def get_email_handler():
    """Retorna instancia de EmailHandler para inyección de dependencias."""
    return EmailHandler()
