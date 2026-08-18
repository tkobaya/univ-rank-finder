FROM python:3.12-slim

WORKDIR /app

# app is only needed here to build the package for `pip install .`.
# At runtime the bind mount (./app:/app/app in docker-compose.yml) takes precedence.
COPY pyproject.toml ./
COPY app ./app

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
