FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Installa le dipendenze di sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copia e installa le dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Se easyocr fallisce, usa --no-deps e installa torch dopo
# (ma tentiamo prima con requirements.txt)

COPY autosurf_complete.py .

CMD ["python", "autosurf_complete.py"]
