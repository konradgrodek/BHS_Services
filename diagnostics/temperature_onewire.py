import os
import glob
import time
from datetime import datetime
import re


if __name__ == '__main__':
    # os.system('modeprobe w1-gpio')
    # os.system('modeprobe w1-therm')

    DEVICES_BASEDIR = '/sys/bus/w1/devices/'
    DEVICE_SUBDIR = '/w1_slave'
    device_file_re_pattern = re.compile('.*t=(-?\\d*)')

    temperature = 'temperature'
    error = 'error'
    reference = 'reference'

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
                if lines[0].endswith('YES'):  # crc check
                    temp_matched = device_file_re_pattern.match(lines[1])
                    if temp_matched:
                        temp = int(temp_matched.group(1))/1000
                        results.append({temperature: temp, reference: sensor_reference})
                    else:
                        results.append({error: f'parsing error: {lines[1]}', reference: sensor_reference})
                else:
                    results.append({error: f'error reported: {lines[1]}', reference: sensor_reference})

        os.system('clear')
        print('Temperature one-wire interface test')

        for result in results:
            if not result.get(error):
                print(f'Device {result[reference]} {result[temperature]:3.3} [\u2103]')
            else:
                print(f'Device {result[reference]} FAILED, {result[error]}')

        print(f'Measurement duration: {(datetime.now() - mark).total_seconds():4.2} seconds')

