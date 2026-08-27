VACACIONES_SLUGS = {"vacaciones", "extraordinaria"}

PERMISO_LLEGAR_TARDE_SLUG = "permiso_llegar_tarde"
PERMISO_SALIR_TEMPRANO_SLUG = "permiso_salir_temprano"

COMPENSATORIO_SLUG = "compensatorio"
# Entrada sintetica solo para display (dropdown de filtro en RRHH > Ausencias) -- NO es una
# fila de tb_cat_tipos_ausencia y no debe convertirse en una: ese catalogo alimenta el form
# de "Nueva solicitud de ausencia" (tipo_ausencia_id -> tb_solicitudes_ausencia), mientras que
# compensatorio vive en tb_he_solicitudes_compensatorio con su propio flujo de aprobacion y
# bolsa de minutos. Insertarlo como fila real lo haria seleccionable ahi sin que el resto del
# sistema sepa procesarlo. Por eso solo trae slug/nombre/abreviatura -- los unicos campos que
# consume el template (tipo.slug, tipo.abreviatura); no le agregues id/orden/etc. con valores
# inventados, un futuro tipo.id fantasma seria peor que la falta del campo.
TIPO_COMPENSATORIO = {"slug": COMPENSATORIO_SLUG, "nombre": "Compensatorio", "abreviatura": "COMP"}

ESTADOS_SOLICITUD = ("pendiente", "aprobado", "rechazado", "cancelado")
ROLES_FIRMA = ("solicitante", "aprobador")
TIPOS_FIRMA = ("subida", "dibujada")

ALERTA_DIAS_AMARILLO = 90
ALERTA_DIAS_ROJO = 30
