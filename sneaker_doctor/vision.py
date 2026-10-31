"""Carga de los modelos de visión y predicción del material.

En el servidor se usan los modelos en TensorFlow Lite (models/*.tflite) con LiteRT, que es liviano.
Si no existen, se usa el modelo de Keras con TensorFlow (entrenamiento y desarrollo local).
"""
import json
from functools import lru_cache

import numpy as np
from PIL import Image, ImageOps

from sneaker_doctor import config

IMG_SIZE = 224

# Clases de calzado de ImageNet: zueco, bota vaquera, mocasín, zapatilla deportiva y sandalia.
SHOE_CLASSES = [502, 514, 630, 770, 774]
SHOE_MIN = 0.03  # probabilidad total de calzado para aceptar la foto (probado con las fotos de cleanlab.pe)


def preprocess(image: Image.Image) -> np.ndarray:
    """Imagen RGB 224x224 con valores 0-255 (EfficientNet normaliza por dentro)."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    image = ImageOps.pad(image, (IMG_SIZE, IMG_SIZE), color=(255, 255, 255))
    return np.asarray(image, dtype="float32")[None, ...]


class LiteModel:
    """Modelo .tflite con LiteRT (servidor) o, si no está instalado, con el intérprete de TensorFlow."""

    def __init__(self, path):
        try:
            from ai_edge_litert.interpreter import Interpreter
        except ImportError:
            import tensorflow as tf

            Interpreter = tf.lite.Interpreter
        self.interpreter = Interpreter(model_path=str(path))
        self.interpreter.allocate_tensors()
        self.input = self.interpreter.get_input_details()[0]["index"]
        self.output = self.interpreter.get_output_details()[0]["index"]

    def __call__(self, x: np.ndarray) -> np.ndarray:
        self.interpreter.set_tensor(self.input, x)
        self.interpreter.invoke()
        return self.interpreter.get_tensor(self.output)


@lru_cache(maxsize=1)
def load():
    """Devuelve (modelo, etiquetas) o (None, None) si todavía no hay modelo entrenado."""
    if not config.LABELS_PATH.exists():
        return None, None
    labels = json.loads(config.LABELS_PATH.read_text(encoding="utf-8"))
    lite = config.MODEL_PATH.with_suffix(".tflite")
    if lite.exists():
        return LiteModel(lite), labels
    if not config.MODEL_PATH.exists():
        return None, None
    import tensorflow as tf  # solo para entrenar o si no se exportó el .tflite

    model = tf.keras.models.load_model(config.MODEL_PATH)
    return (lambda x: model.predict(x, verbose=0)), labels


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
    probs = model(preprocess(image))[0]
    return sorted(zip(labels, map(float, probs)), key=lambda t: -t[1])


# ---------------- Filtro: ¿la foto muestra un calzado? ----------------

@lru_cache(maxsize=1)
def load_filter():
    """Devuelve una función imagen → (probabilidad de calzado, ¿calzado entre los 5 más probables?).
    Si no se puede cargar, devuelve None y no se filtra."""
    try:
        if config.FILTER_TFLITE_PATH.exists():
            lite = LiteModel(config.FILTER_TFLITE_PATH)
            return lambda x: tuple(map(float, lite(x)[0]))
        import tensorflow as tf

        model = tf.keras.applications.EfficientNetB0(weights="imagenet")

        def full(x):
            probs = model.predict(x, verbose=0)[0]
            top5 = set(np.argsort(probs)[-5:].tolist())
            return float(probs[SHOE_CLASSES].sum()), float(bool(top5 & set(SHOE_CLASSES)))
        return full
    except Exception:
        return None


def shoe_score(image: Image.Image) -> float | None:
    """Probabilidad de que la foto sea un calzado, o None si el filtro no está disponible."""
    model = load_filter()
    if model is None:
        return None
    score, in_top5 = model(preprocess(image))
    # Si algún calzado está entre los 5 objetos más probables, se acepta aunque la suma sea baja
    return max(score, SHOE_MIN) if in_top5 else score


def is_shoe(score: float | None) -> bool:
    return score is None or score >= SHOE_MIN
