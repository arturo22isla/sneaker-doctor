"""Configuración leída de variables de entorno (.env en local, secrets en la nube)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def get(name: str, default: str = "") -> str:
    return os.getenv(name, default)


FEEDBACK_DIR = Path(get("FEEDBACK_DIR", str(ROOT / "data" / "feedback")))
GLOBAL_PER_MINUTE = int(get("GLOBAL_PER_MINUTE", "12"))  # preguntas por minuto entre todos (Flash-Lite gratis: 15)
MAX_FEEDBACK = 10  # opiniones guardadas por sesión
MAX_QUESTIONS = int(get("MAX_QUESTIONS", "20"))  # por sesión: evita que alguien agote la clave gratuita
MODEL_PATH = Path(get("MODEL_PATH", str(ROOT / "models" / "sneaker_doctor.keras")))
LABELS_PATH = MODEL_PATH.with_name("labels.json")
CATALOG_PATH = ROOT / "data" / "catalog.csv"
CO_PURCHASE_PATH = ROOT / "data" / "co_purchase.csv"

# gemini | groq | none
LLM_PROVIDER = get("LLM_PROVIDER", "gemini").lower()
GEMINI_MODEL = get("GEMINI_MODEL", "gemini-flash-lite-latest")
GEMINI_FALLBACK_MODEL = get("GEMINI_FALLBACK_MODEL", "gemini-flash-latest")
LLM_TIMEOUT = float(get("LLM_TIMEOUT", "15"))
GROQ_MODEL = get("GROQ_MODEL", "llama-3.1-8b-instant")
