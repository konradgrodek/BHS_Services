import serial
from datetime import datetime
import struct
import time
from gpiozero import DigitalOutputDevice
from os import system
import sys
from array import array
import random
from scipy import stats


class AirQualitySensor:
    CMD_MODE = 2
    CMD_QUERY_DATA = 4
    CMD_DEVICE_ID = 5
    CMD_SLEEP = 6
    CMD_FIRMWARE = 7
    CMD_WORKING_PERIOD = 8
    MODE_ACTIVE = 0
    MODE_QUERY = 1

    def __init__(self, power_pin: int):
        self.device = serial.Serial("/dev/ttyAMA0", 9600)
        self.power = DigitalOutputDevice(pin=power_pin, active_high=False)

    def _execute_command(self, cmd, data=[]):
        assert len(data) <= 12
        data += [0, ] * (12 - len(data))
        checksum = (sum(data) + cmd - 2) % 256
        bts = list()
        bts.append(ord('\xaa'))
        bts.append(ord('\xb4'))
        bts.append(cmd)
        for d in data:
            bts.append(d)
        bts.append(ord('\xff'))
        bts.append(ord('\xff'))
        bts.append(checksum)
        bts.append(ord('\xab'))

        self.device.write(bts)
        self.device.flushOutput()
        return self._read_response()

    def execute_command_read_data(self):
        return self._execute_command(self.CMD_MODE, [0x1, 1])

    def _read_response(self) -> bytes:
        """
        Reads 10 bytes staring from 'aa'
        :return:
        """
        start_byte = 0
        while start_byte != b'\xaa':
            start_byte = self.device.read()

        rest_of_bytes = self.device.read(size=9)

        return start_byte + rest_of_bytes

    def read_single(self) -> tuple:
        read_bytes = self._execute_command(self.CMD_QUERY_DATA)

        if read_bytes[1] != 192:
            return None, None

        pms = struct.unpack('<HHxxBB', read_bytes[2:])
        pm25 = pms[0]
        pm10 = pms[1]

        return pm25, pm10


if __name__ == '__main__':
    sensor = AirQualitySensor(26)
    bck = '\b'

    while True:
        system('clear')

        print(f'Air Quality Sensor (UART + power @ {sensor.power.pin}) ')
        sensor.power.on()
        print('Powered on. Warming up... ', end='')

        for s in range(60):
            print(f'{60-s:02}', end='')
            sys.stdout.flush()
            time.sleep(1)
            print(f'{bck*2}', end='')

        print(f'{bck*10}ed up.      ')

        print('Starting measurement... ', end=' ')

        # command to read data
        sensor.execute_command_read_data()

        print('Started.')

        pm10 = array('i')
        pm25 = array('i')

        time_mark = datetime.now()
        m = 0
        while (datetime.now() - time_mark).total_seconds() < 60:

            # result = (int(random.gauss(200, 20)), int(random.gauss(300, 30)))
            result = sensor.read_single()

            if len(result) != 2:
                print(f'Error reading from UART device. Additional info: {result}')
                break

            if not result[0] or not result[1]:
                print(f'Error reading from UART device')
                break

            if m > 0:
                print(f'{bck * 56}', end='')
                sys.stdout.flush()

            m += 1

            pm25.append(result[0])
            pm10.append(result[1])

            pm10_mode = stats.mode(pm10, nan_policy='omit').mode[0] / 10
            pm25_mode = stats.mode(pm25, nan_policy='omit').mode[0] / 10

            print(f'[{m:04}] Last: PM2.5 {int(result[0]/10):03} PM10 {int(result[1]/10):03} '
                  f'Mode: PM2.5 {int(pm25_mode):03} PM10 {int(pm10_mode):03}', end='')
            sys.stdout.flush()

            # time.sleep(0.2)

        sensor.power.off()
        print('\nPowered off')
        time.sleep(60)






