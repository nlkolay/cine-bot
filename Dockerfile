FROM python:3.12-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py extractor.py tmdb_client.py omdb_client.py formatter.py llm_client.py arr_client.py main.py ./

CMD ["python", "main.py"]
