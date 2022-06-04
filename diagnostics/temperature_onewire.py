import os
import glob
from rich.live import Live
from rich.table import Table
from datetime import datetime
import re


if __name__ == '__main__':
    # os.system('modeprobe w1-gpio')
    # os.system('modeprobe w1-therm')

    os.system('clear')

    DEVICES_BASEDIR = '/sys/bus/w1/devices/'
    DEVICE_SUBDIR = '/w1_slave'
    device_file_re_pattern = re.compile('.*t=(-?\\d*)')

    temperature = 'temperature'
    error = 'error'
    reference = 'reference'

    def update_table(results: list = None, duration: float = None, attempt: int = None) -> Table:
        table = Table(title='Temperature one-wire interface test',
                      caption=f'{attempt} measurements, time: {duration:.2} s' if results is not None else f'Measurement in progress...')
        table.add_column(reference)
        table.add_column('reading')
        if results is not None:
            for _r in results:
                table.add_row(_r[reference],
                              f'[green]{_r[temperature]:3.3f} [\u2103]'
                              if _r.get(temperature) is not None else f'[red]{_r[error]}')
        return table


    attempt = 1

    with Live(update_table(), refresh_per_second=4) as live:
        while True:

            mark = datetime.now()

            results = list()
            device_dirs = glob.glob(DEVICES_BASEDIR + '28*')

            for device_dir in device_dirs:
                device_file = device_dir + DEVICE_SUBDIR
                sensor_reference = os.path.basename(device_dir)

                with open(device_file, 'r') as file:
                    lines = file.read().splitlines(keepends=False)
                    reading_timestamp = datetime.now()
                    sensor_last_modification = datetime.fromtimestamp(os.stat(device_file).st_mtime)
                    success = None
                    temp = None
                    if lines is None:
                        results.append({error: 'device file empty', reference: sensor_reference})
                    elif len(lines) != 2:
                        results.append({error: f'parsing error, no separator: {lines}', reference: sensor_reference})
                    elif lines[0].endswith('YES'):  # crc check
                        temp_matched = device_file_re_pattern.match(lines[1])
                        if temp_matched:
                            temp = int(temp_matched.group(1))/1000
                            results.append({temperature: temp, reference: sensor_reference})
                        else:
                            results.append({error: f'parsing error: {lines[1]}', reference: sensor_reference})
                    else:
                        results.append({error: f'error reported: {lines[1]}', reference: sensor_reference})

            live.update(update_table(results, (datetime.now() - mark).total_seconds(), attempt), refresh=True)
            attempt += 1


