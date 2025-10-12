#!/bin/bash
# Cron script to calculate and save rental statistics
# This script calls the statistics API endpoint

# Configuration
API_URL="${API_URL:-http://localhost:5000/api/statistics/calculate}"
LOG_FILE="${LOG_FILE:-/tmp/rental_statistics_cron.log}"

# Function to log messages
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Make API call
log "Starting rental statistics calculation..."

response=$(curl -s -X POST "$API_URL" \
    -H "Content-Type: application/json" \
    -w "\nHTTP_STATUS:%{http_code}")

# Extract HTTP status code
http_status=$(echo "$response" | grep "HTTP_STATUS" | cut -d: -f2)
body=$(echo "$response" | sed '/HTTP_STATUS/d')

# Check response
if [ "$http_status" = "200" ]; then
    log "✓ Statistics calculated successfully"
    log "Response: $body"
    exit 0
else
    log "✗ Failed to calculate statistics (HTTP $http_status)"
    log "Response: $body"
    exit 1
fi
