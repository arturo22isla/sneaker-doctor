"""Lectura del catálogo publicado en cleanlab.pe (tienda Shopify).

Shopify publica los productos en /products.json: nombre, precio, precio anterior
(promociones), disponibilidad, categoría y descripción con el modo de uso.
"""
import html
import re

import requests

STORE = "https://cleanlab.pe"
INSTRUCTION_HEADINGS = r"(Modo de uso|Instrucciones de uso|Instrucciones|Cómo usar)"
CUT_AT = r"(Mira nuestro video|Consejos útiles|Importante:|Preguntas frecuentes)"


def fetch_products(timeout: float = 15) -> list[dict]:
    """Todos los productos de la tienda (paginando de a 250)."""
    products, page = [], 1
    while True:
        resp = requests.get(f"{STORE}/products.json", params={"limit": 250, "page": page}, timeout=timeout)
        resp.raise_for_status()
        batch = resp.json().get("products", [])
        products += batch
        if len(batch) < 250:
            return products
        page += 1


def html_to_text(body: str) -> str:
    body = re.sub(r"<(br|/p|/li|/h\d|/div)[^>]*>", "\n", body or "")
    text = html.unescape(re.sub(r"<[^>]+>", "", body))
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", text)).strip()


def instructions(text: str) -> str:
    """Sección 'Modo de uso' de la descripción, si existe."""
    match = re.search(INSTRUCTION_HEADINGS + r"\s*:?\s*\n?", text, flags=re.IGNORECASE)
    if not match:
        return ""
    section = text[match.end():]
    return re.split(CUT_AT, section, maxsplit=1)[0].strip()


def short_name(title: str) -> str:
    """'Kit de Gamuza Premium — Limpiador en seco…' → 'Kit de Gamuza Premium'."""
    return re.split(r"\s+[—–-]\s+", title.strip(), maxsplit=1)[0].strip()


def is_gift(title: str) -> bool:
    """Productos de regalo con compra (🎁 … (50% off)): no se recomiendan."""
    return title.startswith("🎁") or bool(re.search(r"\(\d+% off\)", title, flags=re.IGNORECASE))


def to_rows(products: list[dict]) -> list[dict]:
    """Una fila por SKU con precio, promoción, disponibilidad e instrucciones."""
    rows, seen = [], set()
    for p in products:
        if is_gift(p["title"]):
            continue
        text = html_to_text(p.get("body_html", ""))
        for v in p.get("variants", []):
            sku = (v.get("sku") or "").strip()
            if not sku or sku in seen:
                continue
            seen.add(sku)
            price = float(v["price"])
            before = float(v["compare_at_price"]) if v.get("compare_at_price") else None
            rows.append({
                "sku": sku,
                "variant_id": v.get("id"),
                "nombre": short_name(p["title"]),
                "precio": price,
                "precio_antes": before if before and before > price else None,
                "disponible": bool(v.get("available")),
                "categoria_web": p.get("product_type") or "",
                "url": f"{STORE}/products/{p['handle']}",
                "imagen": (p.get("images") or [{}])[0].get("src", ""),
                "descripcion": text[:600],
                "instrucciones": instructions(text),
            })
    return rows
