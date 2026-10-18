# Sneaker Doctor · by Clean Lab

> A platform that identifies your sneakers' material from a photo and tells you which product to use and how to clean them.

Proyecto final del bootcamp de **Data Science & IA de Le Wagon**, desarrollado con [Clean Lab](https://cleanlab.pe), marca peruana de cuidado de zapatillas.

## ¿Qué hace?

1. **Tu zapatilla:** el cliente sube una foto y un modelo de visión detecta el material (gamuza, cuero, lona o malla). Si la zapatilla combina materiales, sugiere los dos; el cliente puede corregirlo.
2. **Cuéntanos más:** estado de la suela (blanca, amarilla, desgastada) y necesidades extra (arrugas, mal olor, mantener la forma…).
3. **Tu kit Clean Lab:** los productos indicados con precios, promociones e imágenes de cleanlab.pe en tiempo real. Calcula si conviene más un pack o los productos sueltos y arma el carrito con un clic.
4. **Pregúntale a Sneaker Doctor:** un chat con IA que ve la foto y explica paso a paso cómo limpiarla, siguiendo el modo de uso oficial de cada producto.

## Cómo funciona

```
Foto ──► CNN (EfficientNetB0, transfer learning) ──► material
                                                       │
Catálogo cleanlab.pe (Shopify) ──► reglas + packs ──► kit más barato ──► carrito
Compras conjuntas (SQL en BigQuery) ─┘                 │
                                                       ▼
                         Chat (Gemini, con la foto) ──► guía de limpieza
```

| Parte | Tecnología |
|---|---|
| Visión | TensorFlow / Keras, EfficientNetB0 + fine-tuning, entrenado en Google Colab (GPU T4) |
| Datos de entrenamiento | [UT Zappos50K](https://www.kaggle.com/datasets/aryashah2k/large-shoe-dataset-ut-zappos50k) (Kaggle), etiquetado por el campo `Material` |
| Catálogo | `products.json` de la tienda Shopify: precios, promociones, stock, imágenes y modo de uso |
| Recomendación | Kit por material y estado de la suela + optimización de packs + compras conjuntas (SQL) |
| Chat | Gemini API (Flash-Lite, nivel gratuito) con respuesta en streaming; Groq o guía fija como respaldo |
| App | Streamlit; despliegue en Streamlit Community Cloud o Google Cloud Run (Docker) |

## Estructura

```
sneaker-doctor/
├── app.py                       app de Streamlit (3 columnas + chat)
├── sneaker_doctor/
│   ├── vision.py                carga del modelo y predicción
│   ├── catalog.py               kit por material, suela y necesidades; enlace de carrito
│   ├── packs.py                 opción más barata combinando packs y productos sueltos
│   ├── web_catalog.py           lectura del catálogo de cleanlab.pe
│   ├── chat.py                  prompt, Gemini / Groq / guía fija, streaming, límites
│   ├── feedback.py              opiniones 👍/👎 sobre el material detectado
│   └── config.py                variables de entorno
├── scripts/
│   ├── prepare_zappos.py        etiqueta UT Zappos50K en 4 materiales
│   ├── prepare_cleanlab.py      agrega fotos propias de Clean Lab
│   ├── train.py                 entrenamiento y métricas
│   ├── actualizar_catalogo.py   actualiza data/catalog.csv desde la web
│   ├── co_purchase.sql          compras conjuntas en BigQuery (sin datos personales)
│   └── exportar_productos.sql
├── notebooks/entrenar_en_colab.ipynb
├── data/catalog.csv             catálogo público de Clean Lab
├── models/                      modelo entrenado, etiquetas y métricas
├── tests/                       pruebas con pytest
└── Dockerfile
```

## Instalación

Requiere Python 3.11 o 3.12.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt
copy .env.sample .env           # macOS/Linux: cp .env.sample .env
pytest
```

En `.env` va la clave gratuita de Gemini ([Google AI Studio](https://aistudio.google.com/apikey)). Sin clave, el chat responde con la guía fija.

```bash
streamlit run app.py
```

## Entrenar el modelo

1. Abrir `notebooks/entrenar_en_colab.ipynb` en Google Colab con GPU.
2. Agregar el token de Kaggle en *Secrets* (ícono de llave) y ejecutar las celdas: descarga UT Zappos50K, etiqueta los materiales, entrena y descarga el modelo.
3. Copiar `sneaker_doctor.keras`, `labels.json` y `metrics.json` en `models/`.

En local: `python scripts/prepare_zappos.py` y `python scripts/train.py --finetune-epochs 6`. Las métricas por material quedan en `models/metrics.json`.

Para actualizar precios y productos: `python scripts/actualizar_catalogo.py`.

## Despliegue en Streamlit Community Cloud

1. En [share.streamlit.io](https://share.streamlit.io) → *Create app* → este repositorio, rama `main`, archivo `app.py`. En *Advanced settings* elegir **Python 3.12** (TensorFlow 2.19 no funciona con 3.13).
2. En *Advanced settings → Secrets*:
   ```toml
   LLM_PROVIDER = "gemini"
   GEMINI_API_KEY = "tu-clave"
   ```

Alternativa con Docker en Google Cloud Run:

```bash
gcloud run deploy sneaker-doctor --source . --region us-central1 --allow-unauthenticated --memory 2Gi --set-secrets GEMINI_API_KEY=gemini-key:latest
```

## Seguridad y privacidad

- Las claves van en `.env` o en los *Secrets* de la plataforma; nunca en el repositorio.
- Ningún dato de clientes (pedidos, nombres, correos) está en el repositorio: el SQL trabaja con datos agregados y `data/feedback/` está excluido.
- La foto se envía a Gemini para el chat sin metadatos (EXIF/GPS) y la app lo avisa al cliente (Ley N.º 29733). La foto solo se guarda para reentrenar si el cliente lo autoriza.
- Límites contra el abuso: 20 preguntas por sesión, 12 por minuto en total, 400 caracteres por pregunta, fotos de hasta 10 MB.
- El chat solo recomienda productos del catálogo, ignora instrucciones que intenten cambiar sus reglas y no muestra enlaces externos.

## Pendiente de validar con Clean Lab

- Kit base por material (`BASE_KIT`) y por estado de la suela (`SOLE_KIT`) en `sneaker_doctor/catalog.py`.
- Guía de limpieza (`CARE_GUIDE`, `SOLE_GUIDE`) en `sneaker_doctor/chat.py`.
- Contenido de los packs en `sneaker_doctor/packs.py` y productos marcados `revisar` en `data/catalog.csv`.

## Próximos pasos

- Reentrenar con fotos reales de Clean Lab y las opiniones 👍/👎 de los clientes (mejorar gamuza y chimpunes).
- Detectar el estado de la suela desde la foto.
- Guardar las opiniones en BigQuery o Google Sheets en lugar de un CSV local.

## Créditos

- Dataset: A. Yu y K. Grauman, *Fine-Grained Visual Comparisons with Local Learning*, CVPR 2014 (UT Zappos50K). Uso académico, no comercial.
- Productos, precios e instrucciones de uso: [cleanlab.pe](https://cleanlab.pe).
