FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PIP_NO_CACHE_DIR=1 TZ=Asia/Seoul
WORKDIR /app

COPY requirements-web.txt .
RUN pip install -r requirements-web.txt

COPY . .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8110
ENTRYPOINT ["./docker-entrypoint.sh"]
