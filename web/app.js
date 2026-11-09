// Sneaker Doctor · página web. Habla con la API del mismo servidor (/api/...).
// Seguridad: todo texto que llega del servidor o del usuario se escapa antes de mostrarse.
"use strict";

const $ = (s) => document.querySelector(s);
// Modo incrustado (?embed=1): la página vive dentro de cleanlab.pe en un iframe
const EMBED = document.documentElement.classList.contains("embed");
const TARGET = EMBED ? `target="_top"` : `target="_blank" rel="noopener"`; // en la tienda, la compra sigue en la misma pestaña
const MAX_PHOTO = 10 * 1024 * 1024;
const SUGGESTIONS = {
  "Mancha de barro": "¿Cómo saco una mancha de barro?",
  "¿Lavadora?": "¿Puedo lavarlas en la lavadora?",
  "Protector": "¿Cada cuánto aplico el protector?",
  "¿Qué modelo es?": "¿Qué marca y modelo es mi zapatilla?",
};
const HELLO = "¡Hola! Sube una foto de tu zapatilla y te explico paso a paso cómo limpiarla con productos Clean Lab.";

const state = {
  opts: null, fotoId: null, photo64: null, ranking: [], materials: [], suela: "normal", needs: [], quitados: [],
  forced: false, file: null, kit: null, chatKey: "", kitKey: "", messages: [], asked: 0, busy: false, rated: false,
};

// ---------------- Utilidades ----------------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => `S/ ${Number(n).toFixed(2)}`;
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const safeUrl = (u) => (/^https:\/\//.test(u || "") ? u : "");

function toast(text) {
  // Dentro de la tienda el aviso lo muestra cleanlab.pe: el iframe es alto y un aviso fijo podría quedar fuera de la vista
  if (EMBED && window.parent !== window) return window.parent.postMessage({ tipo: "sneaker-doctor:aviso", texto: String(text).slice(0, 200) }, "*");
  const t = $("#toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 3500);
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = "Algo salió mal. Inténtalo de nuevo.";
    try { const body = await res.json(); if (typeof body.detail === "string") detail = body.detail; } catch (_) { /* sin cuerpo */ }
    throw new Error(detail);
  }
  return res;
}
const postJSON = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

// Markdown mínimo y seguro: negritas, listas y párrafos (sobre texto ya escapado; sin enlaces)
function md(text) {
  const blocks = [];
  let list = null;
  const close = () => { if (list) { blocks.push(`<${list.tag}>${list.items.join("")}</${list.tag}>`); list = null; } };
  for (const raw of esc(text).split("\n")) {
    const line = raw.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
    const ol = line.match(/^\s*\d+[.)]\s+(.*)/), ul = line.match(/^\s*[-*•]\s+(.*)/);
    if (ol || ul) {
      const tag = ol ? "ol" : "ul";
      if (!list || list.tag !== tag) { close(); list = { tag, items: [] }; }
      list.items.push(`<li>${(ol || ul)[1]}</li>`);
    } else if (line.trim()) { close(); blocks.push(`<p>${line}</p>`); } else close();
  }
  close();
  return blocks.join("");
}

// Foto: se reduce en el navegador (más rápido y sin metadatos como el GPS)
async function shrink(file, maxSide, quality) {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return new Promise((ok) => canvas.toBlob(ok, "image/jpeg", quality));
}
const toBase64 = (blob) => new Promise((ok) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1]); r.readAsDataURL(blob); });

// ---------------- Opciones (chips) ----------------
function chips(container, entries, isOn, onClick) {
  container.innerHTML = entries.map(([value, label]) =>
    `<button type="button" class="chip" data-v="${esc(value)}" aria-pressed="${isOn(value)}">${esc(label)}</button>`).join("");
  container.onclick = (e) => { const b = e.target.closest(".chip"); if (b && !b.disabled) onClick(b.dataset.v); };
}
function renderOptions() {
  const o = state.opts;
  chips($("#materials"), o.materiales.map((m) => [m, cap(m)]), (m) => state.materials.includes(m), (m) => {
    state.materials = state.materials.includes(m) ? state.materials.filter((x) => x !== m) : [...state.materials, m];
    renderOptions(); updateKit();
  });
  chips($("#soles"), Object.entries(o.suelas), (s) => state.suela === s, (s) => { state.suela = s; renderOptions(); updateKit({ changed: true }); });
  chips($("#needs"), Object.entries(o.necesidades), (n) => state.needs.includes(n), (n) => {
    state.needs = state.needs.includes(n) ? state.needs.filter((x) => x !== n) : [...state.needs, n];
    renderOptions(); updateKit({ changed: true });
  });
  chips($("#suggestions"), Object.keys(SUGGESTIONS).map((k) => [k, k]), () => false, (k) => send(SUGGESTIONS[k]));
  $("#suggestions").querySelectorAll(".chip").forEach((b) => (b.disabled = !chatReady()));
}

// ---------------- 1 · Foto y diagnóstico ----------------
async function handleFile(file) {
  if (!file) return;
  if (file.size > MAX_PHOTO) return toast("La foto pesa más de 10 MB.");
  state.file = file; state.forced = false; state.rated = false; state.quitados = [];
  let upload = file;
  state.photo64 = null;
  try {
    upload = await shrink(file, 1280, 0.9);
    state.photo64 = await toBase64(await shrink(file, 768, 0.85));
  } catch (_) { /* formato que el navegador no puede abrir: se envía tal cual */ }
  $("#preview").src = URL.createObjectURL(upload);
  $("#intro").hidden = true; // la portada da paso a la herramienta
  $("#tool").hidden = false;
  $("#diagnosis").hidden = false;
  $("#result").innerHTML = `<div class="label">Revisando la foto…</div><div class="typing"><span></span><span></span><span></span></div>`;
  $("#notshoe").hidden = true;
  $("#details").hidden = true;
  state.upload = upload;
  await diagnose();
}

async function diagnose() {
  const form = new FormData();
  form.append("foto", state.upload, "foto.jpg");
  form.append("forzar", state.forced ? "true" : "false");
  let data;
  try { data = await (await api("/api/diagnostico", { method: "POST", body: form })).json(); }
  catch (e) { $("#result").innerHTML = `<div class="warn">${esc(e.message)}</div>`; return resetKit(); }
  state.fotoId = data.foto_id;
  if (!data.es_calzado && !state.forced) {
    $("#result").innerHTML = "";
    $("#notshoe").hidden = false;
    state.materials = [];
    return resetKit();
  }
  state.ranking = data.ranking || [];
  state.materials = data.sugeridos;
  const title = state.materials.length === 1 ? cap(state.materials[0]) : `${cap(state.materials[0])} y ${state.materials[1]}`;
  const bars = state.ranking.slice(0, 3).map((r) =>
    `<div class="bar"><span>${esc(cap(r.material))}</span><div class="track"><div class="fill" data-w="${Math.round(r.prob * 100)}"></div></div></div>`).join("");
  const changed = data.verificado && state.ranking.length && state.ranking[0].material !== state.materials[0];
  $("#result").innerHTML = `<div class="label">Material detectado</div><div class="value">${esc(title)}</div>` +
    (changed ? `<div class="label">Confirmado con IA mirando tu foto</div>` : bars) +
    (data.incierto ? `<div class="warn">No estoy seguro del material. Revisa la sugerencia y corrígela si hace falta.</div>` : "");
  // El ancho se fija desde JavaScript: la política de seguridad (CSP) no permite estilos escritos en el HTML
  $("#result").querySelectorAll(".fill").forEach((f) => (f.style.width = `${Number(f.dataset.w)}%`));
  $("#details").hidden = false;
  $("#feedback").hidden = !state.ranking.length;
  $("#feedback").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
  renderOptions();
  updateKit();
}

$("#file").addEventListener("change", (e) => handleFile(e.target.files[0]));
// Se puede arrastrar la foto sobre la portada o sobre "Cambiar foto"
for (const zone of [$("#drop"), $("#intro")]) {
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("over"); handleFile(e.dataTransfer.files[0]); });
}
$("#cta").addEventListener("click", () => $("#file").click());
$("#force").addEventListener("click", () => { state.forced = true; $("#notshoe").hidden = true; diagnose(); });

$("#feedback").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-ok]");
  if (!b || state.rated || !state.ranking.length) return;
  state.rated = true;
  b.setAttribute("aria-pressed", "true");
  try {
    await postJSON("/api/opinion", { foto_id: state.fotoId, predicho: state.ranking[0].material, materiales: state.materials, acerto: b.dataset.ok === "1" });
    toast("¡Gracias! Esto nos ayuda a mejorar el detector.");
  } catch (err) { toast(err.message); }
});

// ---------------- 3 · Kit ----------------
function resetKit(message = "Aquí aparecerán los productos Clean Lab indicados para tu zapatilla, con la opción de mejor precio.") {
  state.kit = null;
  $("#kit").hidden = true;
  $("#kit-empty").hidden = false;
  $("#kit-empty").textContent = message;
  resetChat();
}

function card(i, removable) {
  const img = safeUrl(i.imagen) ? `<img src="${esc(i.imagen)}" alt="" loading="lazy">` : `<div class="noimg"></div>`;
  const incl = i.contenido?.length ? `<div class="incl">Incluye: ${esc(i.contenido.join(", "))}</div>` : "";
  const before = i.precio_antes ? `<span class="before">${money(i.precio_antes)}</span>` : "";
  const why = i.porque ? `<details><summary>¿Por qué te lo recomendamos?</summary><p>${esc(i.porque)}</p></details>` : "";
  const buy = safeUrl(i.url) ? `<a class="buy" href="${esc(i.url)}" ${TARGET}>Comprar</a>` : "";
  const x = removable ? `<button type="button" class="remove" data-rm="${esc(i.sku)}" aria-label="Quitar ${esc(i.nombre)} del kit" title="Quitar del kit">✕</button>` : "";
  return `<div class="item">${x}${img}<div><div class="name">${esc(i.nombre)}</div>${incl}
    <div class="prices"><span class="now">${money(i.precio)}</span>${before}</div>${i.disponible ? "" : `<div class="out">Agotado</div>`}${why}</div>${buy}</div>`;
}

function totalBox(k) {
  const v = k.volumen;
  const lines = v.porcentaje
    ? `<div class="row"><span>Subtotal</span><span>${money(k.total)}</span></div>
       <div class="row"><span>Descuento por volumen (${v.porcentaje} %)</span><span>−${money(v.descuento)}</span></div>` : "";
  const save = k.badge ? `<p class="save">${esc(k.badge)}</p>` : "";
  const gift = k.regalo ? `<p class="gift">🎁 ${esc(k.regalo)}</p>` : "";
  // Siguiente escalón de descuento: barra de progreso (solo si está cerca)
  const s = v.siguiente;
  const next = s && s.falta <= 60
    ? `<div class="progress"><p>Te faltan <b>${money(s.falta)}</b> para <b>${s.porcentaje} % de descuento</b></p>
       <div class="ptrack"><div class="pfill" data-w="${Math.round((k.total / (k.total + s.falta)) * 100)}"></div></div></div>` : "";
  const extras = save || gift || next ? `<div class="extras">${save}${gift}${next}</div>` : "";
  return `<div class="total">${lines}
    <div class="row grand"><span>Total</span><span class="amount">${money(v.pagas)}</span></div>${extras}</div>`;
}
function perks(k) {
  const ship = k.envio.gratis ? "Tu pedido tiene envío GRATIS" : `Te faltan ${money(k.envio.falta)} para envío GRATIS`;
  return `<ul class="store-perks"><li>${ship}</li><li>Compras seguras</li><li>Recojo en tienda GRATIS</li></ul>`;
}

let kitRequest = 0;
async function updateKit({ changed = false, note = "" } = {}) {
  if (!state.materials.length) return resetKit("Elige al menos un material.");
  const id = ++kitRequest;
  const before = new Set((state.kit?.items || []).map((i) => i.nombre));
  let k;
  try { k = await (await postJSON("/api/kit", kitBody())).json(); } catch (e) { return toast(e.message); }
  if (id !== kitRequest) return; // llegó una respuesta más nueva
  const soleChanged = state.kit && state.kitKey.split("|")[0] !== state.suela;
  state.kit = k;
  $("#kit-empty").hidden = true;
  const kit = $("#kit");
  kit.hidden = false;
  const alt = k.sueltos ? `<details class="alt"><summary>Prefiero comprar los productos sueltos (${money(k.sueltos.final)}${k.sueltos.final < k.sueltos.total ? " con descuento por volumen" : ""})</summary>
      <div class="list">${k.sueltos.items.map((i) => card(i, false)).join("")}</div>
      ${safeUrl(k.sueltos.carrito) ? `<a class="button cart" href="${esc(k.sueltos.carrito)}" ${TARGET}>Agregar los sueltos al carrito</a>` : ""}</details>` : "";
  const removed = k.quitados.length ? `<div class="removed"><h3>Quitaste de tu kit</h3><ul>${k.quitados.map((i) =>
      `<li><b>${esc(i.nombre)}</b> <button type="button" class="link" data-back="${esc(i.sku)}">Volver a agregar</button>
       ${i.porque ? `<span class="why">Te lo recomendamos porque: ${esc(i.porque)}</span>` : ""}</li>`).join("")}</ul></div>` : "";
  const extra = k.extra ? `<p class="small">Los clientes que compran este kit también suelen llevar <b>${esc(k.extra.nombre)}</b> (${money(k.extra.precio)}).</p>` : "";
  const prices = k.precios.en_vivo ? "Precios, promociones e imágenes en vivo de cleanlab.pe."
    : `Precios de cleanlab.pe${k.precios.fecha ? ` al ${esc(k.precios.fecha)}` : ""}. Confírmalos en la tienda antes de comprar.`;
  kit.innerHTML = (k.items.length ? `<div class="list">${k.items.map((i) => card(i, true)).join("")}</div>
      ${totalBox(k)}
      ${safeUrl(k.carrito) ? `<a class="button cart" href="${esc(k.carrito)}" ${TARGET}>Agregar todo al carrito</a>` : ""}
      ${perks(k)}`
      : `<div class="empty">Quitaste todos los productos del kit.</div>`) + alt + removed + extra + `<p class="small">${prices}</p>`;
  kit.querySelectorAll(".pfill").forEach((f) => (f.style.width = `${Number(f.dataset.w)}%`)); // CSP: sin estilos en el HTML

  // Chat: se reinicia con otra foto u otro material; con cambios en el kit, solo se avisa
  const chatKey = `${state.fotoId}|${state.materials.join(",")}`;
  if (chatKey !== state.chatKey) {
    state.chatKey = chatKey;
    state.messages = [{ rol: "assistant", texto: k.intro }];
  } else if (note) {
    addNote(note);
  } else if (changed) {
    const now = new Set(k.items.map((i) => i.nombre));
    const added = [...now].filter((n) => !before.has(n)), gone = [...before].filter((n) => !now.has(n));
    const parts = [];
    if (added.length) parts.push(`agregué **${added.join(", ")}**`);
    if (gone.length) parts.push(`quité ${gone.join(", ")}`);
    addNote((parts.length ? `Actualicé tu kit: ${parts.join(" y ")}.` : "Actualicé tu kit.") + (soleChanged ? `\n\n${k.guia_suela}` : ""));
  }
  state.kitKey = `${state.suela}|${state.needs.join(",")}`;
  renderMessages();
}

$("#kit").addEventListener("click", (e) => {
  const rm = e.target.closest("[data-rm]"), back = e.target.closest("[data-back]");
  if (rm) {
    const item = state.kit.items.find((i) => i.sku === rm.dataset.rm);
    state.quitados.push(rm.dataset.rm);
    updateKit({ note: item ? `Quitaste **${item.nombre}** de tu kit.${item.porque ? ` Te lo recomendamos porque: ${item.porque}` : ""} Si cambias de opinión, puedes volver a agregarlo.` : "" });
  } else if (back) {
    state.quitados = state.quitados.filter((s) => s !== back.dataset.back);
    updateKit({ changed: true });
  }
});

const kitBody = () => ({ materiales: state.materials, suela: state.suela, necesidades: state.needs, quitados: state.quitados });

// ---------------- 4 · Chat ----------------
const chatReady = () => Boolean(state.kit) && !state.busy && state.asked < (state.opts?.max_preguntas ?? 20);

function resetChat() {
  state.chatKey = "";
  state.messages = [{ rol: "assistant", texto: HELLO }];
  renderMessages();
}
function addNote(texto) { state.messages.push({ rol: "assistant", texto, note: true }); }

function bubble(m) {
  const avatar = m.rol === "user" ? "/assets/user.png" : "/assets/bot.png";
  return `<div class="msg ${m.rol}${m.note ? " note" : ""}"><img src="${avatar}" alt=""><div class="bubble">${m.html ?? md(m.texto)}</div></div>`;
}
function renderMessages(extra = "") {
  const box = $("#messages");
  box.innerHTML = state.messages.map(bubble).join("") + extra;
  box.scrollTop = box.scrollHeight;
  const ready = chatReady();
  $("#question").disabled = !ready;
  $("#ask button").disabled = !ready;
  $("#question").placeholder = state.asked >= (state.opts?.max_preguntas ?? 20) ? "Llegaste al límite de preguntas por hoy" : "Escribe tu pregunta…";
  $("#suggestions").querySelectorAll(".chip").forEach((b) => (b.disabled = !ready));
}

async function send(question) {
  question = question.trim();
  if (!question || !chatReady()) return;
  // Historial para el modelo: preguntas y respuestas, sin el saludo ni los avisos del kit
  const historial = state.messages.slice(1).filter((m) => !m.note).map((m) => ({ rol: m.rol, texto: m.texto.slice(0, 4000) }));
  state.messages.push({ rol: "user", texto: question });
  state.busy = true;
  const typing = `<div class="msg assistant"><img src="/assets/bot.png" alt=""><div class="bubble"><div class="typing"><span></span><span></span><span></span></div></div></div>`;
  renderMessages(typing);
  let target = "", shown = 0, done = false, failed = false, guia = false;
  const reply = { rol: "assistant", texto: "" };
  try {
    const res = await postJSON("/api/chat", { ...kitBody(), pregunta: question, historial, foto: state.photo64 });
    state.asked += 1;
    const reader = res.body.getReader(), decoder = new TextDecoder();
    // Efecto de escritura: el texto recibido se muestra de a pocos caracteres (con un temporizador, no depende de la animación)
    const tick = () => {
      if (shown < target.length) {
        shown = Math.min(target.length, shown + Math.max(3, Math.ceil((target.length - shown) / 20)));
        reply.texto = target.slice(0, shown);
        if (!state.messages.includes(reply)) state.messages.push(reply);
        renderMessages();
      }
      if (!done || shown < target.length) setTimeout(tick, document.hidden ? 0 : 25);
      else finish();
    };
    setTimeout(tick, 25);
    for (;;) {
      const { value, done: end } = await reader.read();
      if (end) break;
      target += decoder.decode(value, { stream: true });
      if (target.includes("\u0000guia")) { guia = true; target = target.replace("\u0000guia", ""); }
    }
    done = true;
  } catch (e) {
    failed = done = true;
    state.messages.push({ rol: "assistant", texto: e.message, note: true });
    state.busy = false;
    renderMessages();
  }
  function finish() {
    if (failed) return;
    reply.texto = target.trim() || "No pude responder ahora. Inténtalo de nuevo.";
    if (!state.messages.includes(reply)) state.messages.push(reply);
    if (guia) addNote("Respuesta de la guía básica: el chat con IA no está disponible en este momento.");
    state.busy = false;
    renderMessages();
    $("#question").focus({ preventScroll: true }); // sin mover la página de la tienda
  }
}

$("#ask").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("#question").value;
  $("#question").value = "";
  send(q);
});

// ---------------- Modo incrustado: avisa a la tienda el alto del contenido ----------------
if (EMBED && window.parent !== window) {
  let last = 0;
  const report = () => {
    const height = Math.ceil(document.body.getBoundingClientRect().height); // alto real del contenido (no del iframe)
    if (Math.abs(height - last) > 2) { last = height; window.parent.postMessage({ tipo: "sneaker-doctor:alto", alto: height }, "*"); }
  };
  new ResizeObserver(report).observe(document.body);
  window.addEventListener("load", report);
}

// ---------------- Inicio ----------------
(async () => {
  resetChat();
  try {
    state.opts = await (await api("/api/opciones")).json();
    $("#question").maxLength = state.opts.max_caracteres;
    renderOptions();
  } catch (e) { toast(e.message); }
})();
