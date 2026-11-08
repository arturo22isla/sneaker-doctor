# Tope de facturación (S/ 150 al mes)

Si el gasto del mes del proyecto `tribal-flux-481018-u9` llega a **S/ 150**, el servicio `tope-facturacion`
desconecta la cuenta de facturación: **se apaga todo el proyecto** (Sneaker Doctor, Falabella, Mercado Libre, BigQuery)
y Google deja de cobrar.

```
Presupuesto "Tope S/ 150" ──(Pub/Sub, varias veces al día)──► servicio tope-facturacion ──► Cloud Billing: desconectar
```

- La cuenta `tope-facturacion-sa` solo tiene el rol personalizado `cortarFacturacion`: ver el proyecto y desconectar su facturación.
- El servicio es privado: solo Pub/Sub puede llamarlo.
- Google informa los costos con varias horas de retraso: el gasto puede pasar un poco de S/ 150 antes del corte.
- Sin facturación, Google advierte que algunos recursos pueden eliminarse si no se reactiva a tiempo.

## Instalación (una vez, en PowerShell)

Copiar y pegar en orden. La primera línea define variables que usan las demás.

```powershell
$p = "tribal-flux-481018-u9"; $sa = "tope-facturacion-sa@$p.iam.gserviceaccount.com"
```
```powershell
gcloud.cmd services enable cloudbilling.googleapis.com cloudresourcemanager.googleapis.com --project $p
```
```powershell
gcloud.cmd iam roles create cortarFacturacion --project $p --title "Cortar facturacion del proyecto" --permissions "resourcemanager.projects.get,resourcemanager.projects.deleteBillingAssignment" --stage GA
```
```powershell
gcloud.cmd iam service-accounts create tope-facturacion-sa --display-name "Tope de facturacion" --project $p
```
```powershell
gcloud.cmd projects add-iam-policy-binding $p --member "serviceAccount:$sa" --role "projects/$p/roles/cortarFacturacion" --condition=None
```
```powershell
cd C:\Users\artur\sneaker-doctor\infra\tope_facturacion
```
```powershell
gcloud.cmd run deploy tope-facturacion --source . --function tope --base-image python312 --region us-central1 --project $p --service-account $sa --no-allow-unauthenticated --max-instances 1 --quiet
```
```powershell
gcloud.cmd run services add-iam-policy-binding tope-facturacion --region us-central1 --project $p --member "serviceAccount:$sa" --role roles/run.invoker
```
```powershell
gcloud.cmd iam service-accounts add-iam-policy-binding $sa --project $p --member "serviceAccount:service-928770385966@gcp-sa-pubsub.iam.gserviceaccount.com" --role roles/iam.serviceAccountTokenCreator
```
```powershell
gcloud.cmd pubsub topics create tope-facturacion --project $p
```
```powershell
$url = gcloud.cmd run services describe tope-facturacion --region us-central1 --project $p --format "value(status.url)"
```
```powershell
gcloud.cmd pubsub subscriptions create tope-facturacion-push --topic tope-facturacion --project $p --push-endpoint $url --push-auth-service-account $sa --ack-deadline 60
```
```powershell
gcloud.cmd billing budgets create --billing-account=01AF1A-55949F-8BB589 --billing-project=$p --display-name="Tope S/ 150 (corta la facturacion)" --budget-amount=150PEN --filter-projects="projects/$p" --calendar-period=month --threshold-rule=percent=0.8 --threshold-rule=percent=1.0 --notifications-rule-pubsub-topic="projects/$p/topics/tope-facturacion"
```

## Simulacro (no corta nada)

```powershell
gcloud.cmd pubsub topics publish tope-facturacion --project $p --message "{}" --attribute simulacro=1
```

Un minuto después, ver el resultado. Debe decir `"permiso_para_cortar": true` y `"facturacion_activa": true`:

```powershell
gcloud.cmd logging read "resource.labels.service_name=tope-facturacion AND jsonPayload.evento=tope-facturacion" --project $p --limit 3 --freshness=15m --format="value(jsonPayload)"
```

## Reactivar la facturación después de un corte

```powershell
gcloud.cmd billing projects link tribal-flux-481018-u9 --billing-account=01AF1A-55949F-8BB589
```

O en la consola: **Facturación → Administrar cuentas de facturación → Mis proyectos → ⋮ → Cambiar facturación**.
Al reactivar, revisa que Sneaker Doctor, Falabella y Mercado Libre vuelvan a responder.

## Quitar el tope

```powershell
gcloud.cmd pubsub subscriptions delete tope-facturacion-push --project tribal-flux-481018-u9
```
(y borrar el presupuesto "Tope S/ 150" en **Facturación → Presupuestos y alertas**).
