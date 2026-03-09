# ── TuskerSquad: React + Vite Frontend ────────────────────────────────────────
FROM node:20-alpine

WORKDIR /app

# 1. Copy manifests first (cached layer)
COPY package.json package-lock.json ./

# 2. Install deps (reproducible, no audit noise)
RUN npm ci --no-audit --no-fund

# 3. Copy source
COPY . .

EXPOSE 5173

# Vite dev server — proxy targets set via VITE_DASH_URL / VITE_INTEGRATION_URL env
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
