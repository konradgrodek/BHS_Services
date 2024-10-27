# https://sensirion.com/media/documents/8600FF88/64A3B8D6/Sensirion_PM_Sensors_Datasheet_SPS30.pdf
# https://github.com/Sensirion/embedded-uart-sps/tree/master/sps30-uart
# all bytes big-endian

import serial

from collections import namedtuple
from functools import reduce
from threading import Thread
from datetime import datetime
from time import sleep

Command = namedtuple('Command', ['code', 'name', 'kind', 'timeout_ms', 'min_version'])
CMD_START = Command(code=0x00, name='Start Measurement', kind='Execute', timeout_ms=20, min_version=(1, 0))
CMD_STOP = Command(code=0x01, name='Stop Measurement', kind='Execute', timeout_ms=20, min_version=(1, 0))
CMD_MEASURE = Command(code=0x03, name='Read Measured Value', kind='Read', timeout_ms=20, min_version=(1, 0))
CMD_SLEEP = Command(code=0x10, name='Sleep', kind='Execute', timeout_ms=5, min_version=(2, 0))
CMD_WAKEUP = Command(code=0x11, name='Wake-up', kind='Execute', timeout_ms=5, min_version=(2, 0))
CMD_CLEAN = Command(code=0x56, name='Start Fan Cleaning', kind='Execute', timeout_ms=20, min_version=(1, 0))
CMD_SET_AUTO_CLEAN = Command(code=0x80, name='Read/Write Auto Cleaning Interval', kind='Read / Write', timeout_ms=20,
                             min_version=(1, 0))
CMD_INFO = Command(code=0xD0, name='Device Information', kind='Read', timeout_ms=20, min_version=(1, 0))
CMD_VERSION = Command(code=0xD1, name='Read Version', kind='Read', timeout_ms=20, min_version=(1, 0))
CMD_STATUS = Command(code=0xD2, name='Read Device Status Register', kind='Read', timeout_ms=20, min_version=(2, 2))
CMD_RESET = Command(code=0xD3, name='Reset', kind='Execute', timeout_ms=20, min_version=(1, 0))
COMMANDS = (
    CMD_START, CMD_STOP, CMD_MEASURE, CMD_SLEEP, CMD_WAKEUP, CMD_CLEAN,
    CMD_SET_AUTO_CLEAN, CMD_INFO, CMD_VERSION, CMD_STATUS, CMD_RESET,
)

ERRORS = {
    0x01: 'Wrong data length for this command (too much or little data)',
    0x02: 'Unknown command',
    0x03: 'No access right for command',
    0x04: 'Illegal command parameter or parameter out of allowed range',
    0x28: 'Internal function argument out of range',
    0x43: 'Command not allowed in current state',
}

FRAME_START = 0x7E
FRAME_SLAVE_ADR = 0x00
FRAME_STOP = FRAME_START


class SHDLCError(Exception):

    def __init__(self, msg: str):
        Exception.__init__(self, msg)


class ResponseFrameError(SHDLCError):

    def __init__(self, msg: str, data=None):
        SHDLCError.__init__(self, f'The received frame has incorrect structure or content. {msg}')
        self.original_bytes_received: bytes = data


class DeviceError(SHDLCError):

    def __init__(self):
        SHDLCError.__init__(self, f'Device error was reported. Query for Device Status Register for details')


class DeviceCommunicationError(SHDLCError):

    def __init__(self, msg):
        SHDLCError.__init__(self, f'There was a problem with communicating with the device. {msg}')


class ResponseError(SHDLCError):

    def __init__(self, error_code: int):
        self.error_code = error_code
        self.error = ERRORS[error_code] if error_code in ERRORS else "Unknown error"
        SHDLCError.__init__(self, f'The device responded with '
                                  f'the following error code: 0x{error_code:X} ({self.error})')


class ConfigurationError(SHDLCError):

    def __init__(self, msg: str):
        SHDLCError.__init__(self, f'The used parameter is incorrect. {msg}')


def str_bytes(content: bytes):
    return "|".join([f"0x{_b:X}" for _b in content])


class MOSIFrame:
    """
    Implements Master Out Slave In frame, part of SHDLC protocol.
    It represents the command sent from master (RPi) to the SPS30 sensor.
    """

    BYTES_DISEMBOWELLING_START = 0x7D
    BYTES_STUFFING = {
        0x7E: [BYTES_DISEMBOWELLING_START, 0x5E],
        0x7D: [BYTES_DISEMBOWELLING_START, 0x5D],
        0x11: [BYTES_DISEMBOWELLING_START, 0x31],
        0x13: [BYTES_DISEMBOWELLING_START, 0x33],
    }

    def __init__(self, command: Command, data: bytes):
        if len(data) > 255:
            raise ValueError(f'The data provided with command `{command.name}` exceeds maximum length of 255 bytes')

        self.command = command
        self.original_data = data

    def _byte_stuffing(self, _byte: int) -> list:
        if _byte in self.BYTES_STUFFING:
            return self.BYTES_STUFFING[_byte]
        return [_byte]

    def get_command(self) -> int:
        return self.command.code

    def get_data_len(self) -> int:
        return len(self.original_data)

    def get_checksum(self) -> int:
        return 0xFF - (sum([FRAME_SLAVE_ADR, self.get_command(), self.get_data_len()]+list(self.original_data)) % 0x100)

    def get_frame(self) -> bytes:
        return bytes(
            [FRAME_START,
             FRAME_SLAVE_ADR,
             self.get_command()
             ] + self._byte_stuffing(self.get_data_len()) +
            reduce(lambda x, y: x + y, [self._byte_stuffing(b) for b in self.original_data], []) +
            self._byte_stuffing(self.get_checksum()) +
            [FRAME_STOP]
        )

    def __repr__(self):
        return str_bytes(self.get_frame())


class MISOFrame:
    """
    Implements Master In Slave Out frame, part of SHDLC protocol.
    It is a data frame that is sent as response from SPS30 sensor (slave) to Raspberry Pi (master)
    """

    BYTES_DISEMBOWELLING = {
        MOSIFrame.BYTES_STUFFING[ori_byte][1]: ori_byte
        for ori_byte in MOSIFrame.BYTES_STUFFING
    }

    def __init__(self, bytes_received: bytes):
        self.raw_frame_bytes = bytes_received

        if self.raw_frame_bytes is None or len(self.raw_frame_bytes) == 0:
            raise ResponseFrameError(f'The sensor has not sent any data')
        if len(self.raw_frame_bytes) < 7:
            raise ResponseFrameError(f'The length of received data from the sensor '
                                     f'is unexpectedly short ({len(self.raw_frame_bytes)} bytes), '
                                     f'full frame: {str_bytes(self.raw_frame_bytes)}', self.raw_frame_bytes)
        if self.raw_frame_bytes[0] != FRAME_START:
            raise ResponseFrameError(f'The first byte is not a start-byte, expected 0x{FRAME_START:X}, '
                                     f'actual 0x{self.raw_frame_bytes[0]:X}', self.raw_frame_bytes)
        if self.raw_frame_bytes[1] != FRAME_SLAVE_ADR:
            raise ResponseFrameError(f'The second byte is not a valid slave-address, expected 0x{FRAME_SLAVE_ADR:X}, '
                                     f'actual 0x{self.raw_frame_bytes[1]:X}', self.raw_frame_bytes)
        if self.raw_frame_bytes[-1] != FRAME_STOP:
            raise ResponseFrameError(f'The last byte is not a stop-byte, expected 0x{FRAME_STOP:X}, '
                                     f'actual 0x{self.raw_frame_bytes[-1]:X}', self.raw_frame_bytes)

        self.frame_bytes = [self.raw_frame_bytes[0]]
        _i = 1
        while _i < len(self.raw_frame_bytes) - 1:
            if self.raw_frame_bytes[_i] == MOSIFrame.BYTES_DISEMBOWELLING_START:
                if self.raw_frame_bytes[_i+1] in self.BYTES_DISEMBOWELLING:
                    self.frame_bytes.append(self.BYTES_DISEMBOWELLING[self.raw_frame_bytes[_i+1]])
                else:
                    raise ResponseFrameError(f"Incorrect byte-stuffing found: "
                                             f"{str_bytes(self.raw_frame_bytes[_i:_i+2])}, "
                                             f"full frame: {str_bytes(self.raw_frame_bytes)}", self.raw_frame_bytes)
                _i += 2
            else:
                self.frame_bytes.append(self.raw_frame_bytes[_i])
                _i += 1
        self.frame_bytes.append(self.raw_frame_bytes[_i])

        self.command = {cmd.code: cmd for cmd in COMMANDS}.get(self.frame_bytes[2])
        if self.command is None:
            raise ResponseFrameError(f'The second byte is not a valid command: 0x{self.frame_bytes[2]:X}. '
                                     f'Full frame: {str_bytes(self.raw_frame_bytes)}', self.raw_frame_bytes)

        _state = self.frame_bytes[3]
        # The first bit (b7) indicates that at least one of the error flags is set in the Device Status Register
        if _state & 2 ** 7:
            raise DeviceError()

        if _state:
            raise ResponseError(_state)

        _data_length = self.frame_bytes[4]
        if not (0 <= _data_length <= 255):
            raise ResponseFrameError(f"The length of data indicated {_data_length} is out of acceptable boundaries. "
                                     f"Full frame: {str_bytes(self.raw_frame_bytes)}", self.raw_frame_bytes)
        if len(self.frame_bytes) - _data_length != 7:
            raise ResponseFrameError(f"The length of data indicated {_data_length} is incorrect, "
                                     f"expected {len(self.frame_bytes)-7}. "
                                     f"Full frame: {str_bytes(self.raw_frame_bytes)}", self.raw_frame_bytes)

        self.data = self.frame_bytes[5:5+_data_length]

        _chk = self.frame_bytes[-2]
        _act_chk = 0xFF - (sum(self.frame_bytes[1:-2]) % 0x100)
        if _chk != _act_chk:
            raise ResponseFrameError(f"Wrong checksum detected. "
                                     f"Expected 0x{_act_chk:X}, received: 0x{_chk:X}. "
                                     f"Full frame: {str_bytes(self.raw_frame_bytes)}", self.raw_frame_bytes)

    def __repr__(self):
        return str_bytes(self.raw_frame_bytes)


class CommandExecution(Thread):

    class CommandExecutionTrace:

        def __init__(self, cmd: Command):
            self._command = cmd
            self.tm_start = None
            self.tm_command_sent = None
            self.tm_reading_started = None
            self.tm_end = None

        def start(self):
            self.tm_start = datetime.now()

        def command_sent(self):
            self.tm_command_sent = datetime.now()

        def reading_started(self):
            self.tm_reading_started = datetime.now()

        def end(self):
            self.tm_end = datetime.now()

        @staticmethod
        def _log(tm: datetime, msg: str, include_timestamps: bool) -> str:
            return (f'{tm.strftime("%H:%M:%S.%f")[:-3]} ' if include_timestamps else '') + msg

        def write_duration_ms(self):
            if self.tm_command_sent is None:
                return None
            return round((self.tm_command_sent - self.tm_start).total_seconds() / 1000)

        def read_duration_ms(self):
            if self.tm_end is None:
                return None
            return round((self.tm_end - self.tm_reading_started).total_seconds() / 1000)

        def total_duration_ms(self):
            if self.tm_end is None:
                return None
            return round((self.tm_end - self.tm_start).total_seconds() / 1000)

        def collect_log(self, include_timestamps=True) -> list:
            _log = list([self._log(
                self.tm_start,
                f'Executing command 0x{self._command.code:X} {self._command.name}',
                include_timestamps
            )])
            if self.tm_command_sent is not None:
                _log.append(self._log(
                    self.tm_command_sent,
                    f'Command sent to device, write took {self.write_duration_ms()} ms',
                    include_timestamps
                ))
            if self.tm_reading_started is not None:
                _log.append(self._log(
                    self.tm_reading_started,
                    f'Reading started',
                    include_timestamps
                ))
            if self.tm_end is not None:
                _log.append(self._log(
                    self.tm_end,
                    f'Reading concluded in {self.read_duration_ms()} ms. '
                    f'Total execution duration: {self.total_duration_ms()} ms',
                    include_timestamps
                ))
            return _log

    def __init__(self, device: serial.Serial, command: Command, data: bytes):
        Thread.__init__(self)
        self._device = device
        self._command = command
        self._mosi = MOSIFrame(command, data)
        self._miso = None
        self._error = None
        self._callback_fnc = None
        self._trace = self.CommandExecutionTrace(command)

    def run(self) -> None:
        self._trace.start()
        self._prepare()
        try:
            self._device.write(self._mosi.get_frame())
        except serial.SerialTimeoutException as _x:
            self._error = DeviceCommunicationError(
                f'Timeout occurred during attempt to send command <{self._command.name}>. '
                f'Root cause: {str(_x)}'
            )
            return
        self._trace.command_sent()
        sleep(self._command.timeout_ms / 1000)
        self._trace.reading_started()
        try:
            response_data = self._device.read_all()
        except serial.SerialTimeoutException as _x:
            self._error = DeviceCommunicationError(
                f'Timeout occurred during attempt to read response on <{self._command.name}> command. '
                f'Root cause: {str(_x)}'
            )

        try:
            self._miso = MISOFrame(response_data)
            if self._callback_fnc is not None:
                self._callback_fnc(self._miso)
        except SHDLCError as _x:
            self._error = _x

        self._trace.end()

    def _prepare(self):
        pass

    def get_mosi(self) -> MOSIFrame:
        return self._mosi

    def get_command(self) -> Command:
        return self._command

    def get_miso(self) -> MISOFrame:
        self.join()
        return self._miso

    def has_succeeded(self) -> bool:
        self.join()
        return self._error is None

    def raise_error(self):
        self.join()
        if self._error is not None:
            raise self._error

    def get_trace(self) -> CommandExecutionTrace:
        return self._trace

    def register_callback(self, callback_fnc):
        if self._callback_fnc is None:
            self._callback_fnc = callback_fnc
        else:
            raise ValueError('Internal error: callback function is already registered')


class StartMeasurement(CommandExecution):
    """
    Starts the measurement. After power up, the module is in Idle-Mode. Before any measurement values can be read,
    the Measurement-Mode needs to be started using this command
    """

    def __init__(self, device: serial.Serial):
        CommandExecution.__init__(self, device, CMD_START, bytes([0x01, 0x05]))


class StopMeasurement(CommandExecution):
    """
    Stops the measurement. Use this command to return to the initial state (Idle-Mode).
    """

    def __init__(self, device: serial.Serial):
        CommandExecution.__init__(self, device, CMD_STOP, bytes())


class ReadMeasuredValues(CommandExecution):
    """
    Reads the measured values from the module. This command can be used to poll for new measurement values.
    The measurement interval is 1 second.
    """

    def __init__(self, device: serial.Serial):
        CommandExecution.__init__(self, device, CMD_MEASURE, bytes())


class Sleep(CommandExecution):
    """
    Enters the Sleep-Mode with minimum power consumption. This will also deactivate the UART interface,
    note the wakeup sequence described at the Wake-up command.
    """

    def __init__(self, device: serial.Serial):
        CommandExecution.__init__(self, device, CMD_SLEEP, bytes())


class WakeUp(CommandExecution):
    """
    Use this command to switch from Sleep-Mode to Idle-Mode. In Sleep-Mode the UART interface is disabled and must first
    be activated by sending a low pulse on the RX pin. This pulse is generated by sending a single byte with
    the value 0xFF.
    If then a Wake-up command follows within 100ms, the module will switch on again and is ready for further commands
    in the Idle-Mode. If the low pulse is not followed by the Wake-up command, the microcontroller returns to Sleep-Mode
    after 100ms and the interface is deactivated again.
    The Wake-up command can be sent directly after the 0xFF, without any delay. However, it is important that no other
    value than 0xFF is used to generate the low pulse, otherwise it’s not guaranteed the UART interface synchronize
    correctly.
    """

    def __init__(self, device: serial.Serial):
        CommandExecution.__init__(self, device, CMD_WAKEUP, bytes())

    def _prepare(self) -> None:
        self._device.write(bytes([0xFF]))


class StartFanCleaning(CommandExecution):
    """
    Starts the fan-cleaning manually
    """

    def __init__(self, device: serial.Serial):
        CommandExecution.__init__(self, device, CMD_CLEAN, bytes())


class ReadAutoCleaningInterval(CommandExecution):
    """
    Reads the interval [s] of the periodic fan-cleaning
    """

    def __init__(self, device: serial.Serial):
        CommandExecution.__init__(self, device, CMD_SET_AUTO_CLEAN, bytes([0x00]))


class WriteAutoCleaningInterval(CommandExecution):
    """
    Writes the interval [s] of the periodic fan-cleaning
    """

    def __init__(self, device: serial.Serial, ac_interval_s: int):
        if ac_interval_s <= 0 or ac_interval_s >= 2 ^ 32:
            raise ConfigurationError(f"Ato cleaning interval {ac_interval_s} is out of acceptable bounds "
                                     f"(should be unsigned 32-bit int)")

        CommandExecution.__init__(self, device, CMD_SET_AUTO_CLEAN,
                                  bytes([0x00])+ac_interval_s.to_bytes(4, byteorder='big'))


class DeviceInformationProductType(CommandExecution):
    """
    This command returns the requested device information. It is defined as a string value with a maximum length of
    32 ASCII characters (including terminating null character).
    """

    def __init__(self, device: serial.Serial):
        CommandExecution.__init__(self, device, CMD_INFO, bytes([0x00]))


class DeviceInformationSerialNumber(CommandExecution):
    """
    This command returns the requested device information. It is defined as a string value with a maximum length of
    32 ASCII characters (including terminating null character).
    """

    def __init__(self, device: serial.Serial):
        CommandExecution.__init__(self, device, CMD_INFO, bytes([0x03]))


class ReadVersion(CommandExecution):
    """
    Gets version information about the firmware, hardware, and SHDLC protocol.
    """

    def __init__(self, device: serial.Serial):
        CommandExecution.__init__(self, device, CMD_VERSION, bytes())


class ReadDeviceStatusRegister(CommandExecution):
    """
    Use this command to read the Device Status Register.
    Note: If one of the device status flags of type “Error” is set, this is also indicated in every SHDLC response frame
    by the Error-Flag in the state byte.
    """

    def __init__(self, device: serial.Serial):
        CommandExecution.__init__(self, device, CMD_STATUS, bytes())


class DeviceReset(CommandExecution):
    """
    Soft reset command. After calling this command, the module is in the same state as after a Power-Reset. The reset is
    executed after sending the MISO response frame.
    Note: To perform a reset when the sensor is in sleep mode, it is required to send first a wake-up sequence to
    activate the interface
    """

    def __init__(self, device: serial.Serial):
        CommandExecution.__init__(self, device, CMD_RESET, bytes())


class ParticulateMatterSensor:
    READ_TIMEOUT_MS = 1000
    WRITE_TIMEOUT_MS = 1000

    def __init__(self):
        try:
            self.device = serial.Serial(
                port="/dev/ttyAMA0",
                baudrate=115200,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,  # number of data bits
                exclusive=True,  # port cannot be opened in exclusive access mode if it is already open in this mode
                timeout=ParticulateMatterSensor.READ_TIMEOUT_MS / 1000,
                write_timeout=ParticulateMatterSensor.WRITE_TIMEOUT_MS / 1000
            )
        except serial.SerialException as _x:
            raise DeviceCommunicationError(f"The UART port cannot be initialized. Root cause: {str(_x)}")
        except ValueError as _x:
            raise ConfigurationError(f"Parameter out of range. Root cause: {str(_x)}")

    def _active_device(self) -> serial.Serial:
        if not self.device.is_open:
            self.device.open()
        return self.device

    def _handle_action(self, action: CommandExecution, callback_fnc) -> CommandExecution:
        if callback_fnc is not None:
            action.register_callback(callback_fnc)

        action.start()

        if callback_fnc is None:
            action.join()
            action.raise_error()  # this will detect error of communication and raise appropriate exception

        return action

    def start_measurement(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=StartMeasurement(device=self._active_device()),
            callback_fnc=callback_fnc
        )

    def stop_measurement(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=StopMeasurement(device=self._active_device()),
            callback_fnc=callback_fnc
        )

    def read_measured_values(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=ReadMeasuredValues(device=self._active_device()),
            callback_fnc=callback_fnc
        )

    def sleep(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=Sleep(device=self._active_device()),
            callback_fnc=callback_fnc
        )

    def wake_up(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=WakeUp(device=self._active_device()),
            callback_fnc=callback_fnc
        )

    def start_fan_cleaning(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=StartFanCleaning(device=self._active_device()),
            callback_fnc=callback_fnc
        )

    def get_auto_cleaning_interval(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=ReadAutoCleaningInterval(device=self._active_device()),
            callback_fnc=callback_fnc
        )

    def set_auto_cleaning_interval(self, interval_s: int, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=WriteAutoCleaningInterval(device=self._active_device(), ac_interval_s=interval_s),
            callback_fnc=callback_fnc
        )

    def get_product_type(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=DeviceInformationProductType(device=self._active_device()),
            callback_fnc=callback_fnc
        )

    def get_serial_number(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=DeviceInformationSerialNumber(device=self._active_device()),
            callback_fnc=callback_fnc
        )

    def get_version(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=ReadVersion(device=self._active_device()),
            callback_fnc=callback_fnc
        )

    def get_status(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=ReadDeviceStatusRegister(device=self._active_device()),
            callback_fnc=callback_fnc
        )

    def reset(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=DeviceReset(device=self._active_device()),
            callback_fnc=callback_fnc
        )


if __name__ == "__main__":
    sensor = ParticulateMatterSensor()
    sensor.read_measured_values()
