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
    device_file_re_pattern = re.compile('.*t=(\\d*)')

    while True:

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
                        print(f'Temperature read: {temp} [\u2103] @ {device_file}. '
                              f'Reference: {sensor_reference}. '
                              f'Sensor last-modification: {sensor_last_modification}, '
                              f'Timestamp: {reading_timestamp}')
                    else:
                        print(f'Temperature reading @ {device_file} failed. '
                              f'Cannot unparse temperature from {lines[1]} using '
                              f'pattern {device_file_re_pattern.pattern}. '
                              f'First line is: {lines[0]}')
                else:
                    print(f'Temperature reading failed. Read lines are: {lines}')

            time.sleep(5)
