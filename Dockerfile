FROM python:3.12-slim

WORKDIR /app

# PyAudio needs portaudio to compile; keep only the runtime lib in the final layer.
COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev portaudio19-dev libportaudio2 \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y gcc libc6-dev portaudio19-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# uid 1000 must match the host owner (ubuntu) of the bind-mounted ./logs, or the
# app's FileHandler fails to open its log file and the container dies on startup.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/logs \
    && chown appuser:appuser /app/logs

EXPOSE 8000 8001

USER appuser

# Web server by default; the twilio compose service overrides this command.
CMD ["python", "client.py"]
