# =============================================================================
# Kubernetes manifests — render + policy (no cluster required)
# =============================================================================
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
K8S = ROOT / "deploy" / "k8s"
COMPOSE = ROOT / "docker-compose.yml"
COMPOSE_PROD = ROOT / "docker-compose.prod.yml"
DOCKERFILE_API = ROOT / "Dockerfile.api"


def _kustomization() -> dict:
    path = K8S / "kustomization.yaml"
    assert path.is_file(), "missing deploy/k8s/kustomization.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["kind"] == "Kustomization"
    return data


def _load_docs() -> list[dict]:
    kust = _kustomization()
    docs: list[dict] = []
    for rel in kust.get("resources") or []:
        path = K8S / rel
        assert path.is_file(), f"kustomization resource missing: {rel}"
        for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if doc:
                docs.append(doc)
    return docs


def _by_kind(kind: str) -> list[dict]:
    return [d for d in _load_docs() if d.get("kind") == kind]


def test_kustomize_overlay_exists_and_lists_workloads() -> None:
    kust = _kustomization()
    resources = set(kust.get("resources") or [])
    for name in (
        "deployment-api.yaml",
        "deployment-worker.yaml",
        "deployment-portal.yaml",
        "ingress.yaml",
        "networkpolicy.yaml",
    ):
        assert name in resources, f"kustomization must include {name}"


def test_stateless_deployments_api_worker_portal() -> None:
    names = {d["metadata"]["name"] for d in _by_kind("Deployment")}
    assert {"api", "ingestion-worker", "portal"} <= names


def test_no_postgres_qdrant_or_redis_workloads() -> None:
    for doc in _load_docs():
        if doc.get("kind") not in {"Deployment", "StatefulSet", "DaemonSet"}:
            continue
        name = str(doc.get("metadata", {}).get("name", "")).lower()
        image = " ".join(
            str(c.get("image", "")).lower()
            for c in (doc.get("spec", {}).get("template", {}).get("spec", {}).get("containers") or [])
        )
        blob = f"{name} {image}"
        for forbidden in ("postgres", "postgresql", "qdrant", "redis"):
            assert forbidden not in blob, f"managed store must stay outside the cluster: {blob}"


def test_api_and_portal_probe_health() -> None:
    deploys = {d["metadata"]["name"]: d for d in _by_kind("Deployment")}
    api = deploys["api"]
    container = api["spec"]["template"]["spec"]["containers"][0]
    for probe_name in ("livenessProbe", "readinessProbe"):
        probe = container[probe_name]["httpGet"]
        assert probe["path"] == "/health"
    portal = deploys["portal"]
    portal_probe = portal["spec"]["template"]["spec"]["containers"][0]["readinessProbe"]["httpGet"]
    assert portal_probe["path"] in {"/", "/health"}


def test_pods_are_unprivileged_with_readonly_root() -> None:
    for deploy in _by_kind("Deployment"):
        pod = deploy["spec"]["template"]["spec"]
        pod_sc = pod.get("securityContext") or {}
        assert pod_sc.get("runAsNonRoot") is True, deploy["metadata"]["name"]
        for container in pod["containers"]:
            sc = container.get("securityContext") or {}
            assert sc.get("allowPrivilegeEscalation") is False, deploy["metadata"]["name"]
            assert sc.get("readOnlyRootFilesystem") is True, deploy["metadata"]["name"]
            assert "ALL" in ((sc.get("capabilities") or {}).get("drop") or [])


def test_worker_is_single_replica_and_hpa_absent() -> None:
    worker = next(d for d in _by_kind("Deployment") if d["metadata"]["name"] == "ingestion-worker")
    assert worker["spec"]["replicas"] == 1
    assert _by_kind("HorizontalPodAutoscaler") == []
    cmd = worker["spec"]["template"]["spec"]["containers"][0].get("command") or []
    assert "worker_entry.py" in " ".join(cmd) or "worker_entry.py" in " ".join(
        worker["spec"]["template"]["spec"]["containers"][0].get("args") or []
    )


def test_api_image_comes_from_dockerfile_api() -> None:
    assert DOCKERFILE_API.is_file()
    api = next(d for d in _by_kind("Deployment") if d["metadata"]["name"] == "api")
    labels = api["spec"]["template"]["metadata"].get("labels") or {}
    annotations = api["metadata"].get("annotations") or {}
    image = api["spec"]["template"]["spec"]["containers"][0]["image"]
    assert "Dockerfile.api" in str(labels) + str(annotations) + image or image.startswith(
        "zent-api"
    )


def test_ingress_has_tls_and_networkpolicy_exists() -> None:
    ingresses = _by_kind("Ingress")
    assert ingresses, "Ingress with TLS is required"
    tls = ingresses[0]["spec"].get("tls") or []
    assert tls and tls[0].get("secretName")
    assert _by_kind("NetworkPolicy"), "basic NetworkPolicy required"


def test_secrets_are_referenced_not_inlined() -> None:
    api = next(d for d in _by_kind("Deployment") if d["metadata"]["name"] == "api")
    env = api["spec"]["template"]["spec"]["containers"][0].get("env") or []
    secret_refs = [e for e in env if e.get("valueFrom", {}).get("secretKeyRef")]
    assert secret_refs, "API must pull secrets from a Secret, not plaintext env"
    for e in env:
        if "PASSWORD" in e.get("name", "") or "SECRET" in e.get("name", "") or e.get("name", "").endswith("_KEY"):
            assert e.get("valueFrom", {}).get("secretKeyRef"), e.get("name")


def test_demo_and_prod_compose_remain() -> None:
    assert COMPOSE.is_file()
    demo = COMPOSE.read_text(encoding="utf-8")
    assert "ollama" in demo
    assert "ingestion-worker" in demo
    prod = COMPOSE_PROD.read_text(encoding="utf-8")
    assert "Dockerfile.api" in prod
    assert "ingestion-worker" in prod


def test_ci_runs_alembic_upgrade_like_api_container() -> None:
    """CI used to apply only db_init/01–31 SQL. App code INSERTs
    organizations.primary_region_id (Alembic 047). Docker API runs
    `alembic upgrade head` on boot; CI must do the same after pip install.
    """
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    dockerfile = DOCKERFILE_API.read_text(encoding="utf-8")
    assert "alembic upgrade head" in dockerfile
    assert "alembic upgrade head" in ci
    assert "primary_region_id" in (
        ROOT / "src" / "infrastructure" / "postgres" / "relational_db.py"
    ).read_text(encoding="utf-8")


def test_kubernetes_docs_explain_when_not_to_use_it() -> None:
    docs = (ROOT / "docs" / "platform" / "KUBERNETES.md").read_text(encoding="utf-8")
    assert "cuando" in docs.lower() or "when" in docs.lower()
    assert "compose" in docs.lower()
    assert "no es requisito" in docs.lower() or "not a sales" in docs.lower()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Kubernetes" in readme
    assert "requisito de venta" in readme.lower() or "not a sales" in readme.lower()
