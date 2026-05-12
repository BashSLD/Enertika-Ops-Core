-- 065: Persistir filtro RFC emisor para que el worker SAT pueda recuperar jobs.
ALTER TABLE tb_sat_jobs
ADD COLUMN IF NOT EXISTS rfc_emisor_filtro VARCHAR(13);

CREATE INDEX IF NOT EXISTS idx_sat_jobs_active_created
ON tb_sat_jobs(created_at ASC)
WHERE estado NOT IN ('completado', 'error');
