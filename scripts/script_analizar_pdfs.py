import pdfplumber
import json
import os
import re

def clean_text(text):
    if not text: return None
    # Elimina espacios múltiples y comillas
    return re.sub(r'\s+', ' ', text).strip().replace('"', '')

def extract_hybrid_v6(pdf_path):
    res = {
        "archivo": os.path.basename(pdf_path),
        "fecha_operacion": None,
        "beneficiario": None,
        "monto": None,
        "moneda": "MXN"
    }

    with pdfplumber.open(pdf_path) as pdf:
        raw_text = pdf.pages[0].extract_text()
        lines = raw_text.split('\n')
        
        match_fecha = re.search(r'(\d{2}/\d{2}/\d{4})', raw_text)
        if match_fecha: res["fecha_operacion"] = match_fecha.group(1)

        match_monto = re.search(r'Importe.*?\$?\s*([\d,]+\.\d{2})', raw_text)
        if match_monto: res["monto"] = float(match_monto.group(1).replace(',', ''))

        if any(x in raw_text for x in ["USD", "D&oacute;lares", "Divisa: USD"]):
            res["moneda"] = "USD"

        found_in_lines = False
        for i, line in enumerate(lines):
            if "Nombre del tercero" in line or "Nombre de la empresa a pagar" in line:
                parts = line.split(":")
                candidate = parts[-1].strip() if len(parts) > 1 else ""
                
                # Si está vacío, miramos la siguiente línea
                if not candidate and i + 1 < len(lines):
                    candidate = lines[i+1].strip()
                
                # Corrección para nombres cortados (Caso "CV")
                if len(candidate) < 5 or candidate in ["CV", "SA", "SA DE CV"]:
                    if i > 0 and ":" not in lines[i-1]:
                        candidate = f"{lines[i-1].strip()} {candidate}"
                
                if candidate:
                    res["beneficiario"] = clean_text(candidate)
                    found_in_lines = True
                    break

        # "stoppers"
        if not found_in_lines:
            # Busca el bloque que empieza en "Datos del beneficiario" y termina en cualquiera de estos:
            block_pattern = r'Datos del beneficiario\s*(.*?)\s*(?:Datos del ordenante|Puedes obtener|BBVA|Cerrar)'
            bloque = re.search(block_pattern, raw_text, re.DOTALL)
            
            if bloque:
                bloque_lines = bloque.group(1).split('\n')
                for line in bloque_lines:
                    # Limpieza: ignorar la etiqueta "Nombre:" y líneas vacías
                    clean_l = line.replace("Nombre:", "").strip()
                    if clean_l and "Dirección" not in clean_l and "RFC" not in clean_l:
                        res["beneficiario"] = clean_text(clean_l)
                        break

    return res

def main():
    folder = input("Ruta de los PDFs: ")
    if os.path.isdir(folder):
        final = [extract_hybrid_v6(os.path.join(folder, f)) for f in os.listdir(folder) if f.endswith('.pdf')]
        
        with open("comprobantes_final_v6.json", "w", encoding="utf-8") as f:
            json.dump(final, f, indent=4, ensure_ascii=False)
        print(f"Proceso V6 completado. {len(final)} archivos procesados.")

if __name__ == "__main__":
    main()
    
