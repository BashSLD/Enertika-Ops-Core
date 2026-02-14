import logging
import json
from uuid import UUID
from typing import List, Optional
from fastapi.templating import Jinja2Templates

logger = logging.getLogger("ComercialServices")

class NotificationService:
    """
    Sub-servicio encargado de la gestión de correos y notificaciones.
    """

    def __init__(self):
        self.templates = Jinja2Templates(directory="templates")

    def _is_multisite_heuristic(self, row: dict) -> bool:
        """Determina si es multisitio incluso si queda 1 solo sitio (Ported from ComercialService)."""
        if (row.get('cantidad_sitios') or 0) > 1:
            return True
        try:
            proj = (row.get('nombre_proyecto') or "").strip().upper()
            id_int = (row.get('id_interno_simulacion') or "").strip().upper()
            if proj and id_int and id_int.endswith(f"_{proj}"):
                return True
        except: pass
        return False

    async def get_oportunidad_for_email(self, conn, id_oportunidad: UUID) -> Optional[dict]:
        """Recupera datos básicos de oportunidad."""
        row = await conn.fetchrow("SELECT * FROM tb_oportunidades WHERE id_oportunidad = $1", id_oportunidad)
        return dict(row) if row else None

    async def update_email_status(self, conn, id_oportunidad: UUID):
        """Marca email como enviado."""
        await conn.execute("UPDATE tb_oportunidades SET email_enviado = TRUE WHERE id_oportunidad = $1", id_oportunidad)

    async def get_parent_titulo(self, conn, parent_id: UUID) -> Optional[str]:
        return await conn.fetchval("SELECT titulo_proyecto FROM tb_oportunidades WHERE id_oportunidad = $1", parent_id)

    async def get_email_threading_context(self, conn, row: dict, legacy_search_term: Optional[str] = None) -> dict:
        """Determina contexto de hilo de correo."""
        search_key = None
        modo = "NUEVO"
        log = f"ENVÍO INICIAL para '{row.get('op_id_estandar')}'"
        
        if legacy_search_term:
            search_key = legacy_search_term
            modo = "HOMOLOGACIÓN"
            log = f"MODO HOMOLOGACIÓN: '{search_key}'"
        elif row.get('parent_id'):
            search_key = await self.get_parent_titulo(conn, row['parent_id'])
            modo = "SEGUIMIENTO"
            log = f"SEGUIMIENTO: '{search_key}'"
            
        return {"search_key": search_key, "modo": modo, "log_message": log}

    async def get_data_for_email_form(self, conn, id_oportunidad: UUID) -> dict:
        """Prepara datos para UI de envío de correos, incluyendo reglas/triggers."""
        row = await conn.fetchrow("""
            SELECT o.*, 
                tec.nombre as tipo_tecnologia,
                tipo_sol.nombre as tipo_solicitud,
                tipo_sol.es_seguimiento,
                db.uso_sistema_json,
                db.cargas_criticas_kw,
                db.tiene_motores,
                db.potencia_motor_hp,
                db.tiempo_autonomia,
                db.voltaje_operacion,
                db.cargas_separadas,
                db.tiene_planta_emergencia
            FROM tb_oportunidades o
            LEFT JOIN tb_cat_tecnologias tec ON o.id_tecnologia = tec.id
            LEFT JOIN tb_cat_tipos_solicitud tipo_sol ON o.id_tipo_solicitud = tipo_sol.id
            LEFT JOIN tb_detalles_bess db ON o.id_oportunidad = db.id_oportunidad
            WHERE o.id_oportunidad = $1
        """, id_oportunidad)
        
        if not row: return None

        sitios_rows = await conn.fetch("SELECT * FROM tb_sitios_oportunidad WHERE id_oportunidad = $1 ORDER BY nombre_sitio", id_oportunidad)
        
        # Defaults
        defaults = await conn.fetchrow("SELECT * FROM tb_email_defaults WHERE id = 1")
        def_to = (defaults['default_to'] or "").replace(";", ",").split(",") if defaults else []
        def_cc = (defaults['default_cc'] or "").replace(";", ",").split(",") if defaults else []
        
        fixed_to = [d.strip() for d in def_to if d.strip()] 
        fixed_cc = [d.strip() for d in def_cc if d.strip()]

        # Reglas
        rules = await conn.fetch("SELECT * FROM tb_config_emails WHERE modulo = 'COMERCIAL'")
        FIELD_MAPPING = {
            "Tecnología": "id_tecnologia",
            "Tipo Solicitud": "id_tipo_solicitud",
            "Estatus": "id_estatus_global",
            "Cliente": "cliente_nombre"
        }

        for rule in rules:
            field = rule['trigger_field']
            val_trigger = str(rule['trigger_value']).strip().upper()
            db_key = FIELD_MAPPING.get(field, field)
            val_actual = row.get(db_key)
            
            match = False
            if field == "Cliente":
                if val_trigger in str(val_actual or "").upper(): match = True
            else:
                if str(val_actual or "") == val_trigger: match = True
            
            if match:
                email = rule['email_to_add']
                if rule['type'] == 'TO':
                    if email not in fixed_to: fixed_to.append(email)
                else:
                    if email not in fixed_cc: fixed_cc.append(email)

        # BESS Objetivos
        bess_str = ""
        if row.get('uso_sistema_json'):
            try:
                raw = row['uso_sistema_json']
                loaded = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(loaded, list): bess_str = ", ".join(loaded)
            except Exception as e:
                logger.warning(f"Error parseando uso_sistema_json: {e}")

        return {
            "op": dict(row),
            "sitios": [dict(s) for s in sitios_rows],
            "fixed_to": fixed_to,
            "fixed_cc": fixed_cc,
            "bess_objetivos_str": bess_str,
            "has_multisitio_file": self._is_multisite_heuristic(dict(row)),
            "editable": row.get('es_seguimiento', False) and self._is_multisite_heuristic(dict(row)),
            "is_followup": row.get('es_seguimiento', False)
        }

    async def get_email_recipients_context(self, conn, recipients_str: str, fixed_to: List[str], fixed_cc: List[str], extra_cc: str) -> dict:
        """Consolida TO, CC, BCC usando defaults."""
        final_to = set([e.strip() for e in recipients_str.replace(",", ";").split(";") if e.strip()])
        final_to.update([e.strip() for e in fixed_to if e.strip()])
        
        final_cc = set([e.strip() for e in fixed_cc if e.strip()])
        final_cc.update([e.strip() for e in extra_cc.replace(",", ";").split(";") if e.strip()])
        
        final_bcc = set()
        defaults = await conn.fetchrow("SELECT default_cco FROM tb_email_defaults WHERE id = 1")
        if defaults and defaults['default_cco']:
             final_bcc.update([e.strip() for e in defaults['default_cco'].replace(",", ";").split(";") if e.strip()])
             
        return {"to": list(final_to), "cc": list(final_cc), "bcc": list(final_bcc)}

    async def enviar_notificacion_extraordinaria(self, conn, ms_auth, token: str, id_oportunidad: UUID, base_url: str, user_email: str):
        """Envía notificación extraordinaria."""
        EVENTO_EXTRAORDINARIA = "EXTRAORDINARIA"
        reglas = await conn.fetch("""
            SELECT email_to_add, type FROM tb_config_emails 
            WHERE modulo = 'COMERCIAL' AND trigger_field = 'EVENTO' AND trigger_value = $1
        """, EVENTO_EXTRAORDINARIA)
        
        if not reglas: return

        op_data = await conn.fetchrow("""
            SELECT o.op_id_estandar, o.cliente_nombre, o.solicitado_por,
                   to_char(o.fecha_solicitud AT TIME ZONE 'UTC' AT TIME ZONE 'America/Mexico_City', 'DD/MM/YYYY HH24:MI') as fecha_solicitud
            FROM tb_oportunidades o WHERE o.id_oportunidad = $1
        """, id_oportunidad)
        
        if not op_data: return

        recipients = [r['email_to_add'] for r in reglas if r['type'] == 'TO']
        cc_list = [r['email_to_add'] for r in reglas if r['type'] == 'CC']
        
        template = self.templates.get_template("comercial/emails/notification_extraordinaria.html")
        html_body = template.render({"op": op_data, "dashboard_url": f"{base_url}/comercial/ui"})

        subject = f"Nueva Solicitud Extraordinaria: {op_data['op_id_estandar']} - {op_data['cliente_nombre']}"
        await ms_auth.send_email_with_attachments(
            access_token=token, from_email=user_email, subject=subject,
            body=html_body, recipients=recipients, cc_recipients=cc_list, importance="high"
        )
        logger.info(f"Notificación extraordinaria enviada: {op_data['op_id_estandar']}")
