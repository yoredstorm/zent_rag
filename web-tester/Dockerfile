# =============================================================================
# Web Tester Dockerfile — Sirve el SPA via HTTP (Python http.server)
# =============================================================================
FROM python:3.11-alpine

WORKDIR /app
COPY index.html /app/

EXPOSE 8080

CMD ["python", "-m", "http.server", "8080", "--bind", "0.0.0.0"]
