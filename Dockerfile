# Development-only image. It runs migrations, bootstrap_dev, and Django's
# runserver on 0.0.0.0. Do not deploy it. Production and self-host images
# live in deploy/production and deploy/selfhost and require real secrets.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate && python manage.py bootstrap_dev && python manage.py runserver 0.0.0.0:8000"]
