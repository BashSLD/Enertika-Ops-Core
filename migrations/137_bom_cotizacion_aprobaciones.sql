-- 137: Aprobaciones post-BOM de cotizaciones por Direccion (Fase 1 del plan
-- _Planes_Activos/2026-06-29-aprobaciones-cotizaciones-post-bom.md). Tabla separada de
-- tb_bom_aprobaciones (workflow inicial del BOM): audita solicitud, aprobacion,
-- rechazo y reemplazo de cotizaciones despues de APROBADO_FINAL.

CREATE TABLE IF NOT EXISTS tb_bom_cotizacion_aprobaciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cotizacion_id UUID NOT NULL REFERENCES tb_bom_cotizaciones(id),
    bom_id UUID NOT NULL REFERENCES tb_bom(id_bom),
    proyecto_id UUID NOT NULL REFERENCES tb_proyectos_gate(id_proyecto),
    estatus VARCHAR(30) NOT NULL DEFAULT 'PENDIENTE_DIRECCION'
        CONSTRAINT ck_bom_cot_aprob_estatus CHECK (estatus IN (
            'PENDIENTE_DIRECCION',
            'APROBADA',
            'RECHAZADA',
            'REEMPLAZADA',
            'CANCELADA_PROVEEDOR'
        )),
    solicitado_por UUID NOT NULL REFERENCES tb_usuarios(id_usuario),
    solicitado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    aprobado_por UUID REFERENCES tb_usuarios(id_usuario),
    aprobado_en TIMESTAMPTZ,
    rechazado_por UUID REFERENCES tb_usuarios(id_usuario),
    rechazado_en TIMESTAMPTZ,
    motivo_rechazo TEXT,
    comentarios_solicitud TEXT,
    comentarios_direccion TEXT,
    cotizacion_reemplazada_id UUID REFERENCES tb_bom_cotizaciones(id),
    aprobacion_reemplazada_id UUID REFERENCES tb_bom_cotizacion_aprobaciones(id),
    motivo_reemplazo TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bom_cot_aprob_bom_estatus
    ON tb_bom_cotizacion_aprobaciones (bom_id, estatus);

CREATE INDEX IF NOT EXISTS idx_bom_cot_aprob_proyecto_estatus
    ON tb_bom_cotizacion_aprobaciones (proyecto_id, estatus);

CREATE INDEX IF NOT EXISTS idx_bom_cot_aprob_cotizacion
    ON tb_bom_cotizacion_aprobaciones (cotizacion_id);

CREATE INDEX IF NOT EXISTS idx_bom_cot_aprob_reemplazada
    ON tb_bom_cotizacion_aprobaciones (aprobacion_reemplazada_id)
    WHERE aprobacion_reemplazada_id IS NOT NULL;

-- Maximo una aprobacion activa (pendiente o aprobada) por cotizacion;
-- las historicas (RECHAZADA/REEMPLAZADA/CANCELADA_PROVEEDOR) no cuentan.
CREATE UNIQUE INDEX IF NOT EXISTS uq_bom_cot_aprob_activa
    ON tb_bom_cotizacion_aprobaciones (cotizacion_id)
    WHERE estatus IN ('PENDIENTE_DIRECCION', 'APROBADA');
