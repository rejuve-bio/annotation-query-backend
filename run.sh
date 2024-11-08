#!/bin/bash
#read the environment variables
source .env
# Define the network name
NETWORK_NAME="annotation_network"

# Function to handle cleanup
cleanup() {
    echo "Cleaning up existing containers and network..."
    docker stop mongodb annotation_service caddy || true
    docker rm mongodb annotation_service caddy || true
    docker network rm annotation_network || true
}

if [ "$1" == "run" ]; then
    cleanup

    # Create the Docker network
    echo "Creating Docker network: $NETWORK_NAME..."
    docker network create $NETWORK_NAME

    # Pull the necessary images
    echo "Pulling Docker images..."
    docker pull mongo:latest
    docker pull $DOCKER_HUB_REPO
    docker pull caddy:latest

    # Run MongoDB container
    echo "Running MongoDB container..."
    sudo docker run -d \
      --name mongodb \
      --network $NETWORK_NAME \
      -p $MONGODB_DOCKER_PORT:27017 \
      -v mongo_data:/data/db \
      mongo:latest

    # Wait for MongoDB to start
    echo "Waiting for MongoDB to start..."
    sleep 10

    # Run Annotation Service container
    echo "Running Annotation Service container..."
    sudo docker run -d \
      --name annotation_service \
      --network $NETWORK_NAME \
      -p $APP_PORT:$APP_PORT \
      -e MONGO_URI=mongodb://mongodb:27017/annotation \
      $DOCKER_HUB_REPO

    # Wait for Annotation Service to start
    echo "Waiting for Annotation Service to start..."
    sleep 10

    # Run Caddy container
    echo "Running Caddy container..."
    sudo docker run -d \
      --name caddy \
      --network $NETWORK_NAME \
      -p $CADDY_PORT:$CADDY_PORT_FORWARD \
      -v caddy_data:/data \
      -v caddy_config:/config \
      caddy:latest \
      caddy reverse-proxy --from http://localhost:$CADDY_PORT --to http://annotation_service:$APP_PORT

    echo "All containers are up and running!"

elif [ "$1" == "push" ]; then
    echo "Building Docker images..."
    sudo docker-compose build

    echo "Pushing Docker images to Docker Hub..."
    sudo docker-compose push

    echo "Pushing to Docker Hub is finished."


elif [ "$1" == "clean" ]; then
    cleanup

elif [ "$1" == "stop" ]; then
    echo "Stopping existing containers and network..."
    docker stop mongodb annotation_service caddy || true

elif [ "$1" == "re-run" ]; then
    echo "Re-running existing containers..."
    if ! docker network inspect annotation_network >/dev/null 2>&1; then
        echo "Creating Docker network: annotation_network..."
        docker network create annotation_network
    fi

    # Run existing containers (no need to pull again)
    echo "Starting MongoDB container..."
    sudo docker start mongodb || {
        echo "MongoDB container does not exist, creating it..."
        sudo docker run -d \
          --name mongodb \
          --network annotation_network \
          -p $MONGODB_DOCKER_PORT:27017 \
          -v mongo_data:/data/db \
          mongo:latest
    }

    echo "Starting Annotation Service container..."
    sudo docker start annotation_service || {
        echo "Annotation Service container does not exist, creating it..."
        sudo docker run -d \
          --name annotation_service \
          --network annotation_network \
          -p $APP_PORT:$APP_PORT \
          -e MONGO_URI=mongodb://mongodb:27017/annotation \
          $DOCKER_HUB_REPO
    }

    echo "Starting Caddy container..."
    sudo docker start caddy || {
        echo "Caddy container does not exist, creating it..."
        sudo docker run -d \
          --name caddy \
          --network annotation_network \
          -p $CADDY_PORT:$CADDY_PORT_FORWARD \
          -v caddy_data:/data \
          -v caddy_config:/config \
          caddy:latest \
          caddy reverse-proxy --from http://localhost:$CADDY_PORT --to http://annotation_service:$APP_PORT
    }

    echo "Containers are started or running!"

else
    echo "Invalid command: Allowed commands are push/run/clean/stop/re-run."
fi
