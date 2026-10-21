FROM docker.io/library/python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 IDEAS_DB=/data/ideas.db
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && useradd -u 10001 -M -s /usr/sbin/nologin app \
 && mkdir /data && chown app /data
COPY app ./app
USER 10001
EXPOSE 8787
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787", "--no-server-header"]
