# Vistora backend — container image for Hugging Face Spaces (Docker SDK),
# also usable on Render, Railway, Fly.io or any Docker host.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/.cache/huggingface \
    PORT=7860 \
    # Hosting platforms put a proxy in front of the app; use the visitor's
    # address from X-Forwarded-For for per-visitor search limits.
    TRUST_PROXY_HEADERS=true

# Spaces run containers as user 1000.
RUN useradd --create-home --uid 1000 user
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=user:user . .

USER user
EXPOSE 7860

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
