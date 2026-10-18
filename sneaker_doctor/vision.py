"""Carga del modelo de visión y predicción del material."""
import json
from functools import lru_cache

import numpy as np
from PIL import Image, ImageOps

from sneaker_doctor import config

IMG_SIZE = 224


def preprocess(image: Image.Image) -> np.ndarray:
    """Imagen RGB 224x224 con valores 0-255 (EfficientNet de Keras normaliza por dentro)."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    image = ImageOps.pad(image, (IMG_SIZE, IMG_SIZE), color=(255, 255, 255))
    return np.asarray(image, dtype="float32")[None, ...]


@lru_cache(maxsize=1)
def load():
    """Devuelve (modelo, etiquetas) o (None, None) si todavía no hay modelo entrenado."""
    if not config.MODEL_PATH.exists() or not config.LABELS_PATH.exists():
        return None, None
    import tensorflow as tf  # se importa solo si hay modelo

    model = tf.keras.models.load_model(config.MODEL_PATH)
    labels = json.loads(config.LABELS_PATH.read_text(encoding="utf-8"))
    return model, labels


def detected(ranking: list[tuple[str, float]], second_min: float = 0.30) -> list[str]:
    """Material principal y, si el segundo también es probable, ambos (zapatillas mixtas)."""
    materials = [ranking[0][0]]
    if len(ranking) > 1 and ranking[1][1] >= second_min:
        materials.append(ranking[1][0])
    return materials


def predict(image: Image.Image) -> list[tuple[str, float]] | None:
    """Materiales ordenados de más a menos probable, o None si no hay modelo."""
    model, labels = load()
    if model is None:
        return None
    probs = model.predict(preprocess(image), verbose=0)[0]
    return sorted(zip(labels, map(float, probs)), key=lambda t: -t[1])
