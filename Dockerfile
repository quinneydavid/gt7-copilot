FROM python:3.13.15-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b
LABEL org.opencontainers.image.title="gt7-copilot" \
      org.opencontainers.image.description="Gran Turismo 7 telemetry collector, lap analysis, tune library and voice copilot" \
      org.opencontainers.image.source="https://github.com/quinneydavid/gt7-copilot" \
      org.opencontainers.image.licenses="MIT"
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
# /models is made first: an ADD --chmod=644 that creates the directory gives the directory 644 too (no entry, 0.3.0 bug).
RUN mkdir -p /models && chmod 755 /models
# Kokoro voice model (the copilot's voice is made locally). Pinned by checksum.
ADD --checksum=sha256:7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5 --chmod=644 \
    https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx /models/kokoro-v1.0.onnx
ADD --checksum=sha256:bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d --chmod=644 \
    https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin /models/voices-v1.0.bin
# Named volumes take their owner from these folders: the app runs as user 1000 and must be able to write both.
RUN mkdir -p /data /shared && chown 1000:1000 /data /shared
COPY data/cars.csv data/maker.csv data/carspecs.csv data/stockpp.csv data/knowledge.json data/circuits.json /app/data/
COPY web /app/web
COPY earpiece /app/earpiece
COPY gt7copilot /app/gt7copilot
COPY LICENSE THIRD-PARTY-NOTICES.md /app/
WORKDIR /app
USER 1000:1000
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/tmp GT7C_DATA=/data GT7C_MODELS=/models GT7C_PORT=8765
EXPOSE 8765/tcp 33740/udp
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python3", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('GT7C_PORT', '8765') + '/healthz', timeout=4)"]
ENTRYPOINT ["python3", "-m", "gt7copilot.daemon"]
