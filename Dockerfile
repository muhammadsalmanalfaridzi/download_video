FROM python:3.12-slim
# node dipakai yt-dlp untuk menjalankan JS challenge YouTube
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-8012}
