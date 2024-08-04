# https://sensirion.com/media/documents/8600FF88/64A3B8D6/Sensirion_PM_Sensors_Datasheet_SPS30.pdf
# https://github.com/Sensirion/embedded-uart-sps/tree/master/sps30-uart
# all bytes big-endian

import serial

from collections import namedtuple
from functools import reduce

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




