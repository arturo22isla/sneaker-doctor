import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from sneaker_doctor import api, config


@pytest.fixture()
def client(monkeypatch):
    def offline(*a, **k):
        raise ConnectionError("sin red en las pruebas")

    monkeypatch.setattr(api, "fetch_products", offline)  # se usan los precios del CSV
    monkeypatch.setattr(config, "LLM_PROVIDER", "none")  # el chat responde con la guía fija
    for limit in api.LIMITS.values():
        limit.calls.clear()
    with TestClient(api.app) as c:
        yield c


def test_cabeceras_de_seguridad_y_sin_documentacion_publica(client):
    r = client.get("/api/salud")
    assert r.json() == {"ok": True}
    assert "frame-ancestors" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404


def test_kit_valida_entradas(client):
    assert client.post("/api/kit", json={"materiales": ["plastico"]}).status_code == 422
    assert client.post("/api/kit", json={"materiales": []}).status_code == 422
    assert client.post("/api/kit", json={"materiales": ["cuero"], "quitados": ["<script>"]}).status_code == 422


def test_kit_con_carrito_etiquetado_y_motivos(client):
    k = client.post("/api/kit", json={"materiales": ["gamuza"]}).json()
    assert k["items"] and all(i["porque"] for i in k["items"])
    assert "attributes%5Borigen%5D=Sneaker+Doctor" in k["carrito"] and "utm_source=sneaker-doctor" in k["carrito"]
    assert all("utm_source=sneaker-doctor" in i["url"] for i in k["items"] if i["url"])
    assert k["precios"]["en_vivo"] is False


def test_quitar_producto_y_pack(client):
    k = client.post("/api/kit", json={"materiales": ["gamuza"]}).json()
    pack = next(i["sku"] for i in k["items"] if i["contenido"])
    sin_pack = client.post("/api/kit", json={"materiales": ["gamuza"], "quitados": [pack]}).json()
    assert pack not in {i["sku"] for i in sin_pack["items"]}
    assert sin_pack["quitados"][0]["sku"] == pack and sin_pack["quitados"][0]["porque"]
    sin_protector = client.post("/api/kit", json={"materiales": ["gamuza"], "quitados": [pack, "PCLPP"]}).json()
    assert "PCLPP" not in {i["sku"] for i in sin_protector["items"]}
    assert {"PCLPP", pack} == {i["sku"] for i in sin_protector["quitados"]}


def test_diagnostico_rechaza_archivos_que_no_son_imagenes(client):
    r = client.post("/api/diagnostico", files={"foto": ("x.jpg", b"no soy una foto", "image/jpeg")})
    assert r.status_code == 400
    big = b"0" * (api.MAX_PHOTO + 1)
    assert client.post("/api/diagnostico", files={"foto": ("x.jpg", big, "image/jpeg")}).status_code == 413


def test_diagnostico_responde_con_una_imagen(client):
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(buf, format="JPEG")
    r = client.post("/api/diagnostico", files={"foto": ("x.jpg", buf.getvalue(), "image/jpeg")}, data={"forzar": "true"})
    assert r.status_code == 200 and len(r.json()["foto_id"]) == 16 and r.json()["ranking"]


def test_chat_sin_ia_usa_la_guia_y_valida(client):
    r = client.post("/api/chat", json={"materiales": ["lona"], "pregunta": "¿Cómo la limpio?"})
    assert r.status_code == 200 and r.text.endswith("\u0000guia") and "lona" in r.text
    assert client.post("/api/chat", json={"materiales": ["lona"], "pregunta": "x" * 401}).status_code == 422
    assert client.post("/api/chat", json={"materiales": ["lona"], "pregunta": "hola", "foto": "@@@"}).status_code == 400


def test_limite_de_preguntas_por_minuto(client):
    codes = [client.post("/api/chat", json={"materiales": ["lona"], "pregunta": "hola"}).status_code for _ in range(7)]
    assert codes[:6] == [200] * 6 and codes[6] == 429


def test_la_ip_no_se_puede_falsificar():
    class R:  # Cloud Run agrega la IP real al final
        headers = {"x-forwarded-for": "1.1.1.1, 203.0.113.7"}
        client = None

    assert api.client_ip(R()) == "203.0.113.7"


def test_enlaces_externos_se_quitan_mientras_llega_la_respuesta():
    parts = ["Mira [la ", "guía](https://", "otro.com/x) y ", "https://cleanlab.pe/products/foam ok"]
    text = "".join(api.cleaned(iter(parts)))
    assert "otro.com" not in text and "la guía" in text and "https://cleanlab.pe/products/foam" in text


def test_modo_incrustado_para_cleanlab(client):
    normal, embed = client.get("/").text, client.get("/?embed=1").text
    assert 'class="embed"' in embed and 'class="embed"' not in normal
    csp = client.get("/?embed=1").headers["content-security-policy"]
    for sitio in ("https://*.cleanlab.pe", "https://cleanlab-pe.myshopify.com", "https://admin.shopify.com", "https://*.shopifyapps.com"):
        assert sitio in csp  # la tienda y el editor de temas pueden mostrarla
    assert "*.myshopify.com" not in csp and "shopifypreview" not in csp  # otras tiendas de Shopify no
