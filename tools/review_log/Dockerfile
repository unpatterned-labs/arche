FROM python:3.12-slim

WORKDIR /app

COPY tools/review_log/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tools/review_log/app.py .

ENV REVIEW_PACK=/data/adjudication_pack.csv

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
