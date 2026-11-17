# Tablas de mortalidad

`makeham_supuesto.csv` — **supuesto**, no es una tabla oficial. Gompertz-Makeham
mu(x) = A + B·c^x, qx = 1 − exp(−mu(x)):

| sexo | A | B | c |
|---|---|---|---|
| M | 0.0005 | 0.00003 | 1.10 |
| F | 0.0003 | 0.000015 | 1.10 |

Tabla oficial a usar como reemplazo: TM-2020 de la CMF y la Superintendencia de Pensiones
(NCG CMF N°495 / NCG SP N°306, vigentes desde el 1-7-2023): CB-H-2020 (hombres) y B-M-2020 (mujeres).
Las tablas son de pensionados/beneficiarios, por lo que para una cartera de trabajadores activos
son una aproximación conservadora. Fuentes:

- https://www.spensiones.cl/portal/compendio/596/w3-propertyvalue-10625.html (Anexo N°9, qx en imágenes)
- https://www.cmfchile.cl/portal/principal/623/w4-article-61114.html

Para reemplazarla: guardar un CSV con columnas `age,sex,qx` (sex en {M, F}, qx base 2020) y apuntar
`mortality_table` en `config/generator*.yaml` a ese archivo.
