# core/email_rules.py
"""
Servicio centralizado para resolución de reglas de correo electrónico.
Cualquier módulo puede usar este servicio para obtener emails TO/CC/CCO
basados en reglas configuradas en tb_config_emails (Admin Dashboard).

Siempre incluye las reglas GLOBAL + las del módulo específico.
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger("Core.EmailRules")


class EmailRulesService:
    """
    Servicio compartido para evaluar reglas de correo.

    Uso:
        from core.email_rules import EmailRulesService

        rules_svc = EmailRulesService()

        # Evento del sistema (ej: EXTRAORDINARIA, SOLICITUD_VIATICOS)
        emails = await rules_svc.get_emails_by_event(conn, 'COMERCIAL', 'EXTRAORDINARIA')
        # -> {"to": ["a@x.com"], "cc": ["b@x.com"], "cco": []}

        # Matching por campos de un registro
        emails = await rules_svc.get_emails_by_record(conn, 'COMERCIAL', record_dict)
        # -> {"to": ["a@x.com"], "cc": ["b@x.com"]}
    """

    # Mapeo de nombre legible (trigger_field en BD) -> columna real en el registro
    FIELD_MAPPING = {
        "Tecnología": "id_tecnologia",
        "Tipo Solicitud": "id_tipo_solicitud",
        "Estatus": "id_estatus_global",
        "Cliente": "cliente_nombre",
    }

    async def get_emails_by_event(
        self, conn, modulo: str, evento: str
    ) -> Dict[str, List[str]]:
        """
        Retorna emails TO/CC/CCO para un evento del sistema.

        Args:
            conn: Conexión a la base de datos.
            modulo: Módulo que invoca (ej: 'COMERCIAL', 'LEVANTAMIENTOS').
            evento: Valor del evento (ej: 'EXTRAORDINARIA', 'SOLICITUD_VIATICOS').

        Returns:
            Dict con claves 'to', 'cc', 'cco', cada una con lista de emails.
        """
        rows = await conn.fetch("""
            SELECT email_to_add, type
            FROM tb_config_emails
            WHERE modulo        IN ($1, 'GLOBAL')
              AND trigger_field = 'EVENTO'
              AND trigger_value = $2
            ORDER BY email_to_add
        """, modulo, evento)

        result = {"to": [], "cc": [], "cco": []}
        for r in rows:
            email = r['email_to_add']
            tipo = r['type'].upper()
            if tipo == 'TO' and email not in result['to']:
                result['to'].append(email)
            elif tipo == 'CC' and email not in result['cc']:
                result['cc'].append(email)
            elif tipo == 'CCO' and email not in result['cco']:
                result['cco'].append(email)

        logger.debug(
            f"Reglas evento '{evento}' para {modulo}: "
            f"TO={len(result['to'])}, CC={len(result['cc'])}, CCO={len(result['cco'])}"
        )

        return result

    async def get_emails_by_record(
        self, conn, modulo: str, record: dict
    ) -> Dict[str, List[str]]:
        """
        Evalúa reglas contra los campos de un registro y retorna emails que aplican.

        Lógica de matching:
        - 'Cliente': búsqueda parcial (CONTAINS), case-insensitive.
        - Otros campos: comparación exacta (id como string).

        Args:
            conn: Conexión a la base de datos.
            modulo: Módulo que invoca (ej: 'COMERCIAL').
            record: Dict con los datos del registro (ej: fila de tb_oportunidades).

        Returns:
            Dict con claves 'to' y 'cc', cada una con lista de emails que aplican.
        """
        rules = await conn.fetch(
            "SELECT * FROM tb_config_emails WHERE modulo IN ($1, 'GLOBAL')",
            modulo
        )

        result = {"to": [], "cc": []}

        for rule in rules:
            field = rule['trigger_field']

            # Ignorar reglas de tipo EVENTO (se resuelven con get_emails_by_event)
            if field == 'EVENTO':
                continue

            val_trigger = str(rule['trigger_value']).strip().upper()
            db_key = self.FIELD_MAPPING.get(field, field)
            val_actual = record.get(db_key)

            match = False
            if field == "Cliente":
                # Búsqueda parcial, case-insensitive
                if val_trigger in str(val_actual or "").upper():
                    match = True
            else:
                # Comparación exacta (id como string)
                if str(val_actual or "").strip().upper() == val_trigger:
                    match = True

            if match:
                email = rule['email_to_add']
                tipo = rule['type'].upper()
                if tipo == 'TO' and email not in result['to']:
                    result['to'].append(email)
                elif tipo != 'TO' and email not in result['cc']:
                    result['cc'].append(email)

                logger.debug(
                    f"Regla match [{rule.get('id')}]: {field}='{val_trigger}' "
                    f"-> {email} ({tipo})"
                )

        logger.debug(
            f"Reglas record para {modulo}: "
            f"TO={len(result['to'])}, CC={len(result['cc'])}"
        )

        return result


def get_email_rules_service() -> EmailRulesService:
    """Helper para inyección de dependencias."""
    return EmailRulesService()
