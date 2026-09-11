FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY sql/ ./sql/
COPY models/ ./models/

# Cloud Run injects PORT. Do not hardcode 8080.
ENV PORT=8080
EXPOSE 8080

CMD exec uvicorn src.api:app --host 0.0.0.0 --port ${PORT}
