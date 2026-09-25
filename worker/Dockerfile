FROM python:3.12-slim
WORKDIR /app
COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY worker/agent.py .
CMD ["python", "-u", "agent.py"]
