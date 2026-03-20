-- Migración 026: BOM Fase E — Módulo Finanzas + Pagos BOM
-- Tabla tb_bom_pagos: registro de pagos realizados por Finanzas
-- Tabla tb_comprobantes_pago: nuevas columnas id_bom_pago + origen para trazabilidad

-- ─── tb_bom_pagos ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tb_bom_pagos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Autorización pagada
    autorizacion_id UUID NOT NULL REFERENCES tb_bom_autorizaciones(id),

    -- Datos del pago
    monto_pagado     NUMERIC(14,2) NOT NULL,
    moneda           CHAR(3)       NOT NULL DEFAULT 'MXN',
    tipo_cambio_usado NUMERIC(10,4),           -- snapshot al momento del pago
    fecha_pago       DATE          NOT NULL,
    referencia_bancaria VARCHAR(100),
    comprobante_url  TEXT,                     -- PDF en SharePoint (nullable en MVP)

    -- Trazabilidad
    registrado_por   UUID          NOT NULL REFERENCES tb_usuarios(id_usuario),
    registrado_en    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT tb_bom_pagos_autorizacion_unique UNIQUE (autorizacion_id),
    CONSTRAINT tb_bom_pagos_moneda_check CHECK (moneda IN ('MXN', 'USD'))
);

CREATE INDEX IF NOT EXISTS idx_bom_pagos_autorizacion ON tb_bom_pagos(autorizacion_id);
CREATE INDEX IF NOT EXISTS idx_bom_pagos_fecha ON tb_bom_pagos(fecha_pago);
CREATE INDEX IF NOT EXISTS idx_bom_pagos_registrado_por ON tb_bom_pagos(registrado_por);

-- ─── Enlace en tb_comprobantes_pago ──────────────────────────────────────────
-- id_bom_pago: FK al pago BOM que originó este comprobante (NULL para comprobantes normales)
-- origen: distingue si el comprobante vino del flujo BOM o del flujo normal de Compras

ALTER TABLE tb_comprobantes_pago
    ADD COLUMN IF NOT EXISTS id_bom_pago UUID REFERENCES tb_bom_pagos(id),
    ADD COLUMN IF NOT EXISTS origen VARCHAR(20) DEFAULT 'COMPRAS';

CREATE INDEX IF NOT EXISTS idx_comprobantes_bom_pago
    ON tb_comprobantes_pago(id_bom_pago)
    WHERE id_bom_pago IS NOT NULL;
