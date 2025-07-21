from collections import OrderedDict

import boto3
from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Key
import os
import traceback
import json


dynamodb = boto3.resource('dynamodb')
meter_table = dynamodb.Table('meter_readings')
tariff_table = dynamodb.Table('tariff_info')


def query_meter_table_for_previous_reading_by_date(date_string):
    response = meter_table.query(
            KeyConditionExpression=Key('pk').eq('reading') & Key('date').lte(date_string),
            ScanIndexForward=False,  # get latest first
            Limit=1
        )

    # Check if we got a previous reading for the supplied date
    if not len(response['Items']) == 1:
        return {
            'statusCode': 400,
            'body': 'No previous reading found for the supplied date'
        }

    # Extract the first item from the response
    previous_reading_values = response['Items'][0]

    # Build the dictionary with the values you want
    previous_data = {
        'peak': previous_reading_values.get('peak'),
        'off_peak': previous_reading_values.get('off_peak'),
        'date': datetime.strptime(previous_reading_values.get('date'), '%Y-%m-%d').date()
    }

    return previous_data


def calculate_cost_between_current_and_past_date(current, date, tariff):
    past_date_reading = query_meter_table_for_previous_reading_by_date(date)
    delta_peak_usage = current['peak'] - past_date_reading['peak']
    delta_off_peak_usage = current['off_peak'] - past_date_reading['off_peak']
    delta_days = (datetime.strptime(current['date'], "%Y-%m-%d").date() - past_date_reading['date']).days
    cost = round((delta_peak_usage * tariff.get('peak_rate')) + (delta_off_peak_usage * tariff.get('off_peak_rate')) + delta_days * tariff.get('standing_charge'), 2)
    off_peak_percentage = round(delta_off_peak_usage / (delta_off_peak_usage + delta_peak_usage) * 100, 1)
    return cost, off_peak_percentage


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
        previous_reading = query_meter_table_for_previous_reading_by_date(current_date_string)

        # Check if the date has not been recorded yet
        if current_date == previous_reading['date']:
            return {
                'statusCode': 400,
                'body': f'A reading on {current_date_string} has already been stored'
            }

        # Check if the readings make sense
        if current_peak < previous_reading['peak'] or current_off_peak < previous_reading['off_peak']:
            return {
                'statusCode': 400,
                'body': 'One or both of the meter values are lower then the previous reading'
            }

        # Calculate the difference between current and previous readings
        delta_peak_usage = current_peak - previous_reading['peak']
        delta_off_peak_usage = current_off_peak - previous_reading['off_peak']

        # Calculate the number of days between readings
        days_diff = (current_date - previous_reading['date']).days

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

            daily_cost = round((delta_peak_usage * peak_rate) + (delta_off_peak_usage * off_peak_rate) + standing_charge, 2)

            # Create estimated entries for missing days and the current day
            for i in range(1, days_diff + 1):
                missing_date = previous_reading['date'] + timedelta(days=i)
                missing_day = missing_date.strftime('%Y-%m-%d')

                if i == days_diff:
                    # We know the reading of the current day
                    estimated_peak = current_peak
                    estimated_off_peak = current_off_peak
                else:
                    # Calculate estimated values for the missing day
                    estimated_peak = previous_reading['peak'] + (delta_peak_usage * i)
                    estimated_off_peak = previous_reading['off_peak'] + (delta_off_peak_usage * i)

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
            daily_cost = round((delta_peak_usage * peak_rate) + (delta_off_peak_usage * off_peak_rate) + standing_charge, 2)

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

        # 29 and 364 because query_meter_table_for_previous_reading_by_date() gets the previous reading.
        date_str_30_days_ago = (current_date - timedelta(days=29)).strftime("%Y-%m-%d")
        date_str_1_year_ago = (current_date - timedelta(days=364)).strftime("%Y-%m-%d")
        date_str_beginning_plus_1 = "2024-05-30"
        date_str_01_of_current_month = current_date_string[:-2] + "01"

        cost_last_30_days, off_peak_percentage_last_30 = calculate_cost_between_current_and_past_date(body, date_str_30_days_ago, tariff)
        cost_last_year, off_peak_percentage_last_year = calculate_cost_between_current_and_past_date(body, date_str_1_year_ago, tariff)
        cost_all_time, off_peak_percentage_all_time = calculate_cost_between_current_and_past_date(body, date_str_beginning_plus_1, tariff)
        cost_of_current_month_so_far, off_peak_percentage_current_month_so_far = calculate_cost_between_current_and_past_date(body, date_str_01_of_current_month, tariff)

        data = OrderedDict([
            ('peak_usage', delta_peak_usage),
            ('off_peak_usage', delta_off_peak_usage),
            ('cost', '£' + str(daily_cost)),
            ('=', '--'),
            ('cost_current_month', '£' + str(cost_of_current_month_so_far)),
            ('off_peak_%_current_month', str(off_peak_percentage_current_month_so_far) + "%"),
            ('-', '--'),
            ('cost_of_last_30_days', '£' + str(cost_last_30_days)),
            ('off_peak_%_last_30', str(off_peak_percentage_last_30) + "%"),
            ('--', '--'),
            ('cost_of_last_year',    '£' + str(cost_last_year)),
            ('off_peak_%_last_year', str(off_peak_percentage_last_year) + "%"),
            ('---', '--'),
            ('cost_of_all_time',     '£' + str(cost_all_time)),
            ('off_peak_%_all_time', str(off_peak_percentage_all_time) + "%")
        ])

        # Build Markdown table string
        lines = ["|----------------------|----------|"]
        for k in data.keys():
            lines.append(f"| {k:<20} | {data.get(k)!s:<8} |")

        lines.append("|----------------------|----------|\n")

        markdown_table = "\n".join(lines)

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': markdown_table
        }

    except Exception:
        return {
            'statusCode': 500,
            'body': traceback.format_exc()
        }
