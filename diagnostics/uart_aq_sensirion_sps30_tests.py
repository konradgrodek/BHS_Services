from unittest import TestCase
import time
import random
from enum import Enum

import sys
sys.path.append('..')

from device.dev_serial_sps30 import *


class BytesStuffingTests(TestCase):

    def setUp(self) -> None:
        pass

    def test_01_empty_data(self):
        stuffing_empty = stuffing(bytes(0))
        self.assertEqual(
            0, len(stuffing_empty),
            f"It is expected that the length of the stuffed empty list of bytes will result in empty list of bytes, "
            f"which is violated")
        unstuffing_empty = unstuffing(bytes(0))
        self.assertEqual(
            0, len(unstuffing_empty),
            f"It is expected that the length of the unstuffed empty list of bytes will result in empty list of bytes, "
            f"which is violated")
        # and the full test
        self._stuff_unstuff_verify(bytes(0))

    def test_02_single_normal_bytes(self):
        bytes_to_test = bytes([0x00, 0xFF, 0x22, 0x66, 0xA0, 0xBE])
        for btt in bytes_to_test:
            self._stuff_unstuff_verify(bytes([btt]))

    def test_03_single_special_bytes(self):
        for btt in BYTES_STUFFING_MAP:
            self._stuff_unstuff_verify(bytes([btt]))
        for btt in BYTES_UNSTUFFING_MAP:
            self._stuff_unstuff_verify(bytes([btt]))

    def test_04_random_bytes(self):
        for _ in range(1000):
            self._stuff_unstuff_verify(bytes(random.choices(range(0x100), k=random.randint(1, 255))))

    def _stuff_unstuff_verify(self, data: bytes):
        processed = bytes(unstuffing(bytes(stuffing(data))))
        self.assertEqual(
            len(data), len(processed),
            f"The length of the data after bytes-stuffing and -unstuffing was expected to be the same, "
            f"whereas it is different")
        deviations = [f"0x{b:02X} --> 0x{a:02X}" for b, a in zip(data, processed) if b != a]
        if len(deviations) > 0:
            self.fail(f"The data before and after bytes-stuffing and -unstuffing is different.\n"
                      f"List of differences: {', '.join(deviations)}\n"
                      f"Expected data: {str_bytes(data)}\n"
                      f"Actual data: {str_bytes(processed)}")

# ----------------------------------------------------------------------------------------------------------------------


class _DeviceSimulatorInternalState(Enum):
    IDLE = 0
    DEEP_SLEEP = -2
    SLEEP = -1
    MEASUREMENT = 1


class Malfunction(Enum):
    NONE = 0
    NOT_RESPONDING = 1


class SensirionDeviceSimulator:
    """
    This implements the mock-up for Sensirion SPS-30 device by mimicking serial.Serial implementation.
    It provides the same API as used by the driver to get data from serial port
    """

    def __init__(self):
        self.port = "/dev/null"
        self.is_open = False
        self.internal_state = _DeviceSimulatorInternalState.IDLE
        self.malfunction = Malfunction.NONE
        self.timeout = SensirionSPS30.READ_TIMEOUT_MS / 1000
        self.write_timeout = SensirionSPS30.WRITE_TIMEOUT_MS / 1000
        self.response_to_last_command = bytes()

    def open(self):
        self.is_open = True

    def write(self, frame: bytes):
        if not self.is_open:
            raise serial.PortNotOpenError()
        if self.malfunction == Malfunction.NOT_RESPONDING:
            time.sleep(self.write_timeout)
            raise serial.SerialTimeoutException(f"Simulated timeout after {self.write_timeout:.2f} seconds")
        self.response_to_last_command = self.prepare_response(frame)

    def read_all(self) -> bytes:
        if not self.is_open:
            raise serial.PortNotOpenError()
        if self.malfunction == Malfunction.NOT_RESPONDING:
            time.sleep(self.timeout)
            raise serial.SerialTimeoutException(f"Simulated timeout after {self.timeout:.2f} seconds")
        return self.response_to_last_command

    def prepare_response(self, frame: bytes) -> bytes:
        pass