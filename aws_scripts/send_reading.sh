#!/bin/bash

# Check if all arguments are provided
if [ "$#" -ne 4 ] && [ "$#" -ne 1 ]; then
    echo "Usage: ./send_reading.sh store <date> <peak> <off_peak>"
    echo "Usage: ./send_reading.sh <command>"
    echo ""
    echo "Example: ./send_reading.sh store 2025-06-03 14 33"
    echo "Example: ./send_reading.sh check"
    echo ""
    echo "Available commands: "
    echo "store <date> <peak> <off_peak>"
    echo "delete (latest entry)"
    echo "check (latest entry)"
    echo "calculate (statistics)"
    exit 1
fi


COMMAND="${1:-"store"}"

DATE="${2:-"none"}"
PEAK="${3:-0}"
OFF_PEAK="${4:-0}"


# Send the request
curl -s -X POST $LAMBDA_URL \
  -H "Content-Type: application/json" \
  -d "{\"command\": \"$COMMAND\", \"peak\": $PEAK, \"off_peak\": $OFF_PEAK, \"date\": \"$DATE\", \"api_key\": \"$METER_READINGS_PROCESSOR_LAMBDA_API_KEY\"}"

