# fd-cn-report image — flat py-modules layout, full dependency set.
#
# The source tree is copied to /app and the server runs in place
# (`python server.py`) so every root-level module ships; `pip install .`
# exists only to resolve the pyproject dependency set. HTTP transport is the
# image default (MCP_TRANSPORT=http, 0.0.0.0:8301); set MCP_BEARER_TOKEN at
# deploy time to require a bearer token. Report PDFs, the extraction cache,
# and the rules DB live under /data — mount the fd-cn-report-data PVC there
# (CNREPORT_SAVE_DIR / CNREPORT_CACHE_DIR / DAAS_DATABASE_URL in the k8s
# manifest point at it).
#
# Built and pushed by .github/workflows/docker-publish.yml
# -> <HARBOR_HOST>/finddata/fd-cn-report.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8301

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 1000 cnreport
USER cnreport

EXPOSE 8301
ENTRYPOINT ["python", "server.py"]
