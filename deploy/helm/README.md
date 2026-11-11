# Helm chart

This chart is unsupported.

The installation path named in `docs/engineering/self-host.md` is the provisioned Linux arm64 Docker package in `deploy/selfhost`. The packaged-install scope is `docs/engineering/self-host-package.md`.

The files here are `Chart.yaml` (`version: 0.1.0`, `appVersion: "1.0.0"`), `values.yaml`, `templates/api-deployment.yaml`, and `templates/worker-deployment.yaml`. They are not an install procedure.

`values.yaml` sets `ingress.enabled` to true. The templates directory has no Ingress manifest. `postgresql.enabled` and `rabbitmq.enabled` are false. The API template and the worker template both reference `modelanvil/control-plane:1.0.0`. Nothing in this directory builds or publishes that image.

Do not install ModelAnvil with this chart.
