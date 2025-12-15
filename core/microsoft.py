import msal
import requests
import os
import base64
from .config import Config

class MicrosoftAuth:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MicrosoftAuth, cls).__new__(cls)
            cls._instance.app = msal.ConfidentialClientApplication(
                Config.CLIENT_ID,
                authority=Config.AUTHORITY,
                client_credential=Config.CLIENT_SECRET,
            )
            cls._instance.token_cache = None
        return cls._instance

    def get_auth_url(self):
        return self.app.get_authorization_request_url(
            Config.SCOPE,
            redirect_uri=Config.REDIRECT_URI
        )

    def get_token_from_code(self, code):
        result = self.app.acquire_token_by_authorization_code(
            code,
            scopes=Config.SCOPE,
            redirect_uri=Config.REDIRECT_URI
        )
        if "error" in result:
            raise Exception(f"Error login: {result.get('error_description')}")
        
        self.token_cache = result # Guardamos el token en memoria
        return result

    def get_headers(self):
        """Recupera el token valido (o lanza error si no hay login)"""
        if not self.token_cache or "access_token" not in self.token_cache:
            raise Exception("Usuario no autenticado. Inicie sesión primero.")
        return {
            "Authorization": "Bearer " + self.token_cache["access_token"],
            "Content-Type": "application/json"
        }

    def send_email_with_attachments(self, subject, body, recipients, attachments_files=[]):
        """
        Envía un correo usando Microsoft Graph API.
        attachments_files: Lista de objetos FilePicker (o rutas)
        """
        if not recipients: return False, "Sin destinatarios"

        # 1. Preparar adjuntos en base64
        attachments_data = []
        for file_obj in attachments_files:
            try:
                # Si es un objeto de Flet (FilePickerResultEvent) o ruta string
                path = file_obj.path if hasattr(file_obj, "path") else file_obj
                name = file_obj.name if hasattr(file_obj, "name") else os.path.basename(path)
                
                with open(path, "rb") as f:
                    content_bytes = f.read()
                
                b64_content = base64.b64encode(content_bytes).decode("utf-8")
                
                attachments_data.append({
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": name,
                    "contentBytes": b64_content
                })
            except Exception as e:
                print(f"Error procesando adjunto {name}: {e}")

        # 2. Construir el JSON del correo
        email_msg = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "Text",
                    "content": body
                },
                "toRecipients": [{"emailAddress": {"address": email}} for email in recipients],
                "attachments": attachments_data
            },
            "saveToSentItems": "true"
        }

        # 3. Enviar a Graph API
        endpoint = "https://graph.microsoft.com/v1.0/me/sendMail"
        response = requests.post(endpoint, headers=self.get_headers(), json=email_msg)
        
        if response.status_code == 202:
            return True, "Enviado exitosamente"
        else:
            return False, f"Error {response.status_code}: {response.text}"