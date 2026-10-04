# Lean runtime image — graphify (dev tooling) is intentionally excluded.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Dependencies first so the layer is cached between code changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Application only — no tests, no dev tooling, no state.
COPY app ./app
COPY web ./web
COPY data ./data

# Runtime state writes here; mount a volume to persist it.
RUN mkdir -p /srv/.bahi && chmod 777 /srv/.bahi

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; \
      sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
