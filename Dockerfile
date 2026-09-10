FROM python:3.12-slim

# Set a working directory
WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app
COPY app/ ./app/

# Create the data directory (overridden by the volume mount at runtime)
RUN mkdir -p /data

# Expose the web UI port
EXPOSE 8080

# Run the app
CMD ["python", "-m", "app.main"]