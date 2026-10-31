# Sneaker Doctor · página web para Google Cloud Run
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY sneaker_doctor/ sneaker_doctor/
COPY web/ web/
COPY assets/ assets/
COPY data/catalog.csv data/catalog_fecha.txt data/
COPY models/sneaker_doctor.tflite models/filtro_calzado.tflite models/labels.json models/

# No correr como root
RUN useradd --create-home app && chown -R app /app
USER app

# Cloud Run indica el puerto en $PORT
ENV PORT=8080
CMD exec uvicorn sneaker_doctor.api:app --host 0.0.0.0 --port $PORT --workers 1 --timeout-keep-alive 30
