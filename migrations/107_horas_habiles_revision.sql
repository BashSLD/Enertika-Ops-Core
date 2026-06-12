-- Migración 107: Horas hábiles para medición de tiempo en revisión (excluye sábado/domingo).
--
-- Contexto:
--   El tiempo en "En Revisión" se medía como tiempo de reloj crudo, contando sábado y
--   domingo. Si Dirección recibe el viernes y devuelve el lunes, sumaba ~3 días aunque
--   Simulación no podía actuar el fin de semana.
--
-- Solución:
--   fn_segundos_habiles_mx(inicio, fin) integra el intervalo día por día en hora
--   America/Mexico_City y descarta los días cuyo DOW sea domingo(0) o sábado(6),
--   devolviendo solo los segundos hábiles. México no observa DST desde 2022, por lo que
--   sumar intervalos de 1 día sobre timestamptz no introduce desfases.
--
--   Config UMBRAL_HORAS_REVISION_TARDE controla el umbral (en horas hábiles) a partir del
--   cual una oportunidad tarde se reporta como "espera de Dirección" en el PDF.
--
-- Idempotente: CREATE OR REPLACE + INSERT condicional.

CREATE OR REPLACE FUNCTION fn_segundos_habiles_mx(p_inicio timestamptz, p_fin timestamptz)
RETURNS double precision
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT COALESCE(SUM(
        GREATEST(
            EXTRACT(EPOCH FROM (
                LEAST(p_fin, dia_mx + INTERVAL '1 day') - GREATEST(p_inicio, dia_mx)
            )),
            0
        )
    ), 0)::double precision
    FROM generate_series(
        (date_trunc('day', p_inicio AT TIME ZONE 'America/Mexico_City')) AT TIME ZONE 'America/Mexico_City',
        p_fin,
        INTERVAL '1 day'
    ) AS dia_mx
    WHERE p_fin > p_inicio
      -- DOW de Postgres: domingo=0, sábado=6. Esta definición de fin de semana es
      -- intencionalmente independiente de la config DIAS_FIN_SEMANA que usa
      -- modules/comercial/sla_calculator.py (convención Python weekday: sáb=5, dom=6).
      -- Aquí es un reporte analítico interno, no el motor de SLA; mantener fija evita
      -- que una función IMMUTABLE dependa de tb_configuracion_global.
      AND EXTRACT(DOW FROM dia_mx AT TIME ZONE 'America/Mexico_City') NOT IN (0, 6);
$$;

COMMENT ON FUNCTION fn_segundos_habiles_mx(timestamptz, timestamptz) IS
    'Segundos del intervalo [inicio, fin) que caen en días hábiles (lun-vie) en hora America/Mexico_City. Excluye sábado y domingo completos.';

INSERT INTO tb_configuracion_global (clave, valor, descripcion, tipo_dato)
SELECT 'UMBRAL_HORAS_REVISION_TARDE', '24',
       'Horas hábiles en En Revisión a partir de las cuales una oportunidad tarde se reporta como espera de Dirección', 'integer'
WHERE NOT EXISTS (SELECT 1 FROM tb_configuracion_global WHERE clave = 'UMBRAL_HORAS_REVISION_TARDE');
