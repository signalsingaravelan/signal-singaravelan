FROM python:3.11-slim

# Set working directory
WORKDIR /trader-bot

# Copy only requirements first (for caching)
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Entrypoint
ENTRYPOINT ["python", "execute-trade.py"]
