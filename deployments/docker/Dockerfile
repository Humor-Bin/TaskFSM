FROM python:3.12-slim
WORKDIR /app
COPY apps/server/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY apps/server /app/apps/server
COPY apps/web /app/apps/web
WORKDIR /app/apps/server
ENV PYTHONPATH=/app/apps/server
CMD ["uvicorn", "taskfsm.main:app", "--host", "0.0.0.0", "--port", "8000"]
