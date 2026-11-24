FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends espeak-ng \
    && useradd --system --uid 10002 --home-dir /opt/coinline coinline \
    && install -d -o coinline -g coinline /var/lib/coinline/providers
WORKDIR /opt/coinline
COPY service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY service/coinline_adsi ./coinline_adsi
COPY fixtures ./fixtures
COPY docs/spec/graph.schema.json ./graph.schema.json
COPY --from=web /web/dist ./web
USER coinline
CMD ["uvicorn", "coinline_adsi.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
