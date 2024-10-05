# https://sensirion.com/media/documents/8600FF88/64A3B8D6/Sensirion_PM_Sensors_Datasheet_SPS30.pdf
# https://github.com/Sensirion/embedded-uart-sps/tree/master/sps30-uart
# all bytes big-endian

import serial

from collections import namedtuple
from functools import reduce
from threading import Thread

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

    def __init__(self, msg: str):
        SHDLCError.__init__(self, f'The received frame has incorrect structure or content. {msg}')


class DeviceError(SHDLCError):

    def __init__(self):
        SHDLCError.__init__(self, f'Device error was reported. Query for Device Status Register for details')


class ResponseError(SHDLCError):

    def __init__(self, error_code: int):
        self.error_code = error_code
        self.error = ERRORS[error_code] if error_code in ERRORS else "Unknown error"
        SHDLCError.__init__(self, f'The device responded with '
                                  f'the following error code: 0x{error_code:X} ({self.error})')


class ConfigurationError(SHDLCError):

    def __init__(self, msg: str):
        SHDLCError.__init__(self, f'The used parameter is incorrect. {msg}')


class MOSIFrame:
    """
    Implements Master Out Slave In frame, part of SHDLC protocol.
    It represents the command sent from master (RPi) to the SPS30 sensor.
    """

    BYTES_STUFFING = {
        0x7E: [0x7D, 0x5E],
        0x7D: [0x7D, 0x5D],
        0x11: [0x7D, 0x31],
        0x13: [0x7D, 0x33],
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
        return 0xFF - (sum([FRAME_SLAVE_ADR, self.get_command(), self.get_data_len()]+list(self.original_data)) % 0xFF)

    def get_frame(self) -> bytes:
        return bytes(
            [FRAME_START,
             FRAME_SLAVE_ADR,
             self.get_command()
             ] + self._byte_stuffing(self.get_data_len()) +
            reduce(lambda x, y: x + y, [self._byte_stuffing(b) for b in self.original_data]) +
            self._byte_stuffing(self.get_checksum()) +
            [FRAME_STOP]
        )

        # f"{1000%256:X}"


class MISOFrame:
    """
    Implements Master In Slave Out frame, part of SHDLC protocol.
    It is a data frame that is sent as response from SPS30 sensor (slave) to Raspberry Pi (master)
    """

    BYTES_DISEMBOWELLING = {
        MOSIFrame.BYTES_STUFFING[ori_byte][1]: ori_byte
        for ori_byte in MOSIFrame.BYTES_STUFFING
    }

    @staticmethod
    def _str_bytes(_bytes: bytes) -> str:
        return "|".join([f"0x{_b:X}" for _b in _bytes])

    def __init__(self, bytes_received: bytes):
        self.raw_frame_bytes = bytes_received

        if len(self.raw_frame_bytes) < 7:
            raise ResponseFrameError(f'The length of received data from the sensor '
                                     f'is unexpectedly short ({len(self.raw_frame_bytes)} bytes), '
                                     f'full frame: {MISOFrame._str_bytes(self.raw_frame_bytes)}')
        if self.raw_frame_bytes[0] != FRAME_START:
            raise ResponseFrameError(f'The first byte is not a start-byte, expected 0x{FRAME_START:X}, '
                                     f'actual 0x{self.raw_frame_bytes[0]:X}')
        if self.raw_frame_bytes[1] != FRAME_SLAVE_ADR:
            raise ResponseFrameError(f'The second byte is not a valid slave-address, expected 0x{FRAME_SLAVE_ADR:X}, '
                                     f'actual 0x{self.raw_frame_bytes[1]:X}')
        if self.raw_frame_bytes[-1] != FRAME_STOP:
            raise ResponseFrameError(f'The last byte is not a stop-byte, expected 0x{FRAME_STOP:X}, '
                                     f'actual 0x{self.raw_frame_bytes[-1]:X}')

        self.frame_bytes = [self.raw_frame_bytes[0]]
        _i = 1
        while _i < len(self.raw_frame_bytes) - 1:
            if self.raw_frame_bytes[_i] == FRAME_START:
                if self.raw_frame_bytes[_i+1] in self.BYTES_DISEMBOWELLING:
                    self.frame_bytes.append(self.BYTES_DISEMBOWELLING[self.raw_frame_bytes[_i+1]])
                else:
                    raise ResponseFrameError(f"Incorrect byte-stuffing found: "
                                             f"{MISOFrame._str_bytes(self.raw_frame_bytes[_i:_i+2])}, "
                                             f"full frame: {MISOFrame._str_bytes(self.raw_frame_bytes)}")
                _i += 2
            else:
                self.frame_bytes.append(self.raw_frame_bytes[_i])
                _i += 1
        self.frame_bytes = [self.raw_frame_bytes[_i]]

        self.command = {cmd.code: cmd for cmd in COMMANDS}.get(self.frame_bytes[2])
        if self.command is None:
            raise ResponseFrameError(f'The second byte is not a valid command: 0x{self.frame_bytes[2]:X}')

        _state = self.frame_bytes[3]
        # The first bit (b7) indicates that at least one of the error flags is set in the Device Status Register
        if _state & 2 ** 7:
            raise DeviceError()

        if _state:
            raise ResponseError(_state)

        _data_length = self.frame_bytes[4]
        if not 0 >= _data_length >= 255:
            raise ResponseFrameError(f"The length of data indicated {_data_length} is out of acceptable boundaries. "
                                     f"Full frame: {MISOFrame._str_bytes(self.raw_frame_bytes)}")
        if len(self.frame_bytes) - _data_length != 7:
            raise ResponseFrameError(f"The length of data indicated {_data_length} is incorrect, "
                                     f"expected {len(self.frame_bytes)-7}. "
                                     f"Full frame: {MISOFrame._str_bytes(self.raw_frame_bytes)}")

        self.data = self.frame_bytes[5:5+_data_length]

        _chk = self.frame_bytes[-2]
        _act_chk = 0xFF - (sum(self.frame_bytes[1:-2]) % 0xFF)
        if _chk != _act_chk:
            raise ResponseFrameError(f"Wrong checksum detected. "
                                     f"Expected 0x{_act_chk:X}, received: 0x{_chk:X}. "
                                     f"Full frame: {MISOFrame._str_bytes(self.raw_frame_bytes)}")


class CommandExecution(Thread):
    MAX_EXEC_TIME_MS = 1000

    def __init__(self, device: serial.Serial, command: Command, data: bytes):
        Thread.__init__(self)
        self._device = device
        self._command = command
        self._mosi = MOSIFrame(command, data)
        self._log = []
        self._miso: MISOFrame = None
        self._error: SHDLCError = None

    def run(self) -> None:
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

    def get_log(self) -> list:
        return self._log


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
        if ac_interval_s <= 0 or ac_interval_s >= 2^32:
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

