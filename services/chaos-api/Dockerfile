FROM node:20-alpine

WORKDIR /app

# Install dependencies first (Docker layer caching)
COPY package.json ./
RUN npm install --production

# Copy application code
COPY . .

EXPOSE 3000

# Run as non-root for security
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser

CMD ["node", "server.js"]
