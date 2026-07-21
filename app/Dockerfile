FROM python:3.12-slim
WORKDIR /app
# tesseract-ocr-msa (Malay) is left out — ponytail: not confirmed to install cleanly on
# this base image; English OCR still reads most Malay Latin text acceptably. Add it here
# if it packages cleanly on a real build.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Bake the embedding model into the image so neither api nor bot pays a first-request
# download stall, and both work offline.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
