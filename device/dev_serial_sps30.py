# https://sensirion.com/media/documents/8600FF88/64A3B8D6/Sensirion_PM_Sensors_Datasheet_SPS30.pdf
# https://github.com/Sensirion/embedded-uart-sps/tree/master/sps30-uart
# all bytes big-endian

import serial

from collections import namedtuple, deque
from functools import reduce
from threading import Thread, Event, Lock
from datetime import datetime, timedelta
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

    def __init__(self, msg: str, data: bytes):
        SHDLCError.__init__(self, f'The received frame has incorrect structure or signalizes an error. {msg}. '
                                  f'Frame content: {str_bytes(data)}')
        self.original_bytes_received: bytes = data


class NoDataInResponse(ResponseFrameError):

    def __init__(self):
        ResponseFrameError.__init__(
            self,
            f"No data received from the sensor. Maybe it is put to sleep? "
            f"This may also be caused by not connected or wrongly connected hardware. "
            f"Check if TX\\RX are cross-connected (i.e. TX of RPi goes to RX of the sensor)",
            bytes()
        )


class DeviceError(SHDLCError):

    def __init__(self):
        SHDLCError.__init__(self, f'Device error was reported. Query for Device Status Register for details')


class DeviceCommunicationError(SHDLCError):

    def __init__(self, msg):
        SHDLCError.__init__(self, f'There was a problem with communicating with the device. {msg}')


class ResponseError(ResponseFrameError):

    def __init__(self, error_code: int, data: bytes, msg=None):
        self.error_code = error_code
        self.error = ERRORS[error_code] if error_code in ERRORS else "Unknown error"
        ResponseFrameError.__init__(
            self,
            f'The device responded with the following error code: 0x{error_code:X} ({self.error})'
            if msg is None else msg,
            data
        )


class CommandNotAllowed(SHDLCError):

    def __init__(self, data: bytes):
        self.original_bytes_received: bytes = data
        SHDLCError.__init__(
            self,
            f"The command is not allowed in current state. "
            f"Make sure the sequence of commands ensures correct internal state of the sensor"
        )


class CommandNotSupported(SHDLCError):

    def __init__(self, command: Command, firmware_version: tuple):
        SHDLCError.__init__(
            self,
            f"Your sensor do not allow to run the command 0x{command.code:02X} {command.name}. "
            f"Your firmware version is {firmware_version[0]}.{firmware_version[1]}, "
            f"whereas the minimal required version is {command.min_version[0]}.{command.min_version[1]}"
        )


class ConfigurationError(SHDLCError):

    def __init__(self, msg: str):
        SHDLCError.__init__(self, f'The used parameter is incorrect. {msg}')


class NoNewMeasurement(SHDLCError):

    def __init__(self):
        SHDLCError.__init__(self, f"The sensor insists there are no new measurements at the moment. "
                                  f"The reason is either too short period between subsequent measurements or "
                                  f"incorrect device state (measurement not started). "
                                  f"Ensure both reasons are checked and try again")


class ResponseCorrupted(ResponseFrameError):

    def __init__(self, msg: str, data: bytes):
        ResponseFrameError.__init__(self, msg, data)


Measurement = namedtuple('Measurement', [
    'mass_concentration_pm_1_0_ug_m3',
    'mass_concentration_pm_2_5_ug_m3',
    'mass_concentration_pm_4_0_ug_m3',
    'mass_concentration_pm_10_ug_m3',
    'number_concentration_pm_0_5_per_cm3',
    'number_concentration_pm_1_0_per_cm3',
    'number_concentration_pm_2_5_per_cm3',
    'number_concentration_pm_4_0_per_cm3',
    'number_concentration_pm_10_per_cm3',
    'typical_particle_size_um',
    'timestamp'
])

AutoCleanInterval = namedtuple('AutoCleanInterval', ['interval_s'])

DeviceInfo = namedtuple('DeviceInformation', ['info'])

Versions = namedtuple('Version', ['firmware', 'hardware', 'protocol'])

DeviceStatus = namedtuple('DeviceStatus', ['speed_warning', 'laser_error', 'fan_error', 'register'])

BYTES_STUFFING_START_BYTE = 0x7D
BYTES_STUFFING_MAP = {
    0x7E: [BYTES_STUFFING_START_BYTE, 0x5E],
    0x7D: [BYTES_STUFFING_START_BYTE, 0x5D],
    0x11: [BYTES_STUFFING_START_BYTE, 0x31],
    0x13: [BYTES_STUFFING_START_BYTE, 0x33],
}
BYTES_UNSTUFFING_MAP = {
    BYTES_STUFFING_MAP[ori_byte][1]: ori_byte
    for ori_byte in BYTES_STUFFING_MAP
}


def stuffing(data: bytes) -> list:
    return reduce(
        lambda x, y: x + y,
        [BYTES_STUFFING_MAP[b] if b in BYTES_STUFFING_MAP else [b] for b in data],
        []
    )


def unstuffing(data: bytes) -> list:
    return [
        c if p != BYTES_STUFFING_START_BYTE else BYTES_UNSTUFFING_MAP[c]
        for c, p in zip(list(data), [None]+list(data)[:-1])
        if c != BYTES_STUFFING_START_BYTE
    ]


def checksum(data) -> int:
    return 0xFF - (sum(data) % 0x100)


def str_bytes(content: bytes):
    return "|".join([f"0x{_b:02X}" for _b in content])


class MOSIFrame:
    """
    Implements Master Out Slave In frame, part of SHDLC protocol.
    It represents the command sent from master (RPi) to the SPS30 sensor.
    """

    def __init__(self, command: Command, data: bytes):
        if len(data) > 255:
            raise ValueError(f'The data provided with command `{command.name}` exceeds maximum length of 255 bytes')

        self.command = command
        self.original_data = data

    def get_command(self) -> int:
        return self.command.code

    def get_data_len(self) -> int:
        return len(self.original_data)

    def get_checksum(self) -> int:
        return checksum([FRAME_SLAVE_ADR, self.get_command(), self.get_data_len()]+list(self.original_data))

    def get_frame(self) -> bytes:
        return bytes(
            [FRAME_START,
             FRAME_SLAVE_ADR,
             self.get_command()
             ] + stuffing(bytes([self.get_data_len()])) +
            stuffing(self.original_data) +
            stuffing(bytes([self.get_checksum()])) +
            [FRAME_STOP]
        )

    def __repr__(self):
        return str_bytes(self.get_frame())


class MISOFrame:
    """
    Implements Master In Slave Out frame, part of SHDLC protocol.
    It is a data frame that is sent as response from SPS30 sensor (slave) to Raspberry Pi (master)
    """

    def __init__(self, bytes_received: bytes):
        self.raw_frame_bytes = bytes_received
        self.timestamp = datetime.now()

        if self.raw_frame_bytes is None or len(self.raw_frame_bytes) == 0:
            raise NoDataInResponse()
        if len(self.raw_frame_bytes) < 7:
            raise ResponseFrameError(f'The length of received data from the sensor '
                                     f'is unexpectedly short ({len(self.raw_frame_bytes)} bytes)', self.raw_frame_bytes)
        if self.raw_frame_bytes[0] != FRAME_START:
            raise ResponseFrameError(f'The first byte is not a start-byte, expected 0x{FRAME_START:X}, '
                                     f'actual 0x{self.raw_frame_bytes[0]:X}', self.raw_frame_bytes)
        if self.raw_frame_bytes[1] != FRAME_SLAVE_ADR:
            raise ResponseFrameError(f'The second byte is not a valid slave-address, expected 0x{FRAME_SLAVE_ADR:X}, '
                                     f'actual 0x{self.raw_frame_bytes[1]:X}', self.raw_frame_bytes)
        if self.raw_frame_bytes[-1] != FRAME_STOP:
            raise ResponseFrameError(f'The last byte is not a stop-byte, expected 0x{FRAME_STOP:X}, '
                                     f'actual 0x{self.raw_frame_bytes[-1]:X}', self.raw_frame_bytes)

        try:
            self.frame_bytes = bytes(
                [self.raw_frame_bytes[0]] +
                unstuffing(self.raw_frame_bytes[1:-1]) +
                [self.raw_frame_bytes[-1]]
            )
        except KeyError:
            raise ResponseFrameError(f"Incorrect byte-stuffing found: "
                                     f"{str_bytes(self.raw_frame_bytes[1:-1])}",
                                     self.raw_frame_bytes)

        self.command = {cmd.code: cmd for cmd in COMMANDS}.get(self.frame_bytes[2])
        if self.command is None:
            raise ResponseFrameError(f'The second byte is not a valid command: 0x{self.frame_bytes[2]:X}',
                                     self.raw_frame_bytes)

        _state = self.frame_bytes[3]
        # The first bit (b7) indicates that at least one of the error flags is set in the Device Status Register
        if _state & 2 ** 7:
            if self.command not in (CMD_STATUS, CMD_VERSION, CMD_INFO, CMD_SLEEP, CMD_WAKEUP):
                raise DeviceError()
            # clear the error flag and proceed
            _state = _state & (2 ** 7 - 1)

        if _state:
            raise ResponseError(_state, self.raw_frame_bytes) if _state != 0x43 else \
                CommandNotAllowed(self.raw_frame_bytes)

        _data_length = self.frame_bytes[4]
        if not (0 <= _data_length <= 255):
            raise ResponseFrameError(f"The length of data indicated {_data_length} is out of acceptable boundaries",
                                     self.raw_frame_bytes)
        if len(self.frame_bytes) - _data_length != 7:
            raise ResponseFrameError(f"The length of data indicated {_data_length} is incorrect, "
                                     f"expected {len(self.frame_bytes)-7}",
                                     self.raw_frame_bytes)

        self.data = bytes(self.frame_bytes[5:5+_data_length])

        _chk = self.frame_bytes[-2]
        _act_chk = checksum(self.frame_bytes[1:-2])
        if _chk != _act_chk:
            raise ResponseFrameError(f"Wrong checksum detected. "
                                     f"Expected 0x{_act_chk:X}, received: 0x{_chk:X}",
                                     self.raw_frame_bytes)

    def __repr__(self):
        return str_bytes(self.raw_frame_bytes)

    def interpret_data(self) -> namedtuple:
        if self.command == CMD_START:
            return {}
        if self.command == CMD_STOP:
            return {}
        if self.command == CMD_MEASURE:
            if len(self.data) == 0:
                raise NoNewMeasurement()
            if len(self.data) != 20:
                raise ResponseCorrupted(f"It is expected that executing 0x{self.command.code:02X} {self.command.name} "
                                        f"will provide 20-bytes length result whereas {len(self.data)} bytes was found",
                                        self.data)

            return Measurement(
                mass_concentration_pm_1_0_ug_m3=int.from_bytes(self.data[0:2], byteorder="big"),
                mass_concentration_pm_2_5_ug_m3=int.from_bytes(self.data[2:4], byteorder="big"),
                mass_concentration_pm_4_0_ug_m3=int.from_bytes(self.data[4:6], byteorder="big"),
                mass_concentration_pm_10_ug_m3=int.from_bytes(self.data[6:8], byteorder="big"),
                number_concentration_pm_0_5_per_cm3=int.from_bytes(self.data[8:10], byteorder="big"),
                number_concentration_pm_1_0_per_cm3=int.from_bytes(self.data[10:12], byteorder="big"),
                number_concentration_pm_2_5_per_cm3=int.from_bytes(self.data[12:14], byteorder="big"),
                number_concentration_pm_4_0_per_cm3=int.from_bytes(self.data[14:16], byteorder="big"),
                number_concentration_pm_10_per_cm3=int.from_bytes(self.data[16:18], byteorder="big"),
                typical_particle_size_um=int.from_bytes(self.data[18:], byteorder="big"),
                timestamp=self.timestamp,
            )
        if self.command == CMD_SLEEP:
            return {}
        if self.command == CMD_WAKEUP:
            return {}
        if self.command == CMD_CLEAN:
            return {}
        if self.command == CMD_SET_AUTO_CLEAN:
            # to interpret result of this command, the length of the data received is checked
            # this is to distinguish the response on SET from GET - it is not possible to
            # determine it otherwise as the command code is exactly the same
            if len(self.data) == 0:  # SET
                return {}
            # GET
            if len(self.data) != 4:
                raise ResponseCorrupted(f"It is expected that executing 0x{self.command.code:02X} {self.command.name} "
                                        f"will provide 4-bytes length result whereas {len(self.data)} bytes was found",
                                        self.data)
            return AutoCleanInterval(interval_s=int.from_bytes(self.data, byteorder="big"))
        if self.command == CMD_INFO:
            if len(self.data) > 32 or len(self.data) < 2:
                raise ResponseCorrupted(f"It is expected that executing 0x{self.command.code:02X} {self.command.name} "
                                        f"will provide up to 31 ASCII characters whereas {len(self.data)} "
                                        f"bytes was found",
                                        self.data)
            return DeviceInfo(info=self.data[:-1].decode("ascii"))
        if self.command == CMD_VERSION:
            if len(self.data) != 7:
                raise ResponseCorrupted(f"It is expected that executing 0x{self.command.code:02X} {self.command.name} "
                                        f"will provide 7-bytes length result whereas {len(self.data)} bytes was found",
                                        self.data)
            return Versions(
                firmware=(int.from_bytes(self.data[0:1], byteorder="big"),
                          int.from_bytes(self.data[1:2], byteorder="big")),
                hardware=int.from_bytes(self.data[3:4], byteorder="big"),
                protocol=(int.from_bytes(self.data[5:6], byteorder="big"),
                          int.from_bytes(self.data[6:], byteorder="big"))
            )
        if self.command == CMD_STATUS:
            if len(self.data) != 5:
                raise ResponseCorrupted(f"It is expected that executing 0x{self.command.code:02X} {self.command.name} "
                                        f"will provide 5-bytes length response whereas {len(self.data)} bytes was found",
                                        self.data)
            register = int.from_bytes(self.data[0:4], byteorder="big")
            return DeviceStatus(
                speed_warning=(register & (2 ** 21)) > 0,
                laser_error=(register & (2 ** 5)) > 0,
                fan_error=(register & (2 ** 4)) > 0,
                register=f"{register:b}"
            )
        if self.command == CMD_RESET:
            return {}

        raise NotImplementedError(f"The command 0x{self.command.code:02X} {self.command.name} is not supported")


class CommandExecution(Thread):

    class CommandExecutionTrace:

        def __init__(self, cmd: Command):
            self._command = cmd
            self.tm_start = None
            self.tm_command_sent = None
            self.tm_reading_started = None
            self.tm_end = None

        def mark_start(self):
            self.tm_start = datetime.now()

        def mark_command_sent(self):
            self.tm_command_sent = datetime.now()

        def mark_reading_started(self):
            self.tm_reading_started = datetime.now()

        def mark_end(self):
            self.tm_end = datetime.now()

        @staticmethod
        def _log(tm: datetime, msg: str, include_timestamps: bool) -> str:
            return (f'{tm.strftime("%H:%M:%S.%f")[:-3]} ' if include_timestamps else '') + msg

        def write_duration_ms(self):
            if self.tm_command_sent is None:
                return None
            return round((self.tm_command_sent - self.tm_start).total_seconds() * 1000)

        def read_duration_ms(self):
            if self.tm_end is None:
                return None
            return round((self.tm_end - self.tm_reading_started).total_seconds() * 1000)

        def total_duration_ms(self):
            if self.tm_end is None:
                return None
            return round((self.tm_end - self.tm_start).total_seconds() * 1000)

        def collect_log(self, include_timestamps=True) -> list:
            _log = list([self._log(
                self.tm_start,
                f'Executing command 0x{self._command.code:02X} {self._command.name}',
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

    def __init__(self, device: serial.Serial, device_lock: Lock, command: Command, data: bytes):
        Thread.__init__(self, name=f"Command 0x{command.code:02X} {command.name} execution")
        self._device = device
        self._device_lock = device_lock
        self._command = command
        self._mosi = MOSIFrame(command, data)
        self._miso = None
        self._error = None
        self._callback_fnc = None
        self._trace = self.CommandExecutionTrace(command)

    def run(self) -> None:
        self._trace.mark_start()
        self._device_lock.acquire()
        self._prepare()
        try:
            self._device.write(self._mosi.get_frame())
        except serial.SerialTimeoutException as _x:
            self._error = DeviceCommunicationError(
                f'Timeout occurred during attempt to send command <{self._command.name}>. '
                f'Root cause: {str(_x)}'
            )
            return
        self._trace.mark_command_sent()
        sleep(self._command.timeout_ms / 1000)
        self._trace.mark_reading_started()
        try:
            response_data = self._device.read_all()
            try:
                self._miso = MISOFrame(response_data)
                if self._callback_fnc is not None:
                    self._callback_fnc(self._miso)
            except SHDLCError as _x:
                self._error = _x
        except serial.SerialTimeoutException as _x:
            self._error = DeviceCommunicationError(
                f'Timeout occurred during attempt to read response on <{self._command.name}> command. '
                f'Root cause: {str(_x)}'
            )
        self._device_lock.release()
        self._trace.mark_end()

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

    def __init__(self, device: serial.Serial, device_lock: Lock):
        CommandExecution.__init__(self, device=device, device_lock=device_lock,
                                  command=CMD_START, data=bytes([0x01, 0x05]))


class StopMeasurement(CommandExecution):
    """
    Stops the measurement. Use this command to return to the initial state (Idle-Mode).
    """

    def __init__(self, device: serial.Serial, device_lock: Lock):
        CommandExecution.__init__(self, device=device, device_lock=device_lock, command=CMD_STOP, data=bytes())


class ReadMeasuredValues(CommandExecution):
    """
    Reads the measured values from the module. This command can be used to poll for new measurement values.
    The measurement interval is 1 second.
    """

    def __init__(self, device: serial.Serial, device_lock: Lock):
        CommandExecution.__init__(self, device=device, device_lock=device_lock, command=CMD_MEASURE, data=bytes())


class Sleep(CommandExecution):
    """
    Enters the Sleep-Mode with minimum power consumption. This will also deactivate the UART interface,
    note the wakeup sequence described at the Wake-up command.
    """

    def __init__(self, device: serial.Serial, device_lock: Lock):
        CommandExecution.__init__(self, device=device, device_lock=device_lock, command=CMD_SLEEP, data=bytes())


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

    def __init__(self, device: serial.Serial, device_lock: Lock):
        CommandExecution.__init__(self, device=device, device_lock=device_lock, command=CMD_WAKEUP, data=bytes())

    def _prepare(self) -> None:
        self._device.write(bytes([0xFF]))


class StartFanCleaning(CommandExecution):
    """
    Starts the fan-cleaning manually
    """

    def __init__(self, device: serial.Serial, device_lock: Lock):
        CommandExecution.__init__(self, device=device, device_lock=device_lock, command=CMD_CLEAN, data=bytes())


class ReadAutoCleaningInterval(CommandExecution):
    """
    Reads the interval [s] of the periodic fan-cleaning
    """

    def __init__(self, device: serial.Serial, device_lock: Lock):
        CommandExecution.__init__(self, device=device, device_lock=device_lock,
                                  command=CMD_SET_AUTO_CLEAN, data=bytes([0x00]))


class WriteAutoCleaningInterval(CommandExecution):
    """
    Writes the interval [s] of the periodic fan-cleaning
    """

    def __init__(self, device: serial.Serial, device_lock: Lock, ac_interval_s: int):
        if ac_interval_s <= 0 or ac_interval_s >= 2 ^ 32:
            raise ConfigurationError(f"Auto cleaning interval {ac_interval_s} is out of the acceptable bounds "
                                     f"(should be an unsigned 32-bit int)")

        CommandExecution.__init__(self, device=device, device_lock=device_lock, command=CMD_SET_AUTO_CLEAN,
                                  data=bytes([0x00])+ac_interval_s.to_bytes(4, byteorder='big'))


class DeviceInformationProductType(CommandExecution):
    """
    This command returns the requested device information. It is defined as a string value with a maximum length of
    32 ASCII characters (including terminating null character).
    """

    def __init__(self, device: serial.Serial, device_lock: Lock):
        CommandExecution.__init__(self, device=device, device_lock=device_lock, command=CMD_INFO, data=bytes([0x00]))


class DeviceInformationSerialNumber(CommandExecution):
    """
    This command returns the requested device information. It is defined as a string value with a maximum length of
    32 ASCII characters (including terminating null character).
    """

    def __init__(self, device: serial.Serial, device_lock: Lock):
        CommandExecution.__init__(self, device=device, device_lock=device_lock, command=CMD_INFO, data=bytes([0x03]))


class ReadVersion(CommandExecution):
    """
    Gets version information about the firmware, hardware, and SHDLC protocol.
    """

    def __init__(self, device: serial.Serial, device_lock: Lock):
        CommandExecution.__init__(self, device=device, device_lock=device_lock, command=CMD_VERSION, data=bytes())


class ReadDeviceStatusRegister(CommandExecution):
    """
    Use this command to read the Device Status Register.
    Note: If one of the device status flags of type “Error” is set, this is also indicated in every SHDLC response frame
    by the Error-Flag in the state byte.
    """

    def __init__(self, device: serial.Serial, device_lock: Lock, clear_after_reading=False):
        CommandExecution.__init__(self, device=device, device_lock=device_lock,
                                  command=CMD_STATUS, data=bytes([0x01 if clear_after_reading else 0x00]))


class DeviceReset(CommandExecution):
    """
    Soft reset command. After calling this command, the module is in the same state as after a Power-Reset. The reset is
    executed after sending the MISO response frame.
    Note: To perform a reset when the sensor is in sleep mode, it is required to send first a wake-up sequence to
    activate the interface
    """

    def __init__(self, device: serial.Serial, device_lock: Lock):
        CommandExecution.__init__(self, device=device, device_lock=device_lock, command=CMD_RESET, data=bytes())


class SensirionSPS30:
    READ_TIMEOUT_MS = 1000
    WRITE_TIMEOUT_MS = 1000

    def __init__(self, port="/dev/ttyAMA0", _device=None):
        try:
            self._device = serial.Serial(
                port=port,
                baudrate=115200,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,  # number of data bits
                exclusive=True,  # port cannot be opened in exclusive access mode if it is already open in this mode
                timeout=SensirionSPS30.READ_TIMEOUT_MS / 1000,
                write_timeout=SensirionSPS30.WRITE_TIMEOUT_MS / 1000
            ) if _device is None else _device
        except serial.SerialException as _x:
            raise DeviceCommunicationError(f"The UART port cannot be initialized. Root cause: {str(_x)}")
        except ValueError as _x:
            raise ConfigurationError(f"Parameter out of range. Root cause: {str(_x)}")
        self._device_lock = Lock()

    def _active_device(self) -> serial.Serial:
        if not self._device.is_open:
            self._device.open()
        return self._device

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
            action=StartMeasurement(device=self._active_device(), device_lock=self._device_lock),
            callback_fnc=callback_fnc
        )

    def stop_measurement(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=StopMeasurement(device=self._active_device(), device_lock=self._device_lock),
            callback_fnc=callback_fnc
        )

    def read_measured_values(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=ReadMeasuredValues(device=self._active_device(), device_lock=self._device_lock),
            callback_fnc=callback_fnc
        )

    def sleep(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=Sleep(device=self._active_device(), device_lock=self._device_lock),
            callback_fnc=callback_fnc
        )

    def wake_up(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=WakeUp(device=self._active_device(), device_lock=self._device_lock),
            callback_fnc=callback_fnc
        )

    def start_fan_cleaning(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=StartFanCleaning(device=self._active_device(), device_lock=self._device_lock),
            callback_fnc=callback_fnc
        )

    def get_auto_cleaning_interval(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=ReadAutoCleaningInterval(device=self._active_device(), device_lock=self._device_lock),
            callback_fnc=callback_fnc
        )

    def set_auto_cleaning_interval(self, interval_s: int, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=WriteAutoCleaningInterval(device=self._active_device(), ac_interval_s=interval_s,
                                             device_lock=self._device_lock),
            callback_fnc=callback_fnc
        )

    def get_product_type(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=DeviceInformationProductType(device=self._active_device(), device_lock=self._device_lock),
            callback_fnc=callback_fnc
        )

    def get_serial_number(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=DeviceInformationSerialNumber(device=self._active_device(), device_lock=self._device_lock),
            callback_fnc=callback_fnc
        )

    def get_version(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=ReadVersion(device=self._active_device(), device_lock=self._device_lock),
            callback_fnc=callback_fnc
        )

    def get_status(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=ReadDeviceStatusRegister(device=self._active_device(), device_lock=self._device_lock),
            callback_fnc=callback_fnc
        )

    def reset(self, callback_fnc=None) -> CommandExecution:
        return self._handle_action(
            action=DeviceReset(device=self._active_device(), device_lock=self._device_lock),
            callback_fnc=callback_fnc
        )


class _ContinuousMeasurement(Thread):

    def __init__(self, the_sensor, results: deque, exit_event: Event, measurements_count: int, duration: timedelta):
        Thread.__init__(self, name="Continuous Measurement")
        self._the_sensor = the_sensor
        self._results = results
        self._exit_event = exit_event
        self._measurements_count = measurements_count
        self._duration = duration

    def run(self):
        _start = datetime.now()
        while not self._exit_event.is_set():
            _measurement_start = datetime.now()
            try:
                self._results.append(self._the_sensor.measure())
            except SHDLCError as _x:
                self._results.append(_x)

            self._measurements_count -= 1
            if self._measurements_count <= 0 or (datetime.now() - _start) >= self._duration:
                break

            self._exit_event.wait(timeout=1-(datetime.now() - _measurement_start).total_seconds())

    def interrupt(self):
        self._exit_event.set()


class ParticulateMatterMeter:

    def __init__(self, port="/dev/ttyAMA0", _device=None):
        self._sensor = SensirionSPS30(port=port, _device=_device)
        self._versions: Versions = None
        self._serial_number: str = None
        self._continuous_measurement_thread: _ContinuousMeasurement = None

    def __del__(self):
        # if the continous measurement is up, stop it
        if self._continuous_measurement_thread is not None and self._continuous_measurement_thread.is_alive():
            self.interrupt_continuous_measurement()

        # try to put the sensor to sleep
        try:
            self.sleep()
        except SHDLCError:
            # silently ignore if unsuccessful
            pass

    def _ensure_idle(self):
        try:
            self._sensor.wake_up()
        except CommandNotAllowed:
            # measurement mode, stop it
            self._sensor.stop_measurement()

    def _get_versions(self) -> Versions:
        """
        Provides cached values of:
        - firmware version as tuple (major, minor)
        - hardware revision as single number
        - protocol version  as tuple (major, minor)
        :return: namedtuple Versions
        """
        if self._versions is None:
            try:
                self._versions = self._sensor.get_version().get_miso().interpret_data()
            except NoDataInResponse:
                # sleep mode, wake the sensor up
                self._sensor.wake_up()
                self._versions = self._sensor.get_version().get_miso().interpret_data()
        return self._versions

    def _validate_command(self, command: Command):
        if self.get_firmware_ver() < command.min_version:
            raise CommandNotSupported(
                command=command,
                firmware_version=self.get_firmware_ver()
            )

    def get_firmware_ver(self) -> tuple:
        return self._get_versions().firmware

    def get_protocol_ver(self) -> tuple:
        return self._get_versions().protocol

    def get_hardware_rev(self) -> int:
        return self._get_versions().hardware

    def get_serial_number(self) -> str:
        if self._serial_number is None:
            self._validate_command(CMD_INFO)
            self._serial_number = self._sensor.get_serial_number().get_miso().interpret_data().info
        return self._serial_number

    def sleep(self):
        self._validate_command(CMD_SLEEP)
        try:
            self._sensor.sleep()
        except CommandNotAllowed:
            self._validate_command(CMD_STOP)
            self._sensor.stop_measurement()
            self.sleep()

    def measure(self) -> Measurement:
        self._validate_command(CMD_MEASURE)
        try:
            m = self._sensor.read_measured_values().get_miso().interpret_data()
        except NoDataInResponse:
            #  most likely the sensor is put into sleep mode, wake it up
            self._validate_command(CMD_WAKEUP)
            self._sensor.wake_up()
            m = self.measure()
        except NoNewMeasurement as _x:
            # check if the measurement is not started
            self._validate_command(CMD_START)
            try:
                self._sensor.start_measurement()
            except CommandNotAllowed:
                # no, the measurement is up and running; simply there are no new measurements available
                raise _x
            m = self._sensor.read_measured_values().get_miso().interpret_data()
        return m

    def continuous_measurement(self, results: deque, exit_event: Event = None, max_measurements=0, duration=0):
        if self._continuous_measurement_thread is not None and self._continuous_measurement_thread.is_alive():
            raise ValueError(f"The continuous measurement is already running at the moment")
        if results is None:
            raise ValueError(f"The measurement cannot be start without having object receiving results")
        if exit_event is None:
            exit_event = Event()
        if max_measurements is None or max_measurements <= 0:
            max_measurements = 2 ** 31 - 2
        if duration is None:
            duration = 0
        if isinstance(duration, int):
            if duration <= 0:
                duration = timedelta(seconds=max_measurements+1)
            else:
                duration = timedelta(seconds=duration)
        if not isinstance(duration, timedelta):
            raise ValueError(f"The duration is expected to be either number of seconds or timedelta object, "
                             f"got `{duration}`")

        self._continuous_measurement_thread = _ContinuousMeasurement(
            the_sensor=self,
            results=results,
            exit_event=exit_event,
            measurements_count=max_measurements,
            duration=duration
        )

        self._continuous_measurement_thread.start()

    def interrupt_continuous_measurement(self):
        if self._continuous_measurement_thread is None:
            raise ValueError(f"The continuous measurement can not be interrupted as it was not started")

        if self._continuous_measurement_thread.is_alive():
            self._continuous_measurement_thread.interrupt()
            self._continuous_measurement_thread.join()


if __name__ == "__main__":
    sensor = SensirionSPS30()
    sensor.read_measured_values()
