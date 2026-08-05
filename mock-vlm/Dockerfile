FROM python:3.12-slim
# Stdlib only - no pip installs needed.
COPY server.py /app/server.py
ENV PORT=9090 LOG_DIR=/logs
EXPOSE 9090
CMD ["python", "-u", "/app/server.py"]
