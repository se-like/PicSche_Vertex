FROM python:3.11-slim-bookworm

WORKDIR /app

# pip を更新してからインストール（Cloud Build での互換性向上）
RUN pip install --no-cache-dir -U pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
