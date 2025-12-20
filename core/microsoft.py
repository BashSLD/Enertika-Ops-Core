import msal
import requests
import os
import base64
# Importamos settings de la configuración central de FastAPI
from core.config import settings 

class MicrosoftAuth:
    """Clase Singleton para manejar la autenticación y las llamadas a Microsoft Graph API."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MicrosoftAuth, cls).__new__(cls)
            # Inicialización del cliente confidencial de MSAL
            cls._instance.app = msal.ConfidentialClientApplication(
                settings.GRAPH_CLIENT_ID,
                authority=settings.AUTHORITY_URL, # Usamos la URL calculada
                client_credential=settings.GRAPH_CLIENT_SECRET,
            )
        return cls._instance

    def get_auth_url(self):
        # Aseguramos que scopes sea una lista si es string
        scopes = settings.GRAPH_SCOPES.split(" ") if isinstance(settings.GRAPH_SCOPES, str) else settings.GRAPH_SCOPES
        return self.app.get_authorization_request_url(
            scopes,
            redirect_uri=settings.REDIRECT_URI
        )

    def get_token_from_code(self, code):
        scopes = settings.GRAPH_SCOPES.split(" ") if isinstance(settings.GRAPH_SCOPES, str) else settings.GRAPH_SCOPES
        # Retorna el diccionario del token completo, NO lo guardamos en self
        return self.app.acquire_token_by_authorization_code(
            code,
            scopes=scopes,
            redirect_uri=settings.REDIRECT_URI
        )

    def get_headers(self, access_token: str):
        """Retorna los headers de autorización para Graph API usando el token proporcionado."""
        return {
            "Authorization": "Bearer " + access_token,
            "Content-Type": "application/json"
        }

    def get_user_profile(self, access_token: str):
        """Obtiene el perfil del usuario logueado desde Microsoft Graph incluyendo departamento."""
        # Solicitamos campos específicos para permisos
        endpoint = "https://graph.microsoft.com/v1.0/me?$select=id,displayName,mail,userPrincipalName,department,jobTitle"
        headers = self.get_headers(access_token)
        response = requests.get(endpoint, headers=headers)
        if response.status_code == 200:
            return response.json() # Returns dict with displayName, mail, id, department, etc.
        return None

    # Updated method to support CC
    def send_email_with_attachments(self, access_token: str, subject, body, recipients, cc_recipients=[], attachments_files=[]):
        print(f"--- INICIANDO ENVÍO DE CORREO ---")
        print(f"Destinatarios TO: {recipients}")
        print(f"Destinatarios CC: {cc_recipients}")
        print(f"Archivos a adjuntar: {len(attachments_files)}")

        if not recipients: return False, "Sin destinatarios"

        # 1. Preparar adjuntos
        attachments_data = []
        for file_obj in attachments_files:
            try:
                # Caso Dict (ya procesado bytes) o UploadFile (stream)
                if isinstance(file_obj, dict):
                    content_b64 = base64.b64encode(file_obj["content_bytes"]).decode("utf-8")
                    name = file_obj["name"]
                    ctype = file_obj.get("contentType", "application/octet-stream")
                else:
                    # Fallback por si llega directo (pero en router.py ya lo procesamos)
                    content_bytes = file_obj.file.read()
                    content_b64 = base64.b64encode(content_bytes).decode("utf-8")
                    name = file_obj.filename
                    ctype = file_obj.content_type

                attachments_data.append({
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": name,
                    "contentType": ctype,
                    "contentBytes": content_b64
                })
            except Exception as e:
                print(f"-> ERROR procesando adjunto {name}: {e}")

        # 2. Construir el JSON
        email_msg = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "Text",
                    "content": body
                },
                "toRecipients": [{"emailAddress": {"address": email}} for email in recipients],
                "ccRecipients": [{"emailAddress": {"address": email}} for email in cc_recipients],
                "attachments": attachments_data
            },
            "saveToSentItems": "true"
        }

        # 3. Enviar a Graph API
        endpoint = "https://graph.microsoft.com/v1.0/me/sendMail"
        print("Enviando request a Graph API...")
        try:
            # Check headers before sending to catch auth errors early
            headers = self.get_headers(access_token)
            response = requests.post(endpoint, headers=headers, json=email_msg)
            
            print(f"Respuesta Graph: {response.status_code}")
            if response.status_code == 202:
                return True, "Enviado exitosamente"
            else:
                print(f"Error detalle: {response.text}")
                return False, f"Error {response.status_code}: {response.text}"
        except Exception as e:
            return False, f"Excepción al enviar: {str(e)}"

# --- Dependencia para inyección en FastAPI ---
def get_ms_auth():
    """Inyecta la instancia Singleton de MicrosoftAuth."""
    return MicrosoftAuth()