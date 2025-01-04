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



class SimulatedResponseFrame:

    def __init__(self, command: Command = None, data: bytes = None, state: int = None):
        if command is None:
            command = random.choice(COMMANDS)
        if state is None:
            state = 0


        self.command = command
        self.data = data
        self.state = state

    def get_frame_bytes(self) -> bytes:
        _frame_content = [FRAME_SLAVE_ADR, self.command.code, self.state] + \
                         stuffing(bytes([len(self.data)])) + stuffing(self.data)

        return bytes(
            [FRAME_START] +
            _frame_content +
            stuffing(bytes([checksum(_frame_content)])) +
            [FRAME_STOP]
        )



class FrameTests(TestCase):

    def _random_data(self, size=-1) -> bytes:
        if size == 0:
            return bytes([])
        if size < 0:
            size = random.randint(1, 255)
        return bytes([random.randint(0, 255) for _ in range(size)])

    def test_01_MOSI(self):
        # too long data
        self.assertRaises(ValueError, MOSIFrame, random.choice(COMMANDS), self._random_data(256))
        self.assertRaises(ValueError, MOSIFrame, random.choice(COMMANDS), self._random_data(random.randint(257, 356)))
        # random data
        test_data = self._random_data()
        test_cmd = random.choice(COMMANDS)
        frame = MOSIFrame(command=test_cmd, data=test_data)
        self.assertEqual(len(test_data), frame.get_data_len(),
                         f"The data lengt measured by the MOSI frame is incorrect")
        self.assertEqual(test_cmd.code, frame.get_command(), f"The frame returned wrong command-code")
        frame_data = frame.get_frame()
        self.assertEqual(FRAME_START, frame_data[0], f"The frame data does not start with the required start-byte")
        self.assertEqual(FRAME_STOP, frame_data[-1], f"The frame data does not end with the required stop-byte")
        self.assertEqual(FRAME_SLAVE_ADR, frame_data[1], f"The frame data does not provide correct slave address byte")
        self.assertEqual(test_cmd.code, frame_data[2], f"The frame data does not provide correct command code")
        # data, len and checksum in the frame content are not tested
        # smoke test of _str_bytes
        print(repr(frame))

    def test_02_MISO_reaction_on_wrong_data(self):
        pass


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