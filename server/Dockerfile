FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir '.[service]'
ENV SCORE_PARTS_USAGE_DB=/data/trial_usage.sqlite3
RUN mkdir -p /data
EXPOSE 8000
CMD ["uvicorn", "score_parts.ai_service:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
