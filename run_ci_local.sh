#!/bin/bash
set -e

# Load your secrets
if [ ! -r .secrets ]; then
  echo "Error: .secrets file is missing or not readable. Create .secrets with the required environment variables before running this script." >&2
  exit 1
fi

# Variables
IMAGE_TAG="abdum1964/annotation:staging"
APP_PORT="5006"
MONGODB_DOCKER_PORT="27021"
CADDY_PORT="5557"
CADDY_PORT_FORWARD="6001"
MONGO_URI="mongodb://mongodb:27017/annotation"
REDIS_URL="redis://redis:6379/0"
REDIS_EXPIRATION="3600"
PARENT_DIR="/tmp/test_data"
LLM_MODEL="gemini"
MAIL_USE_TLS="False"
MAIL_USE_SSL="False"
DOCKER_HUB_REPO="abdum1964/annotation"
AXIOM_DATASET="application-logs"
AXIOM_PERFORMANCE_LOGS="performance-metrics"

# Step 1: Build
echo "=== Building image ==="
docker build --build-arg APP_PORT=$APP_PORT -t $IMAGE_TAG .

# Step 2: Write compose file
cat > docker-compose.ci.yml << EOF
services:
  annotation_service:
    image: ${IMAGE_TAG}
    container_name: annotation_service-staging
    ports:
      - "${APP_PORT}:${APP_PORT}"
    volumes:
      - .:/app
    command: gunicorn app.main:socket_app --workers 1 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:${APP_PORT}
    restart: unless-stopped
    depends_on:
      - mongodb
      - redis
    environment:
      - APP_PORT=${APP_PORT}
      - MONGO_URI=${MONGO_URI}
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - REDIS_URL=${REDIS_URL}
      - REDIS_EXPIRATION=${REDIS_EXPIRATION}
      - NEO4J_URI=${NEO4J_URI}
      - NEO4J_USERNAME=${NEO4J_USERNAME}
      - NEO4J_PASSWORD=${NEO4J_PASSWORD}
      - HUMAN_NEO4J_URI=${HUMAN_NEO4J_URI}
      - HUMAN_NEO4J_USERNAME=${HUMAN_NEO4J_USERNAME}
      - HUMAN_NEO4J_PASSWORD=${HUMAN_NEO4J_PASSWORD}
      - FLY_NEO4J_URI=${FLY_NEO4J_URI}
      - FLY_NEO4J_USERNAME=${FLY_NEO4J_USERNAME}
      - FLY_NEO4J_PASSWORD=${FLY_NEO4J_PASSWORD}
      - LLM_MODEL=${LLM_MODEL}
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - JWT_SECRET=${JWT_SECRET}
      - SECRET_KEY=${SECRET_KEY}
      - MAIL_SERVER=${MAIL_SERVER}
      - MAIL_PORT=${MAIL_PORT}
      - MAIL_USERNAME=${MAIL_USERNAME}
      - MAIL_PASSWORD=${MAIL_PASSWORD}
      - MAIL_DEFAULT_SENDER=${MAIL_DEFAULT_SENDER}
      - MAIL_USE_TLS=${MAIL_USE_TLS}
      - MAIL_USE_SSL=${MAIL_USE_SSL}
      - SENTRY_DSN=${SENTRY_DSN}
      - AXIOM_TOKEN=${AXIOM_TOKEN}
      - AXIOM_DATASET=${AXIOM_DATASET}
      - AXIOM_PERFORMANCE_LOGS=${AXIOM_PERFORMANCE_LOGS}
      - MORK_URL=${MORK_URL}
      - PARENT_DIR=${PARENT_DIR}
      - MORK_DATA_DIR=/tmp/mork_data
      - ES_URL=http://elasticsearch:9200
      - ES_API_KEY=test_api_key
      - DOCKER_HUB_REPO=${DOCKER_HUB_REPO}

  mongodb:
    image: mongo:latest
    container_name: mongodb-staging
    ports:
      - "${MONGODB_DOCKER_PORT}:27017"
    restart: unless-stopped

  redis:
    image: redis:latest
    container_name: redis-staging
    ports:
      - "6382:6379"
    restart: unless-stopped

  caddy:
    image: caddy:latest
    container_name: caddy-staging
    ports:
      - "${CADDY_PORT}:${CADDY_PORT_FORWARD}"
    command: caddy reverse-proxy --from http://0.0.0.0:${CADDY_PORT_FORWARD} --to http://annotation_service:${APP_PORT}
    restart: unless-stopped
    depends_on:
      - annotation_service

volumes:
  mongo_data:
  redis_data:
  caddy_data:
  caddy_config:
EOF

# Step 3: Setup dirs
mkdir -p /tmp/test_data /tmp/mork_data public
touch /tmp/mork_data/annotation.act

# Step 4: Start
echo "=== Starting services ==="
docker compose -p annotation-staging -f docker-compose.ci.yml up -d

MAX_HEALTH_WAIT_SECONDS=60
HEALTH_CHECK_INTERVAL_SECONDS=2
HEALTH_ELAPSED_SECONDS=0
until curl -fsS "http://localhost:${APP_PORT}/health" >/dev/null; do
  if [ "$HEALTH_ELAPSED_SECONDS" -ge "$MAX_HEALTH_WAIT_SECONDS" ]; then
    break
  fi
  sleep "$HEALTH_CHECK_INTERVAL_SECONDS"
  HEALTH_ELAPSED_SECONDS=$((HEALTH_ELAPSED_SECONDS + HEALTH_CHECK_INTERVAL_SECONDS))
done
# Step 5: Check
docker logs annotation_service-staging --tail 50
if curl -fsS "http://localhost:${APP_PORT}/health" >/dev/null; then
  echo "HEALTH OK"
else
  echo "HEALTH FAILED"
fi