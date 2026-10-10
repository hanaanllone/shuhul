# The website: built once, then served by Caddy, which also passes
# /api to the API container.
FROM node:22-slim AS build
WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend .
RUN npm run build

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv/site
