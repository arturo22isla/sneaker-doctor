# Publicar Sneaker Doctor en Google Cloud

La página web (FastAPI + HTML) corre en **Google Cloud Run**: se apaga sola cuando nadie la usa, arranca en segundos y,
con el tráfico de una demo o de los primeros clientes, entra en el nivel gratuito (uno o dos dólares al mes como máximo).

```
Navegador ──► Cloud Run (página + API) ──► Gemini (chat)
                    │
                    ├──► Storefront API de Shopify (precios en vivo cada 15 min)
                    └──► Secret Manager (claves: nunca en el código)
```

## 1. Shopify: permiso para leer los precios (una vez)

1. En el admin de Shopify → **Configuración → Apps y canales de ventas → Shopify App Store** → instala **Headless** (gratis, de Shopify).
2. En Headless → **Crear tienda (storefront)** → **Storefront API** → **Administrar permisos**: deja activado solo
   *leer productos y colecciones* (`unauthenticated_read_product_listings`).
3. Copia el **Token de acceso público** (Public access token). Es de solo lectura del catálogo.
4. En **Configuración → Dominios** anota el dominio que termina en `.myshopify.com`.

## 2. Shopify Flow: etiquetar los pedidos de Sneaker Doctor (una vez)

Cada carrito armado en Sneaker Doctor llega con el atributo `origen = Sneaker Doctor` y la campaña `utm_source=sneaker-doctor`.

1. Instala **Shopify Flow** (gratis, de Shopify) → **Crear flujo de trabajo**.
2. Desencadenador: **Pedido creado** (*Order created*).
3. Condición (cualquiera de las dos):
   - *Order → Custom attributes*: **Key** es igual a `origen` y **Value** es igual a `Sneaker Doctor`, **o**
   - *Order → Customer journey summary → Last visit → UTM parameters → Source* es igual a `sneaker-doctor`.
4. Acción: **Agregar etiquetas al pedido** → `Sneaker Doctor`.
5. **Activar**. En **Pedidos** puedes filtrar por la etiqueta `Sneaker Doctor`.

Haz un pedido de prueba (por ejemplo con un descuento del 100 %) para confirmar que aparece la etiqueta.

## 3. Google Cloud (una vez)

1. Crea un proyecto en [console.cloud.google.com](https://console.cloud.google.com) y actívale la facturación.
2. **Facturación → Presupuestos y alertas** → crea un presupuesto de 10 USD con aviso por correo.
3. Instala la CLI de Google Cloud e inicia sesión. En PowerShell usa `gcloud.cmd` (Windows bloquea los scripts `.ps1`):

```bash
winget install Google.CloudSDK
```
```bash
gcloud.cmd auth login
```

4. Crea los secretos (vacíos) y súbeles los valores desde `.env` sin mostrarlos:

```bash
gcloud.cmd secrets create gemini-api-key --replication-policy=automatic --project TU-PROYECTO
```
```bash
gcloud.cmd secrets create shopify-storefront-token --replication-policy=automatic --project TU-PROYECTO
```
```bash
.venv\Scripts\python.exe scripts\subir_secretos.py
```

5. Crea una **cuenta de servicio propia**, sin permisos sobre el proyecto, que solo lea esos dos secretos.
   No uses la cuenta por defecto (`…-compute@developer…`): tiene rol Editor y daría acceso a BigQuery y a todo el proyecto.

```bash
gcloud.cmd iam service-accounts create sneaker-doctor-sa --display-name "Sneaker Doctor" --project TU-PROYECTO
```
```bash
gcloud.cmd secrets add-iam-policy-binding gemini-api-key --member serviceAccount:sneaker-doctor-sa@TU-PROYECTO.iam.gserviceaccount.com --role roles/secretmanager.secretAccessor --project TU-PROYECTO
```
```bash
gcloud.cmd secrets add-iam-policy-binding shopify-storefront-token --member serviceAccount:sneaker-doctor-sa@TU-PROYECTO.iam.gserviceaccount.com --role roles/secretmanager.secretAccessor --project TU-PROYECTO
```

## 4. Publicar (y volver a publicar después de cada cambio)

Desde la carpeta del proyecto. Antes, si reentrenaste el modelo: `python scripts/exportar_tflite.py`.

```bash
gcloud.cmd run deploy sneaker-doctor --source . --region us-central1 --project TU-PROYECTO --service-account sneaker-doctor-sa@TU-PROYECTO.iam.gserviceaccount.com --allow-unauthenticated --memory 1Gi --cpu 1 --max-instances 3 --concurrency 20 --set-env-vars "LLM_PROVIDER=gemini,SHOPIFY_DOMAIN=TU-TIENDA.myshopify.com" --set-secrets "GEMINI_API_KEY=gemini-api-key:latest,SHOPIFY_STOREFRONT_TOKEN=shopify-storefront-token:latest"
```

Al terminar muestra la dirección, por ejemplo `https://sneaker-doctor-xxxx.us-central1.run.app`.
`--max-instances 3` pone un techo al costo aunque alguien abuse de la página.

## 5. Dirección propia (opcional): doctor.cleanlab.pe

```bash
gcloud.cmd beta run domain-mappings create --service sneaker-doctor --domain doctor.cleanlab.pe --region us-central1
```

Google pide verificar que el dominio es de Clean Lab (Search Console) y muestra un registro **CNAME** (`ghs.googlehosted.com`)
para agregar donde se administra el DNS de cleanlab.pe. El certificado HTTPS se crea solo.

También se puede mostrar dentro de la tienda: en Shopify **Tienda online → Páginas → Agregar página**, en modo HTML:

```html
<iframe src="https://doctor.cleanlab.pe" title="Sneaker Doctor" style="width:100%;height:900px;border:0" allow="camera"></iframe>
```

## Seguridad

| Riesgo | Cómo está cubierto |
|---|---|
| Robo de claves | Solo en Secret Manager; el navegador nunca las ve. `.gcloudignore` y `.dockerignore` impiden subir `.env` |
| Acceso a otros datos del proyecto | El servicio corre con `sneaker-doctor-sa`: sin roles en el proyecto, solo lee sus 2 secretos (nada de BigQuery) |
| Abuso del chat (gastar la cuota) | Por visitante: 6 preguntas/minuto y 60/día; en total: 12/minuto; preguntas de 400 caracteres como máximo |
| Fotos maliciosas o enormes | Máximo 10 MB, se abren con Pillow con protección contra "bombas" de píxeles y se recodifican sin metadatos |
| Entradas inventadas | Cada campo se valida (materiales, suela, necesidades y códigos de producto de una lista cerrada) |
| Inyección de código en la página | Todo texto se escapa; política de seguridad (CSP) que solo permite scripts propios; sin estilos ni scripts en línea |
| Enlaces falsos en el chat | Se quitan los enlaces que no son de cleanlab.pe mientras llega la respuesta |
| Falsificar la IP para saltarse límites | Se usa la IP que agrega Google, no la que manda el navegador |
| Ver detalles internos | Sin documentación pública de la API ni trazas de error; el contenedor corre sin permisos de administrador |
| Costos inesperados | `--max-instances 3` y alerta de presupuesto |
| Privacidad (Ley 29733) | No se guardan fotos ni datos personales; las opiniones 👍/👎 se registran sin datos personales en Cloud Logging |
