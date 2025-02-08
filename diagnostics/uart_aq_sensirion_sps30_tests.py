from unittest import TestCase
import random

import sys
sys.path.append('..')
sys.path.append('.')

from device.dev_serial_sps30 import *
from uart_aq_sensirion_sps30_testdata import *
from uart_aq_sensirion_sps30_mock import SensirionDeviceSimulator


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
            elif isinstance(data_structure, Empty):
                # expected empty tuple
                self.assertTupleEqual(data_structure, the_frame.interpret_data())
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


class AbstractTestAdvancedUsage(TestCase):

    def sensor(self) -> SensirionSPS30:
        raise NotImplementedError()

    def _execute_command(self, action: CommandExecution):
        action.raise_error()
        return action.get_miso().interpret_data()

    def assertEmptyResult(self, actual: tuple, cmd: Command):
        self.assertTupleEqual((), actual, f"{cmd.name} is expected to return no data")

    def assertNamedtupleAllFieldsNonEmpty(self, actual):
        for attr in actual._fields:
            self.assertIsNotNone(getattr(actual, attr), f"The {attr} of {type(actual).__name__} "
                                                        f"unexpectedly happen to be empty")

    def test_000_Reset(self):
        try:
            try:
                self._execute_command(self.sensor().wake_up())
            except CommandNotAllowed:
                # can be safely ignored under assumption the device was in IDLE mode
                pass
            result = self._execute_command(self.sensor().reset())
            self.assertEmptyResult(result, CMD_RESET)
            # reset should also work in MEASURE mode:
            self._execute_command(self.sensor().start_measurement())
            result = self._execute_command(self.sensor().reset())
            self.assertEmptyResult(result, CMD_RESET)
        except CommandNotAllowed:
            self.fail(f"Testing of performing device reset failed with 'command not allowed'")
        except SHDLCError as ex:
            # failure
            self.fail(f"Unexpected error occurred while testing resetting the device: {str(ex)}")

    def test_001_Sleep_WakeUp(self):
        # it is assumed that at the beginning each test starts with device in IDLE mode
        try:
            result = self._execute_command(self.sensor().sleep())
            self.assertEmptyResult(result, CMD_SLEEP)
            result = self._execute_command(self.sensor().wake_up())
            self.assertEmptyResult(result, CMD_WAKEUP)
        except CommandNotAllowed:
            self.fail(f"Testing putting to sleep and waking up the device failed with 'command not allowed'. "
                      f"This may be either true problem, or the consequence of prior errors, "
                      f"leading to incorrect initial state of the device "
                      f"(IDLE is always assumed to be at the start of each test")
        except SHDLCError as ex:
            # failure
            self.fail(f"Unexpected error occurred while testing waking up the device: {str(ex)}")
        # each of the tests must clean-up after running, so to be sure next test starts with sensor in IDLE mode
        # in this example, there's nothing to do

    def test_002_Measure(self):
        try:
            result = self._execute_command(self.sensor().start_measurement())
            self.assertEmptyResult(result, CMD_START)
            for _ in range(5):
                result = self._execute_command(self.sensor().read_measured_values())
                self.assertIsInstance(result, Measurement, f"Measurement returned unexpected type")
                print(result)
                self.assertNamedtupleAllFieldsNonEmpty(result)
                sleep(1)
            result = self._execute_command(self.sensor().stop_measurement())
            self.assertEmptyResult(result, CMD_STOP)
        except CommandNotAllowed:
            self.fail(f"Testing putting to sleep and waking up the device failed with 'command not allowed'. "
                      f"This may be either true problem, or the consequence of prior errors, "
                      f"leading to incorrect initial state of the device "
                      f"(IDLE is always assumed to be at the start of each test")
        except SHDLCError as ex:
            # failure
            self.fail(f"Unexpected error occurred while testing waking up the device: {str(ex)}")

    def test_003_Clean(self):
        try:
            result = self._execute_command(self.sensor().start_measurement())
            self.assertEmptyResult(result, CMD_START)
            result = self._execute_command(self.sensor().start_fan_cleaning())
            self.assertEmptyResult(result, CMD_CLEAN)
            result = self._execute_command(self.sensor().stop_measurement())
            self.assertEmptyResult(result, CMD_STOP)
            # in IDLE mode CLEAN will fail with CommandNotAllowed
            try:
                self._execute_command(self.sensor().start_fan_cleaning())
                self.fail(f"The {CMD_CLEAN} command in IDLE state should rise {CommandNotAllowed.__name__}, "
                          f"which has not happen")
            except CommandNotAllowed:
                # as expected
                pass

        except CommandNotAllowed:
            self.fail(f"Testing of instruction to clean the fan failed with 'command not allowed'. "
                      f"This may be either true problem, or the consequence of prior errors, "
                      f"leading to incorrect initial state of the device "
                      f"(IDLE is always assumed to be at the start of each test")
        except SHDLCError as ex:
            # failure
            self.fail(f"Unexpected error occurred while testing cleaning the fan: {str(ex)}")

    def test_004_SetAutoClean(self):
        pass
        # HERE I AM

class TestAdvancedUsageMock(AbstractTestAdvancedUsage):

    def setUp(self) -> None:
        self.device = SensirionSPS30(_device=SensirionDeviceSimulator())

    def sensor(self) -> SensirionSPS30:
        return self.device


del AbstractTestAdvancedUsage
