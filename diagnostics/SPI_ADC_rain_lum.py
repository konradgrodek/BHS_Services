import spidev
from os import system
import time

if __name__ == '__main__':

    adc = spidev.SpiDev()
    adc.open(0, 0)
    adc.max_speed_hz = 1100000
    channels = (0x80, 0xC0)

    ref_voltage = 3.3

    while 1 == 1:

        time.sleep(0.2)
        system('clear')

        print(f'ADC Converter (ABelectronics) measuring rain and luminescence @ SPI')

        for channel in channels:
            raw = adc.xfer2([1, channel, 0])
            ret = ((raw[1] & 0x0F) << 8) + (raw[2])
            perc = 100.0 * (1.0 - ret / 4096)
            volt = ref_voltage * (ret / 4096)

            print(f'CHANNEL {channel}\t{raw}\t{ret}, {volt:2.2}[V].\tOutput: {perc:4.4}%')

