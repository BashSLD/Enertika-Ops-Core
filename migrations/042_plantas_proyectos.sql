-- Añadir ID Proyecto y Zona Incidencia
ALTER TABLE public.tb_calculadora_plantas 
    ADD COLUMN IF NOT EXISTS id_proyecto UUID REFERENCES public.tb_proyectos_gate(id_proyecto) NULL;

ALTER TABLE public.tb_calculadora_plantas 
    ADD COLUMN IF NOT EXISTS zona_incidencia varchar(50) NULL;
