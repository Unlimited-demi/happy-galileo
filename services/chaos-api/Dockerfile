FROM node:20-alpine

WORKDIR /app

# Install OpenSSL required by Prisma engine on Alpine Linux
RUN apk add --no-cache openssl libc6-compat

# Install dependencies
COPY package.json ./
RUN npm install

# Copy Prisma schema & generate client
COPY prisma ./prisma/
RUN npx prisma generate

# Copy application source
COPY . .

EXPOSE 3000

# Non-root user for security
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
RUN chown -R appuser:appgroup /app
USER appuser

CMD ["node", "server.js"]
