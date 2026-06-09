FROM mcr.microsoft.com/playwright/python:v1.59.0-noble

WORKDIR /app

# El image trae los browsers en /ms-playwright pero no el módulo pip de playwright.
# Pinear a 1.59.* para que matchee con los binarios del image.
RUN pip install --no-cache-dir requests "playwright==1.59.*" "psycopg[binary]>=3.1"

COPY *.py ./
COPY *.js ./

ENV CELICA_BIND=0.0.0.0 \
    CELICA_PORT=8765 \
    PYTHONUNBUFFERED=1

EXPOSE 8765

CMD ["python3", "serve.py"]
