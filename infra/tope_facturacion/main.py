"""Tope de facturación del proyecto de Google Cloud.

El presupuesto "Tope S/ 150" publica en Pub/Sub varias veces al día el gasto acumulado del mes.
Si el gasto llega al monto del presupuesto, este servicio desconecta la cuenta de facturación del
proyecto: todo lo de pago se detiene y Google deja de cobrar.

Para reactivar la facturación (desde la carpeta del proyecto):
    gcloud.cmd billing projects link tribal-flux-481018-u9 --billing-account=01AF1A-55949F-8BB589

Simulacro (no corta nada): mensaje con el atributo simulacro=1. Comprueba el permiso y lo informa.
"""
import base64
import json
import os

import functions_framework
import requests

PROJECT = os.environ.get("PROYECTO", "tribal-flux-481018-u9")
BILLING = f"https://cloudbilling.googleapis.com/v1/projects/{PROJECT}/billingInfo"
METADATA = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
PERMISSION = "resourcemanager.projects.deleteBillingAssignment"


def token() -> str:
    resp = requests.get(METADATA, headers={"Metadata-Flavor": "Google"}, timeout=10)
    resp.raise_for_status()
    return resp.json()["access_token"]


def log(**data):
    print(json.dumps({"severity": data.pop("severity", "INFO"), "evento": "tope-facturacion", **data}), flush=True)


@functions_framework.http
def tope(request):
    envelope = request.get_json(silent=True) or {}
    message = envelope.get("message") or {}
    try:
        data = json.loads(base64.b64decode(message.get("data", "")).decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        log(severity="WARNING", detalle="mensaje no válido")
        return ("mensaje no válido", 200)  # 200: Pub/Sub no reintenta un mensaje que nunca será válido
    cost, budget = float(data.get("costAmount", 0)), float(data.get("budgetAmount", 0))
    simulacro = (message.get("attributes") or {}).get("simulacro") == "1"
    headers = {"Authorization": f"Bearer {token()}"}

    if simulacro:
        check = requests.post(f"https://cloudresourcemanager.googleapis.com/v1/projects/{PROJECT}:testIamPermissions",
                              headers=headers, json={"permissions": [PERMISSION]}, timeout=15)
        allowed = PERMISSION in check.json().get("permissions", [])
        info = requests.get(BILLING, headers=headers, timeout=15).json()
        result = {"simulacro": True, "gasto": cost, "tope": budget, "cortaria": budget > 0 and cost >= budget,
                  "permiso_para_cortar": allowed, "facturacion_activa": info.get("billingEnabled")}
        log(**result)
        return (json.dumps(result), 200)

    if budget <= 0 or cost < budget:
        log(gasto=cost, tope=budget, accion="ninguna")
        return ("bajo el tope", 200)

    info = requests.get(BILLING, headers=headers, timeout=15).json()
    if not info.get("billingEnabled"):
        log(gasto=cost, tope=budget, accion="ya estaba desactivada")
        return ("facturación ya desactivada", 200)

    resp = requests.put(BILLING, headers=headers, json={"billingAccountName": ""}, timeout=30)
    if resp.ok:
        log(severity="ALERT", gasto=cost, tope=budget, accion="FACTURACIÓN DESACTIVADA")
        return ("facturación desactivada", 200)
    log(severity="ERROR", gasto=cost, tope=budget, accion="no se pudo desactivar", codigo=resp.status_code)
    return ("error", 500)  # 500: Pub/Sub reintenta
