import serial
import struct

from gpiozero import DigitalOutputDevice


class AirQualityMeasurement:
    def __init__(self, pm_2_5: int, pm_10: int):
        self.pm_2_5 = int(pm_2_5)
        self.pm_10 = int(pm_10)

    def PM_2_5(self) -> int:
        return self.pm_2_5

    def PM_10(self) -> int:
        return self.pm_10


class AirQualityDevice:
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

    def read_single(self) -> AirQualityMeasurement:
        read_bytes = self._execute_command(self.CMD_QUERY_DATA)

        if read_bytes[1] != 192:
            raise AirQualityMeasurementException(f'Measurement failed. Read bytes: {read_bytes}')

        pms = struct.unpack('<HHxxBB', read_bytes[2:])

        return AirQualityMeasurement(pms[0], pms[1])


class AirQualityMeasurementException(Exception):
    def __init__(self, msg):
        Exception.__init__(msg)