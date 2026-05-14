from typing import List


class EmailRulesDBService:
    """Queries SQL puras para reglas de correo."""

    async def get_event_rules(self, conn, modulo: str, evento: str) -> List[dict]:
        rows = await conn.fetch(
            """
            SELECT email_to_add, type
            FROM tb_config_emails
            WHERE modulo        IN ($1, 'GLOBAL')
              AND trigger_field = 'EVENTO'
              AND trigger_value = $2
            ORDER BY email_to_add
            """,
            modulo,
            evento,
        )
        return [dict(row) for row in rows]

    async def get_module_rules(self, conn, modulo: str) -> List[dict]:
        rows = await conn.fetch(
            "SELECT * FROM tb_config_emails WHERE modulo IN ($1, 'GLOBAL')",
            modulo,
        )
        return [dict(row) for row in rows]


def get_email_rules_db_service() -> EmailRulesDBService:
    return EmailRulesDBService()
