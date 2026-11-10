FROM python:3.11-slim@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY inference/requirements.lock /srv/requirements.lock
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home inference
COPY app/__init__.py /srv/app/__init__.py
COPY app/core/__init__.py app/core/config.py app/core/service_auth.py /srv/app/core/
COPY app/model_inference /srv/app/model_inference
COPY inference/__init__.py inference/service.py /srv/inference/
USER 10001
EXPOSE 8081
HEALTHCHECK --interval=30s --timeout=3s --start-period=180s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/ready', timeout=2)"
CMD ["uvicorn", "inference.service:app", "--host", "0.0.0.0", "--port", "8081", "--no-access-log", "--timeout-graceful-shutdown", "65", "--limit-concurrency", "32"]
