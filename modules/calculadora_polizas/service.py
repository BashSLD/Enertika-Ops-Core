# modules/calculadora/service.py
from typing import Optional
from fastapi import Depends, HTTPException
import logging
import io

from .db_service import CalculadoraDBService
from .schemas import CalcularRequest, CalcularResponse, ImportExcelResult

logger = logging.getLogger("CalculadoraPolizas.Service")


class CalculadoraService:

    def __init__(self):
        self.db = CalculadoraDBService()

    # ----------------------------------------
    # CÁLCULO PRINCIPAL
    # ----------------------------------------

    async def calcular(self, conn, req: CalcularRequest) -> CalcularResponse:
        planta = await self.db.get_planta_by_id(conn, req.planta_id)
        if not planta:
            raise ValueError(f"Planta '{req.planta_id}' no encontrada")

        potencia_kw = float(planta["potencia_kw"] or 0)
        num_paneles = int(planta["num_paneles"] or 0)

        if potencia_kw <= 0:
            raise ValueError("La planta no tiene potencia kW registrada")
        if num_paneles <= 0:
            raise ValueError("La planta no tiene cantidad de paneles registrada")

        precios_zona = await self.db.get_precios_zona(conn)
        costos = await self.db.get_costos_fijos(conn)
        wattabit_tier = await self.db.get_wattabit_para_kwp(conn, potencia_kw)

        zona = planta["zona"]
        precio_panel = precios_zona.get(zona)
        if precio_panel is None:
            raise ValueError(f"No existe precio configurado para la zona '{zona}'")

        if wattabit_tier is None:
            raise ValueError(f"La potencia {potencia_kw} kWp está fuera del rango Wattabit (máx 1,500 kWp)")

        tipo = req.tipo_poliza if isinstance(req.tipo_poliza, str) else req.tipo_poliza.value
        utilidad = req.utilidad

        # Componentes de costo
        if tipo == "premium":
            mtto_principal = precio_panel * num_paneles * 2   # 2 visitas/año
            mtto_fijo = costos["mtto_correctivo"]
        else:
            mtto_principal = costos["mtto_diagnostico_estandar"]
            mtto_fijo = 0.0

        wattabit_precio = float(wattabit_tier["precio_anual_mxp"])
        internet = costos["internet_anual"]
        gestion = costos["gestion_energetica_por_panel"] * num_paneles

        sub_total = mtto_principal + mtto_fijo + wattabit_precio + internet + gestion
        sub_total_utilidad = sub_total / (1 - utilidad)
        total_final = sub_total_utilidad * (1 + costos["iva"])

        peso_kwp = sub_total_utilidad / potencia_kw
        peso_panel = sub_total_utilidad / num_paneles

        # Proyección 5 años (3% anual)
        factor = costos.get("incremento_anual", 0.03)
        anos = []
        valor = sub_total_utilidad
        for i in range(5):
            if i > 0:
                valor *= (1 + factor)
            anos.append(round(valor, 2))

        return CalcularResponse(
            planta_id=planta["id"],
            nombre_planta=planta["nombre"],
            zona=zona,
            potencia_kw=potencia_kw,
            num_paneles=num_paneles,
            tipo_poliza=tipo,
            utilidad=utilidad,
            mtto_principal=round(mtto_principal, 2),
            mtto_fijo=round(mtto_fijo, 2),
            wattabit=round(wattabit_precio, 2),
            internet=round(internet, 2),
            gestion=round(gestion, 2),
            sub_total=round(sub_total, 2),
            sub_total_utilidad=round(sub_total_utilidad, 2),
            total_final=round(total_final, 2),
            peso_kwp=round(peso_kwp, 4),
            peso_panel=round(peso_panel, 4),
            anio_1=anos[0],
            anio_3=anos[2],
            anio_5=anos[4],
            acumulado_1_3=round(sum(anos[:3]), 2),
            acumulado_1_5=round(sum(anos), 2),
            nombre_wattabit=wattabit_tier["nombre"],
        )

    # ----------------------------------------
    # IMPORTACIÓN EXCEL
    # ----------------------------------------

    async def importar_plantas_excel(self, conn, contenido: bytes) -> ImportExcelResult:
        try:
            import openpyxl
        except ImportError:
            raise ValueError("openpyxl no está instalado en el servidor")

        wb = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
        ws = wb.active

        insertadas = 0
        actualizadas = 0
        errores = []

        # Leer encabezados de la primera fila
        headers = [str(c.value).strip().lower() if c.value else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]

        col_map = {}
        for campo, aliases in {
            "id":          ["id", "codigo", "código"],
            "nombre":      ["nombre", "planta", "name"],
            "zona":        ["zona", "zone"],
            "potencia_kw": ["potencia_kw", "potencia", "kw", "kwp"],
            "num_paneles": ["num_paneles", "paneles", "panels", "cantidad_paneles"],
            "cliente":     ["cliente", "client", "razon_social", "razón_social"],
            "direccion":   ["direccion", "dirección", "address", "ubicacion", "ubicación"],
        }.items():
            for alias in aliases:
                if alias in headers:
                    col_map[campo] = headers.index(alias)
                    break

        required = ["id", "nombre", "zona"]
        missing = [f for f in required if f not in col_map]
        if missing:
            raise ValueError(f"Columnas requeridas no encontradas: {', '.join(missing)}")

        for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            try:
                planta_id = str(row[col_map["id"]]).strip() if row[col_map["id"]] is not None else ""
                nombre = str(row[col_map["nombre"]]).strip() if row[col_map["nombre"]] is not None else ""
                zona = str(row[col_map["zona"]]).strip() if row[col_map["zona"]] is not None else ""

                if not planta_id or not nombre or not zona:
                    continue  # fila vacía, saltar sin error

                potencia_kw = None
                if "potencia_kw" in col_map and row[col_map["potencia_kw"]] is not None:
                    potencia_kw = float(row[col_map["potencia_kw"]])

                num_paneles = None
                if "num_paneles" in col_map and row[col_map["num_paneles"]] is not None:
                    num_paneles = int(row[col_map["num_paneles"]])

                cliente = None
                if "cliente" in col_map and row[col_map["cliente"]] is not None:
                    cliente = str(row[col_map["cliente"]]).strip() or None

                direccion = None
                if "direccion" in col_map and row[col_map["direccion"]] is not None:
                    direccion = str(row[col_map["direccion"]]).strip() or None

                existente = await self.db.get_planta_by_id(conn, planta_id)
                await self.db.upsert_planta(conn, {
                    "id": planta_id,
                    "nombre": nombre,
                    "zona": zona,
                    "potencia_kw": potencia_kw,
                    "num_paneles": num_paneles,
                    "cliente": cliente,
                    "direccion": direccion,
                    "activa": True,
                })

                if existente:
                    actualizadas += 1
                else:
                    insertadas += 1

            except Exception as exc:
                errores.append(f"Fila {row_num}: {exc}")

        wb.close()
        return ImportExcelResult(insertadas=insertadas, actualizadas=actualizadas, errores=errores)

    # ----------------------------------------
    # GUARDAR COTIZACIÓN
    # ----------------------------------------

    async def guardar_cotizacion(self, conn, resultado: CalcularResponse, user_id,
                                 solicitante_id=None) -> str:
        cotizacion_id = await self.db.save_cotizacion(conn, {
            "planta_id": resultado.planta_id,
            "nombre_planta": resultado.nombre_planta,
            "tipo_poliza": resultado.tipo_poliza,
            "utilidad": resultado.utilidad,
            "sub_total": resultado.sub_total,
            "sub_total_utilidad": resultado.sub_total_utilidad,
            "total_final": resultado.total_final,
            "resultado_json": resultado.model_dump(),
            "creado_por": user_id,
            "solicitante_id": solicitante_id,
        })
        return str(cotizacion_id)


def get_service() -> CalculadoraService:
    return CalculadoraService()
