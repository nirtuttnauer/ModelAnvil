FROM python:3.12-slim AS backend
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements.production.txt requirements.embeddings.txt ./
RUN pip install --no-cache-dir -r requirements.production.txt
COPY manage.py ./
COPY modelanvil ./modelanvil
COPY contracts ./contracts
COPY catalog ./catalog
COPY scripts ./scripts
COPY deploy/production/gunicorn.conf.py ./deploy/production/gunicorn.conf.py
RUN DJANGO_SETTINGS_MODULE=modelanvil.settings python manage.py collectstatic --noinput \
    && rm modelanvil/identity/management/commands/bootstrap_dev.py \
    && chmod -R a+rX /app

FROM node:24-alpine AS frontend
RUN apk add --no-cache python3
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
COPY design/figcraft/variables.json /app/design/figcraft/variables.json
COPY --from=backend /app/modelanvil /app/modelanvil
COPY --from=backend /app/contracts /app/contracts
COPY --from=backend /app/scripts /app/scripts
ARG MODELANVIL_BUILD_REVISION
ENV MODELANVIL_BUILD_REVISION=$MODELANVIL_BUILD_REVISION
RUN npm run build

FROM backend AS api
ARG MODELANVIL_BUILD_REVISION
ENV DJANGO_SETTINGS_MODULE=modelanvil.production \
    DJANGO_DEBUG=0 \
    MODELANVIL_BUILD_REVISION=$MODELANVIL_BUILD_REVISION
COPY --from=frontend /app/web/dist ./web/dist
RUN groupadd --gid 10001 modelanvil \
    && useradd --uid 10001 --gid 10001 --no-create-home modelanvil \
    && mkdir -p /app/storage/artifacts \
    && chown -R modelanvil:modelanvil /app/storage
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/api/v1/ready/', headers={'Host': os.environ['DJANGO_ALLOWED_HOSTS'].split(',')[0]}), timeout=4)"
CMD ["sh", "-c", "python manage.py migrate --check && exec gunicorn --config deploy/production/gunicorn.conf.py modelanvil.wsgi:application"]

FROM caddy:2.11.7-alpine AS web
COPY deploy/production/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend /app/web/dist /srv/web
COPY --from=backend /app/staticfiles /srv/static
