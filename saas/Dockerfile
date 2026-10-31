# Image unique de QA Factory SaaS : sert au conteneur « moteur » (OpenCode) et au conteneur « web ».
# Construction (depuis saas/) : docker compose build
FROM python:3.12-slim-bookworm

ARG NODE_MAJOR=22
ARG OPENCODE_VERSION=1.19.5

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git gnupg pandoc \
 && curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

# OpenCode, version figée (une mise à jour se teste d'abord sur le projet SauceDemo)
RUN npm install -g opencode-ai@${OPENCODE_VERSION}

# MCP Squash (fork) : fourni par le contexte de construction « squash_mcp » (voir docker-compose.yml)
COPY --from=squash_mcp . /opt/squash-tm-mcp
RUN cd /opt/squash-tm-mcp \
 && rm -rf node_modules dist \
 && npm ci \
 && npm run build \
 && npm prune --omit=dev

WORKDIR /srv/qa-factory
COPY saas/requirements.txt saas/requirements.txt
RUN pip install --no-cache-dir -r saas/requirements.txt

COPY . .
RUN git init -q . \
 && useradd -m -u 10001 qaf \
 && mkdir -p /srv/donnees \
 && chown -R qaf:qaf /srv/qa-factory /srv/donnees

USER qaf
ENV QAF_RACINE=/srv/qa-factory \
    QAF_DONNEES=/srv/donnees \
    SQUASH_MCP_DIR=/opt/squash-tm-mcp \
    SQUASH_MCP_INDEX=/opt/squash-tm-mcp/dist/index.js \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["saas/demarrer.sh", "web"]
