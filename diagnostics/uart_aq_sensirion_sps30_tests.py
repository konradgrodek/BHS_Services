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


class TestData:

    def to_bytes(self) -> bytes:
        raise NotImplementedError()

    def data(self) -> namedtuple:
        raise NotImplementedError()


class TestEmptyData(TestData):

    def to_bytes(self) -> bytes:
        return bytes([])

    def data(self) -> namedtuple:
        return {}


class TestDataMeasurement(TestData):
    CONCENTRATION = list(range(0, 65535))
    WEIGHTS = [1 / (3 * c) if c > 0 else 1 / 5 for c in CONCENTRATION]

    def __init__(self):
        _mass, _number, _size = random.choices(self.CONCENTRATION, weights=self.WEIGHTS, k=3)
        def _generate_next(x): return min(65535, max(0, x + random.randint(-x // 10, x // 10)))
        self.measurement = Measurement(
            mass_concentration_pm_1_0_ug_m3=_mass,
            mass_concentration_pm_2_5_ug_m3=_generate_next(_mass),
            mass_concentration_pm_4_0_ug_m3=_generate_next(_mass),
            mass_concentration_pm_10_ug_m3=_generate_next(_mass),
            number_concentration_pm_0_5_per_cm3=_number,
            number_concentration_pm_1_0_per_cm3=_generate_next(_number),
            number_concentration_pm_2_5_per_cm3=_generate_next(_number),
            number_concentration_pm_4_0_per_cm3=_generate_next(_number),
            number_concentration_pm_10_per_cm3=_generate_next(_number),
            typical_particle_size_um=_size,
            timestamp=datetime.now()
        )

    def to_bytes(self) -> bytes:
        def _to_bytes(x: int): return x.to_bytes(2, byteorder='big')
        return _to_bytes(self.measurement.mass_concentration_pm_1_0_ug_m3) + \
            _to_bytes(self.measurement.mass_concentration_pm_2_5_ug_m3) + \
            _to_bytes(self.measurement.mass_concentration_pm_4_0_ug_m3) + \
            _to_bytes(self.measurement.mass_concentration_pm_10_ug_m3) + \
            _to_bytes(self.measurement.number_concentration_pm_0_5_per_cm3) + \
            _to_bytes(self.measurement.number_concentration_pm_1_0_per_cm3) + \
            _to_bytes(self.measurement.number_concentration_pm_2_5_per_cm3) + \
            _to_bytes(self.measurement.number_concentration_pm_4_0_per_cm3) + \
            _to_bytes(self.measurement.number_concentration_pm_10_per_cm3) + \
            _to_bytes(self.measurement.typical_particle_size_um)

    def data(self) -> namedtuple:
        return self.measurement


class TestDataAutoCleanInterval(TestData):

    def __init__(self, interval_s = -1):
        self.auto_clean_interval = AutoCleanInterval(
            interval_s=random.randint(60*60*24, 60*60*24*7) if interval_s < 0 else interval_s
        )

    def to_bytes(self) -> bytes:
        return self.auto_clean_interval.interval_s.to_bytes(4, byteorder='big')

    def data(self) -> namedtuple:
        return self.auto_clean_interval


class TestDataDeviceInfo(TestData):

    def __init__(self, device_info: str = None):
        self.device_info = DeviceInfo(
            info=reduce(lambda x, y: x + y, random.choices('ABCDEFGH0123456789', k=16))
            if device_info is None else device_info
        )

    def to_bytes(self) -> bytes:
        # null-terminated ascii string
        return self.device_info.info.encode('ascii')+bytes([0])

    def data(self) -> namedtuple:
        return self.device_info


class TestDataVersions(TestData):

    def __init__(self, firmware=None, hardware=None, protocol=None):
        self.versions = Versions(
            firmware=(random.randint(0, 255), random.randint(0, 255)) if firmware is None else firmware,
            hardware=random.randint(0, 255) if hardware is None else hardware,
            protocol=(random.randint(0, 255), random.randint(0, 255)) if protocol is None else protocol
        )

    def to_bytes(self) -> bytes:
        return bytes([
            self.versions.firmware[0],
            self.versions.firmware[1],
            0,
            self.versions.hardware,
            0,
            self.versions.protocol[0],
            self.versions.protocol[1]
        ])

    def data(self) -> namedtuple:
        return self.versions


class TestDataDeviceStatus(TestData):

    def __init__(self, speed_warning=-1, laser_error=-1, fan_error=-1):
        s, l, f = (
            random.randint(0, 1) if speed_warning < 0 else speed_warning,
            random.randint(0, 1) if laser_error < 0 else laser_error,
            random.randint(0, 1) if fan_error < 0 else fan_error,
        )

        self.device_status = DeviceStatus(
            speed_warning=s,
            laser_error=l,
            fan_error=f,
            register=f"{s*2**21+l*2**5+f*2**4:b}"
        )

    def to_bytes(self) -> bytes:
        return int(self.device_status.register, base=2).to_bytes(4, byteorder='big')+bytes([0])

    def data(self) -> namedtuple:
        return self.device_status


class SimulatedResponseFrame:

    def __init__(self, command: Command = None, data: TestData = None, state: int = 0):
        if command is None:
            command = random.choice(COMMANDS)
        if state is None:
            state = 0
        if data is None:
            # generate fake data
            if command in (CMD_START, CMD_STOP, CMD_SLEEP, CMD_WAKEUP, CMD_CLEAN, CMD_RESET):
                data = TestEmptyData()
            if command == CMD_MEASURE:
                data = TestDataMeasurement()
            if command == CMD_INFO:
                data = TestDataDeviceInfo()
            if command == CMD_VERSION:
                data = TestDataVersions()
            if command == CMD_STATUS:
                data = TestDataDeviceStatus()
            if command == CMD_SET_AUTO_CLEAN:
                # FIXME how to distinguish SET from GET?
                data = TestEmptyData()

        self.command = command
        self.data = data
        self.state = state

    def get_frame_bytes(self) -> bytes:
        data_bytes = self.data.to_bytes()
        _not_stuffed_frame_content = bytes([FRAME_SLAVE_ADR, self.command.code, self.state, len(data_bytes)]) + data_bytes

        _stuffed_frame_content = [FRAME_SLAVE_ADR, self.command.code, self.state] + \
                                 stuffing(bytes([len(data_bytes)])) + stuffing(data_bytes)

        return bytes(
            [FRAME_START] +
            _stuffed_frame_content +
            stuffing(bytes([checksum(_not_stuffed_frame_content)])) +
            [FRAME_STOP]
        )


class FrameTests(TestCase):

    def setUp(self) -> None:
        # comment it out to have the tests random
        random.seed = 12

    def _random_data(self, size=-1) -> bytes:
        if size == 0:
            return bytes([])
        if size < 0:
            size = random.randint(1, 255)
        return bytes([random.randint(0, 255) for _ in range(size)])

    def assertMeasurementEqual(self, expected: Measurement, actual: Measurement):
        self.assertEqual(expected.mass_concentration_pm_1_0_ug_m3, actual.mass_concentration_pm_1_0_ug_m3,
                         f"Measurement differs on mass-concentration-1-0")
        self.assertEqual(expected.mass_concentration_pm_2_5_ug_m3, actual.mass_concentration_pm_2_5_ug_m3,
                         f"Measurement differs on mass-concentration-2-5")
        self.assertEqual(expected.mass_concentration_pm_4_0_ug_m3, actual.mass_concentration_pm_4_0_ug_m3,
                         f"Measurement differs on mass-concentration-4-0")
        self.assertEqual(expected.mass_concentration_pm_10_ug_m3, actual.mass_concentration_pm_10_ug_m3,
                         f"Measurement differs on mass-concentration-10")
        self.assertEqual(expected.number_concentration_pm_0_5_per_cm3, actual.number_concentration_pm_0_5_per_cm3,
                         f"Measurement differs on number-concentration-0-5")
        self.assertEqual(expected.number_concentration_pm_1_0_per_cm3, actual.number_concentration_pm_1_0_per_cm3,
                         f"Measurement differs on number-concentration-1-0")
        self.assertEqual(expected.number_concentration_pm_2_5_per_cm3, actual.number_concentration_pm_2_5_per_cm3,
                         f"Measurement differs on number-concentration-2-5")
        self.assertEqual(expected.number_concentration_pm_4_0_per_cm3, actual.number_concentration_pm_4_0_per_cm3,
                         f"Measurement differs on number-concentration-4-0")
        self.assertEqual(expected.number_concentration_pm_10_per_cm3, actual.number_concentration_pm_10_per_cm3,
                         f"Measurement differs on number-concentration-10")
        self.assertEqual(expected.typical_particle_size_um, actual.typical_particle_size_um,
                         f"Measurement differs on typical-particle-size")
        self.assertIsNotNone(actual.timestamp, f"The timestamp may not be left empty")
        # NOTE: the actual values of the timestamp are not compared deliberately:
        # this is additional field, not being part of the communication protocol

    def assertAutoCleanIntervalEqual(self, expected: AutoCleanInterval, actual: AutoCleanInterval):
        self.assertEqual(expected.interval_s, actual.interval_s, f"Ato-clean-interval differs")

    def assertDeviceInfoEqual(self, expected: DeviceInfo, actual: DeviceInfo):
        self.assertEqual(expected.info, actual.info, f"Device-info differs")

    def assertVersionsEqual(self, expected: Versions, actual: Versions):
        self.assertTupleEqual(expected.firmware, actual.firmware, f"Version differs on firmware")
        self.assertEqual(expected.hardware, actual.hardware, f"Version differs on hardware")
        self.assertTupleEqual(expected.protocol, actual.protocol, f"Version differs on protocol")

    def assertDeviceStatusEqual(self, expected: DeviceStatus, actual: DeviceStatus):
        self.assertEqual(expected.speed_warning, actual.speed_warning, f"Device-status differs on speed-warning")
        self.assertEqual(expected.laser_error, actual.laser_error, f"Device-status differs on laser-error")
        self.assertEqual(expected.fan_error, actual.fan_error, f"Device-status differs on fan-error")
        self.assertEqual(expected.speed_warning, actual.speed_warning, f"Device-status differs on speed-warning")

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

    def test_02_MISO_correct_data_frame(self):
        for command in list(COMMANDS) + [CMD_INFO, CMD_VERSION, CMD_MEASURE, CMD_STATUS] * 100:
            simulated_frame = SimulatedResponseFrame(command=command)
            the_frame = MISOFrame(simulated_frame.get_frame_bytes())
            self.assertEqual(simulated_frame.command, the_frame.command,
                             "The command returned by frame is different than the one used to create the frame")
            self.assertEqual(simulated_frame.data.to_bytes(), the_frame.data,
                             f"The data bytes returned by frame are different than the bytes used to create it")

            data_structure = simulated_frame.data.data()
            if isinstance(data_structure, Measurement):
                self.assertMeasurementEqual(data_structure, the_frame.interpret_data())
            elif isinstance(data_structure, AutoCleanInterval):
                self.assertAutoCleanIntervalEqual(data_structure, the_frame.interpret_data())
            elif isinstance(data_structure, DeviceInfo):
                self.assertDeviceInfoEqual(data_structure, the_frame.interpret_data())
            elif isinstance(data_structure, Versions):
                self.assertVersionsEqual(data_structure, the_frame.interpret_data())
            elif isinstance(data_structure, DeviceStatus):
                self.assertDeviceStatusEqual(data_structure, the_frame.interpret_data())
            elif isinstance(data_structure, dict):
                # expected empty dict
                self.assertDictEqual(data_structure, the_frame.interpret_data())
            else:
                self.fail(f"Unsupported structure: {type(data_structure)}")

    def test_03_MISO_reaction_on_wrong_data(self):
        self.assertRaises(NoDataInResponse, MISOFrame, None)
        self.assertRaises(NoDataInResponse, MISOFrame, bytes([]))
        for attempt in range(1, 7):
            self.assertRaises(ResponseFrameError, MISOFrame, self._random_data(attempt))

        # simulate device error
        self.assertRaises(DeviceError, MISOFrame,
                          SimulatedResponseFrame(command=CMD_START, state=int('10000000', 2)).get_frame_bytes())
        self.assertRaises(ResponseError, MISOFrame,
                          SimulatedResponseFrame(command=CMD_STATUS, state=int('10000001', 2)).get_frame_bytes())
        self.assertRaises(ResponseError, MISOFrame,
                          SimulatedResponseFrame(command=CMD_STATUS, state=int('10000011', 2)).get_frame_bytes())
        # simulate command-not-allowed
        self.assertRaises(CommandNotAllowed, MISOFrame,
                          SimulatedResponseFrame(command=CMD_STATUS, state=int('11000011', 2)).get_frame_bytes())

        for command in list(COMMANDS) + [CMD_INFO, CMD_VERSION, CMD_MEASURE, CMD_STATUS] * 100:
            valid_frame_bytes = SimulatedResponseFrame(command=command).get_frame_bytes()
            self.assertRaises(ResponseFrameError, MISOFrame, bytes([0])+valid_frame_bytes[1:])
            self.assertRaises(ResponseFrameError, MISOFrame, valid_frame_bytes[0:1]+bytes([0xFF])+valid_frame_bytes[3:])
            self.assertRaises(ResponseFrameError, MISOFrame, valid_frame_bytes[:-1]+bytes([0]))

            # manipulate the length of data
            self.assertRaises(ResponseFrameError, MISOFrame,
                              valid_frame_bytes[:4]+bytes([valid_frame_bytes[4]+5])+valid_frame_bytes[5:])

            # manipulate the checksum
            _d_idx = len(valid_frame_bytes) - 2
            _r_byte = random.randint(0, 255)
            while valid_frame_bytes[_d_idx] == _r_byte:
                _r_byte = random.randint(0, 255)
            invalid_frame_bytes = valid_frame_bytes[:_d_idx] + bytes([_r_byte]) + valid_frame_bytes[_d_idx+1:]
            try:
                MISOFrame(invalid_frame_bytes)
                self.fail(f"It was expected that introducing random disturbance in checksum will result in "
                          f"ResponseFrameError, whilst no exception was reported.\n"
                          f"V: {str_bytes(valid_frame_bytes)}\n"
                          f"I: {str_bytes(invalid_frame_bytes)}")
            except ResponseFrameError:
                # expected
                pass
            except AssertionError as e:
                # if failed...
                raise e
            except Exception as different_exception:
                self.fail(f"It was expected that introducing random disturbance in checksum will result in "
                          f"ResponseFrameError, whereas {different_exception} was reported.\n"
                          f"V: {str_bytes(valid_frame_bytes)}\n"
                          f"I: {str_bytes(invalid_frame_bytes)}")

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

    def __init__(self, firmware_version=(2, 3)):
        self.port = "/dev/null"
        self.is_open = False
        self.internal_state = _DeviceSimulatorInternalState.IDLE
        self.malfunction = Malfunction.NONE
        self.timeout = SensirionSPS30.READ_TIMEOUT_MS / 1000
        self.write_timeout = SensirionSPS30.WRITE_TIMEOUT_MS / 1000
        self.current_command: Command = None
        self.response_to_last_command = bytes()
        self.firmware_version = firmware_version
        self.protocol_version = (2, 0)
        self.hardware_revision = 7
        self.auto_clean_interval = 604800
        self.product_type = "00080000"
        self.serial_number = TestDataDeviceInfo().device_info.info  # random serial number
        self.register = 0

    def open(self):
        self.is_open = True

    def write(self, frame: bytes):
        if not self.is_open:
            raise serial.PortNotOpenError()
        if self.malfunction == Malfunction.NOT_RESPONDING:
            time.sleep(self.write_timeout)
            raise serial.SerialTimeoutException(f"Simulated timeout after {self.write_timeout:.2f} seconds")
        if frame == bytes([0]):
            if self.internal_state == _DeviceSimulatorInternalState.DEEP_SLEEP:
                self.internal_state = _DeviceSimulatorInternalState.SLEEP
                self.response_to_last_command = bytes([])
        else:
            self.response_to_last_command = self.prepare_response(frame)

    def read_all(self) -> bytes:
        if not self.is_open:
            raise serial.PortNotOpenError()
        if self.malfunction == Malfunction.NOT_RESPONDING:
            time.sleep(self.timeout)
            raise serial.SerialTimeoutException(f"Simulated timeout after {self.timeout:.2f} seconds")
        return self.response_to_last_command

    def response_with_no_data(self, error_code: int = 0, command_code: int = -1) -> bytes:
        return SimulatedResponseFrame(
            command=self.current_command.code if command_code < 0 else command_code,
            data=TestEmptyData(),
            state=(2**7+error_code) if error_code > 0 else 0
        ).get_frame_bytes()

    def prepare_response(self, frame: bytes) -> bytes:
        if self.internal_state == _DeviceSimulatorInternalState.DEEP_SLEEP:
            return bytes([])

        if frame[0] != FRAME_START or frame[-1] != FRAME_STOP or frame[1] != FRAME_SLAVE_ADR:
            return bytes([])  # TODO check what would be the response

        frame_content = unstuffing(frame[1:-1])

        expected_chksum = checksum(frame_content[:-1])
        if expected_chksum != frame_content[-1]:
            return bytes([])  # TODO check what would be the response

        self.current_command = {cmd.code: cmd for cmd in COMMANDS}.get(frame_content[1])
        if self.current_command is None or self.current_command.min_version < self.firmware_version:
            return self.response_with_no_data(command_code=frame_content[1], error_code=0x02)

        if self.internal_state == _DeviceSimulatorInternalState.SLEEP and self.current_command != CMD_WAKEUP:
            return bytes([])

        data_len = frame_content[2]
        data = frame_content[3:3+data_len]

        if self.current_command == CMD_START:
            if data_len != 2:
                return self.response_with_no_data(error_code=0x01)
            if data[0] != 0x01 or data[1] not in (0x03, 0x05):
                return self.response_with_no_data(error_code=0x04)
            if self.internal_state != _DeviceSimulatorInternalState.IDLE:
                return self.response_with_no_data(error_code=0x43)
            self.internal_state = _DeviceSimulatorInternalState.MEASUREMENT
            return self.response_with_no_data()
        if self.current_command == CMD_STOP:
            if data_len != 0:
                return self.response_with_no_data(error_code=0x01)
            if self.internal_state != _DeviceSimulatorInternalState.MEASUREMENT:
                return self.response_with_no_data(error_code=0x43)
            self.internal_state = _DeviceSimulatorInternalState.IDLE
            return self.response_with_no_data()
        if self.current_command == CMD_MEASURE:
            if data_len != 0:
                return self.response_with_no_data(error_code=0x01)
            if self.internal_state != _DeviceSimulatorInternalState.MEASUREMENT:
                return self.response_with_no_data(error_code=0x43)
            return SimulatedResponseFrame(self.current_command).get_frame_bytes()
        if self.current_command == CMD_SLEEP:
            if data_len != 0:
                return self.response_with_no_data(error_code=0x01)
            if self.internal_state != _DeviceSimulatorInternalState.IDLE:
                return self.response_with_no_data(error_code=0x43)
            return self.response_with_no_data()
        if self.current_command == CMD_WAKEUP:
            if data_len != 0:
                return self.response_with_no_data(error_code=0x01)
            if self.internal_state != _DeviceSimulatorInternalState.SLEEP:
                return self.response_with_no_data(error_code=0x43)
            return self.response_with_no_data()
        if self.current_command == CMD_CLEAN:
            if data_len != 0:
                return self.response_with_no_data(error_code=0x01)
            if self.internal_state != _DeviceSimulatorInternalState.MEASUREMENT:
                return self.response_with_no_data(error_code=0x43)
            return self.response_with_no_data()
        if self.current_command == CMD_SET_AUTO_CLEAN:
            if self.internal_state not in (
                    _DeviceSimulatorInternalState.MEASUREMENT,
                    _DeviceSimulatorInternalState.IDLE):
                return self.response_with_no_data(error_code=0x43)
            if data_len == 1:
                # read auto-clean-interval
                if data[0] != 0x00:
                    return self.response_with_no_data(error_code=0x04)
                return SimulatedResponseFrame(
                    self.current_command,
                    data=TestDataAutoCleanInterval(self.auto_clean_interval)
                ).get_frame_bytes()
            elif data_len == 5:
                # write auto-clean-interval
                if data[0] != 0x00:
                    return self.response_with_no_data(error_code=0x04)
                self.auto_clean_interval = int.from_bytes(data[1:], byteorder="big")
                if self.auto_clean_interval < 0:
                    return self.response_with_no_data(error_code=0x04)
                return self.response_with_no_data()
            else:
                return self.response_with_no_data(error_code=0x01)
        if self.current_command == CMD_INFO:
            if self.internal_state not in (
                    _DeviceSimulatorInternalState.MEASUREMENT,
                    _DeviceSimulatorInternalState.IDLE):
                return self.response_with_no_data(error_code=0x43)
            if data_len != 1:
                return self.response_with_no_data(error_code=0x01)
            if data[0] == 0x00:
                # product type
                return SimulatedResponseFrame(
                    self.current_command,
                    data=TestDataDeviceInfo(device_info=self.product_type)
                ).get_frame_bytes()
            elif data[0] == 0x03:
                # serial number
                return SimulatedResponseFrame(
                    self.current_command,
                    data=TestDataDeviceInfo(device_info=self.serial_number)
                ).get_frame_bytes()
            else:
                return self.response_with_no_data(error_code=0x04)
        if self.current_command == CMD_VERSION:
            if self.internal_state not in (
                    _DeviceSimulatorInternalState.MEASUREMENT,
                    _DeviceSimulatorInternalState.IDLE):
                return self.response_with_no_data(error_code=0x43)
            if data_len != 0:
                return self.response_with_no_data(error_code=0x01)
            return SimulatedResponseFrame(
                self.current_command,
                data=TestDataVersions(
                    firmware=self.firmware_version,
                    hardware=self.hardware_revision,
                    protocol=self.protocol_version
                )
            ).get_frame_bytes()
        if self.current_command == CMD_STATUS:
            if self.internal_state not in (
                    _DeviceSimulatorInternalState.MEASUREMENT,
                    _DeviceSimulatorInternalState.IDLE):
                return self.response_with_no_data(error_code=0x43)
            if data_len != 0:
                return self.response_with_no_data(error_code=0x01)
            return SimulatedResponseFrame(
                self.current_command,
                data=TestDataDeviceStatus(0, 0, 0)  # FIXME implement malfunctions
            ).get_frame_bytes()
        if self.current_command == CMD_RESET:
            if self.internal_state not in (
                    _DeviceSimulatorInternalState.MEASUREMENT,
                    _DeviceSimulatorInternalState.IDLE):
                return self.response_with_no_data(error_code=0x43)
            if data_len != 0:
                return self.response_with_no_data(error_code=0x01)
            self.internal_state = _DeviceSimulatorInternalState.IDLE
            return self.response_with_no_data()

        # if reached here, it means that one of the commands was omitted
        return self.response_with_no_data(command_code=frame_content[1], error_code=0x02)

# NEXT:
# 1. consider using SimulatedResponseFrame everywhere
# 2. implement internal state, make sure the responses are consistent
# 3. in diagnostic tool add simulated error, test different scenarios




