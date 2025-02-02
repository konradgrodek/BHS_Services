import sys
import time
from enum import Enum
sys.path.append('..')
sys.path.append('.')

from uart_aq_sensirion_sps30_testdata import *


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

    def __str__(self):
        return f"SPS-30 Mock, fw ver {self.firmware_version[0]}.{self.firmware_version[1]}"

    def open(self):
        self.is_open = True

    def write(self, frame: bytes):
        if not self.is_open:
            raise serial.PortNotOpenError()
        if self.malfunction == Malfunction.NOT_RESPONDING:
            time.sleep(self.write_timeout)
            raise serial.SerialTimeoutException(f"Simulated timeout after {self.write_timeout:.2f} seconds")
        if frame == bytes([0xFF]):
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

    def response_with_no_data(self, error_code: int = 0, command: Command = None) -> bytes:
        return SimulatedResponseFrame(
            command=self.current_command if command is None else command,
            data=TestEmptyData(),
            state=(2**7+error_code) if error_code > 0 else 0
        ).get_frame_bytes()

    def _unknown_command(self, command_code: int) -> Command:
        return Command(code=command_code, name='Unknown command', kind='Wrong', timeout_ms=0, min_version=(0, 0))

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
        if self.current_command is None or self.current_command.min_version > self.firmware_version:
            return self.response_with_no_data(command=self._unknown_command(frame_content[1]), error_code=0x02)

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
            return SimulatedResponseFrame(command=self.current_command).get_frame_bytes()
        if self.current_command == CMD_SLEEP:
            if data_len != 0:
                return self.response_with_no_data(error_code=0x01)
            if self.internal_state != _DeviceSimulatorInternalState.IDLE:
                return self.response_with_no_data(error_code=0x43)
            self.internal_state = _DeviceSimulatorInternalState.DEEP_SLEEP
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
                    command=self.current_command,
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
                    command=self.current_command,
                    data=TestDataDeviceInfo(device_info=self.product_type)
                ).get_frame_bytes()
            elif data[0] == 0x03:
                # serial number
                return SimulatedResponseFrame(
                    command=self.current_command,
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
                command=self.current_command,
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
            if data_len != 1:
                return self.response_with_no_data(error_code=0x01)
            # FIXME data interpretation:
            # 0: Do not clear any bit in the Device Status Register after reading.
            # 1: Clear all bits in the Device Status Register after reading.
            return SimulatedResponseFrame(
                command=self.current_command,
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
        return self.response_with_no_data(command=self._unknown_command(frame_content[1]), error_code=0x02)

# NEXT:
# DONE 1. consider using SimulatedResponseFrame everywhere
# DONE 2. implement internal state, make sure the responses are consistent
# 3. in diagnostic tool add simulated error, test different scenarios
# 4. Implement simulated malfunctions
# 5. Write tests using simulated device (and malfuctions)


if __name__ == "__main__":

    responses_history = list()

    def collect_response(response: MISOFrame):
        responses_history.append(response)

    sensor = SensirionSPS30(_device=SensirionDeviceSimulator())

    # action = sensor.wake_up(collect_response)
    action = sensor.get_version(collect_response)

    while action.is_alive():
        print('.', end='')
        time.sleep(1)

    action.raise_error()
    result = action.get_miso().interpret_data()
    print()
    print(result)


