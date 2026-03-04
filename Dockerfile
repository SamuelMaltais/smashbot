# Use official Python slim image
FROM python:3.11-slim

# Set a working directory
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run the bot
CMD ["python", "bot.py"]
