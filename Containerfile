FROM docker.io/library/python:3-slim

WORKDIR /app
COPY . /app
RUN pip install -r requirements.txt

ENTRYPOINT ["python3", "/app/main.py"]
