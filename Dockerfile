FROM python:3.10-slim

# Install system dependencies required for the bot:
# - tesseract-ocr for OCR functionality
# - python3-venv for creating virtual environments
# - build-essential and libtesseract-dev for compiling and linking dependencies
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    python3-venv \
    build-essential \
    libtesseract-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the requirements file and install Python dependencies inside a virtual environment
COPY requirements.txt .

RUN python -m venv --copies /opt/venv \
    && . /opt/venv/bin/activate \
    && pip install --upgrade pip \
    && pip install -r requirements.txt

# Copy the rest of the application code
COPY . .

# Run the Telegram bot
CMD ["/opt/venv/bin/python", "main.py"]
