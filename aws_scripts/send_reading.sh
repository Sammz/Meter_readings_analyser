#!/bin/bash

# Check if all arguments are provided
if [ "$#" -ne 3 ]; then
    echo "Usage: ./send_reading.sh <date> <peak> <off_peak> "
    echo "Example: ./send_reading.sh 2025-06-03 14 33 "
    exit 1
fi

DATE=$1
PEAK=$2
OFF_PEAK=$3

# Send the request
response=$(curl -s -X POST $LAMBDA_URL \
  -H "Content-Type: application/json" \
  -d "{\"peak\": $PEAK, \"off_peak\": $OFF_PEAK, \"date\": \"$DATE\", \"api_key\": \"$METER_READINGS_PROCESSOR_LAMBDA_API_KEY\"}")

echo "-----------------------------------"
echo $response

echo "-----------------------------------"

echo "$response" | jq -r 'to_entries[] | "\(.key): \(.value)"'
echo "-----------------------------------"


#curl -w '\nResponse code: %{http_code}\n' -X POST $LAMBDA_URL -H "Content-Type: application/json" -d "{\"peak\": 1, \"off_peak\": 1, \"date\": \"2020-10-10\", \"api_key\": \"hoi\"}"