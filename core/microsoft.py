import asyncio
import msal
import httpx
import base64
import urllib.parse
import re
import logging
import html
from .config import settings 

logger = logging.getLogger("MicrosoftGraph") 
MICROSOFT_GRAPH_ERRORS = (httpx.HTTPError, RuntimeError, ValueError, KeyError, TypeError)

class MicrosoftAuth:
    # Singleton pattern: safe in asyncio single-thread event loop.
    # All coroutines share one instance; no concurrent __new__ calls possible.
    _instance = None
    _http_client = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MicrosoftAuth, cls).__new__(cls)
            
            # Inicialización de MSAL usando 'settings'
            # Asegúrate de que settings tenga estas variables en core/config.py
            # timeout: MSAL no tiene limite por defecto (puede colgarse indefinidamente
            # si el endpoint de Microsoft esta lento). Se acota por debajo del TTL del
            # lock de renovacion (core/security.py) para que un refresh nunca sobreviva
            # a su propio lock y dispare una renovacion duplicada sin bloqueo.
            cls._instance.app = msal.ConfidentialClientApplication(
                settings.GRAPH_CLIENT_ID,
                authority=settings.AUTHORITY_URL,
                client_credential=settings.GRAPH_CLIENT_SECRET,
                timeout=max(5, settings.TOKEN_REFRESH_LOCK_TTL_SECONDS - 5),
            )
            
            # Cliente HTTP persistente con connection pooling
            cls._instance._http_client = httpx.AsyncClient(
                timeout=30.0,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)
            )
        return cls._instance

    # --- Login (MSAL) ---
    def get_auth_url(self, state: str, nonce: str):
        """state y nonce correlacionan este intento (ver core/oauth_repository.py):
        state se re-emite tal cual en el callback (proteccion CSRF estandar de
        OAuth), nonce se valida contra el claim del id_token en get_token_from_code."""
        return self.app.get_authorization_request_url(
            settings.GRAPH_SCOPES.split(" "),
            redirect_uri=settings.REDIRECT_URI,
            state=state,
            nonce=nonce,
        )

    async def get_token_from_code(self, code, nonce: str | None = None):
        # MSAL automáticamente incluye refresh_token para ConfidentialClientApplication
        # No necesitamos agregar 'offline_access' explícitamente
        import asyncio
        result = await asyncio.to_thread(
            self.app.acquire_token_by_authorization_code,
            code,
            scopes=settings.GRAPH_SCOPES.split(" "),
            redirect_uri=settings.REDIRECT_URI,
            nonce=nonce,
        )
        if "error" in result:
            raise RuntimeError(f"Error login: {result.get('error_description')}")
        return result

    # --- GESTIÓN GLOBAL DE TOKEN (REFRESH) ---
    async def refresh_access_token(self, refresh_token):
        """
        Renueva el access_token usando el refresh_token de larga duración.
        Útil para cualquier módulo que requiera Graph API.
        """
        try:
            # MSAL maneja automáticamente refresh_token sin necesidad de offline_access
            scopes = settings.GRAPH_SCOPES.split(" ")
            
            import asyncio
            result = await asyncio.to_thread(
                self.app.acquire_token_by_refresh_token,
                refresh_token,
                scopes=scopes
            )
            
            if "error" in result:
                logger.error(f"Error renovando token global: {result.get('error_description')}")
                return None
                
            return result # Retorna el nuevo access_token y refresh_token
        except MICROSOFT_GRAPH_ERRORS as e:
            logger.error(f"Excepción crítica en refresh_token: {e}")
            return None

    async def get_application_token(self):
        """
        Obtiene un access token usando Client Credentials Flow (application-only).
        Este token NO requiere usuario logueado y es ideal para tareas en background.
        Útil para envío de emails de notificaciones automáticas.
        
        Returns:
            str: Access token o None si falla
        """
        try:
            # Client Credentials Flow: app actúa en su propio nombre, no en nombre de usuario
            scopes = ["https://graph.microsoft.com/.default"]
            
            # Wrap MSAL call to prevent event loop blocking
            import asyncio
            result = await asyncio.to_thread(self.app.acquire_token_for_client, scopes=scopes)
            
            if "error" in result:
                logger.error(f"Error obteniendo token de aplicación: {result.get('error_description')}")
                return None
                
            logger.info("[APP TOKEN] Token de aplicación obtenido exitosamente")
            return result.get("access_token")
            
        except MICROSOFT_GRAPH_ERRORS as e:
            logger.error(f"Excepción obteniendo token de aplicación: {e}")
            return None

    # --- Utilidades ---
    def get_headers(self, token):
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    async def get_user_profile(self, token):
        try:
            headers = self.get_headers(token)
            resp = await self._http_client.get("https://graph.microsoft.com/v1.0/me", headers=headers)
            if resp.status_code == 200:
                return resp.json()
            return {}
        except MICROSOFT_GRAPH_ERRORS as e:
            logger.error(f"Error obteniendo perfil: {e}")
            return {}

    # --- LÓGICA DE HILOS ---    
    async def find_thread_candidates(self, access_token: str, search_text: str) -> list:
        """
        Busca los IDs de hilos que coincidan con la búsqueda.
        Limpia prefijos (Re:, Fwd:, Rv:, Enc:, Tr:) automáticamente para tolerar inputs sucios.
        CORRECCIONES APLICADAS:
        1. Sin $filter (incompatible con $search).
        2. Sin $orderby (incompatible con $search).
        3. Filtrado de isDraft en Python.
        4. Ordenamiento por fecha en Python.
        5. Retorna múltiples candidatos para mayor robustez.
        """
        if not access_token or not search_text: 
            return None

        headers = self.get_headers(access_token)
        
        # LIMPIEZA ROBUSTA: Elimina comillas y espacios
        clean_text = search_text.replace('"', '').replace("'", "").strip()
        
        # SANITIZACIÓN: Elimina prefijos RE:, FWD:, RV:, ENC:, TR: al inicio (case insensitive)
        clean_text = re.sub(r'^(re|fw|fwd|rv|enc|tr)[:\s]+', '', clean_text, flags=re.IGNORECASE).strip()
        
        encoded_search = urllib.parse.quote(clean_text)
        
        # URL FINAL: Sin $filter ni $orderby. Aumentamos top a 50 para asegurar barrido.
        url = f"https://graph.microsoft.com/v1.0/me/messages?$search=\"{encoded_search}\"&$select=id,subject,conversationId,receivedDateTime,isDraft&$top=50"
        
        try:
            resp = await self._http_client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("value", [])
                
                # Lista para guardar candidatos válidos
                candidatos = []

                # 1. Filtrado en memoria
                for item in items:
                    # Ignorar borradores
                    if item.get("isDraft") is True:
                        continue
                        
                    # Filtrar elementos que NO son mensajes de correo estandar (ej. EventMessage)
                    odata_type = item.get("@odata.type", "")
                    if odata_type and odata_type != "#microsoft.graph.message":
                        continue
                    
                    # Validar texto en asunto
                    subject = item.get("subject", "") or ""
                    if clean_text.lower() in subject.lower():
                        candidatos.append(item)
                
                if not candidatos:
                    logger.info(f"NO se encontró hilo válido con '{clean_text}'")
                    return []

                # 2. Ordenamiento en memoria (El más reciente primero)
                # Las fechas ISO 8601 se pueden ordenar como strings directamente
                candidatos.sort(key=lambda x: x.get("receivedDateTime", ""), reverse=True)
                
                logger.info(f"HILOS ENCONTRADOS: {len(candidatos)} candidatos para {clean_text}")
                return [c["id"] for c in candidatos]

            else:
                logger.error(f"Error Graph: {resp.status_code} - {resp.text}")
                return []
        except MICROSOFT_GRAPH_ERRORS as e:
            logger.error(f"Excepción buscando hilos candidatos: {e}")
            return []

    @staticmethod
    def _recipient_addresses(recipients: list) -> list:
        emails = []
        for recipient in recipients or []:
            address = (
                recipient.get("emailAddress", {}).get("address")
                if isinstance(recipient, dict)
                else None
            )
            if address and address.strip():
                emails.append(address.strip())
        return emails

    @staticmethod
    def _merge_recipients(*groups) -> list:
        result = []
        seen = set()
        for group in groups:
            for email in group or []:
                clean = (email or "").strip()
                key = clean.lower()
                if clean and key not in seen:
                    result.append(clean)
                    seen.add(key)
        return result

    @staticmethod
    def _text_to_html_body(body_text: str) -> str:
        escaped = html.escape(body_text or "").replace("\n", "<br>")
        return (
            "<!-- ENERTIKA_TRANSFER_BODY_START -->"
            f"{escaped}"
            "<!-- ENERTIKA_TRANSFER_BODY_END -->"
        )

    async def get_message_recipients(self, access_token: str, from_email: str, message_id: str) -> dict:
        """Lee asunto y destinatarios de un mensaje encontrado en el buzón del ejecutor."""
        if not access_token or not from_email or not message_id:
            return {}

        headers = self.get_headers(access_token)
        url = (
            f"https://graph.microsoft.com/v1.0/users/{from_email}/messages/{message_id}"
            "?$select=subject,from,toRecipients,ccRecipients,receivedDateTime"
        )

        try:
            resp = await self._http_client.get(url, headers=headers)
            if resp.status_code != 200:
                logger.warning("No se pudo leer destinatarios del hilo %s: %s - %s", message_id, resp.status_code, resp.text)
                return {}

            data = resp.json()
            from_address = data.get("from", {}).get("emailAddress", {}).get("address")
            return {
                "id": message_id,
                "subject": data.get("subject") or "",
                "from": from_address,
                "to": self._recipient_addresses(data.get("toRecipients", [])),
                "cc": self._recipient_addresses(data.get("ccRecipients", [])),
                "receivedDateTime": data.get("receivedDateTime"),
            }
        except MICROSOFT_GRAPH_ERRORS as e:
            logger.warning("Excepción leyendo destinatarios del hilo %s: %s", message_id, e)
            return {}

    async def create_draft_reply(
        self,
        access_token: str,
        from_email: str,
        thread_id: str,
        body_text: str,
        additional_cc: list,
        importance: str = "normal",
    ):
        """Crea un borrador de respuesta dentro del hilo sin enviarlo."""
        if not access_token:
            return False, None, "No hay sesión activa"
        if not from_email:
            return False, None, "Usuario sin email configurado"

        headers = self.get_headers(access_token)
        url_reply = f"https://graph.microsoft.com/v1.0/users/{from_email}/messages/{thread_id}/createReply"

        try:
            resp_reply = await self._http_client.post(url_reply, headers=headers)
            if resp_reply.status_code != 201:
                return False, None, f"Error creando respuesta: {resp_reply.text}"

            draft = resp_reply.json()
            draft_id = draft["id"]
            original_history_html = draft.get("body", {}).get("content", "")
            len_history = len(original_history_html or "")
            if not original_history_html or len_history < 50:
                logger.error("Microsoft retorno un borrador de traspaso sin historial HTML.")
                await self._http_client.delete(
                    f"https://graph.microsoft.com/v1.0/users/{from_email}/messages/{draft_id}",
                    headers=headers,
                )
                return False, None, "Microsoft retorno un borrador sin historial. Intenta nuevamente."

            to_recipients = self._recipient_addresses(draft.get("toRecipients", []))
            cc_recipients = self._merge_recipients(
                self._recipient_addresses(draft.get("ccRecipients", [])),
                additional_cc,
            )
            to_keys = {email.lower() for email in to_recipients}
            cc_recipients = [email for email in cc_recipients if email.lower() not in to_keys]
            body_html = f"{self._text_to_html_body(body_text)}<br><br>{original_history_html}"

            final_subject = draft.get("subject") or ""
            if final_subject and not final_subject.upper().startswith("RE:"):
                final_subject = f"Re: {final_subject}"

            patch_payload = {
                "importance": importance,
                "body": {"contentType": "HTML", "content": body_html},
                "toRecipients": [{"emailAddress": {"address": e}} for e in to_recipients],
                "ccRecipients": [{"emailAddress": {"address": e}} for e in cc_recipients],
            }
            if final_subject:
                patch_payload["subject"] = final_subject

            resp_patch = await self._http_client.patch(
                f"https://graph.microsoft.com/v1.0/users/{from_email}/messages/{draft_id}",
                headers=headers,
                json=patch_payload,
            )
            if resp_patch.status_code != 200:
                await self._http_client.delete(
                    f"https://graph.microsoft.com/v1.0/users/{from_email}/messages/{draft_id}",
                    headers=headers,
                )
                return False, None, f"Error actualizando borrador: {resp_patch.text}"

            return True, {
                "draft_id": draft_id,
                "thread_id": thread_id,
                "subject": final_subject,
                "body_text": body_text,
                "to": to_recipients,
                "cc": cc_recipients,
            }, "Borrador creado"
        except MICROSOFT_GRAPH_ERRORS as e:
            logger.error("Error creando borrador de traspaso: %s", e, exc_info=True)
            return False, None, str(e)

    async def send_draft(self, access_token: str, from_email: str, draft_id: str, subject: str = None, body_text: str = None):
        """Actualiza el borrador editable y lo envía."""
        if not access_token:
            return False, "No hay sesión activa"
        if not from_email:
            return False, "Usuario sin email configurado"
        if not draft_id:
            return False, "Borrador no especificado"

        headers = self.get_headers(access_token)
        draft_url = f"https://graph.microsoft.com/v1.0/users/{from_email}/messages/{draft_id}"

        try:
            if subject is not None or body_text is not None:
                current = await self._http_client.get(f"{draft_url}?$select=subject,body", headers=headers)
                if current.status_code != 200:
                    return False, f"Error leyendo borrador: {current.text}"

                current_data = current.json()
                patch_payload = {}
                if subject is not None and subject.strip():
                    patch_payload["subject"] = subject.strip()

                if body_text is not None:
                    current_html = current_data.get("body", {}).get("content", "")
                    new_body = self._text_to_html_body(body_text)
                    start = "<!-- ENERTIKA_TRANSFER_BODY_START -->"
                    end = "<!-- ENERTIKA_TRANSFER_BODY_END -->"
                    if start in current_html and end in current_html:
                        pattern = f"{re.escape(start)}.*?{re.escape(end)}"
                        updated_html = re.sub(pattern, lambda _m: new_body, current_html, flags=re.DOTALL)
                    else:
                        updated_html = f"{new_body}<br><br>{current_html}"
                    patch_payload["body"] = {"contentType": "HTML", "content": updated_html}

                if patch_payload:
                    patched = await self._http_client.patch(draft_url, headers=headers, json=patch_payload)
                    if patched.status_code != 200:
                        return False, f"Error actualizando borrador: {patched.text}"

            sent = await self._http_client.post(f"{draft_url}/send", headers=headers)
            if sent.status_code == 202:
                return True, "Borrador enviado"
            return False, f"Error enviando borrador: {sent.status_code} - {sent.text}"
        except MICROSOFT_GRAPH_ERRORS as e:
            logger.error("Error enviando borrador de traspaso: %s", e, exc_info=True)
            return False, str(e)

    async def delete_draft(self, access_token: str, from_email: str, draft_id: str):
        """Elimina un borrador de Graph si sigue disponible."""
        if not access_token or not from_email or not draft_id:
            return False, "Datos insuficientes para eliminar borrador"

        headers = self.get_headers(access_token)
        url = f"https://graph.microsoft.com/v1.0/users/{from_email}/messages/{draft_id}"
        try:
            resp = await self._http_client.delete(url, headers=headers)
            if resp.status_code in (204, 404):
                return True, "Borrador eliminado"
            return False, f"Error eliminando borrador: {resp.status_code} - {resp.text}"
        except MICROSOFT_GRAPH_ERRORS as e:
            logger.warning("Error eliminando borrador %s: %s", draft_id, e)
            return False, str(e)

    async def reply_with_new_subject(self, access_token, from_email, thread_id, new_subject, body, recipients, cc_recipients, bcc_recipients, importance, attachments):
        """
        Crea respuesta, PRESERVA el historial, AGREGA 'Re:' y envía.
        """
        if not from_email:
            return False, "Usuario sin email configurado"

        headers = self.get_headers(access_token)

        # 1. Crear Respuesta (Draft vinculado)
        url_reply = f"https://graph.microsoft.com/v1.0/users/{from_email}/messages/{thread_id}/createReply"
        resp_reply = await self._http_client.post(url_reply, headers=headers)
        if resp_reply.status_code != 201:
            return False, f"Error creando respuesta: {resp_reply.text}"

        draft_data = resp_reply.json()
        draft_id = draft_data["id"]

        original_history_html = draft_data.get("body", {}).get("content", "")
        len_history = len(original_history_html or "")
        logger.info(f"Creado borrador de respuesta. Longitud Historial: {len_history} caracteres.")

        if not original_history_html or len_history < 50:
            logger.error("Error Critico: Microsoft retorno un borrador sin historial HTML.")
            await self._http_client.delete(f"https://graph.microsoft.com/v1.0/users/{from_email}/messages/{draft_id}", headers=headers)
            return False, "Error: Microsoft retorno un borrador sin historial. Intenta nuevamente."

        full_body_html = f"{body.replace(chr(10), '<br>')}<br><br>{original_history_html}"

        final_subject = new_subject
        if not final_subject.upper().startswith("RE:"):
            final_subject = f"Re: {final_subject}"

        # 2. Modificar Borrador (PATCH)
        patch_payload = {
            "subject": final_subject,
            "importance": importance,
            "body": {"contentType": "HTML", "content": full_body_html},
            "toRecipients": [{"emailAddress": {"address": e}} for e in recipients],
            "ccRecipients": [{"emailAddress": {"address": e}} for e in cc_recipients],
            "bccRecipients": [{"emailAddress": {"address": e}} for e in bcc_recipients]
        }

        resp_patch = await self._http_client.patch(f"https://graph.microsoft.com/v1.0/users/{from_email}/messages/{draft_id}", headers=headers, json=patch_payload)
        if resp_patch.status_code != 200:
            return False, f"Error actualizando borrador: {resp_patch.text}"

        # 3. Subir Adjuntos (si existen)
        if attachments:
            for f in attachments:
                await self._upload_session(headers, from_email, draft_id, f)

        # 4. Enviar
        resp_send = await self._http_client.post(f"https://graph.microsoft.com/v1.0/users/{from_email}/messages/{draft_id}/send", headers=headers)
        
        if resp_send.status_code == 202:
            return True, "Enviado (Historial preservado)"
        else:
            return False, resp_send.text


    # --- Envío de Correos (Híbrido) ---
    async def send_email_with_attachments(self, access_token, from_email, subject, body, recipients, cc_recipients=None, bcc_recipients=None, importance="normal", attachments_files=None):
        if not settings.EMAIL_SEND_ENABLED:
            logger.info("[EMAIL] Envio suprimido (EMAIL_SEND_ENABLED=false): subject=%s", subject)
            return True, "Envio suprimido (modo no-produccion)"

        if not access_token:
            logger.error("Error: Token nulo.")
            return False, "No hay sesión activa"

        headers = self.get_headers(access_token)
        attachments_files = attachments_files or []
        cc_recipients = cc_recipients or []
        bcc_recipients = bcc_recipients or []
        
        recipients = [e.strip() for e in recipients if e and e.strip()]
        cc_recipients = [e.strip() for e in cc_recipients if e and e.strip()]
        bcc_recipients = [e.strip() for e in bcc_recipients if e and e.strip()]

        if not recipients:
            return False, "Lista de destinatarios vacía."

        total_size = sum([len(f.get("content_bytes", b"")) for f in attachments_files])
        LIMIT_DIRECT_SEND = 3 * 1024 * 1024  # 3 MB

        logger.info(f"Enviando a: {recipients} | CC: {cc_recipients} | BCC: {bcc_recipients} | Peso: {total_size/1024:.2f} KB")

        # A: Envío Directo (< 3MB)
        if total_size < LIMIT_DIRECT_SEND:
            logger.info("Modo: Envío Directo (/sendMail)")
            attachments_payload = []
            for f in attachments_files:
                b64 = base64.b64encode(f["content_bytes"]).decode("utf-8")
                attachments_payload.append({
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": f["name"],
                    "contentType": f.get("contentType", "application/octet-stream"),
                    "contentBytes": b64
                })

            email_msg = {
                "message": {
                    "subject": subject,
                    "importance": importance,  # ACCIÓN 3: Agregar importance
                    "body": {"contentType": "HTML", "content": body},  # Usar HTML sin modificar
                    "toRecipients": [{"emailAddress": {"address": e}} for e in recipients],
                    "ccRecipients": [{"emailAddress": {"address": e}} for e in cc_recipients],
                    "bccRecipients": [{"emailAddress": {"address": e}} for e in bcc_recipients],
                    "attachments": attachments_payload
                },
                "saveToSentItems": "true"
            }

            try:
                # Validar que from_email existe (usuario autenticado)
                if not from_email:
                    logger.error("[EMAIL] from_email vacio - usuario sin email en contexto")
                    return False, "Usuario sin email configurado"
                
                # Con Application token usar /users/{email}/sendMail
                endpoint = f"https://graph.microsoft.com/v1.0/users/{from_email}/sendMail"
                
                res = await self._http_client.post(endpoint, headers=headers, json=email_msg)
                if res.status_code == 202:
                    return True, "Enviado"
                else:
                    logger.error(f"ERROR GRAPH: {res.status_code} - {res.text}")
                    return False, f"Error Microsoft: {res.status_code}"
            except MICROSOFT_GRAPH_ERRORS as e:
                return False, str(e)

        # B: Envío Pesado (Draft + Upload)
        else:
            logger.info("Modo: Archivos Grandes (Draft + Upload)")
            return await self._send_heavy_email(headers, from_email, subject, body, recipients, cc_recipients, bcc_recipients, importance, attachments_files)

    async def _send_heavy_email(self, headers, from_email, subject, body, recipients, cc, bcc, importance, attachments):
        if not from_email:
            logger.error("[EMAIL] from_email vacio en modo heavy - usuario sin email en contexto")
            return False, "Usuario sin email configurado"
        try:
            draft_payload = {
                "subject": subject,
                "importance": importance,
                "body": {"contentType": "HTML", "content": body},
                "toRecipients": [{"emailAddress": {"address": e}} for e in recipients],
                "ccRecipients": [{"emailAddress": {"address": e}} for e in cc],
                "bccRecipients": [{"emailAddress": {"address": e}} for e in bcc]
            }
            # 1. Draft
            res = await self._http_client.post(f"https://graph.microsoft.com/v1.0/users/{from_email}/messages", headers=headers, json=draft_payload)
            if res.status_code != 201: return False, f"Error draft: {res.text}"
            msg_id = res.json()["id"]

            # 2. Upload
            for f in attachments:
                await self._upload_session(headers, from_email, msg_id, f)

            # 3. Send
            res_send = await self._http_client.post(f"https://graph.microsoft.com/v1.0/users/{from_email}/messages/{msg_id}/send", headers=headers)
            if res_send.status_code == 202:
                return True, "Enviado"
            logger.error("Heavy send fallo: status=%s body=%r", res_send.status_code, res_send.text)
            return False, f"HTTP {res_send.status_code}: {res_send.text}"
        except MICROSOFT_GRAPH_ERRORS as e:
            logger.error("Heavy send excepcion: %s", e, exc_info=True)
            return False, str(e) or repr(e)

    async def _upload_session(self, headers, from_email, msg_id, file_data):
        name = file_data["name"]
        content = file_data["content_bytes"]
        size = len(content)
        chunk_size = 327680 * 10

        for attempt in range(3):
            # Crear nueva sesión de upload en cada intento (la URL expira)
            sess = await self._http_client.post(
                f"https://graph.microsoft.com/v1.0/users/{from_email}/messages/{msg_id}/attachments/createUploadSession",
                headers=headers,
                json={"AttachmentItem": {"attachmentType": "file", "name": name, "size": size}}
            )
            if sess.status_code != 201:
                raise RuntimeError(f"Upload session fallo: HTTP {sess.status_code} - {sess.text}")

            upload_url = sess.json()["uploadUrl"]

            try:
                # Cliente desechable para el blob: dominio distinto a Graph API
                async with httpx.AsyncClient(timeout=120.0) as blob_client:
                    for i in range(0, size, chunk_size):
                        chunk = content[i:i+chunk_size]
                        res = await blob_client.put(upload_url, headers={
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {i}-{i+len(chunk)-1}/{size}"
                        }, content=chunk)
                        if not res.is_success:
                            raise RuntimeError(f"Chunk {i}-{i+len(chunk)-1} fallo: HTTP {res.status_code} - {res.text[:200]}")
                return  # todos los chunks subidos correctamente
            except httpx.TransportError as exc:
                if attempt == 2:
                    raise
                logger.warning("Upload error de red (intento %d/3): %s — reintentando en %ds", attempt + 1, exc, 2 ** attempt)
                await asyncio.sleep(2 ** attempt)

def get_ms_auth():
    return MicrosoftAuth()
