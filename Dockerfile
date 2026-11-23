FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TZ=Asia/Jakarta
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY salesapp ./salesapp
COPY app.py ./
COPY .streamlit ./.streamlit

# uid 1000 matches the usual first user on the VPS, so the mounted ./data stays writable
RUN useradd -m -u 1000 appuser && mkdir -p /app/data && chown -R appuser /app
USER appuser

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8501/_stcore/health')"
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
