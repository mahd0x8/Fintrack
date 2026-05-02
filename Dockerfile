FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SQLite database lives on a mounted volume at /data
ENV DB_PATH=/data/finance.db

EXPOSE 5000

# Use gunicorn for production; initialise DB on first start
CMD ["sh", "-c", "python -c 'from app import app, init_db; init_db()' && gunicorn --bind 0.0.0.0:5000 --workers 1 --timeout 120 app:app"]
