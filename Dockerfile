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

EXPOSE 8000 8001

# Web server by default; the twilio compose service overrides this command.
CMD ["python", "client.py"]
