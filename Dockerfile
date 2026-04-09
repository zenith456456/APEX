FROM python:3.11-slim

WORKDIR /app

# Install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY *.py .
COPY .env.example .

# Non-root user for security
RUN useradd -m botuser
USER botuser

CMD ["python", "main.py"]
