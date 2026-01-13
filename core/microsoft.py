import msal
import requests
import base64
import urllib.parse
import re
import logging
from .config import settings 

logger = logging.getLogger("MicrosoftGraph") 

class MicrosoftAuth:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MicrosoftAuth, cls).__new__(cls)
            
            # Inicialización de MSAL usando 'settings'
            # Asegúrate de que settings tenga estas variables en core/config.py
            cls._instance.app = msal.ConfidentialClientApplication(
                settings.GRAPH_CLIENT_ID,
                authority=settings.AUTHORITY_URL,
                client_credential=settings.GRAPH_CLIENT_SECRET,
            )
        return cls._instance

    # --- Login (MSAL) ---
    def get_auth_url(self):
        return self.app.get_authorization_request_url(
            settings.GRAPH_SCOPES.split(" "), # MSAL expects a list or space-separated string? check get_authorization_request_url docs. usually a list. Pydantic settings is string.
            # wait, get_authorization_request_url source: scopes (list[str])
            # ConfidentClientApplication source: scopes (list[str])
            # In config.py: GRAPH_SCOPES: str = "email User.Read Mail.Send Files.ReadWrite.All Sites.Read.All"
            # So I should split it.
            redirect_uri=settings.REDIRECT_URI
        )

    def get_token_from_code(self, code):
        # MSAL automáticamente incluye refresh_token para ConfidentialClientApplication
        # No necesitamos agregar 'offline_access' explícitamente
        result = self.app.acquire_token_by_authorization_code(
            code,
            scopes=settings.GRAPH_SCOPES.split(" "),
            redirect_uri=settings.REDIRECT_URI
        )
        if "error" in result:
            raise Exception(f"Error login: {result.get('error_description')}")
        return result

    # --- GESTIÓN GLOBAL DE TOKEN (REFRESH) ---
    def refresh_access_token(self, refresh_token):
        """
        Renueva el access_token usando el refresh_token de larga duración.
        Útil para cualquier módulo que requiera Graph API.
        """
        try:
            # MSAL maneja automáticamente refresh_token sin necesidad de offline_access
            scopes = settings.GRAPH_SCOPES.split(" ")
            
            result = self.app.acquire_token_by_refresh_token(
                refresh_token,
                scopes=scopes
            )
            
            if "error" in result:
                logger.error(f"Error renovando token global: {result.get('error_description')}")
                return None
                
            return result # Retorna el nuevo access_token y refresh_token
        except Exception as e:
            logger.error(f"Excepción crítica en refresh_token: {e}")
            return None

    def get_application_token(self):
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
            
            result = self.app.acquire_token_for_client(scopes=scopes)
            
            if "error" in result:
                logger.error(f"Error obteniendo token de aplicación: {result.get('error_description')}")
                return None
                
            logger.info("[APP TOKEN] Token de aplicación obtenido exitosamente")
            return result.get("access_token")
            
        except Exception as e:
            logger.error(f"Excepción obteniendo token de aplicación: {e}")
            return None

    # --- Utilidades ---
    def get_headers(self, token):
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    def get_user_profile(self, token):
        try:
            headers = self.get_headers(token)
            resp = requests.get("https://graph.microsoft.com/v1.0/me", headers=headers)
            if resp.status_code == 200:
                return resp.json()
            return {}
        except Exception as e:
            logger.error(f"Error obteniendo perfil: {e}")
            return {}

    # --- LÓGICA DE HILOS ---    
    def find_thread_id(self, access_token: str, search_text: str) -> str:
        """
        Busca el ID del hilo más reciente.
        Limpia prefijos (Re:, Fwd:, Rv:, Enc:, Tr:) automáticamente para tolerar inputs sucios.
        CORRECCIONES APLICADAS:
        1. Sin $filter (incompatible con $search).
        2. Sin $orderby (incompatible con $search).
        3. Filtrado de isDraft en Python.
        4. Ordenamiento por fecha en Python.
        5. Sanitización con Regex para eliminar prefijos de correo.
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
            resp = requests.get(url, headers=headers)
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
                    
                    # Validar texto en asunto
                    subject = item.get("subject", "") or ""
                    if clean_text.lower() in subject.lower():
                        candidatos.append(item)
                
                if not candidatos:
                    logger.info(f"NO se encontró hilo válido con '{clean_text}'")
                    return None

                # 2. Ordenamiento en memoria (El más reciente primero)
                # Las fechas ISO 8601 se pueden ordenar como strings directamente
                candidatos.sort(key=lambda x: x.get("receivedDateTime", ""), reverse=True)
                
                # Tomamos el primero (el más reciente)
                winner = candidatos[0]
                logger.info(f"HILO ENCONTRADO: {winner['id']} ({winner.get('receivedDateTime')})")
                return winner["id"]

            else:
                logger.error(f"Error Graph: {resp.status_code} - {resp.text}")
                return None
        except Exception as e:
            logger.error(f"Excepción buscando hilo: {e}")
            return None

    def reply_with_new_subject(self, access_token, thread_id, new_subject, body, recipients, cc_recipients, bcc_recipients, importance, attachments):
        """
        Crea respuesta, PRESERVA el historial, AGREGA 'Re:' y envía.
        """
        headers = self.get_headers(access_token)
        
        # 1. Crear Respuesta (Draft vinculado)
        # Esto genera un borrador que YA contiene el historial del correo anterior (el "thread")
        url_reply = f"https://graph.microsoft.com/v1.0/me/messages/{thread_id}/createReply"
        resp_reply = requests.post(url_reply, headers=headers)
        if resp_reply.status_code != 201: 
            return False, f"Error creando respuesta: {resp_reply.text}"
            
        draft_data = resp_reply.json()
        draft_id = draft_data["id"]
        
        # --- CORRECCIÓN 1: RECUPERAR HISTORIAL ---
        # Obtenemos el HTML que Microsoft generó automáticamente (que tiene el "From:...", "Sent:...", etc.)
        original_history_html = draft_data.get("body", {}).get("content", "")
        
        # Combinamos: Tu mensaje nuevo + Salto de línea + Historial original
        # Nota: body.replace('\n', '<br>') convierte tus saltos de línea de texto a HTML
        full_body_html = f"{body.replace(chr(10), '<br>')}<br><br>{original_history_html}"

        # --- CORRECCIÓN 2: AGREGAR "Re:" ---
        # Si el asunto nuevo no empieza con Re:, se lo agregamos para mantener el estándar visual
        final_subject = new_subject
        if not final_subject.upper().startswith("RE:"):
            final_subject = f"Re: {final_subject}"

        # 2. Modificar Borrador (PATCH)
        patch_payload = {
            "subject": final_subject,
            "importance": importance,
            "body": {
                "contentType": "HTML", 
                "content": full_body_html  # <--- Enviamos el cuerpo combinado
            },
            "toRecipients": [{"emailAddress": {"address": e}} for e in recipients],
            "ccRecipients": [{"emailAddress": {"address": e}} for e in cc_recipients],
            "bccRecipients": [{"emailAddress": {"address": e}} for e in bcc_recipients]
        }
        
        resp_patch = requests.patch(f"https://graph.microsoft.com/v1.0/me/messages/{draft_id}", headers=headers, json=patch_payload)
        if resp_patch.status_code != 200: 
            return False, f"Error actualizando borrador: {resp_patch.text}"

        # 3. Subir Adjuntos (si existen)
        if attachments:
            for f in attachments:
                self._upload_session(headers, draft_id, f)

        # 4. Enviar
        resp_send = requests.post(f"https://graph.microsoft.com/v1.0/me/messages/{draft_id}/send", headers=headers)
        
        if resp_send.status_code == 202:
            return True, "Enviado (Historial preservado)"
        else:
            return False, resp_send.text


    # --- Envío de Correos (Híbrido) ---
    def send_email_with_attachments(self, access_token, from_email, subject, body, recipients, cc_recipients=None, bcc_recipients=None, importance="normal", attachments_files=None):
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
                
                res = requests.post(endpoint, headers=headers, json=email_msg)
                if res.status_code == 202:
                    return True, "Enviado"
                else:
                    logger.error(f"ERROR GRAPH: {res.status_code} - {res.text}")
                    return False, f"Error Microsoft: {res.status_code}"
            except Exception as e:
                return False, str(e)

        # B: Envío Pesado (Draft + Upload)
        else:
            logger.info("Modo: Archivos Grandes (Draft + Upload)")
            return self._send_heavy_email(headers, subject, body, recipients, cc_recipients, bcc_recipients, importance, attachments_files)

    def _send_heavy_email(self, headers, subject, body, recipients, cc, bcc, importance, attachments):
        try:
            draft_payload = {
                "subject": subject,
                "importance": importance,  # ACCIÓN 3: Agregar importance
                "body": {"contentType": "HTML", "content": body.replace('\n', '<br>')},
                "toRecipients": [{"emailAddress": {"address": e}} for e in recipients],
                "ccRecipients": [{"emailAddress": {"address": e}} for e in cc],
                "bccRecipients": [{"emailAddress": {"address": e}} for e in bcc]
            }
            # 1. Draft
            res = requests.post("https://graph.microsoft.com/v1.0/me/messages", headers=headers, json=draft_payload)
            if res.status_code != 201: return False, f"Error draft: {res.text}"
            msg_id = res.json()["id"]

            # 2. Upload
            for f in attachments:
                self._upload_session(headers, msg_id, f)

            # 3. Send
            res_send = requests.post(f"https://graph.microsoft.com/v1.0/me/messages/{msg_id}/send", headers=headers)
            return (True, "Enviado") if res_send.status_code == 202 else (False, res_send.text)
        except Exception as e:
            return False, str(e)

    def _upload_session(self, headers, msg_id, file_data):
        name = file_data["name"]
        content = file_data["content_bytes"]
        size = len(content)
        
        sess = requests.post(
            f"https://graph.microsoft.com/v1.0/me/messages/{msg_id}/attachments/createUploadSession",
            headers=headers,
            json={"AttachmentItem": {"attachmentType": "file", "name": name, "size": size}}
        )
        if sess.status_code != 201: return
        
        upload_url = sess.json()["uploadUrl"]
        chunk_size = 327680 * 10 
        
        with requests.Session() as s:
            for i in range(0, size, chunk_size):
                chunk = content[i:i+chunk_size]
                s.put(upload_url, headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {i}-{i+len(chunk)-1}/{size}"
                }, data=chunk)

def get_ms_auth():
    return MicrosoftAuth()