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

# Playwright du serveur, versions figées, chacun dans son dossier (ils n'utilisent pas la même version de Playwright) :
#   /opt/qaf-playwright      exécution des scripts des projets (outils/execution_scripts.py) et vérification TypeScript ;
#   /opt/qaf-playwright-mcp  navigateur de l'agent (MCP Playwright, saas/navigateur_mcp.mjs).
# Chromium de chacun et dépendances système.
ARG PLAYWRIGHT_VERSION=1.64.1
ARG PLAYWRIGHT_MCP_VERSION=0.0.84
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    QAF_PLAYWRIGHT_DIR=/opt/qaf-playwright \
    PLAYWRIGHT_MCP_CLI=/opt/qaf-playwright-mcp/node_modules/@playwright/mcp/cli.js
RUN npm config set fetch-retries 5 && npm config set fetch-retry-mintimeout 20000 \
 && npm config set fetch-retry-maxtimeout 120000 && npm config set maxsockets 4 \
 && mkdir -p /opt/qaf-playwright /opt/qaf-playwright-mcp \
 && cd /opt/qaf-playwright && echo '{"name":"qaf-playwright","private":true}' > package.json \
 && npm install --no-audit --no-fund --save-exact @playwright/test@${PLAYWRIGHT_VERSION} typescript@5.7.3 @types/node@22.20.5 \
 && node node_modules/playwright/cli.js install --with-deps chromium \
 && cd /opt/qaf-playwright-mcp && echo '{"name":"qaf-playwright-mcp","private":true}' > package.json \
 && npm install --no-audit --no-fund --save-exact @playwright/mcp@${PLAYWRIGHT_MCP_VERSION} \
 && node node_modules/playwright/cli.js install chromium \
 && rm -rf /var/lib/apt/lists/* /root/.npm \
 && chmod -R a+rX /opt/ms-playwright /opt/qaf-playwright /opt/qaf-playwright-mcp

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
# Construite depuis un poste Windows, la copie peut avoir des fins de ligne CRLF : le script de démarrage ne s'exécuterait pas.
RUN sed -i 's/\r$//' saas/*.sh \
 && git init -q . \
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
