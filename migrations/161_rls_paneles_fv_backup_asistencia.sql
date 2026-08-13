-- 161: Habilita RLS + politica deny_anon_authenticated en tablas que quedaron sin ella.
--
-- Mismo patron que la migracion 156 (revoca acceso anon/authenticated/PostgREST; la app usa
-- conexion directa asyncpg como rol postgres/service_role, que bypassea RLS por rolbypassrls).
-- Estas 5 tablas se crearon despues de la migracion 156 o fuera del flujo de migraciones
-- (tb_asistencia_diaria_backup_20260715 es un backup manual) y nunca recibieron el ENABLE +
-- la politica. Confirmado via MCP: ya estaban correctas en PROD, faltaba solo en DEV — esta
-- migracion es idempotente y no rompe nada donde ya este aplicada.

ALTER TABLE public.tb_cfe_servicio_registradores ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tb_asistencia_solicitudes_manuales ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tb_asistencia_diaria_backup_20260715 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tb_cat_paneles_fv ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tb_proyecto_paneles ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT unnest(ARRAY[
      'tb_cfe_servicio_registradores',
      'tb_asistencia_solicitudes_manuales',
      'tb_asistencia_diaria_backup_20260715',
      'tb_cat_paneles_fv',
      'tb_proyecto_paneles'
    ]) AS tablename
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename = r.tablename
        AND policyname = 'deny_anon_authenticated'
    ) THEN
      EXECUTE format(
        'CREATE POLICY deny_anon_authenticated ON public.%I FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)',
        r.tablename
      );
    END IF;
  END LOOP;
END $$;
