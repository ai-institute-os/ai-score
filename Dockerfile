FROM python:3.12-slim

WORKDIR /app

# System dependencies for Puppeteer/Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    ca-certificates \
    # Chromium runtime deps
    libglib2.0-0 \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libfontconfig1 \
    libfreetype6 \
    libx11-xcb1 \
    libxcb1 \
    libxext6 \
    libxss1 \
    fonts-liberation \
    fonts-noto \
  && rm -rf /var/lib/apt/lists/*

# Install Node.js 20 LTS
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
  && apt-get install -y --no-install-recommends nodejs \
  && rm -rf /var/lib/apt/lists/*

# Install Puppeteer (downloads bundled Chromium)
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application source
COPY scripts/ scripts/
COPY src/ src/

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
