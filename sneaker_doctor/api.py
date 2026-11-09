"""Servidor web de Sneaker Doctor (FastAPI).

uvicorn sneaker_doctor.api:app --port 8080

Sirve la página (carpeta web/) y una API JSON:
    POST /api/diagnostico   foto → ¿es un calzado? y material
    POST /api/kit           materiales, suela, necesidades y productos quitados → kit con precios
    POST /api/chat          pregunta → respuesta de Gemini en streaming
    POST /api/opinion       👍/👎 sobre el material detectado (se registra en Cloud Logging)

Seguridad: las claves solo viven en el servidor, todas las entradas se validan, hay límites por
visitante y globales, tamaño máximo de foto y cabeceras de seguridad (CSP) en todas las respuestas.
"""
import base64
import binascii
import io
import json
import logging
import re
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, StringConstraints

from sneaker_doctor import MATERIALS, chat, config, feedback, vision
from sneaker_doctor.catalog import (EXTRA_NEEDS, FREE_SHIPPING, SOLE_STATES, VOLUME_TIERS, cart_url, final_price, item,
                                    load_catalog, load_co_purchase, next_tier, product_url, reason, recommend,
                                    refresh_from_web, suggestions, volume_rate)
from sneaker_doctor.web_catalog import fetch_products, to_rows

ROOT = Path(__file__).resolve().parent.parent
WEB, ASSETS = ROOT / "web", ROOT / "assets"
MAX_PHOTO = 10 * 1024 * 1024        # bytes de la foto que se sube
MAX_CHAT_PHOTO = 2 * 1024 * 1024    # foto reducida que acompaña cada pregunta
CONFIDENT = 0.8                    # por debajo, el material se confirma con Gemini
PRICE_TTL, PRICE_RETRY = 900, 120   # segundos: precios cada 15 min; si la tienda falla, reintenta a los 2 min

log = logging.getLogger("sneaker_doctor")
logging.basicConfig(level=logging.INFO, format="%(message)s")

Material = Literal[tuple(MATERIALS)]
Sole = Literal[tuple(SOLE_STATES)]
Need = Literal[tuple(EXTRA_NEEDS)]
Sku = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9-]{2,20}$")]  # además se valida contra el catálogo


# ---------------- Límites de uso ----------------

class KeyedLimit:
    """Máximo de `limit` acciones por `window` segundos para cada visitante (por IP)."""

    def __init__(self, limit: int, window: int):
        self.limit, self.window = limit, window
        self.calls: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self.lock:
            if len(self.calls) > 10_000:  # limpieza: no crece sin límite
                self.calls = defaultdict(deque, {k: q for k, q in self.calls.items() if q and now - q[-1] < self.window})
            q = self.calls[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


LIMITS = {
    "foto": KeyedLimit(20, 600),            # 20 fotos cada 10 minutos
    "kit": KeyedLimit(120, 60),             # cambios de opciones
    "chat_min": KeyedLimit(6, 60),          # 6 preguntas por minuto
    "chat_dia": KeyedLimit(config.MAX_QUESTIONS * 3, 86_400),
    "opinion": KeyedLimit(config.MAX_FEEDBACK, 86_400),
}
GLOBAL_CHAT = chat.RateLimit(config.GLOBAL_PER_MINUTE)


def client_ip(request: Request) -> str:
    """IP real del visitante. Cloud Run agrega la IP del cliente al final de X-Forwarded-For;
    lo que el visitante escriba antes se ignora (no se puede falsificar el último valor)."""
    forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    hops = max(1, int(config.get("TRUSTED_PROXY_HOPS", "1")))
    if len(forwarded) >= hops:
        return forwarded[-hops]
    return request.client.host if request.client else "desconocido"


def check(name: str, request: Request):
    if not LIMITS[name].allow(client_ip(request)):
        raise HTTPException(429, "Hiciste muchas solicitudes seguidas. Espera un momento e inténtalo de nuevo.")


# ---------------- Catálogo con precios en vivo ----------------

class CatalogStore:
    """Catálogo del CSV actualizado con los precios de la tienda cada 15 minutos."""

    def __init__(self):
        self.lock = threading.Lock()
        self.base = load_catalog()
        self.co_purchase = load_co_purchase()
        self.catalog, self.live, self.checked, self.updated = self.base, False, 0.0, None

    def get(self):
        with self.lock:
            wait = PRICE_TTL if self.live else PRICE_RETRY
            if time.time() - self.checked > wait:
                self.checked = time.time()
                try:
                    self.catalog = refresh_from_web(self.base, to_rows(fetch_products(timeout=8)))
                    self.live, self.updated = True, date.today()
                except Exception as e:  # la tienda no respondió: se mantiene la última versión
                    log.warning(json.dumps({"severity": "WARNING", "evento": "precios", "error": type(e).__name__}))
                    self.live = False
            return self.catalog, self.live

    def date_label(self) -> str:
        if self.updated:
            return self.updated.strftime("%d/%m/%Y")
        try:
            y, m, d = config.CATALOG_PATH.with_name("catalog_fecha.txt").read_text(encoding="utf-8").strip().split("-")
            return f"{d}/{m}/{y}"
        except (OSError, ValueError):
            return ""


@asynccontextmanager
async def lifespan(app_: FastAPI):
    app_.state.store = CatalogStore()
    vision.load()          # los modelos se cargan al iniciar: la primera foto no espera
    vision.load_filter()
    yield


app = FastAPI(title="Sneaker Doctor", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


# ---------------- Cabeceras de seguridad ----------------

# Sitios que pueden mostrar la página dentro de un iframe: la tienda, el editor de temas de Shopify y sus vistas previas
# (el editor de temas muestra la vista previa dentro de online-store-web.shopifyapps.com, dentro de admin.shopify.com)
# Solo la tienda de Clean Lab: no cualquier tienda de Shopify (*.myshopify.com) ni enlaces de vista previa de terceros
FRAME_ANCESTORS = config.get("FRAME_ANCESTORS", "https://cleanlab.pe https://*.cleanlab.pe https://cleanlab-pe.myshopify.com "
                                                "https://admin.shopify.com https://*.shopifyapps.com")
CSP = ("default-src 'self'; img-src 'self' data: blob: https://cdn.shopify.com; "
       "style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
       "connect-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
       f"frame-ancestors 'self' {FRAME_ANCESTORS}")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update({
        "Content-Security-Policy": CSP,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "Permissions-Policy": "geolocation=(), microphone=(), payment=()",
    })
    return response


@app.exception_handler(Exception)
async def unexpected(request: Request, exc: Exception):
    log.error(json.dumps({"severity": "ERROR", "evento": "error", "ruta": request.url.path, "tipo": type(exc).__name__}))
    return JSONResponse({"detail": "Algo salió mal. Inténtalo de nuevo."}, status_code=500)


# ---------------- Utilidades ----------------

def open_image(raw: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
        return image
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        raise HTTPException(400, "No pude abrir esa imagen. Prueba con otra foto en JPG o PNG.")


def view(item: dict) -> dict:
    """Producto tal como lo necesita la página (solo enlaces https)."""
    image = str(item.get("imagen", ""))
    if image.startswith("https://cdn.shopify.com/"):
        image += ("&" if "?" in image else "?") + "width=240"  # el CDN de Shopify entrega una versión pequeña
    return {"sku": item["sku"], "nombre": item["nombre"], "precio": item["precio"], "precio_antes": item.get("precio_antes"),
            "disponible": item.get("disponible", True), "imagen": image if image.startswith("https://") else "",
            "url": product_url(item), "contenido": item.get("contenido", []), "porque": item.get("porque", "")}


class KitIn(BaseModel):
    materiales: list[Material] = Field(min_length=1, max_length=len(MATERIALS))
    suela: Sole = "normal"
    necesidades: list[Need] = Field(default_factory=list, max_length=len(EXTRA_NEEDS))
    quitados: list[Sku] = Field(default_factory=list, max_length=30)
    agregados: list[Sku] = Field(default_factory=list, max_length=10)


def build_kit(data: KitIn, catalog, co_purchase):
    removed = {s for s in data.quitados if s in catalog.index}
    added = [s for s in data.agregados if s in catalog.index and s not in removed]
    rec = recommend(list(dict.fromkeys(data.materiales)), catalog, co_purchase, data.suela,
                    list(dict.fromkeys(data.necesidades)), removed, added)
    for group in ("kit", "sole_kit", "extras_kit"):
        for i in rec[group]:
            i["porque"] = reason(i["sku"], catalog)
    if rec["pack_option"]:
        for p in rec["pack_option"]["packs"]:
            p["porque"] = reason(p["sku"], catalog)
        for s in rec["pack_option"]["sueltos"]:
            s["porque"] = reason(s["sku"], catalog)
    return rec


# ---------------- Rutas ----------------

@app.get("/api/salud")  # Cloud Run reserva las rutas que terminan en "z", como /healthz
def health():
    return {"ok": True}


@app.get("/api/opciones")
def options():
    return {"materiales": MATERIALS, "suelas": SOLE_STATES, "necesidades": {k: v[0] for k, v in EXTRA_NEEDS.items()},
            "max_preguntas": config.MAX_QUESTIONS, "max_caracteres": chat.QUESTION_MAX}


@app.post("/api/diagnostico")
def diagnose(request: Request, foto: UploadFile = File(...), forzar: bool = Form(False)):
    check("foto", request)
    raw = foto.file.read(MAX_PHOTO + 1)
    if len(raw) > MAX_PHOTO:
        raise HTTPException(413, "La foto pesa más de 10 MB.")
    image = open_image(raw)
    score = vision.shoe_score(image)
    out = {"foto_id": feedback.photo_id(raw), "es_calzado": vision.is_shoe(score)}
    if not out["es_calzado"] and not forzar:
        return out
    ranking = vision.predict(image)
    if ranking is None:
        return {**out, "ranking": [], "sugeridos": [MATERIALS[0]], "incierto": True}
    result = {**out, "ranking": [{"material": m, "prob": round(p, 3)} for m, p in ranking],
              "sugeridos": vision.detected(ranking), "incierto": ranking[0][1] < 0.5, "verificado": False}
    # Si el modelo de Clean Lab no está seguro, Gemini mira la foto y da una segunda opinión
    if ranking[0][1] < CONFIDENT and GLOBAL_CHAT.allow():
        second = chat.material_check(chat.image_to_jpeg(image), MATERIALS)
        if second:
            result["verificado"] = True
            result["incierto"] = False
            if second != ranking[0][0]:
                result["sugeridos"] = [second]
    return result


@app.post("/api/kit")
def kit(data: KitIn, request: Request):
    check("kit", request)
    store: CatalogStore = request.app.state.store
    catalog, live = store.get()
    rec = build_kit(data, catalog, store.co_purchase)
    singles = rec["kit"] + rec["sole_kit"] + rec["extras_kit"]
    pack = rec["pack_option"]
    if pack:
        items = pack["packs"] + pack["sueltos"]
        gift = f"El pack además trae {', '.join(pack['extras'])}" if pack["extras"] else ""
        total, badge = pack["total"], f"Ahorras S/ {pack['ahorro']:.2f} con el pack frente a comprar suelto"
        alternative = {"items": [view(i) for i in singles], "total": rec["total"],
                       "final": final_price(rec["total"]), "carrito": cart_url(singles)}
    else:
        items, total, alternative, gift = singles, rec["total"], None, ""
        badge = f"Ahorras S/ {rec['ahorro']:.2f} con las promociones de hoy" if rec["ahorro"] > 0 else ""
    extra = rec["extra"]
    paid = final_price(total)
    upgrade = next_tier(total)
    # Para llegar al siguiente descuento: productos sugeridos y lo que se pagaría con cada uno
    in_kit = {i["sku"] for i in singles} | {i["sku"] for i in items} | set(data.quitados)
    suggested = []
    if upgrade and upgrade[0] <= 60:
        for s in suggestions(catalog, in_kit, upgrade[0]):
            i = {**item(catalog, s), "porque": reason(s, catalog)}
            suggested.append({**view(i), "pagarias": final_price(total + i["precio"])})
    return {
        "items": [view(i) for i in items], "total": round(total, 2), "badge": badge, "regalo": gift, "carrito": cart_url(items),
        # Descuento por volumen y envío gratis de cleanlab.pe (se aplican al pagar)
        "volumen": {"porcentaje": round(volume_rate(total) * 100), "descuento": round(total - paid, 2), "pagas": paid,
                    "siguiente": {"falta": upgrade[0], "porcentaje": round(upgrade[1] * 100)} if upgrade else None,
                    "sugeridos": suggested},
        "envio": {"gratis": paid >= FREE_SHIPPING, "desde": FREE_SHIPPING, "falta": round(max(0, FREE_SHIPPING - paid), 2)},
        "sueltos": alternative, "quitados": [view(i) for i in rec["removed"]],
        "extra": {"nombre": extra["nombre"], "precio": extra["precio"], "url": product_url(extra)} if extra else None,
        "intro": chat.fallback(data.materiales, data.suela), "guia_suela": chat.sole_text(data.suela),
        "precios": {"en_vivo": live, "fecha": store.date_label()},
    }


class Message(BaseModel):
    rol: Literal["user", "assistant"]
    texto: str = Field(max_length=4000)


class ChatIn(KitIn):
    pregunta: str = Field(min_length=1, max_length=chat.QUESTION_MAX)
    historial: list[Message] = Field(default_factory=list, max_length=40)
    foto: str | None = Field(default=None, max_length=MAX_CHAT_PHOTO * 4 // 3 + 4)  # JPEG en base64
    sesion: str | None = Field(default=None, pattern=r"^[0-9a-f-]{8,40}$")  # código anónimo de la visita


ACTION = re.compile(r"\[\[(agregar|quitar):([A-Z0-9-]{2,20})\]\]")


def actions(stream, found: list, valid: set):
    """Saca de la respuesta las etiquetas [[agregar:SKU]] / [[quitar:SKU]] y guarda las acciones válidas.
    Retiene el texto mientras una etiqueta llega a medias."""
    buf = ""
    for chunk in stream:
        buf += chunk
        if "[[" in buf and "]]" not in buf[buf.rfind("[["):]:
            continue  # etiqueta incompleta: esperar la siguiente parte
        for verb, sku in ACTION.findall(buf):
            if sku in valid and (verb, sku) not in found:
                found.append((verb, sku))
        yield ACTION.sub("", buf)
        buf = ""
    if buf:
        yield ACTION.sub("", buf)


def cleaned(stream):
    """Quita enlaces externos mientras la respuesta llega: retiene el texto solo si hay un enlace a medias."""
    buf = ""
    for chunk in stream:
        buf += chunk
        if "\n" in buf:
            head, buf = buf.rsplit("\n", 1)
            yield chat.clean(head, strip=False) + "\n"
        elif " " in buf and not re.search(r"!?\[[^\]]*$|\[[^\]]*\]\([^)]*$|https?://\S*$", buf):
            head, buf = buf.rsplit(" ", 1)
            yield chat.clean(head, strip=False) + " "
    if buf:
        yield chat.clean(buf, strip=False)


@app.post("/api/chat")
def ask(data: ChatIn, request: Request):
    check("chat_min", request)
    check("chat_dia", request)
    if not GLOBAL_CHAT.allow():
        raise HTTPException(429, "Hay muchas consultas en este momento. Intenta de nuevo en un minuto.")
    photo = None
    if data.foto:
        try:
            photo = chat.image_to_jpeg(open_image(base64.b64decode(data.foto, validate=True)))  # sin metadatos
        except (binascii.Error, ValueError):
            raise HTTPException(400, "Foto no válida.")
    store: CatalogStore = request.app.state.store
    catalog, _ = store.get()
    rec = build_kit(data, catalog, store.co_purchase)
    chosen = rec["kit"] + rec["sole_kit"] + rec["extras_kit"]
    products = [f"{i['nombre']} [{i['sku']}] (S/ {i['precio']:.2f}). Está en su kit porque: {i['porque']} "
                f"Modo de uso: {i['instrucciones'][:700] or 'ver la web'}" for i in chosen]
    if rec["pack_option"]:
        products += [f"{p['nombre']} [{p['sku']}] (S/ {p['precio']:.2f}), incluye: {', '.join(p['contenido'])}"
                     for p in rec["pack_option"]["packs"]]
    # Catálogo completo (nombre y precio): así el chat sabe todo lo que vende Clean Lab, aunque no esté en el kit
    in_kit = {i["sku"] for i in chosen} | set(data.quitados)
    available = catalog[catalog["disponible"]].drop_duplicates("nombre")
    products += [f"{r.nombre} [{r.Index}] (S/ {r.precio:.2f})" for r in available.itertuples() if r.Index not in in_kit]
    valid = set(available.index) | {i["sku"] for i in chosen}  # códigos que el chat puede agregar o quitar
    tiers = ", ".join(f"desde S/ {m} ahorra {round(r * 100)} %" for m, r in sorted(VOLUME_TIERS))
    products.append(f"Promociones de cleanlab.pe: descuento por volumen al pagar ({tiers}); envío GRATIS desde "
                    f"S/ {FREE_SHIPPING}; recojo en tienda gratis; compras seguras.")
    removed = [f"{i['nombre']}. Por qué se lo recomendamos: {i['porque']}" for i in rec["removed"]]
    history = [{"role": m.rol, "content": m.texto} for m in data.historial][-chat.HISTORY:]
    meta: dict = {}
    found: list = []

    def stream():
        reply = []
        for part in cleaned(actions(chat.answer_stream(data.materiales, data.pregunta, products, history, data.suela,
                                                       photo, meta, removed), found, valid)):
            reply.append(part)
            yield part
        if found:  # la página aplica los cambios al kit
            yield "\u0002" + json.dumps([{"accion": v, "sku": s} for v, s in found])
        if meta.get("source") == "guia":
            yield "\u0000guia"  # la página muestra "respuesta de la guía básica"
        # Conversación guardada sin datos personales (Cloud Logging → BigQuery, 1 año)
        log.info(json.dumps({"severity": "INFO", "evento": "chat", "sesion": data.sesion or "",
                             "pregunta": chat.redact(data.pregunta), "respuesta": chat.redact("".join(reply))[:4000],
                             "materiales": data.materiales, "suela": data.suela, "necesidades": data.necesidades,
                             "kit": sorted({i["sku"] for i in chosen}), "acciones": [f"{v}:{s}" for v, s in found],
                             "fuente": meta.get("source", "")}, ensure_ascii=False))

    return StreamingResponse(stream(), media_type="text/plain; charset=utf-8",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


class OpinionIn(BaseModel):
    foto_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    predicho: Material
    materiales: list[Material] = Field(min_length=1, max_length=len(MATERIALS))
    acerto: bool


@app.post("/api/opinion")
def opinion(data: OpinionIn, request: Request):
    check("opinion", request)
    # Se registra en Cloud Logging (sin datos personales ni la foto) para reentrenar el modelo más adelante
    log.info(json.dumps({"severity": "INFO", "evento": "opinion", **data.model_dump()}))
    return {"ok": True}


@app.get("/")
def index(embed: bool = False):
    """Con ?embed=1 la página se adapta para vivir dentro de cleanlab.pe (sin cabecera propia y con alto natural)."""
    page = (WEB / "index.html").read_text(encoding="utf-8")
    if embed:
        page = page.replace('<html lang="es">', '<html lang="es" class="embed">', 1)
    return HTMLResponse(page, headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=WEB), name="static")
app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")
