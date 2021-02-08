import spidev


class ADCDevice:
    def __init__(self):
        self.adc = spidev.SpiDev()
        self.adc.open(0, 0)
        self.adc.max_speed_hz = 1100000
        self.channels = (0x80, 0xC0)

    def read_percentile(self, channel_no: int) -> int:
        if channel_no not in (1, 2):
            raise ValueError(f'Internal error reading from ADC device. '
                             f'The channel number {channel_no} is invalid, only 1 or 2 are acceptable')

        raw = self.adc.xfer2([1, self.channels[channel_no-1], 0])
        ret = ((raw[1] & 0x0F) << 8) + (raw[2])

        return int(1000.0 * (1.0 - ret / 4096))
