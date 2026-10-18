"""Arma la tabla de fotos reales de Clean Lab para sumarlas al entrenamiento.

Estructura esperada (fuera del repositorio):
    fotos_cleanlab/
      gamuza/  Z0001_1.jpg  Z0001_2.jpg  Z0002_1.jpg ...
      cuero/
      lona/
      malla/

El nombre empieza con el código de la zapatilla (Z0001): todas las fotos de una misma
zapatilla quedan en el mismo grupo (train, val o test).

Uso:
    python scripts/prepare_cleanlab.py --photos-dir data/raw/fotos_cleanlab
Salida: data/processed/cleanlab.csv
"""
import argparse
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from prepare_zappos import assign_split  # noqa: E402

from sneaker_doctor import MATERIALS  # noqa: E402

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def shoe_id(name: str) -> str:
    """'Z0001_2.jpg' → 'Z0001'."""
    return re.split(r"[_\-]", Path(name).stem)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photos-dir", default=str(ROOT / "data" / "raw" / "fotos_cleanlab"))
    ap.add_argument("--out", default=str(ROOT / "data" / "processed" / "cleanlab.csv"))
    # Con pocas fotos conviene reservar más para prueba: es la métrica que importa
    ap.add_argument("--test", type=float, default=0.25)
    ap.add_argument("--val", type=float, default=0.15)
    args = ap.parse_args()

    rows = []
    for material in MATERIALS:
        folder = Path(args.photos_dir) / material
        for p in sorted(folder.glob("*")) if folder.exists() else []:
            if p.suffix.lower() in IMAGE_EXT:
                group = f"cl-{material}-{shoe_id(p.name)}"
                rows.append({"path": str(p), "material": material, "group": group,
                             "split": assign_split(group, args.val, args.test), "source": "cleanlab"})
    if not rows:
        sys.exit(f"No encontré fotos en {args.photos_dir}/<material>/")
    df = pd.DataFrame(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(df.pivot_table(index="material", columns="split", values="path", aggfunc="count", fill_value=0).to_string())
    print(f"\n{df['group'].nunique()} zapatillas · {len(df)} fotos · guardado en {args.out}")


if __name__ == "__main__":
    main()
