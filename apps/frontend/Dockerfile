FROM node:20-slim

WORKDIR /app

# Copy package files first for layer caching
COPY package*.json ./

RUN npm install --no-audit --no-fund

# Copy source
COPY . .

EXPOSE 5173

# --host 0.0.0.0 makes Vite accessible from outside the container
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
