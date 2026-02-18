FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY main.py .
COPY config.yaml .

CMD ["python3", "main.py"]
