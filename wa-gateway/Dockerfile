FROM node:22-slim

ENV NODE_ENV=production
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund
COPY server.js ./
RUN mkdir -p /app/auth && chown -R node /app
USER node

EXPOSE 3000
CMD ["node", "server.js"]
