"""Opiniones de los clientes sobre el material detectado, para reentrenar el modelo.

Se guarda solo lo necesario: un identificador de la foto (hash), lo que predijo el modelo,
el material que confirmó el cliente y si acertamos. La foto se guarda únicamente si el cliente
lo autoriza, re-codificada en JPEG (sin metadatos EXIF como la ubicación GPS).
"""
import csv
import hashlib
import io
import threading
from datetime import datetime, timezone

from PIL import Image

from sneaker_doctor import config

LOCK = threading.Lock()  # dos visitantes a la vez no mezclan filas
FIELDS = ["fecha", "foto", "predicho", "confianza", "materiales", "acerto", "foto_guardada"]


def photo_id(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16]


def save(raw: bytes, ranking, materials, correct: bool, keep_photo: bool, folder=None):
    folder = folder or config.FEEDBACK_DIR
    folder.mkdir(parents=True, exist_ok=True)
    pid = photo_id(raw)
    if keep_photo:
        from sneaker_doctor.chat import image_to_jpeg

        (folder / "fotos").mkdir(exist_ok=True)
        (folder / "fotos" / f"{pid}.jpg").write_bytes(image_to_jpeg(Image.open(io.BytesIO(raw))))
    path = folder / "feedback.csv"
    with LOCK, path.open("a", newline="", encoding="utf-8") as f:
        new = f.tell() == 0
        w = csv.DictWriter(f, FIELDS)
        if new:
            w.writeheader()
        w.writerow({"fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"), "foto": pid,
                    "predicho": ranking[0][0], "confianza": round(float(ranking[0][1]), 3),
                    "materiales": "|".join(materials), "acerto": int(correct), "foto_guardada": int(keep_photo)})
