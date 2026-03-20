FROM python:3.11

# Install Node.js 22 LTS via NodeSource (Vite 7 requires Node >= 20)
RUN apt-get update \
  && apt-get install -y --no-install-recommends curl ca-certificates \
  && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
  && apt-get install -y --no-install-recommends nodejs \
  && rm -rf /var/lib/apt/lists/*

# Copy uv from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files first to maximise layer caching
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package-lock.json ./frontend/
COPY backend/pyproject.toml backend/uv.lock ./backend/

# Install all dependencies (Node root + frontend + Python backend)
RUN npm ci \
  && npm ci --prefix frontend \
  && cd backend && uv sync

# Copy project source
COPY . .

EXPOSE 3000 5001

CMD ["npm", "run", "dev"]
