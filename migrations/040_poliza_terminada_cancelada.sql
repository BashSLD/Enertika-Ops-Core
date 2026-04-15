-- 040: Nuevos estatus para ciclo de vida completo de pólizas
-- TERMINADA = poliza que fue renovada (cumplió su ciclo, sigue cubriendo hasta fecha_fin)
-- CANCELADA = poliza cancelada anticipadamente por el cliente (requiere admin)

-- Columna para registrar el motivo de cancelación
ALTER TABLE tb_calculadora_cotizaciones
    ADD COLUMN IF NOT EXISTS motivo_cancelacion TEXT;

-- CHECK constraint de estatus (la columna era VARCHAR sin CHECK)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_cotizacion_estatus'
          AND conrelid = 'tb_calculadora_cotizaciones'::regclass
    ) THEN
        ALTER TABLE tb_calculadora_cotizaciones
            ADD CONSTRAINT chk_cotizacion_estatus
            CHECK (estatus IN (
                'CREADA', 'ENVIADA', 'EN_NEGOCIACION',
                'ACEPTADA', 'RECHAZADA', 'VENCIDA',
                'TERMINADA', 'CANCELADA'
            ));
    END IF;
END $$;
