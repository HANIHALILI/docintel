# docintel service — Phase 1 (fast parse lane + async VLM lane).
FROM python:3.12-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Package copied as docintel/ so `uvicorn docintel.api:app` resolves.
COPY . /srv/docintel/
ENV XBERG_CACHE_DIR=/cache
RUN mkdir -p /cache

EXPOSE 8090
CMD ["uvicorn", "docintel.api:app", "--host", "0.0.0.0", "--port", "8090"]
