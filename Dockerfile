FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/logs /app/config

EXPOSE 7667  # Changed from 7227 to 7667

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7667"]  # Changed from 7227 to 7667