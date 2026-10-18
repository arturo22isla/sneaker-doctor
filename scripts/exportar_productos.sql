-- Catálogo de productos a partir de la tabla de líneas de venta de Clean Lab.
-- No usa datos personales. Reemplazar PROYECTO.DATASET.TABLA_LINEAS por la tabla real.
-- Exportar como CSV y compartirlo: con eso se actualiza data/catalog.csv.
SELECT
  variant_sku AS sku,
  ANY_VALUE(product_title) AS nombre,
  MAX(product_price) AS precio,
  COUNT(DISTINCT order_id) AS pedidos,
  SUM(net_quantity) AS unidades,
  MIN(anio_mes) AS primera_venta,
  MAX(anio_mes) AS ultima_venta
FROM `PROYECTO.DATASET.TABLA_LINEAS`
WHERE net_sales > 0
  AND product_title NOT LIKE '%off)%'   -- excluye regalos con descuento
GROUP BY variant_sku
ORDER BY pedidos DESC;
