FROM node:20-alpine AS deps
WORKDIR /app
# Copy the lock file when present so `npm ci` produces a deterministic
# install across rebuilds. Falls back to `npm install` for early dev
# builds before a lock has been generated.
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then \
      npm ci --no-audit --no-fund; \
    else \
      npm install --no-audit --no-fund; \
    fi

FROM node:20-alpine AS builder
WORKDIR /app
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_API_PORT=8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_PUBLIC_API_PORT=${NEXT_PUBLIC_API_PORT}
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
RUN addgroup -S jsp && adduser -S jsp -G jsp
COPY --from=builder /app/public ./public
COPY --from=builder --chown=jsp:jsp /app/.next/standalone ./
COPY --from=builder --chown=jsp:jsp /app/.next/static ./.next/static
USER jsp
EXPOSE 3000
CMD ["node", "server.js"]
