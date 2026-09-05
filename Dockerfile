# AIE — deployable container (Agentic Institution Engineering runtime)
# Python 3.12 slim base; the runtime is stdlib + sqlite3 only.
FROM python:3.12-slim

WORKDIR /app

COPY src/ ./src/
COPY scripts/ ./scripts/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

# The AIE runtime has no HTTP server of its own — it runs as bridge CLIs
# (aie_revalidate_bridge.py, aie_authority_bridge.py) invoked by TG.
# This container exists for deployment packaging + a smoke entrypoint.
HEALTHCHECK --interval=60s --timeout=10s --retries=2 \
  CMD python -c "import aie_runtime.engine; import aie_runtime.persistent_state" || exit 1

# Run as non-root.
USER 1000

# Default: smoke check that the runtime imports cleanly.
CMD ["python", "-c", "from aie_runtime.engine import AdmissionEngine; from aie_runtime.persistent_state import PersistentState; print('aie runtime ok')"]
