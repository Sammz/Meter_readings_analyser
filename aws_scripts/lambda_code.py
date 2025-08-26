import calendar
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

# Add 2 newlines to all response bodies to avoid terminal clutter when executing send_reading.sh
response_end = "\n\n"


def check_latest_reading():
    latest_reading = meter_table.query(
        KeyConditionExpression=Key('pk').eq('reading'),
        ScanIndexForward=False,  # Get the latest first
        Limit=1  # Limit to one item
    )

    return latest_reading


def delete_latest_reading():
    latest_reading = meter_table.query(
        KeyConditionExpression=Key('pk').eq('reading'),
        ScanIndexForward=False,  # Get the latest first
        Limit=1  # Limit to one item
    )

    response = meter_table.delete_item(
        Key={
            'pk': "reading",
            'date': latest_reading['Items'][0]['date']
        },
        ReturnValues='ALL_OLD'  # This will return the deleted item
    )

    return response


def query_meter_table_for_lt_or_equal_to_date(date_string):
    response = meter_table.query(
            KeyConditionExpression=Key('pk').eq('reading') & Key('date').lte(date_string),
            ScanIndexForward=False,  # get latest first
            Limit=1
        )

    # Check if we got a previous reading for the supplied date
    if not len(response['Items']) == 1:
        return {
            'statusCode': 400,
            'body': 'No reading (or previous reading) found for the supplied date' + response_end
        }

    # Extract the first item from the response
    reading_values = response['Items'][0]

    # Build the dictionary with the values you want
    data = {
        'peak': reading_values.get('peak'),
        'off_peak': reading_values.get('off_peak'),
        'date': datetime.strptime(reading_values.get('date'), '%Y-%m-%d').date()
    }

    return data


def get_tariff(current_date_string):
    # Get tariff information
    response = tariff_table.query(
        KeyConditionExpression=Key('pk').eq('tariff') & Key('start_date').lte(current_date_string),
        ScanIndexForward=False,  # get latest first
        Limit=1
    )
    tariff = response['Items'][0]
    return tariff


def calculate_cost_between_2_dates(start_date_string, end_date_string, tariff):
    start_date_reading = query_meter_table_for_lt_or_equal_to_date(start_date_string)
    end_date_reading = query_meter_table_for_lt_or_equal_to_date(end_date_string)

    delta_peak_usage = end_date_reading['peak'] - start_date_reading['peak']
    delta_off_peak_usage = end_date_reading['off_peak'] - start_date_reading['off_peak']

    delta_days = (end_date_reading['date'] - start_date_reading['date']).days

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
                'body': 'Unauthorized' + response_end
            }

        command = body['command']
        reading_to_store = True

        if command != "store":
            if command == "delete":
                delete_response = delete_latest_reading()
                return {
                    'statusCode': 200,
                    'body': "Deleted item: \n" + str(delete_response['Attributes']) + response_end
                }

            elif command == "check":
                check_response = check_latest_reading()
                return {
                    'statusCode': 200,
                    'body': "Latest entry: \n" + str(check_response['Items'][0]) + response_end
                }

            elif command == "calculate":
                reading_to_store = False

            else:
                return {
                    'statusCode': 400,
                    'body': 'Invalid command: ' + command + response_end
                }

        if reading_to_store:
            # A reading needs to be stored
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
                    'body': 'Invalid input. Required: peak (integer), off_peak (integer), valid date (YYYY-MM-DD)\n' + response_end
                }

            # Get previous reading since current reading does not exist yet in the table
            previous_reading = query_meter_table_for_lt_or_equal_to_date(current_date_string)

            # Check if the date has not been recorded yet
            if current_date == previous_reading['date']:
                return {
                    'statusCode': 400,
                    'body': f'A reading on {current_date_string} has already been stored\n' + response_end
                }

            # Check if the readings aren't too low
            if current_peak < previous_reading['peak']:
                return {
                    'statusCode': 400,
                    'body': 'Peak reading value is lower then the previous reading' + response_end
                }
            if current_off_peak < previous_reading['off_peak']:
                return {
                    'statusCode': 400,
                    'body': 'Off peak reading value is lower then the previous reading' + response_end
                }

            # Check if the readings aren't absurdly high (upper limits estimated)
            if current_peak > previous_reading['peak'] + 20:
                return {
                    'statusCode': 400,
                    'body': 'Peak reading value is higher then the previous reading + 25' + response_end
                }
            if current_off_peak > previous_reading['off_peak'] + 50:
                return {
                    'statusCode': 400,
                    'body': 'Off peak reading value is higher then the previous reading + 50' + response_end
                }

            # Calculate the difference between current and previous readings
            delta_peak_usage = current_peak - previous_reading['peak']
            delta_off_peak_usage = current_off_peak - previous_reading['off_peak']

            # Calculate the number of days between readings
            days_diff = (current_date - previous_reading['date']).days


            tariff = get_tariff(current_date_string)
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
                    missing_day_str = missing_date.strftime('%Y-%m-%d')

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
                            'date': missing_day_str,
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

        else:
            # No reading stored, get information needed to calculate statistics
            current_date = datetime.now()
            current_date_string = current_date.strftime('%Y-%m-%d')
            tariff = get_tariff(current_date_string)

            # Dummy data to make code work.
            delta_peak_usage = 0
            delta_off_peak_usage = 0
            daily_cost = 0

        # Readings are stored at the end of a day!
        # Get the previous months for statistics
        if current_date.month == 1:
            date_last_month = current_date.replace(year=current_date.year - 1, month=12)
            date_second_to_last_month = current_date.replace(year=current_date.year - 1, month=11)
        else:
            date_last_month = current_date.replace(month=current_date.month - 1)
            if current_date.month == 2:
                date_second_to_last_month = current_date.replace(year=current_date.year - 1, month=12)
            else:
                date_second_to_last_month = current_date.replace(month=current_date.month - 2)

        # Prepare for example: 2025-06-05 into 2025-05-31
        last_day = calendar.monthrange(date_last_month.year, date_last_month.month)[1]
        date_str_last_month_last_day = date_last_month.replace(day=last_day).strftime('%Y-%m-%d')

        # Prepare for example: 2025-06-05 into 2025-04-30
        second_to_last_month_last_day = calendar.monthrange(date_second_to_last_month.year, date_second_to_last_month.month)[1]
        date_str_second_to_last_month_last_day = date_second_to_last_month.replace(day=second_to_last_month_last_day).strftime('%Y-%m-%d')

        # becomes xxxx-12-31 as readings are stored at the end of a day.
        date_str_start_of_current_year = (current_date.replace(month=1, day=1) - timedelta(days=1)).strftime('%Y-%m-%d')
        date_str_beginning = "2024-05-29"

        cost_of_current_month_so_far, off_peak_percentage_current_month_so_far = calculate_cost_between_2_dates(date_str_last_month_last_day, current_date_string, tariff)
        cost_last_month, off_peak_percentage_last_month = calculate_cost_between_2_dates(date_str_second_to_last_month_last_day, date_str_last_month_last_day, tariff)
        cost_current_year, off_peak_percentage_current_year = calculate_cost_between_2_dates(date_str_start_of_current_year, current_date_string, tariff)
        cost_all_time, off_peak_percentage_all_time = calculate_cost_between_2_dates(date_str_beginning, current_date_string, tariff)


        data = OrderedDict([
            ('peak_usage', delta_peak_usage),
            ('off_peak_usage', delta_off_peak_usage),
            ('cost', '£' + str(daily_cost)),
            ('=', '--'),
            ('cost_of_current_month', '£' + str(cost_of_current_month_so_far)),
            ('off_peak_%_current_month', str(off_peak_percentage_current_month_so_far) + "%"),
            ('-', '--'),
            ('cost_of_last_month', '£' + str(cost_last_month)),
            ('off_peak_%_last_month', str(off_peak_percentage_last_month) + "%"),
            ('--', '--'),
            ('cost_current_year_so_far',    '£' + str(cost_current_year)),
            ('off_peak_%_current_year', str(off_peak_percentage_current_year) + "%"),
            ('---', '--'),
            ('cost_of_all_time',     '£' + str(cost_all_time)),
            ('off_peak_%_all_time', str(off_peak_percentage_all_time) + "%")
        ])

        # Create a filtered_dict to filter out stored reading stats if no new reading was stored.
        filtered_data = OrderedDict()
        if reading_to_store:
            # Include the first four entries
            for key, value in list(data.items())[:4]:
                filtered_data[key] = value
        # Include the rest of the entries
        for key, value in list(data.items())[4:]:
            filtered_data[key] = value

        # Build Markdown table string
        lines = ["|---------------------------|----------|"]
        for k in filtered_data.keys():
            lines.append(f"| {k:<25} | {data.get(k)!s:<8} |")

        lines.append("|---------------------------|----------|")

        markdown_table = "\n".join(lines)

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': markdown_table + response_end
        }

    except Exception:
        return {
            'statusCode': 500,
            'body': traceback.format_exc() + response_end
        }
