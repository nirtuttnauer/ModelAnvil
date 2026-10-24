FROM python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS backend
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements*.txt ./
RUN pip install --no-cache-dir --constraint requirements.selfhost.lock.txt -r requirements.production.txt
COPY manage.py LICENSE ./
COPY modelanvil ./modelanvil
COPY contracts ./contracts
COPY catalog ./catalog
COPY scripts ./scripts
COPY deploy/production/gunicorn.conf.py ./deploy/production/gunicorn.conf.py
RUN DJANGO_SETTINGS_MODULE=modelanvil.settings python manage.py check \
    && DJANGO_SETTINGS_MODULE=modelanvil.settings python manage.py collectstatic --noinput \
    && rm modelanvil/identity/management/commands/bootstrap_dev.py \
    && chmod -R a+rX /app

ARG MODELANVIL_BUILD_REVISION
ENV MODELANVIL_BUILD_REVISION=$MODELANVIL_BUILD_REVISION
RUN python -m modelanvil.build_info > /app/build-info.json

FROM node@sha256:06d7adf3e0ef61a13f1d28682726366f97a15aa1888c934d3ecec86c33918b53 AS frontend
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
COPY design/figcraft/variables.json /app/design/figcraft/variables.json
COPY --from=backend /app/build-info.json /app/build-info.json
ENV MODELANVIL_BUILD_INFO_PATH=/app/build-info.json
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

FROM caddy@sha256:eb4d35b7452d1ab6171fbdbe8d9275b2301dad6dad92115d91e19fb9b24d510f AS web
COPY deploy/selfhost/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend /app/web/dist /srv/web
COPY --from=backend /app/staticfiles /srv/static
