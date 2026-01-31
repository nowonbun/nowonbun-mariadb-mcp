#!/usr/bin/env bash
set -e

echo "Stopping existing containers (if any)..."
docker compose down || true

echo "Pulling latest code..."
git pull origin

echo "Building images..."
docker compose build

echo "Starting containers..."
docker compose up -d

echo "Deploy complete."
