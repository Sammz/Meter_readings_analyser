import boto3
from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Key
import os
import traceback
import json

dynamodb = boto3.resource('dynamodb')
meter_table = dynamodb.Table('meter_readings')
tariff_table = dynamodb.Table('tariff_info')


def lambda_handler(event, context):
    try:
        body = json.loads(event['body'])

        # Check for API key
        api_key = body['api_key']
        if api_key != os.environ.get("METER_READINGS_PROCESSOR_LAMBDA_API_KEY"):
            return {
                'statusCode': 401,
                'body': 'Unauthorized'
            }

        current_peak = body['peak']
        current_off_peak = body['off_peak']
        current_date_string = body['date']  # Format: YYYY-MM-DD
        current_date = ""

        # Check validity of the date
        try:
            current_date = datetime.strptime(current_date_string, "%Y-%m-%d").date()
        except ValueError:
            current_date_string = "wrong"

        # Validate input
        if current_date_string == "wrong" or not isinstance(current_peak, int) or not isinstance(current_off_peak, int):
            return {
                'statusCode': 400,
                'body': 'Invalid input. Required: peak (integer), off_peak (integer), valid date (YYYY-MM-DD)'
            }

        # Get previous reading
        response = meter_table.query(
            KeyConditionExpression=Key('pk').eq('reading') & Key('date').lte(current_date_string),
            ScanIndexForward=False,  # get latest first
            Limit=1
        )
        # Check if we got a previous reading for the supplied date
        if not len(response['Items']) == 1:
            return {
                'statusCode': 400,
                'body': 'No previous reading found for the supplied date'
            }

        previous_reading = response['Items'][0]
        previous_peak = previous_reading.get('peak')
        previous_off_peak = previous_reading.get('off_peak')
        previous_date = datetime.strptime(previous_reading.get('date'), '%Y-%m-%d').date()

        # Check if the date has not been recorded yet
        if current_date == previous_date:
            return {
                'statusCode': 400,
                'body': f'A reading on {current_date_string} has already been stored'
            }

        # Check if the readings make sense
        if current_peak < previous_peak or current_off_peak < previous_off_peak:
            return {
                'statusCode': 400,
                'body': 'One or both of the meter values are lower then the previous reading'
            }

        # Calculate the difference between current and previous readings
        delta_peak_usage = current_peak - previous_peak
        delta_off_peak_usage = current_off_peak - previous_off_peak

        # Calculate the number of days between readings
        days_diff = (current_date - previous_date).days

        # Get tariff information
        response = tariff_table.query(
            KeyConditionExpression=Key('pk').eq('tariff') & Key('start_date').lte(current_date_string),
            ScanIndexForward=False,  # get latest first
            Limit=1
        )
        tariff = response['Items'][0]
        peak_rate = tariff.get('peak_rate')
        off_peak_rate = tariff.get('off_peak_rate')
        standing_charge = tariff.get('standing_charge')

        # If there are missing days, create entries with averaged values
        if days_diff > 1:
            # Calculate average daily change, rounded to 2 decimals
            delta_peak_usage = round(delta_peak_usage / days_diff, 2)
            delta_off_peak_usage = round(delta_off_peak_usage / days_diff, 2)

            daily_cost = round((delta_peak_usage * peak_rate) + (delta_off_peak_usage * off_peak_rate) + standing_charge, 3)

            # Create estimated entries for missing days and the current day
            for i in range(1, days_diff + 1):
                missing_date = previous_date + timedelta(days=i)
                missing_day = missing_date.strftime('%Y-%m-%d')

                if i == days_diff:
                    # We know the reading of the current day
                    estimated_peak = current_peak
                    estimated_off_peak = current_off_peak
                else:
                    # Calculate estimated values for the missing day
                    estimated_peak = previous_peak + (delta_peak_usage * i)
                    estimated_off_peak = previous_off_peak + (delta_off_peak_usage * i)

                # Store the estimated reading
                meter_table.put_item(
                    Item={
                        'pk': 'reading',
                        'date': missing_day,
                        'peak': estimated_peak,
                        'off_peak': estimated_off_peak,
                        'peak_usage': delta_peak_usage,
                        'off_peak_usage': delta_off_peak_usage,
                        'cost': daily_cost,
                        'is_estimated': True
                    }
                )
        else:
            # Calculate total usage and cost for the current day
            daily_cost = round((delta_peak_usage * peak_rate) + (delta_off_peak_usage * off_peak_rate) + standing_charge, 3)

            # Store the current reading with calculated usage
            meter_table.put_item(
                Item={
                    'pk': 'reading',
                    'date': current_date_string,
                    'peak': current_peak,
                    'off_peak': current_off_peak,
                    'peak_usage': delta_peak_usage,
                    'off_peak_usage': delta_off_peak_usage,
                    'cost': daily_cost,
                    'is_estimated': False
                }
            )

        return {
            'statusCode': 200,
            'body': {
                'message': 'Reading stored successfully',
                'peak_usage': delta_peak_usage,
                'off_peak_usage': delta_off_peak_usage,
                'cost': daily_cost
            }
        }

    except Exception:
        return {
            'statusCode': 500,
            'body': traceback.format_exc()
        }
