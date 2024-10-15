import csv


def write_to_csv_file(file_path, data, mode='w'):
    with open(file_path, mode, newline='', encoding=' utf-8') as csv_file:
        writer = csv.writer(csv_file, delimiter=',')
        for row in data:
            writer.writerow(row)


def output_to_file(file_path, data, extra=""):
    output_file = open(file_path, 'w', encoding='utf-8')
    for element in data:
        output_file.write(element + extra)

