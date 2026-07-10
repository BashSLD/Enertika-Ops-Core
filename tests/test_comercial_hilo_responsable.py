from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from core.workflow.service import WorkflowService
from modules.comercial.db_service import (
    QUERY_GET_HILO_EMAIL_ANCHOR,
    QUERY_GET_TECNOLOGIA_NAME,
    QUERY_GET_ULTIMO_MOVIMIENTO_HILO,
    QUERY_INSERT_FOLLOWUP,
    QUERY_UPDATE_FECHA_ENVIO_EMAIL,
)
from modules.comercial.service import ComercialService
from modules.comercial.services.notification_service import NotificationService


pytestmark = pytest.mark.asyncio


def _parent_row(**overrides):
    data = {
        "parent_id": None,
        "responsable_comercial_id": None,
        "creado_por_id": uuid4(),
        "titulo_proyecto": "LEVANTAMIENTO_CLIENTE_PROYECTO_FV_CANAL",
        "nombre_proyecto": "Proyecto",
        "cliente_nombre": "CLIENTE",
        "cliente_id": uuid4(),
        "canal_venta": "CANAL",
        "id_tecnologia": 1,
        "cantidad_sitios": 1,
        "direccion_obra": "Direccion",
        "coordenadas_gps": None,
        "google_maps_link": None,
        "sharepoint_folder_url": None,
        "id_interno_simulacion": "OP - TEST_CLIENTE",
        "es_licitacion": False,
    }
    data.update(overrides)
    return data


async def test_create_followup_inherits_clicked_parent_owner_and_thread_key():
    root_id = uuid4()
    clicked_id = uuid4()
    clicked_owner_id = uuid4()
    creator_id = uuid4()
    fixed_now = datetime(2026, 7, 9, 12, 0, tzinfo=ZoneInfo("America/Mexico_City"))

    clicked_parent = _parent_row(
        parent_id=root_id,
        responsable_comercial_id=clicked_owner_id,
        creado_por_id=creator_id,
        titulo_proyecto="OFERTA FINAL_CLIENTE_PROYECTO_FV_CANAL",
    )
    root_parent = _parent_row(
        parent_id=None,
        responsable_comercial_id=None,
        creado_por_id=creator_id,
        titulo_proyecto="LEVANTAMIENTO_CLIENTE_PROYECTO_FV_CANAL",
    )

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[clicked_parent, root_parent])
    conn.fetchval = AsyncMock(side_effect=[7, "Actualizacion", "FV", None])
    conn.execute = AsyncMock()

    service = ComercialService()
    service.get_current_datetime_mx = AsyncMock(return_value=fixed_now)
    service.calcular_fuera_de_horario = AsyncMock(return_value=False)
    service.calcular_deadline_inicial = AsyncMock(return_value=fixed_now + timedelta(days=1))
    service.get_catalog_ids = AsyncMock(return_value={"estatus": {"pendiente": 10}})

    new_id = await service.create_followup_oportunidad(
        clicked_id,
        "ACTUALIZACION",
        "high",
        conn,
        creator_id,
        "Usuario Test",
    )

    insert_call = next(
        call for call in conn.fetchval.await_args_list if call.args[0] == QUERY_INSERT_FOLLOWUP
    )
    assert insert_call.args[1] == new_id
    assert insert_call.args[3] == root_id
    assert insert_call.args[-2] == clicked_owner_id
    assert insert_call.args[-1] == "OFERTA FINAL_CLIENTE_PROYECTO_FV_CANAL"


async def test_create_followup_transforms_tecnologia_when_provided():
    """Un seguimiento de Actualización puede nacer con una tecnología distinta a la del padre
    (ej. FV -> BESS). El título del hilo de correo debe reflejar la tecnología NUEVA."""
    parent_id = uuid4()
    creator_id = uuid4()
    fixed_now = datetime(2026, 7, 9, 12, 0, tzinfo=ZoneInfo("America/Mexico_City"))

    parent = _parent_row(
        parent_id=None,
        responsable_comercial_id=None,
        creado_por_id=creator_id,
        titulo_proyecto="LEVANTAMIENTO_CLIENTE_PROYECTO_FV_CANAL",
        id_tecnologia=1,  # FV
    )

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=parent)
    conn.fetchval = AsyncMock(side_effect=[7, "Actualizacion", "BESS", None])
    conn.execute = AsyncMock()

    service = ComercialService()
    service.get_current_datetime_mx = AsyncMock(return_value=fixed_now)
    service.calcular_fuera_de_horario = AsyncMock(return_value=False)
    service.calcular_deadline_inicial = AsyncMock(return_value=fixed_now + timedelta(days=1))
    service.get_catalog_ids = AsyncMock(return_value={"estatus": {"pendiente": 10}})

    await service.create_followup_oportunidad(
        parent_id,
        "ACTUALIZACION",
        "high",
        conn,
        creator_id,
        "Usuario Test",
        id_tecnologia=2,  # BESS: transformación explícita, distinta a la del padre (FV)
    )

    tecnologia_name_call = next(
        call for call in conn.fetchval.await_args_list if call.args[0] == QUERY_GET_TECNOLOGIA_NAME
    )
    assert tecnologia_name_call.args[1] == 2

    insert_call = next(
        call for call in conn.fetchval.await_args_list if call.args[0] == QUERY_INSERT_FOLLOWUP
    )
    assert insert_call.args[10] == 2
    assert "BESS" in insert_call.args[4]


async def test_create_followup_inherits_tecnologia_when_not_provided():
    """Sin id_tecnologia explícito (flujo multisitio directo, Oferta Final, Levantamiento),
    el seguimiento sigue heredando la tecnología del padre, sin cambio de comportamiento."""
    parent_id = uuid4()
    creator_id = uuid4()
    fixed_now = datetime(2026, 7, 9, 12, 0, tzinfo=ZoneInfo("America/Mexico_City"))

    parent = _parent_row(
        parent_id=None,
        responsable_comercial_id=None,
        creado_por_id=creator_id,
        titulo_proyecto="LEVANTAMIENTO_CLIENTE_PROYECTO_FV_CANAL",
        id_tecnologia=1,  # FV
    )

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=parent)
    conn.fetchval = AsyncMock(side_effect=[7, "Actualizacion", "FV", None])
    conn.execute = AsyncMock()

    service = ComercialService()
    service.get_current_datetime_mx = AsyncMock(return_value=fixed_now)
    service.calcular_fuera_de_horario = AsyncMock(return_value=False)
    service.calcular_deadline_inicial = AsyncMock(return_value=fixed_now + timedelta(days=1))
    service.get_catalog_ids = AsyncMock(return_value={"estatus": {"pendiente": 10}})

    await service.create_followup_oportunidad(
        parent_id,
        "ACTUALIZACION",
        "high",
        conn,
        creator_id,
        "Usuario Test",
    )

    insert_call = next(
        call for call in conn.fetchval.await_args_list if call.args[0] == QUERY_INSERT_FOLLOWUP
    )
    assert insert_call.args[10] == 1


async def test_threading_context_keeps_legacy_term_precedence():
    service = NotificationService()
    conn = AsyncMock()
    row = {
        "op_id_estandar": "OP - TEST",
        "parent_id": uuid4(),
        "hilo_search_key": "OFERTA FINAL_CLIENTE_PROYECTO_FV_CANAL",
    }

    context = await service.get_email_threading_context(
        conn,
        row,
        legacy_search_term="TERMINO LEGACY",
    )

    assert context["search_key"] == "TERMINO LEGACY"
    conn.fetchval.assert_not_awaited()


async def test_threading_context_uses_persisted_hilo_search_key_before_parent():
    service = NotificationService()
    conn = AsyncMock()
    row = {
        "op_id_estandar": "OP - TEST",
        "parent_id": uuid4(),
        "hilo_search_key": "OFERTA FINAL_CLIENTE_PROYECTO_FV_CANAL",
    }

    context = await service.get_email_threading_context(conn, row)

    assert context["search_key"] == "OFERTA FINAL_CLIENTE_PROYECTO_FV_CANAL"
    conn.fetchval.assert_not_awaited()


async def test_threading_context_falls_back_to_parent_title_without_hilo_key():
    service = NotificationService()
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value="LEVANTAMIENTO_CLIENTE_PROYECTO_FV_CANAL")
    parent_id = uuid4()
    row = {"op_id_estandar": "OP - TEST", "parent_id": parent_id}

    context = await service.get_email_threading_context(conn, row)

    assert context["search_key"] == "LEVANTAMIENTO_CLIENTE_PROYECTO_FV_CANAL"
    conn.fetchval.assert_awaited_once()


async def test_extraordinary_notification_sets_send_date_only_when_email_was_sent():
    class FakeNotificationService:
        async def enviar_notificacion_extraordinaria(self, *_args, **_kwargs):
            return True

    fixed_now = datetime(2026, 7, 9, 13, 30, tzinfo=ZoneInfo("America/Mexico_City"))
    conn = AsyncMock()
    conn.execute = AsyncMock()
    op_id = uuid4()
    service = ComercialService(notification_service=FakeNotificationService())
    service.get_current_datetime_mx = AsyncMock(return_value=fixed_now)

    sent = await service.enviar_notificacion_extraordinaria(
        conn,
        ms_auth=object(),
        token="token",
        id_oportunidad=op_id,
        base_url="https://app.test",
        user_email="user@test.com",
    )

    assert sent is True
    conn.execute.assert_awaited_once_with(QUERY_UPDATE_FECHA_ENVIO_EMAIL, op_id, fixed_now)


async def test_extraordinary_notification_does_not_set_send_date_when_email_fails():
    class FakeNotificationService:
        async def enviar_notificacion_extraordinaria(self, *_args, **_kwargs):
            return False

    conn = AsyncMock()
    conn.execute = AsyncMock()
    service = ComercialService(notification_service=FakeNotificationService())

    sent = await service.enviar_notificacion_extraordinaria(
        conn,
        ms_auth=object(),
        token="token",
        id_oportunidad=uuid4(),
        base_url="https://app.test",
        user_email="user@test.com",
    )

    assert sent is False
    conn.execute.assert_not_awaited()


async def test_workflow_detail_context_includes_responsibility_history():
    historial = [{"tipo_evento": "creacion", "op_id_estandar": "OP - TEST"}]
    user_id = uuid4()

    class FakeWorkflowDB:
        async def get_detalle_oportunidad(self, _conn, _id_oportunidad):
            return {
                "id_oportunidad": _id_oportunidad,
                "creado_por_id": user_id,
                "responsable_comercial_id": None,
                "status_global": "En Proceso",
                "cantidad_sitios": 1,
                "notificacion_ganada_at": None,
            }

        async def get_sitios_ganados_detalle(self, _conn, _id_oportunidad):
            return []

        async def get_sitios_oportunidad(self, _conn, _id_oportunidad):
            return []

        async def get_historial_responsables(self, _conn, _id_oportunidad):
            return historial

    service = WorkflowService(db=FakeWorkflowDB())
    context = await service.build_detalle_oportunidad_context(
        conn=AsyncMock(),
        id_oportunidad=uuid4(),
        source_module="comercial",
        user_context={
            "user_db_id": user_id,
            "role": "USER",
            "module_roles": {"comercial": "viewer"},
        },
    )

    assert context["historial_responsables"] == historial


async def test_workflow_detail_context_forces_read_only_flags_when_requested():
    user_id = uuid4()
    owner_id = uuid4()

    class FakeWorkflowDB:
        async def get_detalle_oportunidad(self, _conn, _id_oportunidad):
            return {
                "id_oportunidad": _id_oportunidad,
                "creado_por_id": owner_id,
                "responsable_comercial_id": owner_id,
                "status_global": "Entregado",
                "cantidad_sitios": 1,
                "notificacion_ganada_at": None,
            }

        async def get_sitios_ganados_detalle(self, _conn, _id_oportunidad):
            return []

        async def get_sitios_oportunidad(self, _conn, _id_oportunidad):
            return []

        async def get_historial_responsables(self, _conn, _id_oportunidad):
            return []

    service = WorkflowService(db=FakeWorkflowDB())
    context = await service.build_detalle_oportunidad_context(
        conn=AsyncMock(),
        id_oportunidad=uuid4(),
        source_module="simulacion",
        user_context={
            "user_db_id": owner_id,
            "role": "ADMIN",
            "module_roles": {"comercial": "admin"},
        },
        read_only=True,
    )

    assert context["can_edit_comercial"] is False
    assert context["can_close_sale"] is False
    assert context["can_reassign"] is False


async def test_prepare_transfer_preview_warns_when_new_owner_has_no_email():
    service = ComercialService()
    service.validar_transferencia_comercial = AsyncMock(return_value={
        "nuevo": {"nombre": "Nuevo", "email": None},
        "anterior": {"nombre": "Anterior", "email": "anterior@test.com"},
    })
    service.get_hilo_email_anchor = AsyncMock()

    ms_auth = AsyncMock()

    result = await service.preparar_transferencia_email_preview(
        conn=AsyncMock(),
        ms_auth=ms_auth,
        access_token="token",
        user_email="manager@test.com",
        id_oportunidad=uuid4(),
        new_owner_id=uuid4(),
        motivo=None,
        user_context={"user_db_id": uuid4(), "role": "MANAGER", "module_roles": {"comercial": "editor"}},
    )

    assert result["requires_preview"] is False
    assert result["notice_type"] == "warning"
    service.get_hilo_email_anchor.assert_not_awaited()
    ms_auth.find_thread_candidates.assert_not_awaited()


async def test_ultimo_movimiento_hilo_orders_by_real_email_send_date():
    assert "COALESCE(o.fecha_envio_email, o.fecha_creacion) DESC" in QUERY_GET_ULTIMO_MOVIMIENTO_HILO


async def test_hilo_email_anchor_uses_real_send_date_without_excluding_current_op():
    assert "COALESCE(o.fecha_envio_email, o.fecha_creacion) DESC" in QUERY_GET_HILO_EMAIL_ANCHOR
    assert "o.id_oportunidad <> $1" not in QUERY_GET_HILO_EMAIL_ANCHOR


async def test_ultimo_movimiento_hilo_and_anchor_share_the_same_query():
    assert QUERY_GET_ULTIMO_MOVIMIENTO_HILO is QUERY_GET_HILO_EMAIL_ANCHOR


async def test_prepare_transfer_preview_skips_email_when_no_anchor():
    service = ComercialService()
    service.validar_transferencia_comercial = AsyncMock(return_value={
        "nuevo": {"nombre": "Nuevo", "email": "nuevo@test.com"},
        "anterior": {"nombre": "Anterior", "email": "anterior@test.com"},
    })
    service.get_hilo_email_anchor = AsyncMock(return_value=None)

    ms_auth = AsyncMock()

    result = await service.preparar_transferencia_email_preview(
        conn=AsyncMock(),
        ms_auth=ms_auth,
        access_token="token",
        user_email="manager@test.com",
        id_oportunidad=uuid4(),
        new_owner_id=uuid4(),
        motivo=None,
        user_context={"user_db_id": uuid4(), "role": "MANAGER", "module_roles": {"comercial": "editor"}},
    )

    assert result["requires_preview"] is False
    assert result["notice_type"] == "warning"
    ms_auth.find_thread_candidates.assert_not_awaited()


async def test_prepare_transfer_preview_transfers_directly_when_new_owner_already_in_cc():
    service = ComercialService()
    service.validar_transferencia_comercial = AsyncMock(return_value={
        "nuevo": {"nombre": "Nuevo", "email": "nuevo@test.com"},
        "anterior": {"nombre": "Anterior", "email": "anterior@test.com"},
    })
    service.get_hilo_email_anchor = AsyncMock(return_value={
        "op_id_estandar": "OP - TEST",
        "titulo_proyecto": "OFERTA FINAL_CLIENTE_PROYECTO_FV_CANAL",
    })

    ms_auth = AsyncMock()
    ms_auth.find_thread_candidates = AsyncMock(return_value=["thread-1"])
    ms_auth.get_message_recipients = AsyncMock(return_value={
        "to": ["cliente@test.com"],
        "cc": ["nuevo@test.com"],
    })
    ms_auth.create_draft_reply = AsyncMock()

    result = await service.preparar_transferencia_email_preview(
        conn=AsyncMock(),
        ms_auth=ms_auth,
        access_token="token",
        user_email="manager@test.com",
        id_oportunidad=uuid4(),
        new_owner_id=uuid4(),
        motivo=None,
        user_context={"user_db_id": uuid4(), "role": "MANAGER", "module_roles": {"comercial": "editor"}},
    )

    assert result["requires_preview"] is False
    assert result["notice_type"] == "success"
    ms_auth.create_draft_reply.assert_not_awaited()


async def test_prepare_transfer_preview_creates_draft_when_owner_is_not_in_thread():
    service = ComercialService()
    service.validar_transferencia_comercial = AsyncMock(return_value={
        "nuevo": {"nombre": "Nuevo", "email": "nuevo@test.com"},
        "anterior": {"nombre": "Anterior", "email": "anterior@test.com"},
    })
    service.get_hilo_email_anchor = AsyncMock(return_value={
        "op_id_estandar": "OP - TEST",
        "titulo_proyecto": "OFERTA FINAL_CLIENTE_PROYECTO_FV_CANAL",
    })

    ms_auth = AsyncMock()
    ms_auth.find_thread_candidates = AsyncMock(return_value=["thread-1"])
    ms_auth.get_message_recipients = AsyncMock(return_value={
        "to": ["cliente@test.com"],
        "cc": ["anterior@test.com"],
    })
    ms_auth.create_draft_reply = AsyncMock(return_value=(
        True,
        {
            "draft_id": "draft-1",
            "subject": "Re: OFERTA FINAL_CLIENTE_PROYECTO_FV_CANAL",
            "body_text": "Body",
            "to": ["cliente@test.com"],
            "cc": ["anterior@test.com", "nuevo@test.com"],
        },
        "Borrador creado",
    ))

    result = await service.preparar_transferencia_email_preview(
        conn=AsyncMock(),
        ms_auth=ms_auth,
        access_token="token",
        user_email="manager@test.com",
        id_oportunidad=uuid4(),
        new_owner_id=uuid4(),
        motivo="Seguimiento lead",
        user_context={"user_db_id": uuid4(), "role": "MANAGER", "module_roles": {"comercial": "editor"}},
    )

    assert result["requires_preview"] is True
    assert result["draft"]["draft_id"] == "draft-1"
    draft_call = ms_auth.create_draft_reply.await_args
    assert draft_call.kwargs["thread_id"] == "thread-1"
    assert draft_call.kwargs["additional_cc"] == ["nuevo@test.com"]
