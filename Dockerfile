FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends gcc curl \
    && rm -rf /var/lib/apt/lists/*

# /app is WORKDIR. Python adds the running script's directory to sys.path[0].
# Since CMD runs `python main.py` and main.py lives in /app,
# Python adds /app to sys.path automatically — config.py, scanner.py, etc.
# are all in /app and therefore importable with plain `import config`.
# No PYTHONPATH, no sys.path tricks, no packages — just flat files.
WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

RUN useradd -m -u 1000 ids && chown -R ids:ids /app
USER ids

CMD ["python", "-u", "main.py"]
