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
# Cloudflare responde 429 a los scripts sin identificar ("python-requests"): la app dice quién es.
HEADERS = {"User-Agent": "SneakerDoctor/1.0 (+https://sneaker-doctor.streamlit.app)", "Accept": "application/json"}


STOREFRONT_QUERY = """
query Productos($after: String) {
  products(first: 250, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      title handle productType descriptionHtml
      images(first: 1) { nodes { url } }
      variants(first: 50) {
        nodes { id sku availableForSale price { amount } compareAtPrice { amount } }
      }
    }
  }
}"""


def fetch_storefront(token: str, domain: str, version: str, timeout: float = 15) -> list[dict]:
    """Productos con la Storefront API oficial de Shopify (token de solo lectura).

    Devuelve el mismo formato que /products.json para reutilizar `to_rows`."""
    url = f"https://{domain}/api/{version}/graphql.json"
    headers = {**HEADERS, "Content-Type": "application/json", "X-Shopify-Storefront-Access-Token": token}
    products, after = [], None
    while True:
        resp = requests.post(url, json={"query": STOREFRONT_QUERY, "variables": {"after": after}},
                             headers=headers, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
        if body.get("errors"):
            raise RuntimeError(f"Storefront API: {body['errors'][0].get('message', 'error')}")
        page = body["data"]["products"]
        for n in page["nodes"]:
            products.append({
                "title": n["title"], "handle": n["handle"], "product_type": n.get("productType") or "",
                "body_html": n.get("descriptionHtml") or "",
                "images": [{"src": i["url"]} for i in n["images"]["nodes"]],
                "variants": [{"id": int(v["id"].rsplit("/", 1)[-1]), "sku": v.get("sku") or "",
                              "available": v["availableForSale"], "price": v["price"]["amount"],
                              "compare_at_price": (v.get("compareAtPrice") or {}).get("amount")}
                             for v in n["variants"]["nodes"]],
            })
        if not page["pageInfo"]["hasNextPage"]:
            return products
        after = page["pageInfo"]["endCursor"]


def fetch_products(timeout: float = 15) -> list[dict]:
    """Todos los productos de la tienda: con la Storefront API si hay token; si no, /products.json."""
    from sneaker_doctor import config

    if config.SHOPIFY_STOREFRONT_TOKEN:
        return fetch_storefront(config.SHOPIFY_STOREFRONT_TOKEN, config.SHOPIFY_DOMAIN, config.SHOPIFY_API_VERSION,
                                timeout)
    products, page = [], 1
    while True:
        resp = requests.get(f"{STORE}/products.json", params={"limit": 250, "page": page}, headers=HEADERS,
                            timeout=timeout)
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
