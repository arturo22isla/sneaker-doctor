"""Arma la tabla de imágenes de UT Zappos50K etiquetadas en 4 materiales.

Uso:
    python scripts/prepare_zappos.py --zappos-dir data/raw/zappos --max-per-class 1500

Dataset: https://www.kaggle.com/datasets/aryashah2k/large-shoe-dataset-ut-zappos50k
(uso académico, no comercial).

Salida: data/processed/images.csv con columnas path, material, group, split, source.
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sneaker_doctor import MATERIALS  # noqa: E402

# Palabra del campo Material de Zappos → nuestra clase. Revisar con el resumen que imprime el script.
MATERIAL_RULES = {
    "gamuza": ["suede", "nubuck"],
    "cuero": ["leather", "patent"],
    "lona": ["canvas", "denim", "fabric", "textile", "cotton"],
    "malla": ["mesh", "knit"],
}
# Materiales que no definen la clase (suelas, sintéticos genéricos): se ignoran.
NEUTRAL = ["rubber", "synthetic", "man-made", "manmade", "eva", "foam", "plastic"]


def tokens(raw) -> list[str]:
    if not isinstance(raw, str):
        return []
    return [t.strip().lower() for t in re.split(r"[;,/]", raw) if t.strip()]


def classify(raw) -> str | None:
    """Clase única del material, o None si no hay o si mezcla dos clases (p. ej. cuero y malla)."""
    found = set()
    for tok in tokens(raw):
        if any(n in tok for n in NEUTRAL):
            continue
        for cls, words in MATERIAL_RULES.items():
            if any(w in tok for w in words):
                found.add(cls)
    return found.pop() if len(found) == 1 else None


def norm_id(text: str) -> str:
    """'7590-123' y '7590.123' se comparan igual."""
    return re.sub(r"[.\-_]", "-", str(text).strip())


def assign_split(group: str, val=0.15, test=0.15) -> str:
    """Mismo producto (en cualquier color) siempre en el mismo grupo."""
    bucket = int(hashlib.md5(group.encode()).hexdigest(), 16) % 1000 / 1000
    return "test" if bucket < test else "val" if bucket < test + val else "train"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zappos-dir", default=str(ROOT / "data" / "raw" / "zappos"))
    ap.add_argument("--out", default=str(ROOT / "data" / "processed" / "images.csv"))
    ap.add_argument("--max-per-class", type=int, default=1500)
    ap.add_argument("--categories", default="Shoes", help="Categorías de Zappos separadas por coma (vacío = todas)")
    args = ap.parse_args()

    root = Path(args.zappos_dir)
    meta_files = list(root.rglob("meta-data.csv"))
    if not meta_files:
        sys.exit(f"No encontré meta-data.csv dentro de {root}. ¿Descomprimiste el dataset ahí?")
    meta = pd.read_csv(meta_files[0])
    print(f"Metadatos: {len(meta)} filas · columnas: {list(meta.columns)}")

    if args.categories:
        meta = meta[meta["Category"].isin([c.strip() for c in args.categories.split(",")])]

    print("\nValores más comunes del campo Material:")
    print(meta["Material"].dropna().map(tokens).explode().value_counts().head(25).to_string())

    meta["material"] = meta["Material"].map(classify)
    meta = meta.dropna(subset=["material"])
    meta["key"] = meta["CID"].map(norm_id)
    meta["group"] = meta["CID"].astype(str).str.split("-").str[0]

    images = {norm_id(p.stem): p for p in root.rglob("*.jpg")}
    meta["path"] = meta["key"].map(lambda k: str(images[k]) if k in images else None)
    missing = meta["path"].isna().sum()
    meta = meta.dropna(subset=["path"])
    print(f"\nImágenes encontradas: {len(meta)} · sin archivo: {missing}")

    # Máximo por clase, eligiendo productos completos para no partir grupos
    rows = []
    for cls in MATERIALS:
        sub = meta[meta["material"] == cls]
        groups = sub["group"].drop_duplicates().sample(frac=1, random_state=42)
        kept, n = [], 0
        for g in groups:
            size = (sub["group"] == g).sum()
            if n + size > args.max_per_class and n > 0:
                break
            kept.append(g)
            n += size
        rows.append(sub[sub["group"].isin(kept)])
    df = pd.concat(rows)
    df["split"] = df["group"].map(assign_split)
    df["source"] = "kaggle"

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df[["path", "material", "group", "split", "source"]].to_csv(out, index=False)
    print("\nImágenes por material y grupo:")
    print(df.pivot_table(index="material", columns="split", values="path", aggfunc="count", fill_value=0).to_string())
    print(f"\nGuardado en {out}")


if __name__ == "__main__":
    main()
