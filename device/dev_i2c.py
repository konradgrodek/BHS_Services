import smbus
import time
from datetime import datetime


class MultisensorResult:

    def __init__(self, temperature, humidity, pressure):
        self._temperature = temperature
        self._humidity = humidity
        self._pressure = pressure

    def temperature(self):
        return self._temperature

    def humidity(self):
        return self._humidity

    def pressure(self):
        return self._pressure


class MultisensorReadingException(Exception):
    def __init__(self, msg):
        Exception.__init__(self, msg)


class MultisensorBME280:

    def __init__(self):
        self._bus = smbus.SMBus(1)
        self.I2C_ADDR = 0x77

        # BME280 Registers
        REGISTER_DIG_T1 = 0x88  # Trimming parameter registers
        REGISTER_DIG_T2 = 0x8A
        REGISTER_DIG_T3 = 0x8C

        REGISTER_DIG_P1 = 0x8E
        REGISTER_DIG_P2 = 0x90
        REGISTER_DIG_P3 = 0x92
        REGISTER_DIG_P4 = 0x94
        REGISTER_DIG_P5 = 0x96
        REGISTER_DIG_P6 = 0x98
        REGISTER_DIG_P7 = 0x9A
        REGISTER_DIG_P8 = 0x9C
        REGISTER_DIG_P9 = 0x9E

        REGISTER_DIG_H1 = 0xA1
        REGISTER_DIG_H2 = 0xE1
        REGISTER_DIG_H3 = 0xE3
        REGISTER_DIG_H4 = 0xE4
        REGISTER_DIG_H5 = 0xE5
        REGISTER_DIG_H6 = 0xE6
        REGISTER_DIG_H7 = 0xE7

        OSAMPLE_1 = 1
        OSAMPLE_2 = 2
        OSAMPLE_4 = 3
        OSAMPLE_8 = 4
        OSAMPLE_16 = 5

        # Standby Settings
        STANDBY_0p5 = 0
        STANDBY_62p5 = 1
        STANDBY_125 = 2
        STANDBY_250 = 3
        STANDBY_500 = 4
        STANDBY_1000 = 5
        STANDBY_10 = 6
        STANDBY_20 = 7

        # Filter Settings
        FILTER_off = 0
        FILTER_2 = 1
        FILTER_4 = 2
        FILTER_8 = 3
        FILTER_16 = 4

        self.REGISTER_CHIPID = 0xD0
        self.REGISTER_VERSION = 0xD1
        self.REGISTER_SOFTRESET = 0xE0

        self.REGISTER_STATUS = 0xF3
        self.REGISTER_CONTROL_HUM = 0xF2
        self.REGISTER_CONTROL = 0xF4
        self.REGISTER_CONFIG = 0xF5
        self.REGISTER_DATA = 0xF7

        self.dig_T1 = self.readU16LE(REGISTER_DIG_T1)
        self.dig_T2 = self.readS16LE(REGISTER_DIG_T2)
        self.dig_T3 = self.readS16LE(REGISTER_DIG_T3)

        self.dig_P1 = self.readU16LE(REGISTER_DIG_P1)
        self.dig_P2 = self.readS16LE(REGISTER_DIG_P2)
        self.dig_P3 = self.readS16LE(REGISTER_DIG_P3)
        self.dig_P4 = self.readS16LE(REGISTER_DIG_P4)
        self.dig_P5 = self.readS16LE(REGISTER_DIG_P5)
        self.dig_P6 = self.readS16LE(REGISTER_DIG_P6)
        self.dig_P7 = self.readS16LE(REGISTER_DIG_P7)
        self.dig_P8 = self.readS16LE(REGISTER_DIG_P8)
        self.dig_P9 = self.readS16LE(REGISTER_DIG_P9)

        self.dig_H1 = self.readU8(REGISTER_DIG_H1)
        self.dig_H2 = self.readS16LE(REGISTER_DIG_H2)
        self.dig_H3 = self.readU8(REGISTER_DIG_H3)
        self.dig_H6 = self.readS8(REGISTER_DIG_H7)

        h4 = self.readS8(REGISTER_DIG_H4)
        h4 = (h4 << 4)
        self.dig_H4 = h4 | (self.readU8(REGISTER_DIG_H5) & 0x0F)

        h5 = self.readS8(REGISTER_DIG_H6)
        h5 = (h5 << 4)
        self.dig_H5 = h5 | (self.readU8(REGISTER_DIG_H5) >> 4 & 0x0F)

        self.write8(self.REGISTER_CONTROL, 0x24)  # Sleep mode
        time.sleep(0.002)
        self.write8(self.REGISTER_CONFIG, ((STANDBY_250 << 5) | (FILTER_off << 2)))
        time.sleep(0.002)
        # Set Humidity Oversample
        self.write8(self.REGISTER_CONTROL_HUM, OSAMPLE_1)
        # Set Temp/Pressure Oversample and enter Normal mode
        self.write8(self.REGISTER_CONTROL, ((OSAMPLE_1 << 5) | (OSAMPLE_1 << 2) | 3))

    def writeRaw8(self, value):
        """Write an 8-bit value on the bus (without register)."""
        value = value & 0xFF
        self._bus.write_byte(self.I2C_ADDR, value)

    def write8(self, register, value):
        """Write an 8-bit value to the specified register."""
        value = value & 0xFF
        self._bus.write_byte_data(self.I2C_ADDR, register, value)

    def write16(self, register, value):
        """Write a 16-bit value to the specified register."""
        value = value & 0xFFFF
        self._bus.write_word_data(self.I2C_ADDR, register, value)

    def writeList(self, register, data):
        """Write bytes to the specified register."""
        self._bus.write_i2c_block_data(self.I2C_ADDR, register, data)

    def readList(self, register, length):
        """Read a length number of bytes from the specified register.  Results
        will be returned as a bytearray."""
        return self._bus.read_i2c_block_data(self.I2C_ADDR, register, length)

    def readRaw8(self):
        """Read an 8-bit value on the bus (without register)."""
        return self._bus.read_byte(self.I2C_ADDR) & 0xFF

    def readU8(self, register):
        """Read an unsigned byte from the specified register."""
        return self._bus.read_byte_data(self.I2C_ADDR, register) & 0xFF

    def readS8(self, register):
        """Read a signed byte from the specified register."""
        result = self.readU8(register)
        if result > 127:
            result -= 256
        return result

    def readU16(self, register, little_endian=True):
        """Read an unsigned 16-bit value from the specified register, with the
        specified endianness (default little endian, or least significant byte
        first)."""
        result = self._bus.read_word_data(self.I2C_ADDR, register) & 0xFFFF
        # Swap bytes if using big endian because read_word_data assumes little
        # endian on ARM (little endian) systems.
        if not little_endian:
            result = ((result << 8) & 0xFF00) + (result >> 8)
        return result

    def readS16(self, register, little_endian=True):
        """Read a signed 16-bit value from the specified register, with the
        specified endianness (default little endian, or least significant byte
        first)."""
        result = self.readU16(register, little_endian)
        if result > 32767:
            result -= 65536
        return result

    def readU16LE(self, register):
        """Read an unsigned 16-bit value from the specified register, in little
        endian byte order."""
        return self.readU16(register, little_endian=True)

    def readU16BE(self, register):
        """Read an unsigned 16-bit value from the specified register, in big
        endian byte order."""
        return self.readU16(register, little_endian=False)

    def readS16LE(self, register):
        """Read a signed 16-bit value from the specified register, in little
        endian byte order."""
        return self.readS16(register, little_endian=True)

    def readS16BE(self, register):
        """Read a signed 16-bit value from the specified register, in big
        endian byte order."""
        return self.readS16(register, little_endian=False)

    def read(self, timeout_seconds: float) -> MultisensorResult:
        # Waits for reading to become available on device
        # Does a single burst read of all data values from device
        time_mark = datetime.now()
        wait = self.readU8(self.REGISTER_STATUS) & 0x08
        while wait:  # Wait for conversion to complete
            if (datetime.now() - time_mark).total_seconds() > timeout_seconds:
                raise MultisensorReadingException(f'Timeout occurred while waiting for BME280 answer '
                                                  f'(configured timeout: {timeout_seconds} [s])')

            time.sleep(0.002)
            wait = self.readU8(self.REGISTER_STATUS) & 0x08

        data = self.readList(self.REGISTER_DATA, 8)

        temp_raw = float(((data[3] << 16) | (data[4] << 8) | data[5]) >> 4)
        pressure_raw = float(((data[0] << 16) | (data[1] << 8) | data[2]) >> 4)
        hum_raw = float((data[6] << 8) | data[7])

        """Gets the compensated temperature in degrees celsius."""
        # float in Python is double precision
        var1 = (temp_raw / 16384.0 - float(self.dig_T1) / 1024.0) * float(self.dig_T2)
        var2 = ((temp_raw / 131072.0 - float(self.dig_T1) / 8192.0) * (
                temp_raw / 131072.0 - float(self.dig_T1) / 8192.0)) * float(self.dig_T3)
        t_fine = int(var1 + var2)
        temp = (var1 + var2) / 5120.0

        # get the compensated pressure in Pascals."""
        var1 = float(t_fine) / 2.0 - 64000.0
        var2 = var1 * var1 * float(self.dig_P6) / 32768.0
        var2 = var2 + var1 * float(self.dig_P5) * 2.0
        var2 = var2 / 4.0 + float(self.dig_P4) * 65536.0
        var1 = (float(self.dig_P3) * var1 * var1 / 524288.0 + float(self.dig_P2) * var1) / 524288.0
        var1 = (1.0 + var1 / 32768.0) * float(self.dig_P1)

        pressure = None
        if var1 != 0:
            pressure = 1048576.0 - pressure_raw
            pressure = ((pressure - var2 / 4096.0) * 6250.0) / var1
            var1 = float(self.dig_P9) * pressure * pressure / 2147483648.0
            var2 = pressure * float(self.dig_P8) / 32768.0
            pressure = pressure + (var1 + var2 + float(self.dig_P7)) / 16.0
            # convert to hPa
            pressure = int(pressure / 100)

        # humidity
        hum = float(t_fine) - 76800.0
        hum = (hum_raw - (float(self.dig_H4) * 64.0 + float(self.dig_H5) / 16384.0 * hum)) * (
                float(self.dig_H2) / 65536.0 * (1.0 + float(self.dig_H6) / 67108864.0 * hum * (
                1.0 + float(self.dig_H3) / 67108864.0 * hum)))
        hum = hum * (1.0 - float(self.dig_H1) * hum / 524288.0)
        if hum > 100:
            hum = 100
        elif hum < 0:
            hum = 0

        return MultisensorResult(temperature=temp, humidity=hum, pressure=pressure)
