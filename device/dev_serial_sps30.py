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

ERRORS = {
    0x00: 'No error',
    0x01: 'Wrong data length for this command (too much or little data)',
    0x02: 'Unknown command',
    0x03: 'No access right for command',
    0x04: 'Illegal command parameter or parameter out of allowed range',
    0x28: 'Internal function argument out of range',
    0x43: 'Command not allowed in current state',
}


class MOSIFrame:
    """
    Implements Master Out Slave In frame, part of SHDLC protocol.
    It represents the command sent from master (RPi) to the SPS30 sensor.
    """

    START = 0x7E
    ADR = 0x00
    STOP = START

    _BYTES_STAFFING = {
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
        if _byte in self._BYTES_STAFFING:
            return self._BYTES_STAFFING[_byte]
        return [_byte]

    def get_command(self) -> int:
        return self.command.code

    def get_data_len(self) -> int:
        return len(self.original_data)

    def get_checksum(self) -> int:
        return 0xFF - (sum([MOSIFrame.ADR, self.get_command(), self.get_data_len()]+list(self.original_data)) % 0xFF)

    def get_frame(self) -> bytes:
        return bytes(
            [MOSIFrame.START,
             MOSIFrame.ADR,
             self.get_command()
             ] + self._byte_stuffing(self.get_data_len()) +
            reduce(lambda x, y: x + y, [self._byte_stuffing(b) for b in self.original_data]) +
            self._byte_stuffing(self.get_checksum())
        )

        # f"{1000%256:X}"
