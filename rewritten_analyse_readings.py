import calendar
from datetime import timedelta, date
import helper_functions
import re


readings_file = "your_readings.txt"
output_file = "new_analysed_readings.csv"

headings = ['Date', 'Off Peak', 'Peak', 'Off Peak usage', 'Peak usage', 'Average Off Peak', 'Average Peak', 'Costs', 'Monthly cost', 'Monthly cost (addition calc)']
headings_count = len(headings)
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
mc_addition_index = 9

# Octopus tariffs
# 2024, 5, 29: [0.2987, 0.1253, 0.4839]
# 2024, 10, 8: [0.2882, 0.1209, 0.4921]
tariffs = [[0.2987, 0.1253, 0.4839], [0.2882, 0.1209, 0.4921]]
price_peak_index      = 0
price_off_index       = 1
standing_charge_index = 2

# Store readings on 8 October 2024 for precise costs calculation
tariff_change_date = date(2024, 10, 8)
october_8_off_reading = 0
october_8_peak_reading = 0


csv_row_index = 0  # The headings row is at index 0

# Convert readings into data format
# Assumption 1: date comes before readings in the data file.
# Assumption 2: Dates are read from new to old
with open(readings_file, "r", encoding='utf-8') as f:
    for line in f.readlines():
        if len(line) > 1 and "reading" not in line:
            if "Off Peak" in line:
                # Regular expression to find all numeric values
                numbers = re.findall(r'\d+', line)
                csv[csv_row_index][off_index] = int(numbers[0])
                csv[csv_row_index][peak_index] = int(numbers[1])
            else:
                line_array = line.rstrip().split(' ')
                day = int(re.sub('\\D', '', line_array[0]))  # Remove rd, th, etc. from the day notation
                month = list(calendar.month_abbr).index(line_array[1])
                year = int(line_array[2])
                start_date = date(year, month, day)

                # The first date has no previous date
                if csv_row_index > 0:
                    end_date = csv[csv_row_index - 1][date_index]
                    exclude_end_date_that_already_has_a_row = 1
                    if csv_row_index == 1:
                        end_date = csv[csv_row_index][date_index]
                        exclude_end_date_that_already_has_a_row = 0  # In this case, the end date does not have a row already.

                    missing_dates_count = (end_date - start_date).days
                    missing_dates_count -= exclude_end_date_that_already_has_a_row  # Exclude the end date which has previously already gotten a row
                    missing_dates = [start_date + timedelta(days=x) for x in range(missing_dates_count)]
                    missing_dates.reverse()  # Reverse, since we work from future to past

                    for missing_day in missing_dates:
                        missing_day_row = [missing_day]
                        for heading in range(len(headings) - len(missing_day_row)):
                            missing_day_row.append('')
                        csv.append(missing_day_row)
                        csv_row_index += 1
                else:
                    # The first reading can't have missing dates before it.
                    new_row = [''] * headings_count
                    new_row[0] = start_date
                    csv.append(new_row)
                    csv_row_index += 1  # increment csv row index


# Store initial end usage stats for current month, used to calculate monthly stats
month_end_off_usage = float(csv[1][off_index])
month_end_peak_usage = float(csv[1][peak_index])

first_month_end_off_usage_for_addition = month_end_off_usage
first_month_end_peak_usage_for_addition = month_end_peak_usage


# Calculate missing day statistics and their daily usage
for csv_index, day in enumerate(csv):
    # Skip the header for calculating stats
    if csv_index < 1:
        continue

    # Calculate peak and off-peak daily usage for days without a reading
    if day[off_index] == '' and day[off_usage_index] == '':
        previous_off_reading = float(csv[csv_index - 1][off_index])
        previous_peak_reading = float(csv[csv_index - 1][peak_index])

        # Find the amount of days without reading
        next_csv_index_with_reading = -1
        non_reading_days_counter = 1
        while next_csv_index_with_reading < 0:
            if csv[csv_index + non_reading_days_counter][off_index] == '':
                non_reading_days_counter += 1
            else:
                next_csv_index_with_reading = csv_index + non_reading_days_counter

            if non_reading_days_counter > 1000:
                raise OverflowError("non reading days exceeded 1000")

        next_day_with_reading = csv[next_csv_index_with_reading]
        missing_days_usage_period = non_reading_days_counter + 1  # Include the day before the non reading period started in usage stats
        peak_usage = round((previous_peak_reading - float(next_day_with_reading[peak_index])) / missing_days_usage_period, 1)
        off_usage = round((previous_off_reading - float(next_day_with_reading[off_index])) / missing_days_usage_period, 1)

        # Get reading of the next day in the csv with a reading. Used to calculate an estimated reading on missing days. For monthly usage calculation later.
        off_reading_next_day_with_reading = float(next_day_with_reading[off_index])
        peak_reading_next_day_with_reading = float(next_day_with_reading[peak_index])

        for x in range(missing_days_usage_period):
            # -1 to make sure the stats are added to the right days: all days without reading + the next day with a reading again.
            # This is because of the assumption that readings are made at the end of a day.
            csv[csv_index + x - 1][peak_usage_index] = peak_usage
            csv[csv_index + x - 1][off_usage_index] = off_usage

            if csv[csv_index + x][peak_index] == '':  # Skip the day before the non reading period started which already has a reading.
                csv[csv_index + x][peak_index] = peak_reading_next_day_with_reading + peak_usage * (missing_days_usage_period - x - 1)
                csv[csv_index + x][off_index] = off_reading_next_day_with_reading + off_usage * (missing_days_usage_period - x - 1)


# Calculate monthly statistics and daily costs
for csv_index, day in enumerate(csv):
    # Skip the header for calculating stats
    if csv_index < 1 or csv_index == len(csv) - 1:
        continue

    # Calculate peak and off-peak daily usage for the rest of the days
    # Assumption: readings are done in the evening, meaning daily usage is (day 2 reading) - (day 1 reading)
    if day[peak_usage_index] == '':  # Check after calculating usage stats for missing days, such that we only find days without calc yet
        previous_off_reading = float(csv[csv_index + 1][off_index])
        previous_peak_reading = float(csv[csv_index + 1][peak_index])

        peak_usage = float(day[peak_index]) - previous_peak_reading
        off_usage = float(day[off_index]) - previous_off_reading

        day[peak_usage_index] = peak_usage
        day[off_usage_index] = off_usage

    if day[date_index] == tariff_change_date:
        october_8_off_reading = day[off_index]
        october_8_peak_reading = day[peak_index]



    # Calculate monthly costs on first of the month
    if day[date_index].day == 1:
        first_day_of_month = day[date_index]
        month_length = calendar.monthrange(first_day_of_month.year, first_day_of_month.month)[1]
        # print(day)
        # print(csv[csv_index + 1])
        day[average_off_index] =  round((month_end_off_usage -  float(csv[csv_index + 1][off_index])) / month_length, 1)
        day[average_peak_index] = round((month_end_peak_usage - float(csv[csv_index + 1][peak_index])) / month_length, 1)

        # print(month_end_off_usage )
        # print(month_end_peak_usage)

        # our first tariff we had from May 2024
        tariff_index = 0
        if first_day_of_month.month == 10:  # Check if the day is after our tariff change on 8 october 2024
            tariff_index = 1

        price_peak = tariffs[tariff_index][price_peak_index]
        price_off = tariffs[tariff_index][price_off_index]
        standing_charge = tariffs[tariff_index][standing_charge_index]

        day[monthly_cost_index] = round((day[average_peak_index] * price_peak + day[average_off_index] * price_off + standing_charge) * month_length, 2)

        month_end_off_usage = float(csv[csv_index + 1][off_index])
        month_end_peak_usage = float(csv[csv_index + 1][peak_index])


    # Calculate daily costs
    # Take our first tariff we had from May 2024
    tariff_index = 0
    if day[date_index] > date(2024, 10, 7):  # Check if the day is after our tariff change on 8 October 2024
        tariff_index = 1

    price_peak = tariffs[tariff_index][price_peak_index]
    price_off = tariffs[tariff_index][price_off_index]
    standing_charge = tariffs[tariff_index][standing_charge_index]
    day[costs_index] = round(float(day[peak_usage_index]) * price_peak + float(day[off_usage_index]) * price_off + standing_charge, 2)





# Calculate monthly costs on first of the month with addition of all individual days (as extra check for correctness)
for csv_index, day in enumerate(csv):
    # Skip the header for calculating stats
    if csv_index < 1 or csv_index == len(csv) - 1:
        continue
    if day[date_index].day == 1:
        # print('---- addition check start for date: ' + str( day[date_index]))
        first_day_of_month = day[date_index]
        month_length = calendar.monthrange(first_day_of_month.year, first_day_of_month.month)[1]

        month_total_costs = 0

        for days in range(month_length):
            month_total_costs += float(csv[csv_index - days][costs_index])
            # print(csv[csv_index - days][date_index])
            if float(csv[csv_index - days][off_index]) == first_month_end_off_usage_for_addition:
                break

        day[mc_addition_index] = round(month_total_costs, 2)




helper_functions.write_to_csv_file(output_file, csv)




total_costs = 0
total_monthly_costs = 0
total_monthly_costs_addition_calc = 0
for csv_index, day in enumerate(csv):
    # Skip the header and first reading for calculating stats
    if csv_index < 1 or csv_index == len(csv) - 1:
        continue

    total_costs += float(day[costs_index])

    if day[mc_addition_index] != '':
        total_monthly_costs_addition_calc += float(day[mc_addition_index])

    if day[monthly_cost_index] != '':
        total_monthly_costs += float(day[monthly_cost_index])

print('total costs: ' + str(round(total_costs, 2)))
print('total monthly costs: ' + str(round(total_monthly_costs, 2)))
print('total monthly costs addition calc: ' + str(round(total_monthly_costs_addition_calc, 2)))


first_date = csv[1][date_index]
last_date = csv[-1][date_index]
amount_of_days_may_tariff = (first_date - tariff_change_date).days
amount_of_days_october_tariff = (tariff_change_date - last_date).days

latest_off_reading = float(csv[1][off_index])
latest_peak_reading = float(csv[1][peak_index])

first_off_reading = float(csv[-1][off_index])
first_peak_reading = float(csv[-1][peak_index])

total_off_kwh_may_tariff =  october_8_off_reading - first_off_reading
total_peak_kwh_may_tariff = october_8_peak_reading - first_peak_reading

total_off_kwh_october_tariff = latest_off_reading - october_8_off_reading
total_peak_kwh_october_tariff = latest_peak_reading - october_8_peak_reading

pure_costs_may_tariff = round(total_peak_kwh_may_tariff * tariffs[0][price_peak_index] + total_off_kwh_may_tariff * tariffs[0][price_off_index] + amount_of_days_may_tariff * tariffs[0][standing_charge_index], 2)
pure_costs_october_tariff = round(total_peak_kwh_october_tariff * tariffs[1][price_peak_index] + total_off_kwh_october_tariff * tariffs[1][price_off_index] + amount_of_days_october_tariff * tariffs[1][standing_charge_index], 2)
pure_costs_may_tariff_on_october_usage = round(total_peak_kwh_october_tariff * tariffs[0][price_peak_index] + total_off_kwh_october_tariff * tariffs[0][price_off_index] + amount_of_days_october_tariff * tariffs[0][standing_charge_index], 2)

pure_total_costs = pure_costs_may_tariff + pure_costs_october_tariff


print("pure_costs_may_tariff: " + str(pure_costs_may_tariff))
print("pure_costs_october_tariff: " + str(pure_costs_october_tariff))
print("october usage costs if we didn't switch tariff: " + str(pure_costs_may_tariff_on_october_usage))
print("pure_total_costs: " + str(pure_total_costs))

print("-------------------------------")

print("total_off_kwh_may_tariff: " + str(total_off_kwh_may_tariff))
print("total_peak_kwh_may_tariff: " + str(total_peak_kwh_may_tariff))
print("total_off_kwh_october_tariff: " + str(total_off_kwh_october_tariff))
print("total_peak_kwh_october_tariff: " + str(total_peak_kwh_october_tariff))
print("-------------------------------")

total_off_kwh = total_off_kwh_october_tariff + total_off_kwh_may_tariff
total_peak_kwh = total_peak_kwh_october_tariff + total_peak_kwh_may_tariff
percentage_off = round(total_off_kwh / (total_off_kwh + total_peak_kwh) * 100, 2)

print("total off kwh: " + str(total_off_kwh))
print("total peak kwh: " + str(total_peak_kwh))
print("off kwh percentage: " + str(percentage_off))


