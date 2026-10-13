FROM node:22-alpine3.24 AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine3.24 AS builder
WORKDIR /app
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine3.24 AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN /sbin/apk upgrade --no-cache libssl3 libcrypto3 zlib \
    && /sbin/apk add --no-cache 'zlib>=1.3.2-r1' \
    && /sbin/apk info -v libssl3 libcrypto3 zlib \
    && rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack \
    && rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack \
        /usr/local/bin/pnpm /usr/local/bin/pnpx /usr/local/bin/yarn /usr/local/bin/yarnpkg \
    && node --version
# Keep the application and bundled server code root-owned/read-only to the
# runtime. Only Next's bounded image/cache directory needs write access.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
RUN mkdir -p /app/.next/cache \
    && chown 1000:1000 /app/.next/cache \
    && chmod 0700 /app/.next/cache

# node:22-alpine includes the stable node UID/GID 1000; use numeric IDs
# explicitly so production container identity cannot change with defaults.
USER 1000:1000
EXPOSE 3000
CMD ["node", "server.js"]
