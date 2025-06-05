#!/bin/bash

# Check if all arguments are provided
if [ "$#" -ne 3 ]; then
    echo "Usage: ./send_reading.sh <peak> <off_peak> <date>"
    echo "Example: ./send_reading.sh 14 33 2025-06-03"
    exit 1
fi

PEAK=$1
OFF_PEAK=$2
DATE=$3

# Your Lambda function URL
LAMBDA_URL="https://rk7tfl27zpfw7rfpfyujfiby4e0cners.lambda-url.eu-west-2.on.aws/"

# Send the request
curl -w '\nResponse code: %{http_code}\n' -X POST $LAMBDA_URL \
  -H "Content-Type: application/json" \
  -d "{\"peak\": $PEAK, \"off_peak\": $OFF_PEAK, \"day\": \"$DATE\", \"api_key\": \"$METER_READINGS_PROCESSOR_LAMBDA_API_KEY\"}"

echo "woohoo"


#curl -w '\nResponse code: %{http_code}\n' -X POST https://rk7tfl27zpfw7rfpfyujfiby4e0cners.lambda-url.eu-west-2.on.aws/ -H "Content-Type: application/json" -d "{\"peak\": 1, \"off_peak\": 1, \"day\": \"2020-10-10\", \"api_key\": \"hoi\"}"