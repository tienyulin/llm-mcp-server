FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --trusted-host pypi.org --trusted-host pypi.python.org -r requirements.txt

COPY . .

EXPOSE 8002

ENV PYTHONPATH=/app

CMD ["python", "http_api/main.py"]
