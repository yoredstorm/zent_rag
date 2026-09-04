# Kubernetes (opcional)

Kubernetes **no es requisito de venta** ni el camino por defecto. Fase 11 (Compose prod + PG/Redis/Qdrant/object storage **managed**) cubre el arranque. Estos manifests existen para cuando Compose + una VM **ya no bastan**.

## Cuándo no

- Menos de ~N customers o una sola réplica de API saturada de forma esporádica: escala la VM o añade un segundo proceso worker en Compose.
- “Verse enterprise” en un deck. El cluster cuesta más que el beneficio.
- Querer meter Postgres/Qdrant/Redis en el cluster. **No.** Siguen managed; los backups de Fase 11 son el riesgo #1.

## Cuándo sí (síntoma real)

Documenta el síntoma en el PR antes de aplicar:

- CPU de API sostenida >70% con cola de requests.
- Cola de ingestion (`rag:knowledge:queue`) que no drena con un worker.
- RTO: necesitas rolling deploy sin downtime y ya tienes Ingress/TLS.

Si no hay síntoma, **no despliegues**. `kustomize build deploy/k8s` valida el overlay; no implica un cluster.

## Relación con Compose

| | Demo | Prod Compose (Fase 11) | K8s (esta fase) |
|---|---|---|---|
| Archivo | `docker-compose.yml` | `docker-compose.prod.yml` | `deploy/k8s/` |
| Ollama | sí | no | no |
| PG / Redis / Qdrant | contenedores | managed (o override) | **solo managed** |
| Imagen API/worker | `Dockerfile.api` | misma | misma (`zent-api`) |
| Portal | `portal/Dockerfile` | misma | `zent-portal` |

El demo Compose **no se toca**. Nginx del portal sigue resolviendo el Service `api:8000` (mismo hostname que Compose).

## Cómo renderizar (sin kube)

```bash
kustomize build deploy/k8s
# o
kubectl kustomize deploy/k8s
```

CI corre ese build. No hay `kubeconform` obligatorio si el render + `tests/test_k8s_manifests.py` pasan.

## Cómo aplicar (cuando el síntoma existe)

1. Construir: `docker build -f Dockerfile.api -t zent-api:<git-sha> .` y `docker build -t zent-portal:<git-sha> ./portal`.
2. Rellenar Secret `zent-secrets` (External Secrets / Sealed Secrets / `kubectl create secret`). Nunca commitear valores.
3. Editar ConfigMap: hosts managed, CORS `https` explícito.
4. `kubectl apply -k deploy/k8s`.
5. Ingress TLS: `zent-tls` (cert-manager annotation incluida; ajusta el issuer).

Workers: **una réplica** de `ingestion-worker`. HPA después, solo con métricas CPU/RPS reales.

## Umbral cualitativo de coste

Un cluster managed (control plane + nodos + egress a PG/Qdrant) suele superar el coste de 1–2 VMs + Compose hasta que hay varias réplicas de API **y** un equipo que opere Ingress/NetworkPolicy. Si el número de customers no justifica un on-call de plataforma, quédate en Fase 11.

## Drift y riesgos residuales

- Las variables de `docker-compose.prod.yml` y el ConfigMap/Secret de K8s deben mantenerse alineadas a mano. Fuente de nombres: `.env.example` + `PRODUCTION.md`.
- Backups de Qdrant/PG (Fase 11) siguen siendo el riesgo #1; no hay StatefulSets de datastores aquí.
- Coste de cluster > beneficio por debajo de N customers (ver umbral cualitativo).
- Portal (`nginx:1.27-alpine`) escucha en `:80`. Con `runAsUser: 101` + `drop: ALL` el bind a puerto privilegiado puede fallar; si ocurre, usa `listen 8080` + Service `targetPort` o `NET_BIND_SERVICE`. Los `emptyDir` de `/var/cache/nginx`, `/var/run`, `/tmp` y `/var/log/nginx` son obligatorios con root FS de solo lectura.
