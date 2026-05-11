FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund

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
