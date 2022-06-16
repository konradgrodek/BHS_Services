import spidev
from threading import Event, Lock
from datetime import datetime
from gpiozero import DigitalOutputDevice
import RPi.GPIO as GPIO


class ADCDevice:
    def __init__(self):
        self.adc = spidev.SpiDev()
        self.adc.open(0, 0)
        self.adc.max_speed_hz = 1100000
        self.channels = (0x80, 0xC0)
        self._lock = Lock()

    def read_percentile(self, channel_no: int) -> int:
        if channel_no not in (1, 2):
            raise ValueError(f'Internal error reading from ADC device. '
                             f'The channel number {channel_no} is invalid, only 1 or 2 are acceptable')

        self._lock.acquire()
        raw = self.adc.xfer2([1, self.channels[channel_no-1], 0])
        self._lock.release()
        ret = ((raw[1] & 0x0F) << 8) + (raw[2])

        return int(1000.0 * (1.0 - ret / 4096))



# gain channel
ADS1256_GAIN_E = {'ADS1256_GAIN_1' : 0, # GAIN   1
                  'ADS1256_GAIN_2' : 1,	# GAIN   2
                  'ADS1256_GAIN_4' : 2,	# GAIN   4
                  'ADS1256_GAIN_8' : 3,	# GAIN   8
                  'ADS1256_GAIN_16' : 4,# GAIN  16
                  'ADS1256_GAIN_32' : 5,# GAIN  32
                  'ADS1256_GAIN_64' : 6,# GAIN  64
                 }

# data rate
ADS1256_DRATE_E = {'ADS1256_30000SPS' : 0xF0, # reset the default values
                   'ADS1256_15000SPS' : 0xE0,
                   'ADS1256_7500SPS' : 0xD0,
                   'ADS1256_3750SPS' : 0xC0,
                   'ADS1256_2000SPS' : 0xB0,
                   'ADS1256_1000SPS' : 0xA1,
                   'ADS1256_500SPS' : 0x92,
                   'ADS1256_100SPS' : 0x82,
                   'ADS1256_60SPS' : 0x72,
                   'ADS1256_50SPS' : 0x63,
                   'ADS1256_30SPS' : 0x53,
                   'ADS1256_25SPS' : 0x43,
                   'ADS1256_15SPS' : 0x33,
                   'ADS1256_10SPS' : 0x20,
                   'ADS1256_5SPS' : 0x13,
                   'ADS1256_2d5SPS' : 0x03
                  }

# registration definition
REG_E = {'REG_STATUS' : 0,  # x1H
         'REG_MUX' : 1,     # 01H
         'REG_ADCON' : 2,   # 20H
         'REG_DRATE' : 3,   # F0H
         'REG_IO' : 4,      # E0H
         'REG_OFC0' : 5,    # xxH
         'REG_OFC1' : 6,    # xxH
         'REG_OFC2' : 7,    # xxH
         'REG_FSC0' : 8,    # xxH
         'REG_FSC1' : 9,    # xxH
         'REG_FSC2' : 10,   # xxH
        }

# command definition
CMD = {'CMD_WAKEUP' : 0x00,     # Completes SYNC and Exits Standby Mode 0000  0000 (00h)
       'CMD_RDATA' : 0x01,      # Read Data 0000  0001 (01h)
       'CMD_RDATAC' : 0x03,     # Read Data Continuously 0000   0011 (03h)
       'CMD_SDATAC' : 0x0F,     # Stop Read Data Continuously 0000   1111 (0Fh)
       'CMD_RREG' : 0x10,       # Read from REG rrr 0001 rrrr (1xh)
       'CMD_WREG' : 0x50,       # Write to REG rrr 0101 rrrr (5xh)
       'CMD_SELFCAL' : 0xF0,    # Offset and Gain Self-Calibration 1111    0000 (F0h)
       'CMD_SELFOCAL' : 0xF1,   # Offset Self-Calibration 1111    0001 (F1h)
       'CMD_SELFGCAL' : 0xF2,   # Gain Self-Calibration 1111    0010 (F2h)
       'CMD_SYSOCAL' : 0xF3,    # System Offset Calibration 1111   0011 (F3h)
       'CMD_SYSGCAL' : 0xF4,    # System Gain Calibration 1111    0100 (F4h)
       'CMD_SYNC' : 0xFC,       # Synchronize the A/D Conversion 1111   1100 (FCh)
       'CMD_STANDBY' : 0xFD,    # Begin Standby Mode 1111   1101 (FDh)
       'CMD_RESET' : 0xFE,      # Reset to Power-Up Values 1111   1110 (FEh)
}


class ADCBoard:

    def __init__(self, exit_event: Event = Event()):
        self.adc = spidev.SpiDev()

        self.pin_reset = DigitalOutputDevice(18, active_high=False)
        self.pin_drdy = 17
        GPIO.setup(self.pin_drdy, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self.pin_cs = DigitalOutputDevice(22, active_high=False)
        self.exit_event = exit_event
        self.drdy_wait_time_ms = 10
        self.reset_wait_time_ms = 200

    def _pause(self, delay_ms: float):
        self.exit_event.wait(delay_ms/1000)
        if self.exit_event.is_set():
            raise InterruptedError()

    def _reset(self):
        self.pin_reset.off()
        self._pause(self.reset_wait_time_ms)
        self.pin_reset.on()
        self._pause(self.reset_wait_time_ms)
        self.pin_reset.off()

    def _command(self, cmd):
        self.pin_cs.on()  # cs  0
        self.adc.writebytes([cmd])
        self.pin_cs.off()  # cs 1

    def _write_reg(self, reg, data):
        self.pin_cs.on()  # cs  0
        self.adc.writebytes([CMD['CMD_WREG'] | reg, 0x00, data])
        self.pin_cs.off()  # cs 1

    def _read_reg(self, reg):
        self.pin_cs.on()  # cs  0
        self.adc.writebytes([CMD['CMD_RREG'] | reg, 0x00])
        response = self.adc.readbytes(1)
        self.pin_cs.off()  # cs 1
        return response

    def _wait_for_drdy(self, timeout_ms: int = 2000):
        tm = datetime.now()
        while GPIO.input(self.pin_drdy) == 1:
            self.exit_event.wait(0.01)

            if (datetime.now() - tm).total_seconds() > timeout_ms/1000:
                raise TimeoutError()

            if self.exit_event.is_set():
                raise InterruptedError()

    def _config(self, gain, drate):
        self._wait_for_drdy()
        buf = [0, 0, 0, 0, 0, 0, 0, 0]
        buf[0] = (0 << 3) | (1 << 2) | (0 << 1)
        buf[1] = 0x08
        buf[2] = (0 << 5) | (0 << 3) | (gain << 0)
        buf[3] = drate

        self.pin_cs.on()  # cs  0
        self.adc.writebytes([CMD['CMD_WREG'] | 0, 0x03])
        self.adc.writebytes(buf)
        self.pin_cs.off()  # cs 1
        self._pause(1)

    def get_chip_id(self):
        self._wait_for_drdy()
        id = self._read_reg(REG_E['REG_STATUS'])
        return id[0] >> 4

    def _set_channel(self, ch: int):
        self._write_reg(REG_E['REG_MUX'], (ch << 4) | (1 << 3))

    def init(self) -> int:
        """
        Initializes the device and returns chip-id
        :return: chip-id
        :raises: InterruptedError (when exit event is detected), TimeoutError (in case of communication timeout)
        """
        self.adc.open(0, 0)
        self.adc.max_speed_hz = 20000
        self.adc.mode = 0b01
        self._reset()
        chip_id = self.get_chip_id()
        self._config(ADS1256_GAIN_E['ADS1256_GAIN_1'], ADS1256_DRATE_E['ADS1256_30000SPS'])
        return chip_id

    def read_adc(self, ch):
        self._set_channel(ch)

        self._command(CMD['CMD_SYNC'])
        self._command(CMD['CMD_WAKEUP'])

        self._wait_for_drdy()
        self.pin_cs.on() #cs 0
        self.adc.writebytes([CMD['CMD_RDATA']])
        buf = self.adc.readbytes(3)
        self.pin_cs.off() #cs 0

        read = (buf[0] << 16) & 0xff0000
        read |= (buf[1] << 8) & 0xff00
        read |= (buf[2]) & 0xff
        if read & 0x800000:
            read &= 0xF000000
        return read
