import calendar
from datetime import timedelta, date
import helper_functions
import re


price_off = 0.1253
price_peak = 0.2987
standing_charge = 0.4839

readings_file = "readings.txt"
output_file = "organised_readings.csv"

headings = ['Date', 'Off Peak', 'Peak', 'Off Peak usage', 'Peak usage', 'Average Off Peak', 'Average Peak', 'Costs', 'Monthly cost']
csv = [headings]

date_index = 0
off_index = 1
peak_index = 2
off_usage_index = 3
peak_usage_index = 4
average_off_index = 5
average_peak_index = 6
costs_index = 7
monthly_cost_index = 8

next_date_stats = [date.today()]
date_stats = []
for heading in headings:
    date_stats.append('')
    next_date_stats.append(0)


days = 0
missing_dates_count = 0
missing_dates = []

month_end_peak_usage = 0
month_end_off_usage = 0

def handle_missing_dates():
    global peak_usage, off_usage, missing_day, average_off, average_peak, monthly_costs, month_length, month_end_off_usage, month_end_peak_usage, missing_day_stats, heading
    del missing_dates[-1]  # remove the last element, which is the start_date we will add already.
    peak_usage = round((next_date_stats[peak_index] - date_stats[peak_index]) / missing_dates_count, 1)
    off_usage = round((next_date_stats[off_index] - date_stats[off_index]) / missing_dates_count, 1)
    for missing_day in missing_dates:
        average_off = ''
        average_peak = ''
        monthly_costs = 0
        if missing_day.day == 1:
            month_length = calendar.monthrange(date_stats[date_index].year, date_stats[date_index].month)[1]
            average_off = round((month_end_off_usage - date_stats[off_index]) / month_length, 1)
            average_peak = round((month_end_peak_usage - date_stats[peak_index]) / month_length, 1)
            monthly_costs = round(
                (average_peak * price_peak + average_off * price_off + standing_charge) * month_length, 2)

            month_end_off_usage = date_stats[off_index]
            month_end_peak_usage = date_stats[peak_index]

        missing_day_stats = [missing_day, '', '', off_usage, peak_usage, average_off, average_peak, '', monthly_costs]
        for heading in range(len(headings) - len(missing_day_stats)):
            missing_day_stats.append('')

        csv.append(missing_day_stats)


with open(readings_file, "r", encoding='utf-8') as f:
    for line in f.readlines():
        if len(line) > 1:
            line_array = line.rstrip().split(' ')
            if "Off Peak" in line:
                date_stats[off_index] = int(line_array[2])
            elif "Peak" in line:
                date_stats[peak_index] = int(line_array[1])
            else:
                if days > 0:
                    if days == 1:  # Record the usage of the start month for monthly average calculations
                        month_end_off_usage = date_stats[off_index]
                        month_end_peak_usage = date_stats[peak_index]

                    if date_stats[date_index].day == 1:  # Record monthly average on a day on the first of the month
                        month_length = calendar.monthrange(date_stats[date_index].year, date_stats[date_index].month)[1]
                        date_stats[average_off_index] = round((month_end_off_usage - date_stats[off_index]) / month_length, 1)
                        date_stats[average_peak_index] = round((month_end_peak_usage - date_stats[peak_index]) / month_length, 1)
                        date_stats[monthly_cost_index] = round((date_stats[average_peak_index] * price_peak + date_stats[average_off_index] * price_off + standing_charge) * month_length, 2)

                        month_end_off_usage = date_stats[off_index]
                        month_end_peak_usage = date_stats[peak_index]

                    if missing_dates:
                        handle_missing_dates()

                    else:
                        peak_usage = next_date_stats[peak_index] - date_stats[peak_index]
                        off_usage = next_date_stats[off_index] - date_stats[off_index]

                    if peak_usage >= 0:  # don't add negative daily usage for the first day
                        date_stats[peak_usage_index] = peak_usage
                        date_stats[off_usage_index] = off_usage

                    csv.append(date_stats)
                    next_date_stats = date_stats
                    date_stats = []
                    for heading in headings:  # Re-initiate empty date stats array
                        date_stats.append('')


                day = int(re.sub('\\D', '', line_array[0]))  # Remove rd, th, etc. from the day notation
                month = list(calendar.month_abbr).index(line_array[1])
                year = int(line_array[2])

                start_date = date(year, month, day)
                end_date = next_date_stats[date_index]

                missing_dates_count = (end_date - start_date).days
                missing_dates = [start_date + timedelta(days=x) for x in range(missing_dates_count)]
                missing_dates.reverse()  # Reverse, since we work from future to past

                date_stats[date_index] = start_date
                days += 1





if missing_dates:
    handle_missing_dates()

else:
    peak_usage = next_date_stats[peak_index] - date_stats[peak_index]
    off_usage = next_date_stats[off_index] - date_stats[off_index]

date_stats[peak_usage_index] = peak_usage
date_stats[off_usage_index] = off_usage
csv.append(date_stats)  # Add the last day stats to the csv

# Calculate costs
for row in csv[1:]:
    if row[peak_usage_index] != '':
        row[costs_index] = round(float(row[off_usage_index]) * price_off + float(row[peak_usage_index]) * price_peak + standing_charge, 2)

helper_functions.write_to_csv_file(output_file, csv)

