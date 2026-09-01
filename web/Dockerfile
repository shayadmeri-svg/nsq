# Multi-stage build: node compiles the Vite React app, nginx serves the
# static bundle. Mirrors the repo's pinned-base + curl-healthcheck style.

# --- build stage ---
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY tsconfig.json tsconfig.app.json tsconfig.node.json ./
COPY vite.config.ts tailwind.config.ts postcss.config.js index.html ./
COPY src/ src/
RUN npm run build

# --- serve stage ---
FROM nginx:alpine
RUN apk add --no-cache curl
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost/health || exit 1