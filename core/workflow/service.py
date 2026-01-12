from uuid import UUID, uuid4
from datetime import datetime
from typing import List, Optional
import logging
from zoneinfo import ZoneInfo
from fastapi.templating import Jinja2Templates

# Imports Core
from core.microsoft import MicrosoftAuth

logger = logging.getLogger("WorkflowCore")
templates = Jinja2Templates(directory="templates")

class WorkflowService:
    """
    Servicio Centralizado para gestion de flujo de trabajo y comunicaciones.
    Usado por: Simulacion, Comercial, Ingenieria, etc.
    """
    
    def __init__(self):
        self.ms_auth = MicrosoftAuth()

    async def add_comentario(
        self, 
        conn, 
        user_context: dict, 
        id_oportunidad: UUID, 
        comentario: str, 
        departamento_slug: str,
        modulo_origen: str
    ) -> dict:
        """
        1. Inserta comentario en BD.
        2. Determina destinatarios inteligentes.
        3. Envia notificacion por correo.
        
        Args:
            conn: Conexion a la base de datos
            user_context: Contexto del usuario actual
            id_oportunidad: UUID de la oportunidad
            comentario: Texto del comentario
            departamento_slug: Slug del departamento (ej: 'SIMULACION', 'COMERCIAL')
            modulo_origen: Modulo desde donde se crea (ej: 'simulacion', 'comercial')
            
        Returns:
            dict con datos del comentario creado
        """
        user_id = user_context.get("user_db_id")
        user_name = user_context.get("user_name", "Usuario Sistema")
        user_email = user_context.get("user_email") or user_context.get("email")
        
        # Validación: Si estamos aquí, el usuario DEBE estar autenticado y tener email
        if not user_email:
            logger.error(f"[COMENTARIO] Usuario sin email en contexto: {user_context}")
            raise HTTPException(
                status_code=500,
                detail="Error de sesión: no se pudo obtener el email del usuario. Por favor, cierre sesión y vuelva a iniciar."
            )
        
        logger.info(f"[COMENTARIO] Iniciando add_comentario para {id_oportunidad} por {user_name}")

        # 1. Insertar en BD
        new_id = uuid4()
        now_mx = datetime.now(ZoneInfo("America/Mexico_City"))
        
        query = """
            INSERT INTO tb_comentarios_workflow (
                id, id_oportunidad, usuario_id, usuario_nombre, usuario_email,
                comentario, departamento_origen, modulo_origen, fecha_comentario
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
        """
        
        logger.info(f"[COMENTARIO] Ejecutando INSERT con ID {new_id}")
        await conn.execute(
            query, 
            new_id, id_oportunidad, user_id, user_name, user_email,
            comentario, departamento_slug, modulo_origen, now_mx
        )
        logger.info(f"[COMENTARIO] INSERT exitoso para {new_id}")
        
        # 2. Notificacion Asincrona (Fire & Forget logic)
        try:
            await self._notificar_comentario(conn, id_oportunidad, comentario, user_context, departamento_slug)
        except Exception as e:
            logger.error(f"Fallo al enviar notificacion de comentario: {e}")
            # No bloqueamos el flujo si falla el correo
            
        return {
            "id": new_id,
            "usuario_nombre": user_name,
            "comentario": comentario,
            "fecha": now_mx,
            "departamento": departamento_slug
        }

    async def get_historial(
        self, 
        conn, 
        id_oportunidad: UUID, 
        limit: Optional[int] = None
    ) -> List[dict]:
        """
        Obtiene historial unificado de comentarios para el Muro.
        
        Args:
            conn: Conexion a la base de datos
            id_oportunidad: UUID de la oportunidad
            limit: Limite opcional de resultados
            
        Returns:
            Lista de diccionarios con comentarios ordenados por fecha (mas reciente primero)
        """
        query = """
            SELECT 
                id, usuario_nombre, usuario_email, comentario, 
                departamento_origen, modulo_origen, fecha_comentario
            FROM tb_comentarios_workflow
            WHERE id_oportunidad = $1
            ORDER BY fecha_comentario DESC
        """
        if limit:
            query += f" LIMIT {limit}"
            
        rows = await conn.fetch(query, id_oportunidad)
        return [dict(r) for r in rows]

    # --- LOGICA DE NOTIFICACION INTELIGENTE ---
    
    async def _notificar_comentario(
        self, 
        conn, 
        id_oportunidad: UUID, 
        comentario: str, 
        sender_ctx: dict, 
        depto: str
    ):
        """
        Calcula destinatarios y envia correo de notificacion.
        
        Logica:
        - TO: Notifica a la contraparte (si autor = solicitante -> avisa a responsable y viceversa)
        - CC: Correos configurados en tb_config_emails con trigger NUEVO_COMENTARIO
        - No se notifica a uno mismo
        """
        
        # A. Obtener datos de la oportunidad
        op = await conn.fetchrow("""
            SELECT 
                op_id_estandar, nombre_proyecto, cliente_nombre,
                creado_por_id, responsable_simulacion_id
            FROM tb_oportunidades 
            WHERE id_oportunidad = $1
        """, id_oportunidad)
        
        if not op:
            return

        # B. Obtener Emails de los Actores
        users_map = {}
        target_ids = {op['creado_por_id'], op['responsable_simulacion_id']}
        target_ids = {uid for uid in target_ids if uid}
        
        if target_ids:
            q_users = "SELECT id_usuario, email FROM tb_usuarios WHERE id_usuario = ANY($1::uuid[])"
            rows = await conn.fetch(q_users, list(target_ids))
            for r in rows:
                users_map[r['id_usuario']] = r['email']

        email_solicitante = users_map.get(op['creado_por_id'])
        email_responsable = users_map.get(op['responsable_simulacion_id'])
        
        # C. Definir TO (Destinatarios) - Notificar a la contraparte
        recipients = set()
        sender_id = sender_ctx.get("user_db_id")
        
        # Regla: Si yo soy el solicitante, aviso al responsable. Y viceversa.
        if email_responsable and str(sender_id) != str(op['responsable_simulacion_id']):
            recipients.add(email_responsable)
            
        if email_solicitante and str(sender_id) != str(op['creado_por_id']):
            recipients.add(email_solicitante)
            
        # D. Definir CC (Configuracion Admin - triggers)
        cc_list = set()
        triggers = await conn.fetch("""
            SELECT email_to_add 
            FROM tb_config_emails 
            WHERE (modulo = 'GLOBAL' OR modulo = $1) 
              AND trigger_field = 'NUEVO_COMENTARIO'
        """, depto.upper())
        
        for t in triggers:
            cc_list.add(t['email_to_add'])
            
        if not recipients:
            logger.info("No hay destinatarios para notificar (el usuario se comenta a si mismo sin contraparte).")
            return

        # E. Renderizar Template
        html_content = templates.get_template("shared/emails/workflow/new_comment.html").render({
            "op": op,
            "comentario": comentario,
            "autor": sender_ctx['user_name'],
            "departamento": depto
        })
        
        # F. Enviar via Graph
        subject = f"Nuevo Comentario: {op['op_id_estandar']} - {op['cliente_nombre']}"
        
        # TODO: Integrar con sistema de tokens actual
        # Por ahora, solo logging
        logger.info(f"[NOTIFICACION] Envio simulado a {recipients} CC {cc_list}")
        # Descomentar cuando se integre con tokens:
        # self.ms_auth.send_email_with_attachments(
        #     access_token=token,
        #     subject=subject,
        #     body=html_content,
        #     recipients=list(recipients),
        #     cc_recipients=list(cc_list)
        # )

def get_workflow_service():
    """Helper para inyeccion de dependencias."""
    return WorkflowService()
