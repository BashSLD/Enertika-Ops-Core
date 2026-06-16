-- 110_entregas_componente_fecha_manual.sql
-- Flag para proteger valores fijados a mano (boton "FV Terminado" de Fase 3 o import
-- del Excel de Fase 2): fecha_entrega y magnitud. La sincronizacion automatica
-- (sync_componentes_oportunidad) NO debe sobrescribirlos; solo refresca deadlines y
-- recalcula KPI contra la fecha vigente. Ver PLAN_DECOUPLE_FV_BESS.md Fase 5.

ALTER TABLE tb_entregas_componente
    ADD COLUMN IF NOT EXISTS editado_manual boolean NOT NULL DEFAULT false;
