-- Revierte el error de la migración 136: home_office quedó agrupado con las modalidades que
-- justifican día completo (vacaciones/extraordinaria/incapacidad/permiso_con_goce/permiso_sin_goce).
-- Home Office es un día laborable normal trabajado en remoto: requiere checada real igual que
-- permiso_llegar_tarde/permiso_salir_temprano y nunca debe justificar el día por sola aprobación.
UPDATE tb_cat_tipos_ausencia
   SET justifica_asistencia_dia = false
 WHERE slug = 'home_office'
   AND justifica_asistencia_dia IS DISTINCT FROM false;
