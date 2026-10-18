"""Sneaker Doctor · app de Streamlit.

streamlit run app.py
"""
import base64
import html
import io
import os
import re
import time
from pathlib import Path

import streamlit as st
from PIL import Image, UnidentifiedImageError

# En Streamlit Cloud las claves vienen en st.secrets; se pasan al entorno antes de leer la configuración.
try:
    for k, v in st.secrets.items():
        os.environ.setdefault(k, str(v))
except Exception:
    pass

from sneaker_doctor import MATERIALS, chat, config, feedback, vision  # noqa: E402
from sneaker_doctor.catalog import (EXTRA_NEEDS, SOLE_STATES, cart_url, load_catalog, load_co_purchase,  # noqa: E402
                                    products_for, recommend, refresh_from_web)
from sneaker_doctor.web_catalog import fetch_products, to_rows  # noqa: E402

ASSETS = Path(__file__).parent / "assets"
BOT, USER = str(ASSETS / "bot.png"), str(ASSETS / "user.png")
# Preguntas sugeridas: etiqueta corta → pregunta completa
SUGGESTIONS = {"Mancha de barro": "¿Cómo saco una mancha de barro?",
               "¿Lavadora?": "¿Puedo lavarlas en la lavadora?",
               "Protector": "¿Cada cuánto aplico el protector?",
               "¿Qué modelo es?": "¿Qué marca y modelo es mi zapatilla?"}

st.set_page_config(page_title="Sneaker Doctor · Clean Lab", page_icon=str(ASSETS / "bot.png"), layout="wide")


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode() if path.exists() else ""


st.markdown(f"""
<style>
:root {{ --navy:#1B2E46; --teal:#9AC5C2; --yellow:#FFFF00; --soft:#F2F5F8; --line:#DCE3EA; --muted:#5B6B7F; }}
/* Pantalla completa: la página no se desplaza; cada panel tiene su propio scroll */
html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{ overflow: hidden; }}
header[data-testid="stHeader"] {{ display: none; }}
.block-container {{ max-width: none !important; padding: 12px 24px 0 !important; }}
.sd-hero {{ background: var(--navy); border-radius: 14px; padding: 8px 20px; display:flex; align-items:center; gap:14px; margin-bottom: 10px; height: 64px; }}
.sd-hero img {{ height: 50px; }}
.sd-hero h1 {{ color:#fff; margin:0; padding:0; font-size: 1.5rem; font-weight: 800; line-height: 1.1; }}
.sd-hero p {{ color: var(--teal); margin:0; font-size: .9rem; }}
.st-key-left_panel, .st-key-kit_panel {{ max-height: max(320px, calc(100vh - 136px)) !important; overflow-y: auto !important; overflow-x: hidden; padding: 0 8px 18px 0 !important; }}
/* Chat: ocupa el alto disponible; el contenedor de Streamlit se mantiene en el último mensaje */
div.stVerticalBlock.st-key-chat_msgs, div[data-testid="stLayoutWrapper"]:has(> div.st-key-chat_msgs) {{ height: max(220px, calc(100vh - 262px)) !important; min-height: max(220px, calc(100vh - 262px)) !important; max-height: none !important; }}
.st-key-left_panel > div:first-child, .st-key-kit_panel > div:first-child {{ margin-top: 0 !important; }}
/* En Streamlit Cloud el distintivo de la esquina inferior derecha tapaba el botón de enviar */
[data-testid="stChatInput"] {{ margin-right: 52px; }}
/* Ventanas bajas o angostas (celular): sin paneles fijos, la página se desplaza normalmente */
@media (max-height: 620px), (max-width: 900px) {{
  html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{ overflow: auto !important; }}
  .st-key-left_panel, .st-key-kit_panel {{ max-height: none !important; overflow: visible !important; }}
  div.stVerticalBlock.st-key-chat_msgs, div[data-testid="stLayoutWrapper"]:has(> div.st-key-chat_msgs) {{ height: 460px !important; min-height: 460px !important; }}
}}.sd-step {{ font-size:.78rem; font-weight:800; letter-spacing:.08em; text-transform:uppercase; color: var(--muted); margin: 6px 0 6px; }}
.sd-result {{ background: var(--soft); border-radius: 14px; padding: 14px 16px; }}
.sd-result .label {{ color: var(--muted); font-size: .85rem; }}
.sd-result .value {{ font-size: 1.6rem; font-weight: 800; color: var(--navy); line-height: 1.2; }}
.sd-bar {{ display:flex; align-items:center; gap:8px; font-size:.85rem; margin-top:6px; color: var(--navy); }}
.sd-bar .track {{ flex:1; background:#fff; border:1px solid var(--line); border-radius: 99px; height: 8px; overflow:hidden; }}
.sd-bar .fill {{ background: var(--navy); height: 100%; }}
.sd-warn {{ background:#FFF8D6; border:1px solid #F1D96B; color:#5A4A00; border-radius: 10px; padding: 8px 12px; font-size:.88rem; margin-top:10px; }}
.sd-list {{ display:flex; flex-direction:column; gap: 10px; margin: 4px 0 12px; }}
.sd-item {{ display:grid; grid-template-columns: 88px 1fr auto; align-items:center; gap: 14px; border:1px solid var(--line);
  border-radius: 14px; padding: 10px 14px 10px 10px; background:#fff; }}
.sd-item img {{ width: 88px; height: 88px; object-fit: contain; background: var(--soft); border-radius: 10px; }}
.sd-item .name {{ font-weight: 800; font-size: 1rem; color: var(--navy); }}
.sd-item .incl {{ font-size: .8rem; color: var(--muted); margin-top: 2px; }}
.sd-item .prices {{ margin-top: 6px; }}
.sd-item .now {{ font-weight: 800; font-size: 1.05rem; color: var(--navy); }}
.sd-item .before {{ text-decoration: line-through; color: var(--muted); font-size: .85rem; margin-left: 8px; }}
.sd-item .out {{ color:#B42318; font-size:.8rem; font-weight:700; }}
.sd-item a.buy {{ background: var(--yellow); color: var(--navy) !important; font-weight: 800; border-radius: 10px; padding: 9px 14px;
  text-decoration:none; font-size:.85rem; white-space: nowrap; }}
.sd-item a.buy:hover {{ filter: brightness(.95); }}
.sd-total {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:10px; background: var(--navy); color:#fff; border-radius:14px; padding: 12px 16px; }}
.sd-total .amount {{ font-size: 1.5rem; font-weight: 800; }}
.sd-badge {{ background: var(--yellow); color: var(--navy); font-weight: 800; border-radius: 8px; padding: 2px 10px; font-size: .85rem; }}
.sd-cart {{ display:block; text-align:center; background: var(--yellow); color: var(--navy) !important; font-weight: 800;
  border-radius: 12px; padding: 11px 16px; margin-top: 8px; text-decoration: none; }}
.sd-cart:hover {{ filter: brightness(.95); }}
.sd-typing {{ display:flex; gap:5px; padding: 10px 2px; }}
.sd-typing span {{ width:8px; height:8px; border-radius:50%; background: var(--muted); animation: sd-blink 1.2s infinite ease-in-out; }}
.sd-typing span:nth-child(2) {{ animation-delay: .2s; }}
.sd-typing span:nth-child(3) {{ animation-delay: .4s; }}
@keyframes sd-blink {{ 0%, 80%, 100% {{ opacity:.25; transform: translateY(0); }} 40% {{ opacity:1; transform: translateY(-3px); }} }}
.sd-sub {{ font-weight: 700; margin: 10px 0 0; color: var(--navy); }}
.sd-empty {{ border: 2px dashed var(--line); border-radius: 16px; padding: 28px; text-align:center; color: var(--muted); }}
.sd-steps {{ display:grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 14px; }}
.sd-steps div {{ background: var(--soft); border-radius: 14px; padding: 14px; color: var(--navy); font-size:.9rem; }}
.sd-steps b {{ display:block; font-size: 1.4rem; color: var(--navy); }}
</style>
<div class="sd-hero">
  <img src="data:image/png;base64,{b64(ASSETS / 'logo.png')}" alt="Clean Lab">
  <div><h1>Sneaker Doctor</h1><p>Sube una foto de tu zapatilla y te decimos cómo limpiarla</p></div>
</div>""", unsafe_allow_html=True)


@st.cache_data(ttl=3600)
def data():
    """Catálogo local con precios, promociones, stock e imágenes actualizados desde cleanlab.pe (cada hora)."""
    catalog = load_catalog()
    try:
        catalog = refresh_from_web(catalog, to_rows(fetch_products(timeout=8)))
    except Exception:
        pass  # sin conexión con la tienda: se usan los datos del CSV
    return catalog, load_co_purchase()


@st.cache_data(show_spinner=False, max_entries=20)
def diagnose(raw: bytes):
    """Resultado del modelo por foto: no se recalcula al cambiar la suela, las necesidades o al chatear."""
    return vision.predict(Image.open(io.BytesIO(raw)))


@st.cache_data(show_spinner=False, max_entries=20)
def photo_for_chat(raw: bytes) -> bytes:
    return chat.image_to_jpeg(Image.open(io.BytesIO(raw)))


def cart_button(items: list[dict]):
    url = cart_url(items)
    if url:
        st.markdown(f"<a class='sd-cart' href='{html.escape(url)}' target='_blank'>Agregar todo al carrito</a>",
                    unsafe_allow_html=True)


@st.cache_resource
def rate_limit():
    return chat.RateLimit(config.GLOBAL_PER_MINUTE)


def safe_url(url) -> str:
    """Solo enlaces https (evita javascript: u otros esquemas si la web cambiara)."""
    return url if str(url).startswith("https://") else ""


def card(item: dict) -> str:
    """Fila de producto en HTML: imagen, nombre, contenido, precio y botón de compra."""
    e = html.escape
    item = {**item, "imagen": safe_url(item.get("imagen", "")), "url": safe_url(item.get("url", ""))}
    img = f"<img src='{e(item['imagen'])}' alt='{e(item['nombre'])}'>" if item.get("imagen") else "<div></div>"
    incl = f"<div class='incl'>Incluye: {e(', '.join(item['contenido']))}</div>" if item.get("contenido") else ""
    before = f"<span class='before'>S/ {item['precio_antes']:.2f}</span>" if item.get("precio_antes") else ""
    out = "<div class='out'>Agotado</div>" if not item.get("disponible", True) else ""
    buy = f"<a class='buy' href='{e(item['url'])}' target='_blank'>Comprar</a>" if item.get("url") else ""
    return (f"<div class='sd-item'>{img}<div><div class='name'>{e(item['nombre'])}</div>{incl}"
            f"<div class='prices'><span class='now'>S/ {item['precio']:.2f}</span>{before}</div>{out}</div>{buy}</div>")


def grid(items: list[dict]):
    st.markdown("<div class='sd-list'>" + "".join(card(i) for i in items) + "</div>", unsafe_allow_html=True)


def total_bar(amount: float, badge: str = ""):
    tag = f"<span class='sd-badge'>{badge}</span>" if badge else ""
    st.markdown(f"<div class='sd-total'><span>Total</span><span class='amount'>S/ {amount:.2f}</span>{tag}</div>",
                unsafe_allow_html=True)


catalog, co_purchase = data()
left, middle, right = st.columns([1.05, 1.25, 1.1], gap="medium")

# ---------------- Columna izquierda: foto y diagnóstico ----------------
left.markdown("<div class='sd-step'>1 · Tu zapatilla</div>", unsafe_allow_html=True)
with left, st.container(key="left_panel"):
    photo = st.file_uploader("Foto de la zapatilla", type=["jpg", "jpeg", "png", "webp"], label_visibility="collapsed")
    if photo is None and os.getenv("SD_DEMO_IMAGE"):  # solo para pruebas locales
        photo = os.getenv("SD_DEMO_IMAGE")
    raw, image = None, None
    if photo is not None:
        raw = photo.getvalue() if hasattr(photo, "getvalue") else Path(photo).read_bytes()
        try:  # archivos que no son imágenes, dañados o "bombas" de píxeles gigantes
            image = Image.open(io.BytesIO(raw))
            image.load()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            st.markdown("<div class='sd-warn'>No pude abrir esa imagen. Prueba con otra foto en JPG o PNG.</div>",
                        unsafe_allow_html=True)
            photo, raw = None, None
    st.caption("Tu foto se analiza para recomendarte productos y el chat la envía a Google Gemini para responderte. "
               "No pidas ni compartas datos personales en el chat.")

    if photo is None:
        st.markdown("""
        <div class='sd-empty'>Sube una foto <b>de costado</b>, con buena luz y la zapatilla completa.
          <div class='sd-steps'>
            <div><b>1</b>Sube tu foto</div>
            <div><b>2</b>Detectamos el material</div>
            <div><b>3</b>Recibe tu kit y cómo usarlo</div>
          </div>
        </div>""", unsafe_allow_html=True)
        materials, sole, needs, rec = [], None, [], None
    else:
        with st.spinner("Analizando el material…"):
            ranking = diagnose(raw)
        c_img, c_res = st.columns([2, 3], gap="small")
        c_img.image(image, width="stretch")
        with c_res:
            if ranking is None:
                default = [MATERIALS[0]]
                st.markdown("<div class='sd-warn'>El modelo todavía no está cargado: elige el material.</div>", unsafe_allow_html=True)
            else:
                default = vision.detected(ranking)
                title = default[0].capitalize() if len(default) == 1 else f"{default[0].capitalize()} y {default[1]}"
                bars = "".join(f"<div class='sd-bar'><span style='width:62px'>{m.capitalize()}</span>"
                               f"<div class='track'><div class='fill' style='width:{p * 100:.0f}%'></div></div></div>"
                               for m, p in ranking[:3])
                warn = ("<div class='sd-warn'>No estoy seguro del material. Revisa la sugerencia y corrígela si hace falta."
                        "</div>") if ranking[0][1] < 0.5 else ""
                st.markdown(f"<div class='sd-result'><div class='label'>Material detectado</div>"
                            f"<div class='value'>{title}</div>{bars}{warn}</div>", unsafe_allow_html=True)
        materials = st.multiselect("¿Es correcto? Corrígelo o agrega otro material", MATERIALS, default=default,
                                   format_func=str.capitalize, placeholder="Elige uno o más materiales")
        if ranking is not None:
            photo_id = feedback.photo_id(raw)
            c_q, c_t = st.columns([3, 1], vertical_alignment="center")
            c_q.markdown("**¿Acertamos el material?**")
            with c_t:
                rating = st.feedback("thumbs", key=f"fb_{photo_id}")
            share = st.checkbox("Pueden usar mi foto para mejorar el detector", key=f"fb_ok_{photo_id}")
            answer = (photo_id, rating, tuple(materials), share)
            if (rating is not None and st.session_state.get("fb_saved") != answer
                    and st.session_state.get("fb_count", 0) < config.MAX_FEEDBACK):
                feedback.save(raw, ranking, materials, rating == 1, share)
                st.session_state.fb_saved = answer
                st.session_state.fb_count = st.session_state.get("fb_count", 0) + 1
                st.toast("¡Gracias! Esto nos ayuda a mejorar el detector.")

        st.markdown("<div class='sd-step'>2 · Cuéntanos un poco más</div>", unsafe_allow_html=True)
        sole = st.radio("¿Cómo está la suela?", list(SOLE_STATES), format_func=SOLE_STATES.get, index=0)
        needs = st.pills("¿Algo más que te preocupe? (opcional)", list(EXTRA_NEEDS), format_func=lambda k: EXTRA_NEEDS[k][0],
                         selection_mode="multi") or []

# ---------------- Columna central: el kit ----------------
middle.markdown("<div class='sd-step'>3 · Tu kit Clean Lab</div>", unsafe_allow_html=True)
with middle, st.container(key="kit_panel"):
    if photo is None:
        st.markdown("<div class='sd-empty'>Aquí aparecerán los productos Clean Lab indicados para tu zapatilla, "
                    "con la opción de mejor precio.</div>", unsafe_allow_html=True)
    elif not materials:
        st.info("Elige al menos un material.")
        rec = None
    else:
        rec = recommend(materials, catalog, co_purchase, sole or "normal", needs)
        singles = rec["kit"] + rec["sole_kit"] + rec["extras_kit"]
        pack = rec["pack_option"]

        if pack:  # la opción más barata va primero
            grid(pack["packs"] + pack["sueltos"])
            bonus = f" · el pack además trae {', '.join(pack['extras'])}" if pack["extras"] else ""
            total_bar(pack["total"], f"Mejor precio: ahorras S/ {pack['ahorro']:.2f} frente a comprar suelto{bonus}")
            cart_button(pack["packs"] + pack["sueltos"])
            with st.expander(f"Prefiero comprar los productos sueltos (S/ {rec['total']:.2f})"):
                grid(singles)
        else:
            grid(singles)
            total_bar(rec["total"], f"Ahorras S/ {rec['ahorro']:.2f} con las promociones de hoy" if rec["ahorro"] > 0 else "")
            cart_button(singles)
        if rec["extra"]:
            st.markdown(f"Los clientes que compran este kit también suelen llevar **{rec['extra']['nombre']}** "
                        f"(S/ {rec['extra']['precio']:.2f}).")
        st.caption("Precios, promociones e imágenes de cleanlab.pe, actualizados cada hora.")

# ---------------- Columna derecha: chat ----------------
def typing(stream, dots):
    """Quita los puntos de 'escribiendo' con la primera parte y muestra la respuesta palabra por palabra."""
    first = True
    for chunk in stream:
        if first:
            dots.empty()
            first = False
        for word in re.split(r"(\s+)", chunk):
            if word:
                yield word
                time.sleep(0.018)
    if first:
        dots.empty()


def kit_change(rec, sole, before) -> str:
    """Aviso en el chat cuando cambia la suela o las necesidades: qué productos entran o salen del kit."""
    now = {i["nombre"] for i in rec["sole_kit"] + rec["extras_kit"]} if rec else set()
    added, removed = sorted(now - before["kit"]), sorted(before["kit"] - now)
    parts = []
    if added:
        parts.append(f"agregué **{', '.join(added)}**")
    if removed:
        parts.append(f"quité {', '.join(removed)}")
    text = f"Actualicé tu kit: {' y '.join(parts)}." if parts else "Actualicé tu kit."
    if sole != before["sole"]:
        text += "\n\n" + chat.sole_text(sole or "normal")
    return text


@st.fragment
def chat_panel(materials, sole, needs, rec, photo_jpeg, photo_key):
    """Solo esta parte se vuelve a ejecutar al preguntar: el diagnóstico y el kit no se recalculan."""
    st.markdown("<div class='sd-step'>4 · Pregúntale a Sneaker Doctor</div>", unsafe_allow_html=True)
    shoe = (photo_key, tuple(materials))  # la conversación se reinicia solo con otra foto u otro material
    kit = {"sole": sole, "needs": tuple(needs),
           "kit": {i["nombre"] for i in rec["sole_kit"] + rec["extras_kit"]} if rec else set()}
    if st.session_state.get("shoe") != shoe:
        st.session_state.shoe = shoe
        intro = (chat.fallback(materials, sole or "normal") if materials else
                 "¡Hola! Sube una foto de tu zapatilla y te explico paso a paso cómo limpiarla con productos Clean Lab.")
        st.session_state.messages = [{"role": "assistant", "content": intro}]
        st.session_state.source = ""
    elif materials and (sole, tuple(needs)) != (st.session_state.kit["sole"], st.session_state.kit["needs"]):
        st.session_state.messages.append({"role": "assistant", "content": kit_change(rec, sole, st.session_state.kit),
                                          "note": True})
    st.session_state.kit = kit

    box = st.container(height=480, border=True, key="chat_msgs")  # el alto real lo fija el CSS según la pantalla
    with box:
        for m in st.session_state.messages:
            st.chat_message(m["role"], avatar=BOT if m["role"] == "assistant" else USER).write(m["content"])
        if st.session_state.get("source") == "guia":
            st.caption("Respuesta de la guía básica: el chat con IA no está disponible en este momento.")

    picked = st.pills("Preguntas frecuentes", list(SUGGESTIONS), selection_mode="single", label_visibility="collapsed",
                      key=f"sug_{len(st.session_state.messages)}", disabled=not materials)
    limit = st.session_state.get("asked", 0) >= config.MAX_QUESTIONS
    typed = st.chat_input("Llegaste al límite de preguntas por hoy" if limit else "Escribe tu pregunta…",
                          disabled=not materials or limit, max_chars=chat.QUESTION_MAX)
    question = typed or SUGGESTIONS.get(picked)
    if not (question and materials) or limit:
        return
    if not rate_limit().allow():
        st.toast("Hay muchas consultas en este momento. Intenta de nuevo en un minuto.")
        return

    chosen = rec["kit"] + rec["sole_kit"] + rec["extras_kit"]
    # Productos recomendados con su modo de uso oficial; el resto del catálogo útil, solo con nombre y precio
    products = [f"{i['nombre']} (S/ {i['precio']:.2f}). Modo de uso: {i['instrucciones'][:700] or 'ver la web'}"
                for i in chosen]
    if rec["pack_option"]:
        products += [f"{p['nombre']} (S/ {p['precio']:.2f}), incluye: {', '.join(p['contenido'])}"
                     for p in rec["pack_option"]["packs"]]
    products += [f"{r.nombre} (S/ {r.precio:.2f})" for r in products_for(materials, catalog).itertuples()
                 if r.Index not in {i['sku'] for i in chosen}]

    meta = {}
    with box:
        st.chat_message("user", avatar=USER).write(question)
        with st.chat_message("assistant", avatar=BOT):
            dots = st.empty()
            dots.markdown("<div class='sd-typing'><span></span><span></span><span></span></div>", unsafe_allow_html=True)
            # Los avisos de cambio de kit no se envían al modelo (solo pregunta y respuesta alternadas)
            history = [m for m in st.session_state.messages[1:] if not m.get("note")]
            stream = chat.answer_stream(materials, question, products, history, sole, photo_jpeg, meta)
            reply = chat.clean(st.write_stream(typing(stream, dots)))
    st.session_state.messages += [{"role": "user", "content": question}, {"role": "assistant", "content": reply}]
    st.session_state.source = meta.get("source", "")
    st.session_state.asked = st.session_state.get("asked", 0) + 1
    st.rerun(scope="fragment")  # limpia la pregunta sugerida elegida


with right, st.container(key="chat_panel"):
    chat_panel(materials, sole, needs, rec, photo_for_chat(raw) if raw else None, feedback.photo_id(raw) if raw else None)
