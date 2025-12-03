#!/bin/bash

# Video Downloader - Quick Test Script
# This script helps verify your setup before deployment

echo "=========================================="
echo "Video Downloader - Setup Verification"
echo "=========================================="
echo ""

# Check if Docker is installed
echo "Checking Docker installation..."
if command -v docker &> /dev/null; then
    echo "✓ Docker is installed"
    docker --version
else
    echo "✗ Docker is not installed"
    echo "  Please install Docker first"
    exit 1
fi

echo ""

# Check if Docker Compose is installed
echo "Checking Docker Compose installation..."
if command -v docker-compose &> /dev/null; then
    echo "✓ Docker Compose is installed"
    docker-compose --version
else
    echo "✗ Docker Compose is not installed"
    echo "  Please install Docker Compose first"
    exit 1
fi

echo ""

# Check required files
echo "Checking required files..."
files=("Dockerfile" "docker-compose.yml" "requirements.txt" "supervisord.conf" "app/app.py" "app/templates/index.html")
all_present=true

for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo "✓ $file"
    else
        echo "✗ $file is missing"
        all_present=false
    fi
done

if [ "$all_present" = false ]; then
    echo ""
    echo "Some required files are missing. Please ensure all files are present."
    exit 1
fi

echo ""

# Check/create directories
echo "Checking directories..."
if [ ! -d "downloads" ]; then
    echo "Creating downloads directory..."
    mkdir downloads
fi
echo "✓ downloads/"

if [ ! -d "chrome-data" ]; then
    echo "Creating chrome-data directory..."
    mkdir chrome-data
fi
echo "✓ chrome-data/"

echo ""

# Check port availability
echo "Checking port availability..."
if lsof -Pi :5000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "⚠ Port 5000 is already in use"
    echo "  You may need to change the port in docker-compose.yml"
else
    echo "✓ Port 5000 is available"
fi

if lsof -Pi :6080 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "⚠ Port 6080 is already in use"
    echo "  You may need to change the port in docker-compose.yml"
else
    echo "✓ Port 6080 is available"
fi

echo ""
echo "=========================================="
echo "Setup verification complete!"
echo "=========================================="
echo ""
echo "To deploy the application:"
echo "  docker-compose up -d"
echo ""
echo "To view logs:"
echo "  docker-compose logs -f"
echo ""
echo "To stop the application:"
echo "  docker-compose down"
echo ""
echo "Access the application at:"
echo "  http://localhost:5000"
echo ""
