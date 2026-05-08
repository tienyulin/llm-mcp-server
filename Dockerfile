FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN mkdir -p /root/.pip && \
    echo "[global]\ncert = /dev/null" > /root/.pip/pip.conf && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8002

ENV PYTHONPATH=/app

CMD ["python", "http_api/main.py"]
