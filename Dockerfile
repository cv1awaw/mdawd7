# Use the official slim Python image
FROM python:3.11-slim

# Don’t write .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install the venv module (needed on slim images)
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Create a virtualenv in /opt/venv and add it to PATH
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv --copies $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Copy only requirements.txt first (to leverage Docker cache)
WORKDIR /app
COPY requirements.txt .

# Upgrade pip and install your Python dependencies
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Now copy in your entire bot code (unchanged)
COPY . .

# When the container starts, run your bot:
# (replace bot.py with whatever your script is named)
CMD ["python", "bot.py"]
