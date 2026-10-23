FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY retailpulse ./retailpulse
ENV RETAILPULSE_DATA_DIR=/data
ENV RETAILPULSE_REQUIRE_TOKEN=1
EXPOSE 8000
# One process keeps the retraining job lock coherent. SQLite serializes stock mutations.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "120", "retailpulse.web:create_app()"]
