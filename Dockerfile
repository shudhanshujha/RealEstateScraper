FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies required for headless browsers (Chromium)
RUN apt-get update && apt-get install -y \
    wget gnupg libgconf-2-4 libxss1 libnss3 libnspr4 libasound2 \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxcomposite1 \
    libxdamage1 libxrandr2 libgbm1 libxkbcommon0 libpango-1.0-0 \
    libpangocairo-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Scrapling browser binaries
RUN scrapling install

# Copy application files
COPY . .

# Expose the port the app runs on
EXPOSE 8080

# Command to run the application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
