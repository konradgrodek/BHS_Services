# pressure / humidity / temperature sensor on I2C
# I2C tools: sudo apt-get install i2c-tools
# then run i2cdetect -y 1 to see available devices

import smbus
import time
from os import system
from gpiozero import DigitalOutputDevice

class BME280:

    def __init__(self):
        self._bus = smbus.SMBus(1)
        self.I2C_ADDR = 0x77

        self.TEMPERATURE = 'TEMPERATURE'
        self.HUMIDITY = 'HUMIDITY'
        self.PRESSURE = 'PRESSURE'
    
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

    def read(self) -> dict:
        # Waits for reading to become available on device
        # Does a single burst read of all data values from device
        while self.readU8(self.REGISTER_STATUS) & 0x08:  # Wait for conversion to complete (TODO : add timeout)
            time.sleep(0.002)

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
            pressure = int(pressure/100)

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

        return {self.TEMPERATURE: temp, self.HUMIDITY: hum, self.PRESSURE: pressure}


if __name__ == '__main__':
    sensor = BME280()

    fan = DigitalOutputDevice(pin=16, active_high=False)
    fan.on()

    while 1 == 1:
        system('clear')
        print(f'BME280 multi-sensor @ I2C. Fan is on ({fan.pin})')
        res = sensor.read()
        print(f'Temperature\t{res[sensor.TEMPERATURE]:4.4} [\u2103]')
        print(f'Pressure\t{res[sensor.PRESSURE]} [hPa]')
        print(f'Humidity\t{res[sensor.HUMIDITY]:4.4} %')
        time.sleep(0.2)



'''
import time

# BME280 default address.
BME280_I2CADDR = 0x77

# Operating Modes
BME280_OSAMPLE_1 = 1
BME280_OSAMPLE_2 = 2
BME280_OSAMPLE_4 = 3
BME280_OSAMPLE_8 = 4
BME280_OSAMPLE_16 = 5

# Standby Settings
BME280_STANDBY_0p5 = 0
BME280_STANDBY_62p5 = 1
BME280_STANDBY_125 = 2
BME280_STANDBY_250 = 3
BME280_STANDBY_500 = 4
BME280_STANDBY_1000 = 5
BME280_STANDBY_10 = 6
BME280_STANDBY_20 = 7

# Filter Settings
BME280_FILTER_off = 0
BME280_FILTER_2 = 1
BME280_FILTER_4 = 2
BME280_FILTER_8 = 3
BME280_FILTER_16 = 4

# BME280 Registers

BME280_REGISTER_DIG_T1 = 0x88  # Trimming parameter registers
BME280_REGISTER_DIG_T2 = 0x8A
BME280_REGISTER_DIG_T3 = 0x8C

BME280_REGISTER_DIG_P1 = 0x8E
BME280_REGISTER_DIG_P2 = 0x90
BME280_REGISTER_DIG_P3 = 0x92
BME280_REGISTER_DIG_P4 = 0x94
BME280_REGISTER_DIG_P5 = 0x96
BME280_REGISTER_DIG_P6 = 0x98
BME280_REGISTER_DIG_P7 = 0x9A
BME280_REGISTER_DIG_P8 = 0x9C
BME280_REGISTER_DIG_P9 = 0x9E

BME280_REGISTER_DIG_H1 = 0xA1
BME280_REGISTER_DIG_H2 = 0xE1
BME280_REGISTER_DIG_H3 = 0xE3
BME280_REGISTER_DIG_H4 = 0xE4
BME280_REGISTER_DIG_H5 = 0xE5
BME280_REGISTER_DIG_H6 = 0xE6
BME280_REGISTER_DIG_H7 = 0xE7

BME280_REGISTER_CHIPID = 0xD0
BME280_REGISTER_VERSION = 0xD1
BME280_REGISTER_SOFTRESET = 0xE0

BME280_REGISTER_STATUS = 0xF3
BME280_REGISTER_CONTROL_HUM = 0xF2
BME280_REGISTER_CONTROL = 0xF4
BME280_REGISTER_CONFIG = 0xF5
BME280_REGISTER_DATA = 0xF7

class BME280(object):
    def __init__(self, t_mode=BME280_OSAMPLE_1, p_mode=BME280_OSAMPLE_1, h_mode=BME280_OSAMPLE_1,
                 standby=BME280_STANDBY_250, filter=BME280_FILTER_off, address=BME280_I2CADDR, **kwargs):
        # Check that t_mode is valid.
        if t_mode not in [BME280_OSAMPLE_1, BME280_OSAMPLE_2, BME280_OSAMPLE_4,
                        BME280_OSAMPLE_8, BME280_OSAMPLE_16]:
            raise ValueError(
                'Unexpected t_mode value {0}.'.format(t_mode))
        self._t_mode = t_mode
        # Check that p_mode is valid.
        if p_mode not in [BME280_OSAMPLE_1, BME280_OSAMPLE_2, BME280_OSAMPLE_4,
                        BME280_OSAMPLE_8, BME280_OSAMPLE_16]:
            raise ValueError(
                'Unexpected p_mode value {0}.'.format(p_mode))
        self._p_mode = p_mode
        # Check that h_mode is valid.
        if h_mode not in [BME280_OSAMPLE_1, BME280_OSAMPLE_2, BME280_OSAMPLE_4,
                        BME280_OSAMPLE_8, BME280_OSAMPLE_16]:
            raise ValueError(
                'Unexpected h_mode value {0}.'.format(h_mode))
        self._h_mode = h_mode
        # Check that standby is valid.
        if standby not in [BME280_STANDBY_0p5, BME280_STANDBY_62p5, BME280_STANDBY_125, BME280_STANDBY_250,
                        BME280_STANDBY_500, BME280_STANDBY_1000, BME280_STANDBY_10, BME280_STANDBY_20]:
            raise ValueError(
                'Unexpected standby value {0}.'.format(standby))
        self._standby = standby
        # Check that filter is valid.
        if filter not in [BME280_FILTER_off, BME280_FILTER_2, BME280_FILTER_4, BME280_FILTER_8, BME280_FILTER_16]:
            raise ValueError(
                'Unexpected filter value {0}.'.format(filter))
        self._filter = filter
        # Create I2C device.
        if i2c is None:
            import Adafruit_GPIO.I2C as I2C
            i2c = I2C
        # Create device, catch permission errors
        try:
            self._device = i2c.get_i2c_device(address, **kwargs)
        except IOError:
            print("Unable to communicate with sensor, check permissions.")
            exit()
        # Load calibration values.
        self._load_calibration()
        self._device.write8(BME280_REGISTER_CONTROL, 0x24)  # Sleep mode
        time.sleep(0.002)
        self._device.write8(BME280_REGISTER_CONFIG, ((standby << 5) | (filter << 2)))
        time.sleep(0.002)
        self._device.write8(BME280_REGISTER_CONTROL_HUM, h_mode)  # Set Humidity Oversample
        self._device.write8(BME280_REGISTER_CONTROL, ((t_mode << 5) | (p_mode << 2) | 3))  # Set Temp/Pressure Oversample and enter Normal mode
        self.t_fine = 0.0

    def _load_calibration(self):

        self.dig_T1 = self._device.readU16LE(BME280_REGISTER_DIG_T1)
        self.dig_T2 = self._device.readS16LE(BME280_REGISTER_DIG_T2)
        self.dig_T3 = self._device.readS16LE(BME280_REGISTER_DIG_T3)

        self.dig_P1 = self._device.readU16LE(BME280_REGISTER_DIG_P1)
        self.dig_P2 = self._device.readS16LE(BME280_REGISTER_DIG_P2)
        self.dig_P3 = self._device.readS16LE(BME280_REGISTER_DIG_P3)
        self.dig_P4 = self._device.readS16LE(BME280_REGISTER_DIG_P4)
        self.dig_P5 = self._device.readS16LE(BME280_REGISTER_DIG_P5)
        self.dig_P6 = self._device.readS16LE(BME280_REGISTER_DIG_P6)
        self.dig_P7 = self._device.readS16LE(BME280_REGISTER_DIG_P7)
        self.dig_P8 = self._device.readS16LE(BME280_REGISTER_DIG_P8)
        self.dig_P9 = self._device.readS16LE(BME280_REGISTER_DIG_P9)

        self.dig_H1 = self._device.readU8(BME280_REGISTER_DIG_H1)
        self.dig_H2 = self._device.readS16LE(BME280_REGISTER_DIG_H2)
        self.dig_H3 = self._device.readU8(BME280_REGISTER_DIG_H3)
        self.dig_H6 = self._device.readS8(BME280_REGISTER_DIG_H7)

        h4 = self._device.readS8(BME280_REGISTER_DIG_H4)
        h4 = (h4 << 4)
        self.dig_H4 = h4 | (self._device.readU8(BME280_REGISTER_DIG_H5) & 0x0F)

        h5 = self._device.readS8(BME280_REGISTER_DIG_H6)
        h5 = (h5 << 4)
        self.dig_H5 = h5 | (
        self._device.readU8(BME280_REGISTER_DIG_H5) >> 4 & 0x0F)

        print('0xE4 = {0:2x}'.format(self._device.readU8(BME280_REGISTER_DIG_H4)))
        print('0xE5 = {0:2x}'.format(self._device.readU8(BME280_REGISTER_DIG_H5)))
        print('0xE6 = {0:2x}'.format(self._device.readU8(BME280_REGISTER_DIG_H6)))
        print('dig_H1 = {0:d}'.format(self.dig_H1))
        print('dig_H2 = {0:d}'.format(self.dig_H2))
        print('dig_H3 = {0:d}'.format(self.dig_H3))
        print('dig_H4 = {0:d}'.format(self.dig_H4))
        print('dig_H5 = {0:d}'.format(self.dig_H5))
        print('dig_H6 = {0:d}'.format(self.dig_H6))

    def read_raw_temp(self):
        """Waits for reading to become available on device."""
        """Does a single burst read of all data values from device."""
        """Returns the raw (uncompensated) temperature from the sensor."""
        while (self._device.readU8(
                BME280_REGISTER_STATUS) & 0x08):  # Wait for conversion to complete (TODO : add timeout)
            time.sleep(0.002)
        self.BME280Data = self._device.readList(BME280_REGISTER_DATA, 8)
        raw = ((self.BME280Data[3] << 16) | (self.BME280Data[4] << 8) | self.BME280Data[5]) >> 4
        return raw

    def read_raw_pressure(self):
        """Returns the raw (uncompensated) pressure level from the sensor."""
        """Assumes that the temperature has already been read """
        """i.e. that BME280Data[] has been populated."""
        raw = ((self.BME280Data[0] << 16) | (self.BME280Data[1] << 8) | self.BME280Data[2]) >> 4
        return raw

    def read_raw_humidity(self):
        """Returns the raw (uncompensated) humidity value from the sensor."""
        """Assumes that the temperature has already been read """
        """i.e. that BME280Data[] has been populated."""
        raw = (self.BME280Data[6] << 8) | self.BME280Data[7]
        return raw

    def read_temperature(self):
        """Gets the compensated temperature in degrees celsius."""
        # float in Python is double precision
        UT = float(self.read_raw_temp())
        var1 = (UT / 16384.0 - float(self.dig_T1) / 1024.0) * float(self.dig_T2)
        var2 = ((UT / 131072.0 - float(self.dig_T1) / 8192.0) * (
                UT / 131072.0 - float(self.dig_T1) / 8192.0)) * float(self.dig_T3)
        self.t_fine = int(var1 + var2)
        temp = (var1 + var2) / 5120.0
        return temp

    def read_pressure(self):
        """Gets the compensated pressure in Pascals."""
        adc = float(self.read_raw_pressure())
        var1 = float(self.t_fine) / 2.0 - 64000.0
        var2 = var1 * var1 * float(self.dig_P6) / 32768.0
        var2 = var2 + var1 * float(self.dig_P5) * 2.0
        var2 = var2 / 4.0 + float(self.dig_P4) * 65536.0
        var1 = (
                       float(self.dig_P3) * var1 * var1 / 524288.0 + float(self.dig_P2) * var1) / 524288.0
        var1 = (1.0 + var1 / 32768.0) * float(self.dig_P1)
        if var1 == 0:
            return 0
        p = 1048576.0 - adc
        p = ((p - var2 / 4096.0) * 6250.0) / var1
        var1 = float(self.dig_P9) * p * p / 2147483648.0
        var2 = p * float(self.dig_P8) / 32768.0
        p = p + (var1 + var2 + float(self.dig_P7)) / 16.0
        return p

    def read_humidity(self):
        adc = float(self.read_raw_humidity())
        # print 'Raw humidity = {0:d}'.format (adc)
        h = float(self.t_fine) - 76800.0
        h = (adc - (float(self.dig_H4) * 64.0 + float(self.dig_H5) / 16384.0 * h)) * (
                float(self.dig_H2) / 65536.0 * (1.0 + float(self.dig_H6) / 67108864.0 * h * (
                1.0 + float(self.dig_H3) / 67108864.0 * h)))
        h = h * (1.0 - float(self.dig_H1) * h / 524288.0)
        if h > 100:
            h = 100
        elif h < 0:
            h = 0
        return h

def reverseByteOrder(data):
    """DEPRECATED: See https://github.com/adafruit/Adafruit_Python_GPIO/issues/48"""
    # # Courtesy Vishal Sapre
    # byteCount = len(hex(data)[2:].replace('L','')[::2])
    # val       = 0
    # for i in range(byteCount):
    #     val    = (val << 8) | (data & 0xff)
    #     data >>= 8
    # return val
    raise RuntimeError('reverseByteOrder is deprecated! See: https://github.com/adafruit/Adafruit_Python_GPIO/issues/48')

def get_default_bus():
    """Return the default bus number based on the device platform.  For a
    Raspberry Pi either bus 0 or 1 (based on the Pi revision) will be returned.
    For a Beaglebone Black the first user accessible bus, 1, will be returned.
    """
    plat = Platform.platform_detect()
    if plat == Platform.RASPBERRY_PI:
        if Platform.pi_revision() == 1:
            # Revision 1 Pi uses I2C bus 0.
            return 0
        else:
            # Revision 2 Pi uses I2C bus 1.
            return 1
    elif plat == Platform.BEAGLEBONE_BLACK:
        # Beaglebone Black has multiple I2C buses, default to 1 (P9_19 and P9_20).
        return 1
    else:
        raise RuntimeError('Could not determine default I2C bus for platform.')

def get_i2c_device(address, busnum=None, i2c_interface=None, **kwargs):
    """Return an I2C device for the specified address and on the specified bus.
    If busnum isn't specified, the default I2C bus for the platform will attempt
    to be detected.
    """
    if busnum is None:
        busnum = get_default_bus()
    return Device(address, busnum, i2c_interface, **kwargs)

def require_repeated_start():
    """Enable repeated start conditions for I2C register reads.  This is the
    normal behavior for I2C, however on some platforms like the Raspberry Pi
    there are bugs which disable repeated starts unless explicitly enabled with
    this function.  See this thread for more details:
      http://www.raspberrypi.org/forums/viewtopic.php?f=44&t=15840
    """
    plat = Platform.platform_detect()
    if plat == Platform.RASPBERRY_PI and os.path.exists('/sys/module/i2c_bcm2708/parameters/combined'):
        # On the Raspberry Pi there is a bug where register reads don't send a
        # repeated start condition like the kernel smbus I2C driver functions
        # define.  As a workaround this bit in the BCM2708 driver sysfs tree can
        # be changed to enable I2C repeated starts.
        subprocess.check_call('chmod 666 /sys/module/i2c_bcm2708/parameters/combined', shell=True)
        subprocess.check_call('echo -n 1 > /sys/module/i2c_bcm2708/parameters/combined', shell=True)
    # Other platforms are a no-op because they (presumably) have the correct
    # behavior and send repeated starts.


class Device(object):
    """Class for communicating with an I2C device using the adafruit-pureio pure
    python smbus library, or other smbus compatible I2C interface. Allows reading
    and writing 8-bit, 16-bit, and byte array values to registers
    on the device."""
    def __init__(self, address, busnum, i2c_interface=None):
        """Create an instance of the I2C device at the specified address on the
        specified I2C bus number."""
        self._address = address
        if i2c_interface is None:
            # Use pure python I2C interface if none is specified.
            import Adafruit_PureIO.smbus
            self._bus = Adafruit_PureIO.smbus.SMBus(busnum)
        else:
            # Otherwise use the provided class to create an smbus interface.
            self._bus = i2c_interface(busnum)
        self._logger = logging.getLogger('Adafruit_I2C.Device.Bus.{0}.Address.{1:#0X}' \
                                .format(busnum, address))

    def writeRaw8(self, value):
        """Write an 8-bit value on the bus (without register)."""
        value = value & 0xFF
        self._bus.write_byte(self._address, value)
        self._logger.debug("Wrote 0x%02X",
                     value)

    def write8(self, register, value):
        """Write an 8-bit value to the specified register."""
        value = value & 0xFF
        self._bus.write_byte_data(self._address, register, value)
        self._logger.debug("Wrote 0x%02X to register 0x%02X",
                     value, register)

    def write16(self, register, value):
        """Write a 16-bit value to the specified register."""
        value = value & 0xFFFF
        self._bus.write_word_data(self._address, register, value)
        self._logger.debug("Wrote 0x%04X to register pair 0x%02X, 0x%02X",
                     value, register, register+1)

    def writeList(self, register, data):
        """Write bytes to the specified register."""
        self._bus.write_i2c_block_data(self._address, register, data)
        self._logger.debug("Wrote to register 0x%02X: %s",
                     register, data)

    def readList(self, register, length):
        """Read a length number of bytes from the specified register.  Results
        will be returned as a bytearray."""
        results = self._bus.read_i2c_block_data(self._address, register, length)
        self._logger.debug("Read the following from register 0x%02X: %s",
                     register, results)
        return results

    def readRaw8(self):
        """Read an 8-bit value on the bus (without register)."""
        result = self._bus.read_byte(self._address) & 0xFF
        self._logger.debug("Read 0x%02X",
                    result)
        return result

    def readU8(self, register):
        """Read an unsigned byte from the specified register."""
        result = self._bus.read_byte_data(self._address, register) & 0xFF
        self._logger.debug("Read 0x%02X from register 0x%02X",
                     result, register)
        return result

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
        result = self._bus.read_word_data(self._address,register) & 0xFFFF
        self._logger.debug("Read 0x%04X from register pair 0x%02X, 0x%02X",
                           result, register, register+1)
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


'''