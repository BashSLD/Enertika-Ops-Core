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
            # El token de cache es para el flujo de Delegación (user login)
            cls._instance.token_cache = None 
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
        result = self.app.acquire_token_by_authorization_code(
            code,
            scopes=scopes,
            redirect_uri=settings.REDIRECT_URI
        )
        if "error" in result:
            raise Exception(f"Error login: {result.get('error_description')}")
        
        self.token_cache = result 
        return result

    def get_headers(self):
        """Retorna los headers de autorización para Graph API."""
        if not self.token_cache or "access_token" not in self.token_cache:
            # En un entorno de backend donde se envía correo SIN un usuario logueado 
            # (Service Principal), necesitarías adquirir un token de aplicación.
            # Por ahora, mantendremos la dependencia del token de usuario (Delegated Flow)
            # hasta que se defina si el envío es por usuario o por servicio.
            raise Exception("Usuario no autenticado. Inicie sesión primero.")
            
        return {
            "Authorization": "Bearer " + self.token_cache["access_token"],
            "Content-Type": "application/json"
        }

    def send_email_with_attachments(self, subject, body, recipients, attachments_files=[]):
        print(f"--- INICIANDO ENVÍO DE CORREO ---")
        print(f"Destinatarios: {recipients}")
        print(f"Archivos a adjuntar: {len(attachments_files)}")

        if not recipients: return False, "Sin destinatarios"

        # 1. Preparar adjuntos
        attachments_data = []
        for file_obj in attachments_files:
            try:
                # Obtenemos ruta y nombre
                # Maneja tanto objetos con atributo .path como diccionarios con clave 'path'
                path = file_obj.path if hasattr(file_obj, "path") else (file_obj.get("path") if isinstance(file_obj, dict) else file_obj)
                name = file_obj.name if hasattr(file_obj, "name") else (file_obj.get("name") if isinstance(file_obj, dict) else os.path.basename(path))
                
                print(f"Procesando adjunto: {name} desde {path}")

                with open(path, "rb") as f:
                    content_bytes = f.read()
                
                # Codificar a Base64
                b64_content = base64.b64encode(content_bytes).decode("utf-8")
                
                # Estructura exacta requerida por Graph API
                attachments_data.append({
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": name,
                    "contentType": "application/octet-stream", # Tipo genérico seguro
                    "contentBytes": b64_content
                })
                print(f"-> Adjunto {name} procesado OK.")
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
                "attachments": attachments_data
            },
            "saveToSentItems": "true"
        }

        # 3. Enviar a Graph API
        endpoint = "https://graph.microsoft.com/v1.0/me/sendMail"
        print("Enviando request a Graph API...")
        try:
            # Check headers before sending to catch auth errors early
            headers = self.get_headers()
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