"""Convierte los modelos a TensorFlow Lite para el servidor web.

Uso:
    python scripts/exportar_tflite.py

Genera en models/:
- sneaker_doctor.tflite  detector de material (el modelo entrenado)
- filtro_calzado.tflite  EfficientNetB0 de ImageNet reducido a "¿es un calzado?"

En producción basta con LiteRT (ai-edge-litert, ~10 MB) en lugar de TensorFlow (~600 MB):
el servidor arranca en segundos y usa mucha menos memoria.
"""
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sneaker_doctor import config, vision  # noqa: E402


def convert(model, path: Path):
    import tensorflow as tf

    # Keras 3: se exporta como SavedModel (pesos incluidos) y se convierte desde ahí
    with tempfile.TemporaryDirectory() as tmp:
        model.export(tmp, format="tf_saved_model", verbose=False)
        converter = tf.lite.TFLiteConverter.from_saved_model(tmp)
        converter.optimizations = [tf.lite.Optimize.DEFAULT]
        converter.target_spec.supported_types = [tf.float16]  # pesos en 16 bits: la mitad de peso, mismo resultado
        path.write_bytes(converter.convert())
    print(f"{path.name}: {path.stat().st_size / 1e6:.1f} MB")


def main():
    import tensorflow as tf

    trained = tf.keras.models.load_model(config.MODEL_PATH)
    # El data augmentation solo actúa al entrenar: el modelo de inferencia va sin esas capas
    x = inputs = tf.keras.Input((vision.IMG_SIZE, vision.IMG_SIZE, 3))
    for layer in trained.layers[1:]:
        if layer.name != "augmentation":
            x = layer(x)
    model = tf.keras.Model(inputs, x)
    convert(model, config.MODEL_PATH.with_suffix(".tflite"))

    # El filtro solo necesita la probabilidad total de las clases de calzado de ImageNet
    base = tf.keras.applications.EfficientNetB0(weights="imagenet")
    shoe = tf.keras.layers.Lambda(lambda p: tf.reduce_sum(tf.gather(p, vision.SHOE_CLASSES, axis=1), axis=1,
                                                          keepdims=True))(base.output)
    top5 = tf.keras.layers.Lambda(lambda p: tf.cast(tf.reduce_any(tf.equal(
        tf.math.top_k(p, k=5).indices[:, :, None], tf.constant(vision.SHOE_CLASSES)[None, None, :]), axis=[1, 2]),
        tf.float32)[:, None])(base.output)
    convert(tf.keras.Model(base.input, tf.keras.layers.Concatenate()([shoe, top5])), config.FILTER_TFLITE_PATH)

    # Comprobación: los modelos convertidos responden casi igual que los originales
    x = np.random.default_rng(0).uniform(0, 255, (1, vision.IMG_SIZE, vision.IMG_SIZE, 3)).astype("float32")
    full = trained.predict(x, verbose=0)[0]
    lite = vision.LiteModel(config.MODEL_PATH.with_suffix(".tflite"))(x)[0]
    print("diferencia máxima con el modelo original:", float(np.abs(full - lite).max()))


if __name__ == "__main__":
    main()
