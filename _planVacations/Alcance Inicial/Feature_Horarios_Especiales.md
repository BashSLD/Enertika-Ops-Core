# Feature: Asignaciones especiales por empleado

## Objetivo
Permitir que RH asigne un horario distinto a empleados especificos, aunque pertenezcan a una sucursal con horario general.

Esta feature depende de que exista el CRUD de horarios por sucursal en `RRHH > Admin`, porque las asignaciones especiales deben reutilizar horarios existentes.

## Casos de uso
- Empleado administrativo dentro de una sucursal operativa.
- Medio tiempo.
- Guardia nocturna.
- Turno temporal por proyecto.
- Cambio temporal de jornada.

## Regla de prioridad

```text
Horario especial vigente del empleado
> Horario activo de su sucursal
> sin_horario
```

## Alcance funcional
- RH puede crear, editar, activar y desactivar asignaciones especiales por empleado.
- La asignacion apunta a un horario existente y reutilizable.
- Cada asignacion tiene `fecha_inicio` y `fecha_fin` opcional.
- Cada asignacion incluye `motivo` para trazabilidad.
- La vista de asistencia debe indicar cuando el horario aplicado fue especial.
- Al guardar cambios, se debe recalcular asistencia del rango afectado.

## UI propuesta
Seccion colapsable dentro de `RRHH > Admin > Horarios por sucursal`:

```text
Asignaciones especiales por empleado
```

Tabla:
- Empleado
- Sucursal
- Horario asignado
- Vigencia
- Estado
- Motivo
- Acciones

Formulario:
- Empleado
- Horario
- Fecha inicio
- Fecha fin
- Motivo
- Activo

Ayuda visible:

```text
Usa esta opcion para empleados con turnos distintos al horario general de su sucursal.
```

## Validaciones obligatorias
- No permitir dos asignaciones activas traslapadas para el mismo empleado.
- No permitir `fecha_fin` menor que `fecha_inicio`.
- No permitir asignar horarios inactivos.
- No permitir asignaciones sin empleado, sin horario o sin fecha de inicio.
- Si se desactiva una asignacion vigente, recalcular la asistencia del rango que deja de estar cubierto por esa excepcion.

## Modelo de datos sugerido

```sql
CREATE TABLE tb_horarios_empleado_asignaciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id UUID NOT NULL,
    horario_sucursal_id UUID NOT NULL,
    fecha_inicio DATE NOT NULL,
    fecha_fin DATE,
    activo BOOLEAN NOT NULL DEFAULT true,
    motivo TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by UUID,
    CONSTRAINT fk_horarios_empleado_usuario
        FOREIGN KEY (usuario_id) REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    CONSTRAINT fk_horarios_empleado_horario
        FOREIGN KEY (horario_sucursal_id) REFERENCES tb_horarios_sucursal(id) ON DELETE RESTRICT,
    CONSTRAINT fk_horarios_empleado_updated_by
        FOREIGN KEY (updated_by) REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL,
    CONSTRAINT ck_horarios_empleado_fechas
        CHECK (fecha_fin IS NULL OR fecha_fin >= fecha_inicio)
);
```

Indice recomendado para busqueda:

```sql
CREATE INDEX idx_horarios_empleado_vigencia
    ON tb_horarios_empleado_asignaciones (usuario_id, activo, fecha_inicio, fecha_fin);
```

La validacion de traslapes debe hacerse en service y reforzarse en base de datos si se adopta `daterange` con exclusion constraint.

## Cambios tecnicos esperados

### Calculo de asistencia
Modificar la consulta de contexto para resolver:

```text
asignacion especial vigente por empleado y fecha
si no existe, horario activo por sucursal
```

### Recalculo
Al guardar asignaciones:
- recalcular fechas afectadas;
- limitar por rango configurable;
- mostrar aviso a RH cuando el cambio impacte reportes ya calculados.
