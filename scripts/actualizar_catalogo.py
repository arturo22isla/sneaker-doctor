"""Actualiza data/catalog.csv con los productos, precios, promociones e instrucciones de cleanlab.pe.

Uso:
    python scripts/actualizar_catalogo.py

Conserva la columna 'materiales' que ya estaba en el CSV (revisada a mano).
Para productos nuevos la deduce de la categoría y el nombre; esos quedan marcados para revisar.
"""
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sneaker_doctor import MATERIALS, config  # noqa: E402
from sneaker_doctor.web_catalog import fetch_products, to_rows  # noqa: E402

ALL = "|".join(MATERIALS)


def guess_materials(row) -> str:
    text = f"{row['categoria_web']} {row['nombre']} {row['descripcion']}".lower()
    if re.search(r"todo material|cualquier material|todo tipo de material", text):
        return ALL
    found = [m for m, words in {"gamuza": ["gamuza", "nobuck"], "cuero": ["cuero"], "lona": ["lona"], "malla": ["malla", "mesh"]}.items()
             if any(w in text for w in words)]
    return "|".join(found)


def guess_type(cat: str) -> str:
    cat = cat.lower()
    if "suela" in cat:
        return "suela"
    if cat.startswith("accesorios"):
        return "accesorio"
    if cat.startswith(("proteccion", "restauracion")):
        return "proteccion"
    return "limpieza"


def main():
    web = pd.DataFrame(to_rows(fetch_products()))
    old = pd.read_csv(config.CATALOG_PATH, dtype=str).fillna("") if config.CATALOG_PATH.exists() else pd.DataFrame()
    known = dict(zip(old.get("sku", []), old.get("materiales", [])))

    web["tipo"] = web["categoria_web"].map(guess_type)
    web["materiales"] = [known.get(s, guess_materials(r)) for s, r in zip(web["sku"], web.to_dict("records"))]
    # Productos nuevos quedan marcados para revisar; los que ya estaban conservan su marca
    reviewed = {s: str(v).strip().lower() == "true" for s, v in zip(old.get("sku", []), old.get("revisar", []))}
    web["revisar"] = [reviewed.get(s, True) for s in web["sku"]]
    cols = ["sku", "nombre", "precio", "precio_antes", "disponible", "tipo", "materiales", "categoria_web", "url", "imagen", "variant_id",
            "instrucciones", "revisar"]
    web[cols].sort_values("sku").to_csv(config.CATALOG_PATH, index=False)

    promo = web["precio_antes"].notna().sum()
    print(f"Productos: {len(web)} · en promoción: {promo} · sin stock: {(~web['disponible']).sum()} · con instrucciones: {(web['instrucciones'] != '').sum()}")
    new = web[web["revisar"].astype(bool)]
    if not new.empty:
        print("\nPendientes de revisar (columna materiales):")
        print(new[["sku", "nombre", "materiales"]].to_string(index=False))
    gone = set(known) - set(web["sku"])
    if gone:
        print(f"\nYa no están en la web: {', '.join(sorted(gone))}")
    print(f"\nGuardado en {config.CATALOG_PATH}")


if __name__ == "__main__":
    main()
