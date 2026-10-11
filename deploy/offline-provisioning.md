# ModelAnvil Offline Provisioning & Air-Gapped Deployment Guide

## 1. Overview & Trust Model
ModelAnvil supports air-gapped and offline installation in compliance with **TECH-029**. In this mode:
- The control plane and workers run entirely within an isolated private network.
- **No outbound internet traffic** is required or initiated.
- **No hosted telemetry or third-party phone-home** services are contacted.
- Authentication relies on local tokens or enterprise SAML/OIDC identity providers operating within the perimeter.

## 2. Air-Gapped Package Preparation
To prepare an air-gapped installation bundle on a connected staging machine:

1. **Docker Container Images:**
   ```bash
   docker pull pgvector/pgvector:pg16
   docker pull rabbitmq:3.12-management-alpine
   docker pull chrislusf/seaweedfs:latest
   docker build -t modelanvil/control-plane:1.0.0 -f Dockerfile .
   docker save pgvector/pgvector:pg16 rabbitmq:3.12-management-alpine chrislusf/seaweedfs:latest modelanvil/control-plane:1.0.0 -o modelanvil-images.tar
   ```

2. **Python Wheel Dependencies & Model Weights:**
   ```bash
   pip download -r requirements.txt -d ./offline-wheels/
   # Pre-download foundational base model weights (e.g. HuggingFace safetensors/checkpoints) into local storage
   ```

3. **Transfer to Air-Gapped Environment:**
   Transfer `modelanvil-images.tar`, `./offline-wheels/`, and deployment manifests via audited removable media.

## 3. Deployment & Local Verification
1. Load container images:
   ```bash
   docker load -i modelanvil-images.tar
   ```
2. Initialize database and schemas:
   ```bash
   docker compose -f deploy/compose/docker-compose.yml up -d postgres rabbitmq seaweedfs
   # Run Django schema migrations locally
   docker compose -f deploy/compose/docker-compose.yml run --rm api python manage.py migrate
   ```
3. Seed offline catalog presets:
   ```bash
   python manage.py load_offline_catalog catalog/dataset-presets.json
   ```
4. Verify air-gap integrity:
   - Confirm network isolation via egress deny firewall rules.
   - Run health probe: `curl http://localhost:8000/api/v1/health/` -> `{"status": "ok"}`.
