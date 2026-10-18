"""Genera los recursos visuales de la app en assets/: logo y avatares del chat.

Uso: python scripts/make_assets.py
"""
import io
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"
LOGO_URL = "https://www.cleanlab.pe/cdn/shop/files/logo_final_final_barra_Mesa_de_trabajo_1.png?width=600"
NAVY, TEAL, WHITE = (27, 46, 70), (154, 197, 194), (255, 255, 255)


def circle(size, color):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse([0, 0, size - 1, size - 1], fill=color)
    return img


def main():
    OUT.mkdir(exist_ok=True)
    logo = Image.open(io.BytesIO(requests.get(LOGO_URL, timeout=20).content)).convert("RGBA")
    logo.save(OUT / "logo.png")

    # Bot: zapatilla del logo sobre círculo azul marino
    size = 256
    bot = circle(size, NAVY)
    shoe = logo.crop((0, 0, logo.width, int(logo.height * 0.78)))  # sin el texto inferior
    shoe.thumbnail((int(size * 0.78), int(size * 0.78)))
    bot.alpha_composite(shoe, ((size - shoe.width) // 2, (size - shoe.height) // 2 + 6))
    bot.save(OUT / "bot.png")

    # Usuario: círculo turquesa con silueta simple
    user = circle(size, TEAL)
    d = ImageDraw.Draw(user)
    d.ellipse([88, 52, 168, 132], fill=NAVY)                 # cabeza
    d.pieslice([48, 140, 208, 300], 180, 360, fill=NAVY)     # hombros
    mask = circle(size, WHITE).split()[3]
    user.putalpha(Image.composite(user.split()[3], Image.new("L", (size, size), 0), mask))
    user.save(OUT / "user.png")
    print("Guardado en", OUT)


if __name__ == "__main__":
    main()
