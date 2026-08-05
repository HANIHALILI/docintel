# Single-image XBERG service with the `captioning` feature.
#
# The published xberg/kreuzberg Docker images are compiled WITHOUT the
# `captioning` Cargo feature (verified by binary inspection), so they silently
# ignore captioning config. The Linux Python wheel of xberg 1.0.0rc29 IS
# compiled with it — this image wraps that wheel with a thin HTTP layer.
FROM python:3.12-slim

RUN pip install --no-cache-dir --pre "xberg==1.0.0rc29" fastapi uvicorn python-multipart

COPY app.py /app/app.py
WORKDIR /app

# Model/tessdata cache — mount a volume here so Tesseract language data
# (auto-downloaded on the first scanned-page OCR) survives restarts.
ENV XBERG_CACHE_DIR=/cache
RUN mkdir -p /cache && chmod 777 /cache

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
