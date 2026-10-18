import sys
from pathlib import Path

import pandas as pd
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from prepare_zappos import assign_split, classify, norm_id  # noqa: E402

from sneaker_doctor import MATERIALS, chat
from sneaker_doctor.catalog import BASE_KIT, load_catalog, products_for, recommend
from sneaker_doctor.vision import IMG_SIZE, preprocess


def test_classify_materiales():
    assert classify("Suede") == "gamuza"
    assert classify("Leather;Rubber") == "cuero"
    assert classify("Canvas") == "lona"
    assert classify("Mesh;Synthetic") == "malla"
    assert classify("Leather;Mesh") is None   # mezcla: se descarta
    assert classify(None) is None


def test_ids_y_division_por_producto():
    assert norm_id("7590.123") == norm_id("7590-123")
    assert assign_split("7590") == assign_split("7590")


def test_kits_existen_en_catalogo():
    catalog = load_catalog()
    for material, skus in BASE_KIT.items():
        assert material in MATERIALS
        assert all(s in catalog.index for s in skus)
        assert all(material in catalog.loc[s, "materiales"] for s in skus)


def test_recommend_con_compras_conjuntas():
    catalog = load_catalog()
    co = pd.DataFrame([{"sku": "LCLKG", "also_sku": "LCLE41", "pedidos": 20, "confianza": 0.3},
                       {"sku": "LCLKG", "also_sku": "PCLRP", "pedidos": 30, "confianza": 0.5}])  # cuero: no sirve para gamuza
    rec = recommend("gamuza", catalog, co)
    assert [i["sku"] for i in rec["kit"]] == BASE_KIT["gamuza"]
    assert rec["extra"]["sku"] == "LCLE41"
    assert rec["total"] > 0


def test_suela_amarilla_suma_blanqueador():
    catalog = load_catalog()
    rec = recommend("lona", catalog, sole="amarilla")
    assert [i["sku"] for i in rec["sole_kit"]] == ["ACLRDS"]          # suela amarilla: crema renovadora
    gastada = recommend("lona", catalog, sole="gastada")["sole_kit"]
    assert [i["sku"] for i in gastada] == ["LCLEB", "LCLBP-P"]        # sucia: escobilla dura + blanqueador
    assert recommend("lona", catalog, sole="normal")["sole_kit"] == []
    assert rec["total"] == round(sum(catalog.loc[s, "precio"] for s in BASE_KIT["lona"] + ["ACLRDS"]), 2)
    assert rec["ahorro"] >= 0


def test_chat_incluye_la_suela(monkeypatch):
    monkeypatch.setattr(chat.config, "LLM_PROVIDER", "none")
    reply, _ = chat.answer("cuero", "¿y la suela?", [], sole="amarilla")
    assert "crema renovadora" in reply.lower() and "sol" in reply.lower()


def test_web_catalog_lee_promos_e_instrucciones():
    from sneaker_doctor.web_catalog import instructions, is_gift, short_name, to_rows
    body = "<p>Gran producto.</p><h3>Modo de uso</h3><p>1. Agita.</p><p>2. Aplica.</p><p>Mira nuestro video AQUÍ</p>"
    products = [
        {"title": "🎁 Clean Mat (50% off)", "handle": "x", "body_html": "", "variants": [{"sku": "ACLCM", "price": "14.95"}]},
        {"title": "Protector Premium - Spray impermeabilizante", "handle": "protector", "product_type": "Proteccion",
         "body_html": body, "variants": [{"sku": "PCLPP", "price": "44.90", "compare_at_price": "49.90", "available": True}]},
    ]
    rows = to_rows(products)
    assert len(rows) == 1 and rows[0]["sku"] == "PCLPP"            # el regalo se descarta
    assert rows[0]["precio_antes"] == 49.90 and rows[0]["nombre"] == "Protector Premium"
    assert rows[0]["instrucciones"] == "1. Agita.\n2. Aplica."
    assert is_gift("🎁 Calzador (50% off)") and not is_gift("Calzador Premium")
    assert short_name("Kit de Gamuza Premium — Limpiador en seco") == "Kit de Gamuza Premium"
    assert instructions("sin modo de uso") == ""


def test_zapatilla_mixta_junta_kits_sin_repetir():
    catalog = load_catalog()
    rec = recommend(["gamuza", "malla"], catalog)
    skus = [i["sku"] for i in rec["kit"]]
    assert skus == ["LCLKG", "PCLACP", "PCLPP", "LCLFP", "LCLE41"]  # el Protector aparece una sola vez
    assert len(skus) == len(set(skus))


def test_detected_dos_materiales():
    from sneaker_doctor.vision import detected
    assert detected([("gamuza", 0.55), ("malla", 0.35), ("cuero", 0.1)]) == ["gamuza", "malla"]
    assert detected([("gamuza", 0.9), ("malla", 0.05)]) == ["gamuza"]


def test_chat_guia_mixta(monkeypatch):
    monkeypatch.setattr(chat.config, "LLM_PROVIDER", "none")
    reply, _ = chat.answer(["malla", "gamuza"], "¿cómo la limpio?", [])
    assert "combina" in reply and reply.index("Partes de gamuza") < reply.index("Partes de malla")


def test_opcion_con_pack_mas_barata():
    from sneaker_doctor.packs import PACKS, best_option
    catalog = load_catalog()
    for pack, items in PACKS.items():   # el contenido de cada pack existe en el catálogo
        assert pack in catalog.index and all(s in catalog.index for s in items)
    opt = best_option(["LCLKG", "PCLACP", "PCLPP"], catalog)
    singles = sum(catalog.loc[s, "precio"] for s in ["LCLKG", "PCLACP", "PCLPP"])
    assert opt is not None and opt["total"] < singles and opt["ahorro"] > 0
    assert set(PACKS[opt["packs"][0]]) <= {"LCLKG", "PCLACP", "PCLPP"} | set(opt["extras"])


def test_complementos_hormas_y_shoe_guard():
    rec = recommend("cuero", load_catalog(), needs=["arrugas", "forma"])
    assert [i["sku"] for i in rec["extras_kit"]] == ["PCLSG", "PCLHP"]


def test_products_for():
    assert "PCLRP" not in products_for("gamuza", load_catalog()).index


def test_chat_sin_proveedor_usa_la_guia(monkeypatch):
    monkeypatch.setattr(chat.config, "LLM_PROVIDER", "none")
    reply, source = chat.answer("gamuza", "¿cómo la limpio?", [])
    assert source == "guia" and "gamuza" in reply


def test_chat_sin_clave_no_se_cae(monkeypatch):
    monkeypatch.setattr(chat.config, "LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    reply, source = chat.answer("malla", "hola", [])
    assert source == "guia"


def test_preprocess_forma():
    x = preprocess(Image.new("RGB", (136, 102), "red"))
    assert x.shape == (1, IMG_SIZE, IMG_SIZE, 3)


def test_feedback_guarda_sin_foto_si_no_hay_permiso(tmp_path):
    import io

    from PIL import Image

    from sneaker_doctor import feedback

    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="PNG")
    raw = buf.getvalue()
    feedback.save(raw, [("lona", 0.8)], ["lona"], True, False, folder=tmp_path)
    assert not (tmp_path / "fotos").exists()
    feedback.save(raw, [("lona", 0.8)], ["cuero"], False, True, folder=tmp_path)
    assert (tmp_path / "fotos" / f"{feedback.photo_id(raw)}.jpg").exists()
    lines = (tmp_path / "feedback.csv").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3 and lines[2].endswith(",cuero,0,1")


def test_chat_quita_enlaces_externos():
    from sneaker_doctor import chat

    text = chat.clean("Mira [la guía](https://otro.com) ![x](http://t.co/a.png) en https://cleanlab.pe/products/foam y http://otro.com")
    assert "otro.com" not in text and "t.co" not in text and "https://cleanlab.pe/products/foam" in text


def test_limite_global_de_preguntas():
    from sneaker_doctor import chat

    limit = chat.RateLimit(2)
    assert [limit.allow() for _ in range(3)] == [True, True, False]
