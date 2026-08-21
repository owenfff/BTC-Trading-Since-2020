FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LIVE_ENABLED=false \
    MAXIMUM_LIVE_RISK=0 \
    MAXIMUM_LIVE_NOTIONAL=0

WORKDIR /app

COPY quant/runtime-requirements.txt /app/quant/runtime-requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r /app/quant/runtime-requirements.txt

COPY . /app
RUN python -m compileall -q quant_bot

USER nobody

ENTRYPOINT ["python", "-m", "quant_bot"]
CMD ["run", "--mode", "paper", "--input", "/app/quant/fixtures/model_dataset_smoke.csv", "--state", "/tmp/runtime_state.json", "--limit", "1"]
