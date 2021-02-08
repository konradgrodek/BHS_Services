import serial
from datetime import datetime
import struct
import time
from gpiozero import DigitalOutputDevice


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

    def execute_command(self, cmd, data=[]):
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

    def _read_single(self) -> tuple:
        read_bytes = self.execute_command(self.CMD_QUERY_DATA)

        if read_bytes[1] != 192:
            return None, None

        pms = struct.unpack('<HHxxBB', read_bytes[2:])
        pm25 = pms[0] / 10.0
        pm10 = pms[1] / 10.0

        return pm25, pm10

    def read(self, readings_count: int) -> tuple:
        # power on
        self.power.on()

        # warm up
        time.sleep(10)

        # command to read data
        self.execute_command(self.CMD_MODE, [0x1, 1])

        # read data to obtain N readings
        for i in range(readings_count):
            result = self._read_single()
            print(f'PM2,5: {result[0]}, PM10: {result[1]}')
            time.sleep(1)

        self.power.off()

        return None


if __name__ == '__main__':

    AirQualitySensor(26).read(30)
