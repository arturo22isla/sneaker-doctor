"""Catálogo de Clean Lab y kit recomendado por material."""
from urllib.parse import urlencode

import pandas as pd

from sneaker_doctor import config
from sneaker_doctor.packs import PACKS, best_option

# Kit base por material, según las descripciones de cleanlab.pe. Validar con Clean Lab.
BASE_KIT = {
    "gamuza": ["LCLKG", "PCLACP", "PCLPP"],    # limpieza en seco + color + protector
    "cuero": ["LCLFP", "PCLRP", "PCLPP"],      # espuma + renovador (no apto para gamuza) + protector
    "lona": ["LCLFP", "PCLPP"],                # el Foam Pack trae escobilla de cerdas duras para lona
    "malla": ["LCLFP", "LCLE41", "PCLPP"],     # espuma + cepillo para ranuras + protector
}

# Productos para la suela según su estado (instrucciones de cleanlab.pe).
SOLE_STATES = {
    "normal": "Blanca o en buen estado",
    "amarilla": "Amarilla u oxidada",
    "gastada": "Sucia o desgastada",
}
SOLE_KIT = {
    "normal": [],
    "amarilla": ["ACLRDS"],             # Crema Renovadora: revierte la oxidación con exposición al sol
    "gastada": ["LCLEB", "LCLBP-P"],    # Escobilla Basic para suelas + Blanqueador (pintura acrílica)
}


# Necesidades adicionales que no dependen del material.
EXTRA_NEEDS = {
    "arrugas": ("Arrugas", ["PCLSG"]),           # Shoe Guard: antiarrugas
    "forma": ("Mantener la forma", ["PCLHP"]),  # Hormas Premium
    "olor": ("Mal olor", ["PCLEO"]),                          # Eliminador de Olores
    "proteger_suela": ("Proteger la suela", ["PCLSP"]),  # Sole Shield
    "comodidad": ("Comodidad", ["ACLPP2"]),    # Plantillas Premium
}


# Por qué se recomienda cada producto (resumen de las descripciones de cleanlab.pe). Validar con Clean Lab.
REASONS = {
    "LCLKG": "Limpia la gamuza y el nobuck en seco, sin agua, para no mancharlos ni endurecerlos.",
    "PCLACP": "Revive el color de la gamuza y el nobuck desgastados después de limpiarlos.",
    "PCLPP": "Repele el agua y las manchas: la zapatilla se ensucia menos y la limpieza dura más.",
    "LCLFP": "Limpiador en espuma con escobillas y microfibra: limpia cuero, lona y malla sin dañarlos.",
    "PCLRP": "Hidrata y devuelve el color al cuero liso para que no se reseque ni se agriete.",
    "LCLE41": "Llega a las ranuras, costuras y agujeros de la malla donde la escobilla no entra.",
    "ACLRDS": "Revierte el amarillo de la suela (oxidación) con ayuda del sol.",
    "LCLEB": "Cerdas rígidas para sacar la suciedad incrustada de la suela.",
    "LCLBP-P": "Plumones blanqueadores que devuelven el blanco a la media suela gastada.",
    "PCLSG": "Evita que se formen arrugas en la punta al caminar.",
    "PCLHP": "Mantienen la forma y evitan las arrugas mientras no las usas.",
    "PCLEO": "Elimina el mal olor causado por bacterias dentro del calzado.",
    "PCLSP": "Lámina transparente que protege la suela del desgaste y las manchas.",
    "ACLPP2": "Amortiguan el impacto y dan soporte al arco: más comodidad todo el día.",
}

# Marca de los pedidos que vienen de Sneaker Doctor: se ve en el pedido y Shopify Flow lo etiqueta
ORDER_ATTRIBUTE = ("origen", "Sneaker Doctor")
UTM = {"utm_source": "sneaker-doctor", "utm_medium": "web", "utm_campaign": "kit"}


def load_catalog(path=None) -> pd.DataFrame:
    df = pd.read_csv(path or config.CATALOG_PATH, dtype=str).fillna("")
    df["precio"] = df["precio"].astype(float)
    if "precio_antes" in df:
        df["precio_antes"] = pd.to_numeric(df["precio_antes"], errors="coerce")
    else:
        df["precio_antes"] = float("nan")
    df["disponible"] = df["disponible"].str.lower().ne("false") if "disponible" in df else True
    for col in ["url", "imagen", "instrucciones", "variant_id"]:
        if col not in df:
            df[col] = ""
    df["materiales"] = df["materiales"].map(lambda s: [m for m in s.split("|") if m])
    return df.drop_duplicates("sku").set_index("sku")


def refresh_from_web(catalog: pd.DataFrame, rows: list[dict]) -> pd.DataFrame:
    """Actualiza precio, precio anterior, stock e instrucciones de los productos que siguen en la web."""
    catalog = catalog.copy()
    for r in rows:
        if r["sku"] in catalog.index:
            catalog.loc[r["sku"], ["precio", "precio_antes", "disponible"]] = [
                r["precio"], r["precio_antes"] if r["precio_antes"] else float("nan"), r["disponible"]]
            for col in ["instrucciones", "imagen", "variant_id"]:
                if r.get(col):
                    catalog.loc[r["sku"], col] = str(r[col])  # columnas de texto (pandas 3 no acepta números ahí)
    return catalog


def load_co_purchase(path=None) -> pd.DataFrame:
    """Compras conjuntas calculadas con SQL (scripts/co_purchase.sql). Opcional."""
    path = path or config.CO_PURCHASE_PATH
    try:
        return pd.read_csv(path)
    except FileNotFoundError:
        return pd.DataFrame(columns=["sku", "also_sku", "pedidos", "confianza"])


def as_list(materials) -> list[str]:
    """Acepta un material ('gamuza') o varios (['gamuza', 'malla'])."""
    return [materials] if isinstance(materials, str) else list(materials)


def item(catalog: pd.DataFrame, sku: str) -> dict:
    row = catalog.loc[sku]
    before = row["precio_antes"]
    return {"sku": sku, "nombre": row["nombre"], "precio": float(row["precio"]),
            "precio_antes": None if pd.isna(before) else float(before),
            "disponible": bool(row["disponible"]), "url": row["url"], "imagen": row["imagen"],
            "variant_id": str(row["variant_id"]).split(".")[0] if str(row["variant_id"]) not in ("", "nan") else "",
            "instrucciones": row["instrucciones"]}


def reason(sku: str, catalog: pd.DataFrame) -> str:
    """Motivo por el que se recomienda un producto; para un pack, qué trae y cuánto ahorra."""
    if sku in REASONS:
        return REASONS[sku]
    if sku in PACKS:
        names = [catalog.loc[s, "nombre"] for s in PACKS[sku] if s in catalog.index]
        return f"Trae {', '.join(names)} juntos, más barato que comprarlos por separado."
    return ""


def recommend(materials, catalog: pd.DataFrame, co_purchase: pd.DataFrame | None = None,
              sole: str | None = None, needs: list[str] | None = None, removed=None) -> dict:
    """Kit para uno o varios materiales (sin repetir productos), productos para la suela
    según su estado, complementos según necesidades (arrugas, olor…), la opción más barata
    con packs y, si hay datos de pedidos, el producto que más se compra junto.

    `removed`: productos o packs que el cliente quitó. Un producto quitado sale del kit;
    un pack quitado deja de ofrecerse y sus productos se muestran sueltos."""
    materials = as_list(materials)
    removed = set(removed or [])
    kit = []
    for m in materials:
        kit += [s for s in BASE_KIT.get(m, []) if s in catalog.index and s not in kit]
    sole_kit = [s for s in SOLE_KIT.get(sole, []) if s in catalog.index and s not in kit]
    extras_kit = []
    for need in needs or []:
        extras_kit += [s for s in EXTRA_NEEDS.get(need, ("", []))[1]
                       if s in catalog.index and s not in kit + sole_kit + extras_kit]
    extra = None
    if co_purchase is not None and not co_purchase.empty:
        cand = co_purchase[co_purchase["sku"].isin(kit) & ~co_purchase["also_sku"].isin(kit + sole_kit + extras_kit)]
        cand = cand[cand["also_sku"].isin(catalog.index)]
        fits = lambda s: not catalog.loc[s, "materiales"] or any(m in catalog.loc[s, "materiales"] for m in materials)  # noqa: E731
        cand = cand[cand["also_sku"].map(fits) & cand["also_sku"].map(lambda s: bool(catalog.loc[s, "disponible"]))]
        if not cand.empty:
            best = cand.sort_values(["confianza", "pedidos"], ascending=False).iloc[0]
            extra = {**item(catalog, best["also_sku"]), "confianza": float(best["confianza"])}

    full = kit + sole_kit + extras_kit
    gone = [s for s in full if s in removed] + [p for p in PACKS if p in removed and p in catalog.index]
    kit, sole_kit, extras_kit = ([s for s in group if s not in removed] for group in (kit, sole_kit, extras_kit))
    all_skus = kit + sole_kit + extras_kit
    chosen = [item(catalog, s) for s in all_skus]
    before = sum(i["precio_antes"] or i["precio"] for i in chosen)
    total = sum(i["precio"] for i in chosen)
    pack = best_option(all_skus, catalog, exclude=removed)
    if pack:
        pack = {**pack, "packs": [{**item(catalog, p), "contenido": [catalog.loc[s, "nombre"] for s in PACKS[p] if s in catalog.index]}
                                  for p in pack["packs"]],
                "sueltos": [item(catalog, s) for s in pack["sueltos"]],
                "extras": [catalog.loc[s, "nombre"] for s in pack["extras"] if s in catalog.index]}
    n_kit, n_sole = len(kit), len(sole_kit)
    return {
        "materials": materials,
        "kit": chosen[:n_kit],
        "sole": sole,
        "sole_kit": chosen[n_kit:n_kit + n_sole],
        "extras_kit": chosen[n_kit + n_sole:],
        "total": round(total, 2),
        "ahorro": round(before - total, 2),
        "pack_option": pack,
        "extra": extra,
        "removed": [{**item(catalog, s), "porque": reason(s, catalog)} for s in gone],
    }



def products_for(materials, catalog: pd.DataFrame) -> pd.DataFrame:
    """Productos disponibles que sirven para alguno de los materiales (para el contexto del chat)."""
    materials = as_list(materials)
    fits = catalog["materiales"].map(lambda ms: any(m in ms for m in materials))
    return catalog[fits & catalog["disponible"]]


def cart_url(items: list[dict], store: str = "https://cleanlab.pe", tagged: bool = True) -> str:
    """Enlace de carrito de Shopify que agrega todos los productos de una vez: /cart/ID:1,ID:1.

    Con `tagged`, el pedido lleva el atributo origen=Sneaker Doctor (visible en el pedido y usado por
    Shopify Flow para etiquetarlo) y los parámetros UTM para los informes de marketing."""
    ids = [i["variant_id"] for i in items if i.get("variant_id") and i.get("disponible", True)]
    if not ids:
        return ""
    url = f"{store}/cart/{','.join(f'{v}:1' for v in ids)}"
    if tagged:
        url += "?" + urlencode({f"attributes[{ORDER_ATTRIBUTE[0]}]": ORDER_ATTRIBUTE[1], **UTM})
    return url


def product_url(item_: dict) -> str:
    """Página del producto con UTM: si el cliente compra desde ahí, el pedido también se reconoce."""
    url = item_.get("url", "")
    return f"{url}?{urlencode({**UTM, 'utm_campaign': 'producto'})}" if url.startswith("https://") else ""