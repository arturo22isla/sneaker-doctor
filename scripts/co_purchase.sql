-- Productos que se compran juntos, a partir de la tabla de líneas de venta de Clean Lab.
-- Solo usa order_id y SKU: no toca datos personales, así que no necesita la vista anonimizada.
-- Reemplazar PROYECTO.DATASET.TABLA_LINEAS por la tabla real.
-- Exportar el resultado como data/co_purchase.csv (columnas: sku, also_sku, pedidos, confianza).
WITH canastas AS (
  SELECT DISTINCT order_id, variant_sku AS sku
  FROM `PROYECTO.DATASET.TABLA_LINEAS`
  WHERE net_sales > 0
),
por_producto AS (
  SELECT sku, COUNT(DISTINCT order_id) AS pedidos_sku
  FROM canastas GROUP BY sku
),
pares AS (
  SELECT a.sku, b.sku AS also_sku, COUNT(DISTINCT a.order_id) AS pedidos
  FROM canastas a
  JOIN canastas b ON a.order_id = b.order_id AND a.sku != b.sku
  GROUP BY 1, 2
)
SELECT p.sku, p.also_sku, p.pedidos,
       ROUND(p.pedidos / s.pedidos_sku, 3) AS confianza
FROM pares p
JOIN por_producto s USING (sku)
WHERE p.pedidos >= 5
ORDER BY p.sku, confianza DESC;
