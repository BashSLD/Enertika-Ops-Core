"""Constantes del dominio compartido de proveedores."""

ESTATUS_DOC_SIN_DOCS = "sin_docs"
ESTATUS_DOC_VENCIDO = "vencido"
ESTATUS_DOC_PROXIMO = "proximo"
ESTATUS_DOC_VIGENTE = "vigente"

DIAS_PROXIMO_VENCIMIENTO = 7

ZIP_CATEGORIA_DEFAULT = "Otros"

DOCUMENTO_CATEGORIAS = {
    "constancia_fiscal": "Fiscal",
    "opinion_cumplimiento": "Fiscal",
    "acta_constitutiva": "Legal",
    "poderes_representante": "Legal",
    "ine_representante": "Identificacion",
    "ine": "Identificacion",
    "comprobante_domicilio": "Domicilio",
    "numero_localizacion": "Localizacion",
    "otro": ZIP_CATEGORIA_DEFAULT,
    "documento_adicional": ZIP_CATEGORIA_DEFAULT,
}

SHAREPOINT_PROVEEDORES_ROOT = "Proveedores"

SHAREPOINT_CARPETAS_POR_CATEGORIA = {
    "Fiscal": "01_Fiscal",
    "Legal": "02_Legal",
    "Identificacion": "03_Identificacion",
    "Domicilio": "04_Domicilio",
    "Localizacion": "05_Localizacion",
    ZIP_CATEGORIA_DEFAULT: "99_Otros",
}
