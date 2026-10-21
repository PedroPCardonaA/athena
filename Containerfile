FROM docker.io/library/python:3.13-slim@sha256:cf50a4f6ac4f026458b08d5222023d700ac806410dff5e9ca8728fa44f2b850f
LABEL org.opencontainers.image.source="https://github.com/PedroPCardonaA/ideas_saver" \
      org.opencontainers.image.licenses="MIT"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 IDEAS_DB=/data/ideas.db
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && useradd -u 10001 -M -s /usr/sbin/nologin app \
 && mkdir /data && chown app /data
COPY app ./app
USER 10001
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request as u;u.urlopen('http://127.0.0.1:8787/healthz',timeout=2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787", "--no-server-header"]
