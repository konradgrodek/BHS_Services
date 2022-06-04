import spidev
import time
from rich.live import Live
from rich.table import Table
import os


if __name__ == '__main__':

    os.system('clear')

    adc = spidev.SpiDev()
    adc.open(0, 0)
    adc.max_speed_hz = 1100000
    channels = (0x80, 0xC0)

    ref_voltage = 3.3

    def _table() -> Table:
        table = Table(title=f'ADC Converter (ABelectronics) measuring rain and luminescence @ SPI')
        table.add_column("Channel")
        table.add_column("Raw value")
        table.add_column("Voltage [V]")
        table.add_column("Output [%]")

        for channel in channels:
            raw = adc.xfer2([1, channel, 0])
            ret = ((raw[1] & 0x0F) << 8) + (raw[2])
            perc = 100.0 * (1.0 - ret / 4096)
            volt = ref_voltage * (ret / 4096)

            table.add_row(f'{channel:X}', f'{raw[0]:03} {raw[1]:03} {raw[2]:03}', f'{volt:03.2f}', f'{perc:04.2f}')

        return table

    with Live(_table(), refresh_per_second=4) as live:  
        while 1 == 1:
            time.sleep(0.2)
            live.update(_table())

