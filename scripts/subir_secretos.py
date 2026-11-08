"""Sube las claves de .env a Secret Manager de Google Cloud, sin mostrarlas en pantalla.

Uso (desde la carpeta del proyecto):
    .venv\\Scripts\\python.exe scripts\\subir_secretos.py

Crea una versión nueva de cada secreto. Sirve también para cambiar una clave más adelante:
se actualiza en .env y se vuelve a ejecutar este script.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

PROJECT = "tribal-flux-481018-u9"
SECRETS = {"GEMINI_API_KEY": "gemini-api-key", "SHOPIFY_STOREFRONT_TOKEN": "shopify-storefront-token"}
ENV = Path(__file__).resolve().parent.parent / ".env"


def gcloud() -> str:
    found = shutil.which("gcloud.cmd") or shutil.which("gcloud")
    default = Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd"
    return found or str(default)


def main():
    values = dotenv_values(ENV)
    ok = True
    for var, secret in SECRETS.items():
        value = (values.get(var) or "").strip()
        if not value:
            print(f"✗ {var} está vacío en .env: no se subió {secret}")
            ok = False
            continue
        # El valor va por la entrada estándar: no queda en la pantalla ni en el historial de comandos
        result = subprocess.run([gcloud(), "secrets", "versions", "add", secret, "--data-file=-", f"--project={PROJECT}"],
                                input=value.encode(), capture_output=True)
        if result.returncode == 0:
            print(f"✓ {secret}: nueva versión guardada ({len(value)} caracteres)")
        else:
            print(f"✗ {secret}: Google Cloud respondió con un error")
            ok = False
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
