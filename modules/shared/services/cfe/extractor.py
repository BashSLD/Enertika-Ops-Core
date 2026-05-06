from __future__ import annotations

import logging

import defusedxml.ElementTree as ET

from .schemas import CfeReceipt


logger = logging.getLogger("SharedCfeExtractor")

MAX_XML_SIZE_BYTES = 10 * 1024 * 1024

TARIFA_CODES = {
    "ES1": "Suministro",
    "ED1": "Distribución",
    "ETB": "Transmisión",
    "ECB": "CENACE",
    "EGB": "Generación B",
    "EGI": "Generación I",
    "EGP": "Generación P",
    "EID": "Capacidad",
    "EMB": "SCnMEM(1)",
    "ECS": "CENACE Sub-Categoria",
    "CAP": "Capacidad Adicional",
}

TARIFAS_RECONOCIDAS = {"GDMTH"}

MESES = [
    "ENE", "FEB", "MAR", "ABR", "MAY", "JUN",
    "JUL", "AGO", "SEP", "OCT", "NOV", "DIC",
]

MESES_FORMATO = {
    "ENE": "Ene",
    "FEB": "Feb",
    "MAR": "Mar",
    "ABR": "Abr",
    "MAY": "May",
    "JUN": "Jun",
    "JUL": "Jul",
    "AGO": "Ago",
    "SEP": "Sep",
    "OCT": "Oct",
    "NOV": "Nov",
    "DIC": "Dic",
}


def validar_xml_cfe(content: bytes, filename: str) -> None:
    if len(content) > MAX_XML_SIZE_BYTES:
        raise ValueError(
            f"Archivo {filename} excede el límite de {MAX_XML_SIZE_BYTES // (1024 * 1024)} MB"
        )
    if len(content) < 100:
        raise ValueError(f"Archivo {filename} es demasiado pequeño")

    header = content[:500].decode("utf-8", errors="ignore").lower()
    if "comprobante" not in header and "cfdi" not in header:
        raise ValueError(f"Archivo {filename} no parece ser un XML CFDI válido")


def find_reg_fact(root: ET.Element) -> ET.Element | None:
    for child in root.iter():
        if "clsRegArchFact" in child.tag:
            return child
    return None


def text_of(element: ET.Element, tag_name: str) -> str:
    el = element.find(tag_name)
    if el is not None and el.text:
        return el.text.strip()
    return ""


def extraer_datos_xml(content: bytes, filename: str) -> CfeReceipt:
    validar_xml_cfe(content, filename)

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"XML mal formado en {filename}: {exc}") from exc

    reg = find_reg_fact(root)
    if reg is None:
        raise ValueError(f"No se encontró clsRegArchFact en {filename}")

    cfdi_ns = "http://www.sat.gob.mx/cfd/4"
    tarifa = text_of(reg, "TARIFA_REG")
    tipo_tarifa = text_of(reg, "TARIFA")
    tarifa_reconocida = tarifa in TARIFAS_RECONOCIDAS

    emisor = root.find(f"{{{cfdi_ns}}}Emisor")
    receptor = root.find(f"{{{cfdi_ns}}}Receptor")
    conceptos_cfdi = root.findall(f"{{{cfdi_ns}}}Conceptos/{{{cfdi_ns}}}Concepto")

    imp_root = root.find(f"{{{cfdi_ns}}}Impuestos")
    if imp_root is None or not imp_root.attrib.get("TotalImpuestosTrasladados"):
        for imp in root.findall(f".//{{{cfdi_ns}}}Impuestos"):
            if imp.attrib.get("TotalImpuestosTrasladados"):
                imp_root = imp
                break

    datos: CfeReceipt = {
        "archivo": filename,
        "cfdi": {
            "folio": root.attrib.get("Folio", ""),
            "serie": root.attrib.get("Serie", ""),
            "fecha_emision": root.attrib.get("Fecha", ""),
            "subtotal": float(root.attrib.get("SubTotal", 0)),
            "total": float(root.attrib.get("Total", 0)),
            "moneda": root.attrib.get("Moneda", ""),
            "metodo_pago": root.attrib.get("MetodoPago", ""),
            "forma_pago": root.attrib.get("FormaPago", ""),
            "iva": float(imp_root.attrib.get("TotalImpuestosTrasladados", 0))
            if imp_root is not None else 0,
        },
        "emisor": {
            "nombre": emisor.attrib.get("Nombre", "") if emisor is not None else "",
            "rfc": emisor.attrib.get("Rfc", "") if emisor is not None else "",
        },
        "receptor": {
            "nombre": receptor.attrib.get("Nombre", "") if receptor is not None else "",
            "rfc": receptor.attrib.get("Rfc", "") if receptor is not None else "",
            "uso_cfdi": receptor.attrib.get("UsoCFDI", "") if receptor is not None else "",
        },
        "conceptos_cfdi": [],
        "servicio": {
            "rpu": text_of(reg, "RPU"),
            "tarifa": tarifa,
            "tipo_tarifa": tipo_tarifa,
            "tarifa_reconocida": tarifa_reconocida,
            "advertencia_tarifa": "" if tarifa_reconocida else (
                f"Tarifa no contemplada: {tarifa or 'N/D'}; tipo de tarifa: {tipo_tarifa or 'N/D'}"
            ),
        },
        "periodo": {
            "desde": text_of(reg, "FECDESDE"),
            "hasta": text_of(reg, "FECHASTA"),
            "mes_nombre": _calcular_mes(text_of(reg, "FECHASTA")),
            "limite_pago": text_of(reg, "FECLIMITE"),
            "corte": text_of(reg, "FECORTE"),
        },
        "medicion": {
            "rpu": text_of(reg, "RPU"),
            "medidor": text_of(reg, "NUMMED1"),
            "hilos": text_of(reg, "HILOS"),
            "consumo_kwh": text_of(reg, "CONSUMO_R"),
            "kwh_base": text_of(reg, "CONSUMO3F"),
            "kwh_intermedia": text_of(reg, "CONSUMO2F"),
            "kwh_punta": text_of(reg, "CONSUMO1F"),
            "demanda_kw": text_of(reg, "DEMANDA"),
            "kw_base": text_of(reg, "DEMANDA3P"),
            "kw_intermedia": text_of(reg, "DEMANDA2P"),
            "kw_punta": text_of(reg, "DEMANDA1P"),
            "kwmax": text_of(reg, "DEMANDA"),
            "kvarh": text_of(reg, "KVARH"),
            "carga_contratada": text_of(reg, "CARGA_CONTRATADA"),
            "factor_potencia": text_of(reg, "FacPot"),
        },
        "componentes_tarifarios": [],
        "conceptos_importes": [],
        "conceptos_requeridos": [],
        "mediciones_requeridas": _mediciones_requeridas(reg),
        "lineas_excel": [],
        "extra": {
            "nombre_cliente": text_of(reg, "NOMBRE"),
            "direccion": text_of(reg, "DIRECC"),
            "poblacion": text_of(reg, "NOMPOB"),
            "estado": text_of(reg, "NOMEST"),
        },
    }

    for concepto_cfdi in conceptos_cfdi:
        datos["conceptos_cfdi"].append({
            "descripcion": concepto_cfdi.attrib.get("Descripcion", ""),
            "importe": float(concepto_cfdi.attrib.get("Importe", 0)),
            "unidad": concepto_cfdi.attrib.get("ClaveUnidad", ""),
            "cantidad": concepto_cfdi.attrib.get("Cantidad", ""),
            "objeto_imp": concepto_cfdi.attrib.get("ObjetoImp", ""),
        })

    for index in range(1, 20):
        motivo = text_of(reg, f"MOTIVO_REG_{index}")
        total = text_of(reg, f"IMPTE_TOT_REG_{index}")
        if motivo:
            datos["componentes_tarifarios"].append({
                "codigo": motivo,
                "nombre": TARIFA_CODES.get(motivo, motivo),
                "importe": _numero(total),
            })

    conceptos_el = reg.find("Conceptos")
    importes_el = reg.find("Importes")
    if conceptos_el is not None and importes_el is not None:
        for index in range(1, 20):
            concepto_el = conceptos_el.find(f"Concepto{index}")
            importe_el = importes_el.find(f"Importe{index}")
            concepto = concepto_el.text.strip() if concepto_el is not None and concepto_el.text else ""
            importe = importe_el.text.strip() if importe_el is not None and importe_el.text else ""
            concepto_limpio = _normalizar_concepto(concepto)
            if concepto and importe:
                importe_numero = _numero(importe)
                datos["conceptos_importes"].append({
                    "concepto": concepto_limpio,
                    "importe": importe_numero,
                })
                concepto_requerido = _concepto_requerido(concepto_limpio)
                if concepto_requerido:
                    datos["conceptos_requeridos"].append({
                        "concepto": concepto_requerido,
                        "importe": importe_numero,
                    })
            elif concepto:
                datos["conceptos_importes"].append({
                    "concepto": concepto_limpio,
                    "importe": None,
                })

    datos["lineas_excel"] = _lineas_excel(datos)
    return datos


def _calcular_mes(fecha_hasta: str) -> str:
    partes = fecha_hasta.split()
    for parte in partes:
        if parte.upper() in MESES:
            return MESES_FORMATO[parte.upper()]
    return ""


def _normalizar_concepto(concepto: str) -> str:
    reemplazos = {
        "Cargo Fijo???": "Cargo Fijo((3))",
        "Energ?a": "Energía",
        "2% Baja Tensi?n???": "2% Baja Tension((3))",
        "2% Baja Tensión???": "2% Baja Tension((3))",
        "Bonificaci?n Factor de Potencia???": "Bonificacion Factor de Potencia((3))",
        "Bonificación Factor de Potencia???": "Bonificacion Factor de Potencia((3))",
        "Facturaci?n del Periodo": "Facturación del Periodo",
        "Facturación del Periodo": "Facturación del Periodo",
        "Derecho de Alumbrado P?blico???": "Derecho de Alumbrado Público((3))",
        "Derecho de Alumbrado Público???": "Derecho de Alumbrado Público((3))",
    }
    return reemplazos.get(concepto, concepto)


def _concepto_requerido(concepto: str) -> str:
    concepto_mayus = concepto.upper()
    if concepto_mayus.startswith("2% BAJA"):
        return "2% Baja Tension((3))"
    if "FACTOR DE POTENCIA" in concepto_mayus:
        return "Bonificacion Factor de Potencia((3))"
    if concepto_mayus == "SUBTOTAL":
        return "Subtotal"
    return ""


def _numero(texto: str) -> float | None:
    if texto == "":
        return None
    try:
        return float(texto.replace(",", ""))
    except ValueError:
        logger.warning("numero_cfe_invalido valor=%s", texto)
        return None


def _mediciones_requeridas(reg: ET.Element) -> list[dict[str, float | None | str]]:
    return [
        {"concepto": "kWh base", "importe": _numero(text_of(reg, "CONSUMO3F"))},
        {"concepto": "kWh intermedia", "importe": _numero(text_of(reg, "CONSUMO2F"))},
        {"concepto": "kWh punta", "importe": _numero(text_of(reg, "CONSUMO1F"))},
        {"concepto": "kW base", "importe": _numero(text_of(reg, "DEMANDA3P"))},
        {"concepto": "kW intermedia", "importe": _numero(text_of(reg, "DEMANDA2P"))},
        {"concepto": "kW punta", "importe": _numero(text_of(reg, "DEMANDA1P"))},
        {"concepto": "KWMax", "importe": _numero(text_of(reg, "DEMANDA"))},
        {"concepto": "kVArh", "importe": _numero(text_of(reg, "KVARH"))},
        {"concepto": "Factor de potencia %", "importe": _numero(text_of(reg, "FacPot"))},
    ]


def _lineas_excel(datos: CfeReceipt) -> list[dict[str, str | float | None]]:
    lineas = []
    for componente in datos["componentes_tarifarios"]:
        lineas.append({
            "grupo": "Componentes tarifarios",
            "concepto": componente["nombre"],
            "importe": componente["importe"],
        })
    for concepto in datos["conceptos_requeridos"]:
        lineas.append({
            "grupo": "Ajustes y subtotal",
            "concepto": concepto["concepto"],
            "importe": concepto["importe"],
        })
    for medicion in datos["mediciones_requeridas"]:
        lineas.append({
            "grupo": "Mediciones",
            "concepto": medicion["concepto"],
            "importe": medicion["importe"],
        })
    return lineas
