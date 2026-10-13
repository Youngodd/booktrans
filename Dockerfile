FROM python:3.12-slim

# Build with a nearer PyPI mirror if the default is slow:
#   docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=$PIP_INDEX_URL PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt requirements-web.txt ./
RUN pip install -r requirements-web.txt
COPY booktrans ./booktrans

RUN useradd --create-home app && mkdir /data && chown app /data
USER app
ENV BOOKTRANS_DATA=/data HOST=0.0.0.0 PORT=8000
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
CMD ["python", "-m", "booktrans.web"]
