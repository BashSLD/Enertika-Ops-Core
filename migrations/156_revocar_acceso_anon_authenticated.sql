-- Revoca acceso de los roles anon/authenticated (PostgREST/GraphQL) sobre las tablas y vistas
-- de public y agrega politica deny-all explicita en tablas con RLS sin politicas. La app no usa
-- Supabase client/PostgREST (conexion directa asyncpg como rol postgres, que bypassea RLS);
-- estos roles no se usan en ningun flujo. Objetivo: eliminar los advisories de seguridad
-- pg_graphql_anon_table_exposed / pg_graphql_authenticated_table_exposed / rls_enabled_no_policy.

-- Parte 1: revocar privilegios actuales sobre todas las tablas/vistas existentes en public
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM anon, authenticated;

-- Evitar que las tablas futuras hereden estos grants automaticamente
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;

-- Parte 2: politica deny-all explicita en tablas con RLS habilitado sin politicas (documenta
-- que el acceso via anon/authenticated esta bloqueado a proposito; el rol postgres/service_role
-- que usa la app sigue bypasseando RLS por rolbypassrls=true, sin importar esta politica)
DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT tablename
    FROM pg_tables
    WHERE schemaname = 'public'
      AND rowsecurity = true
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
