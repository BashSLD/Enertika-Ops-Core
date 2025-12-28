import msal
import requests
import base64
import urllib.parse
from .config import settings 

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
                print(f"Error renovando token global: {result.get('error_description')}")
                return None
                
            return result # Retorna el nuevo access_token y refresh_token
        except Exception as e:
            print(f"Excepción crítica en refresh_token: {e}")
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
            print(f"Error obteniendo perfil: {e}")
            return {}

    # --- LÓGICA DE HILOS ---    
    def find_thread_id(self, access_token: str, search_text: str) -> str:
        """Busca el ID de un mensaje existente filtrando por asunto (Lógica Power Automate)."""
        if not access_token or not search_text: return None

        headers = self.get_headers(access_token)
        # Limpieza del texto
        clean_text = search_text.replace('"', '').replace("'", "").strip()
        encoded_search = urllib.parse.quote(clean_text)
        
        # Query: Busca en 'me/messages', no borradores, ordenado por fecha
        url = f"https://graph.microsoft.com/v1.0/me/messages?$search=\"subject:{encoded_search}\"&$filter=isDraft eq false&$orderby=receivedDateTime desc&$top=1"
        
        try:
            resp = requests.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("value", [])
                if items: return items[0]["id"]
            return None
        except Exception as e:
            print(f"Error buscando hilo: {e}")
            return None

    def reply_with_new_subject(self, access_token, thread_id, new_subject, body, recipients, cc_recipients, bcc_recipients, importance, attachments):
        """Estrategia 'Reply-Patch-Send': Crea borrador vinculado -> Modifica Asunto -> Envía."""
        headers = self.get_headers(access_token)
        
        # 1. Crear Respuesta (Draft vinculado)
        url_reply = f"https://graph.microsoft.com/v1.0/me/messages/{thread_id}/createReply"
        resp_reply = requests.post(url_reply, headers=headers)
        if resp_reply.status_code != 201: return False, f"Error creando respuesta: {resp_reply.text}"
            
        draft_id = resp_reply.json()["id"]
        
        # 2. Modificar Borrador (Inyectar NUEVO Asunto y Destinatarios)
        patch_payload = {
            "subject": new_subject,
            "importance": importance,
            "body": {"contentType": "HTML", "content": body.replace('\n', '<br>')},
            "toRecipients": [{"emailAddress": {"address": e}} for e in recipients],
            "ccRecipients": [{"emailAddress": {"address": e}} for e in cc_recipients],
            "bccRecipients": [{"emailAddress": {"address": e}} for e in bcc_recipients]
        }
        
        resp_patch = requests.patch(f"https://graph.microsoft.com/v1.0/me/messages/{draft_id}", headers=headers, json=patch_payload)
        if resp_patch.status_code != 200: return False, f"Error actualizando borrador: {resp_patch.text}"

        # 2.5 Subir Adjuntos (Reutilizamos lógica existente si hay adjuntos)
        if attachments:
            for f in attachments:
                self._upload_session(headers, draft_id, f)

        # 3. Enviar
        resp_send = requests.post(f"https://graph.microsoft.com/v1.0/me/messages/{draft_id}/send", headers=headers)
        return (True, "Enviado (Hilo Continuado)") if resp_send.status_code == 202 else (False, resp_send.text)


    # --- Envío de Correos (Híbrido) ---
    def send_email_with_attachments(self, access_token, subject, body, recipients, cc_recipients=None, bcc_recipients=None, importance="normal", attachments_files=None):
        if not access_token:
            print("Error: Token nulo.")
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

        print(f"Enviando a: {recipients} | CC: {cc_recipients} | BCC: {bcc_recipients} | Peso: {total_size/1024:.2f} KB")

        # A: Envío Directo (< 3MB)
        if total_size < LIMIT_DIRECT_SEND:
            print("Modo: Envío Directo (/sendMail)")
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
                    "body": {"contentType": "HTML", "content": body.replace('\n', '<br>')},
                    "toRecipients": [{"emailAddress": {"address": e}} for e in recipients],
                    "ccRecipients": [{"emailAddress": {"address": e}} for e in cc_recipients],
                    "bccRecipients": [{"emailAddress": {"address": e}} for e in bcc_recipients],
                    "attachments": attachments_payload
                },
                "saveToSentItems": "true"
            }

            try:
                res = requests.post("https://graph.microsoft.com/v1.0/me/sendMail", headers=headers, json=email_msg)
                if res.status_code == 202:
                    return True, "Enviado"
                else:
                    print(f"ERROR GRAPH: {res.status_code} - {res.text}")
                    return False, f"Error Microsoft: {res.status_code}"
            except Exception as e:
                return False, str(e)

        # B: Envío Pesado (Draft + Upload)
        else:
            print("Modo: Archivos Grandes (Draft + Upload)")
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