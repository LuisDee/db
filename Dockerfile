FROM python:3.12-slim

RUN useradd --create-home --uid 10001 dba_agent
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

USER dba_agent
ENV PYTHONUNBUFFERED=1

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s CMD \
    python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)" \
    || exit 1

CMD ["python", "-m", "dba_agent.app"]
