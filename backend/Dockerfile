# Local development image only. AWS deploys use Lambda zip packages (Phase 5), not containers,
# to avoid ECR storage costs.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
# Editable install so docker-compose can mount ./src over it for hot reload.
RUN pip install -e ".[server]"

RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8000
CMD ["uvicorn", "documind.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
