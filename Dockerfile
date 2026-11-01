FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m ensurepip --upgrade && python -m pip install --no-cache-dir --upgrade pip     && python -m pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "telegram_bot.py"]
