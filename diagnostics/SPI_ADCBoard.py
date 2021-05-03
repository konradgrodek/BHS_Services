import spidev
from os import system
import sys
import time
from datetime import datetime
from gpiozero import DigitalOutputDevice, DigitalInputDevice
from threading import Event

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

    def __init__(self):
        self.adc = spidev.SpiDev()

        self.pin_reset = DigitalOutputDevice(18, active_high=False)
        self.pin_drdy = DigitalInputDevice(17)
        self.pin_cs = DigitalOutputDevice(22, active_high=False)

        self.exit_event = Event()

    def _pause(self, delay_ms: int):
        self.exit_event.wait(delay_ms/1000)

    def reset(self):
        self.pin_reset.off()
        self._pause(200)
        self.pin_reset.on()
        self._pause(200)
        self.pin_reset.off()

    def command(self, cmd):
        self.pin_cs.on()  # cs  0
        self.adc.writebytes([cmd])
        self.pin_cs.off()  # cs 1

    def write_reg(self, reg, data):
        self.pin_cs.on()  # cs  0
        self.adc.writebytes([CMD['CMD_WREG'] | reg, 0x00, data])
        self.pin_cs.off()  # cs 1

    def read_reg(self, reg):
        self.pin_cs.on()  # cs  0
        self.adc.writebytes([CMD['CMD_RREG'] | reg, 0x00])
        response = self.adc.readbytes(1)
        self.pin_cs.off()  # cs 1
        return response

    def wait_for_drdy(self, timeout_ms: int = 1000):
        self.pin_drdy.wait_for_inactive(timeout_ms)
        if self.pin_drdy.is_active:
            raise TimeoutError()

    def config(self, gain, drate):
        self.wait_for_drdy()
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

    def get_chip_id(self) -> int:
        self.wait_for_drdy()
        id = self.read_reg(REG_E['REG_STATUS'])
        return id[0] >> 4

    def set_channel(self, ch: int):
        self.write_reg(REG_E['REG_MUX'], (ch << 4) | (1 << 3))

    def init(self) -> int:
        """
        Initializes the device and returns chip-id
        :return:
        """
        self.adc.open(0, 0)
        self.adc.max_speed_hz = 20000
        self.adc.mode = 0b01
        self.reset()
        chip_id = self.get_chip_id()
        print(f'Chip-id: {chip_id}')
        self.config(ADS1256_GAIN_E['ADS1256_GAIN_1'], ADS1256_DRATE_E['ADS1256_30000SPS'])
        return chip_id

    def read_adc(self, ch):
        self.set_channel(ch)

        self.command(CMD['CMD_SYNC'])
        self.command(CMD['CMD_WAKEUP'])

        self.wait_for_drdy()
        self.pin_cs.on()  # cs 0
        self.adc.writebytes([CMD['CMD_RDATA']])
        buf = self.adc.readbytes(3)
        self.pin_cs.off()  # cs 0

        read = (buf[0] << 16) & 0xff0000
        read |= (buf[1] << 8) & 0xff00
        read |= (buf[2]) & 0xff
        if read & 0x800000:
            read &= 0xF000000
        return read


if __name__ == '__main__':

    adc_converter = ADCBoard()
    adc_converter.init()

    while True:
        time.sleep(0.2)

        mark = datetime.now()
        results_raw = list()
        for channel in range(8):
            try:
                results_raw.append((channel, adc_converter.read_adc(channel)))
            except TimeoutError as e:
                print(f'Error reading (timeout) {str(e)}')

        system('clear')
        print(f'ADC Converter Board')

        _min = 220000
        _max = 4420000

        for result_raw in results_raw:
            channel = result_raw[0]
            result_perc = 100 * result_raw[1] / 0x7fffff
            result_v = 3.3 * result_raw[1] / 0x7fffff
            result_transformed = 100 * (result_raw[1] - _min) / (_max - _min)

            print(f'Channel {channel}'
                  f'\t{result_raw[1]:010}'
                  f'\t{result_v:4.4} [V]'
                  f'\t{result_perc:4.4}%'
                  f'\t{result_transformed:4.4}%')

        print(f'Measure time {int((datetime.now() - mark).total_seconds()*1000):04} ms')










