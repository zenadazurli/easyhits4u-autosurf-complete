FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Dipendenze di sistema + Tesseract
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# INSTALLAZIONE SEPARATA: PyTorch prima (chiave per EasyOCR)
RUN pip install --no-cache-dir \
    torch==2.0.1 \
    torchvision==0.15.2 \
    --index-url https://download.pytorch.org/whl/cpu

# Poi il resto delle dipendenze
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia il codice
COPY autosurf_complete.py .

CMD ["python", "autosurf_complete.py"]
