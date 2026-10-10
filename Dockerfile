FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py handlers.py keyboards.py content.py logic.py storage.py ./
COPY photos ./photos
RUN mkdir -p /app/data

CMD ["python", "main.py"]
