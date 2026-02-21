# Migraciones de Base de Datos

Carpeta para scripts SQL versionados que modifican el esquema de la BD.

## Convenciones

- Nombrar archivos: `NNN_descripcion.sql` (ej: `001_initial_schema.sql`)
- Usar `IF NOT EXISTS` / `IF EXISTS` para hacerlos idempotentes
- Ejecutar migración **ANTES** de desplegar código nuevo
- Nunca incluir datos de prueba, solo schema y catálogos esenciales

## Ejecución

```bash
psql "$DB_URL_SYNC" -f migrations/NNN_descripcion.sql
```
