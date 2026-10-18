FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sneaker_doctor/ sneaker_doctor/
COPY data/catalog.csv data/catalog.csv
COPY models/ models/
COPY .streamlit/config.toml .streamlit/config.toml
COPY assets/ assets/
COPY app.py .

# No correr como root
RUN useradd --create-home app && mkdir -p data/feedback && chown -R app /app
USER app

# Cloud Run indica el puerto en $PORT
ENV PORT=8080
CMD streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true
