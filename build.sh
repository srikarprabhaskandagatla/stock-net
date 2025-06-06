#!/bin/bash
set -e
echo "Building Docker Images."
MODE="${1:-nopaxos}"
if [[ "$MODE" == "paxos" ]]; then
    COMPOSE_FILE="docker-compose.paxos.yml"
    echo "Using Compose file: $COMPOSE_FILE"
    docker-compose -f "$COMPOSE_FILE" build
    docker-compose -f "$COMPOSE_FILE" up client-service-paxos
    # echo "Running  Tests."
    docker-compose -f "$COMPOSE_FILE" up test
else
    COMPOSE_FILE="docker-compose.yml"
    echo "Using Compose file: $COMPOSE_FILE"
    docker-compose -f "$COMPOSE_FILE" build
    docker-compose -f "$COMPOSE_FILE" up client-service
    # echo "Running  Tests."
    docker-compose -f "$COMPOSE_FILE" up test
fi