FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates tar && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py admin_panel.py state_store.py db_compat.py hetzner_autoscaler.py scaling_policy.py autoscaler_smoke.py i18n.py .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
