# syntax=docker/dockerfile:1

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

RUN addgroup -g 10001 nodejs && adduser -u 10001 -G nodejs -S nextjs

# `next.config.mjs` sets `distDir` to `.next-build` when NODE_ENV is production, so the
# build output is NOT in `.next` - this copied the development directory instead, and
# `next start` then looked for a production build that was not in the image.
#
# The config has to travel with it. Without it `next start` falls back to the default
# `.next` and reports no production build found, which reads like a failed build rather
# than a missing file.
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next-build ./.next-build
COPY --from=builder /app/next.config.mjs ./next.config.mjs
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json

USER nextjs
EXPOSE 3000

CMD ["npm", "run", "start"]
