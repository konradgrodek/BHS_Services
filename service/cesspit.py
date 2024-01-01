#!/usr/bin/python3

from gpiozero import LED

from service.tank_level import *


class LedSignal:
    def __init__(self, pin_R: int, pin_G: int, pin_B: int):
        self.R = LED(pin_R, initial_value=False)
        self.G = LED(pin_G, initial_value=False)
        self.B = LED(pin_B, initial_value=False)

    def __str__(self):
        return f'RGB LED defined at {self.R.pin} - {self.G.pin} - {self.B.pin}'

    def red(self):
        self.R.on()
        self.G.off()
        self.B.off()

    def violet(self):
        self.R.on()
        self.G.off()
        self.B.on()

    def green_yellow(self):
        self.R.on()
        self.G.on()
        self.B.off()

    def green_blink(self, count):
        self.R.off()
        self.B.off()
        self.G.blink(on_time=0.2, off_time=0.1, n=count)

    def blue_blink(self):
        self.R.off()
        self.G.off()
        self.B.blink(on_time=0.2, off_time=0.1)

    def red_blink(self):
        self.B.off()
        self.G.off()
        self.R.blink(on_time=0.2, off_time=0.1)


class CesspitLevelService(TankLevelService):

    def __init__(self):
        TankLevelService.__init__(self)

        self.reliable_level_increase = self.configuration.getIntConfigValue(
            section=self.tank_level_section,
            parameter='reliable-level-increase', default=5)
        self.reliable_level_increase_per_hour = self.configuration.getIntConfigValue(
            section=self.tank_level_section,
            parameter='reliable-level-increase-per-hour', default=20)
        self.max_acceptable_mode_mean_diff = self.configuration.getIntConfigValue(
            section=self.tank_level_section,
            parameter='max-acceptable-mode-mean-diff-mm', default=10)

        pin_led_R = self.configuration.getIntConfigValue(
            section=self.tank_level_section,
            parameter='pin-led-R')
        pin_led_G = self.configuration.getIntConfigValue(
            section=self.tank_level_section,
            parameter='pin-led-G')
        pin_led_B = self.configuration.getIntConfigValue(
            section=self.tank_level_section,
            parameter='pin-led-B')

        self.led_signal = LedSignal(pin_led_R, pin_led_G, pin_led_B)

        signal_levels = self.configuration.getConfigValue(
            section=self.tank_level_section,
            parameter='tank-fill-percentage-levels')

        self.signal_thresholds = None
        if signal_levels:
            self.signal_thresholds = [int(s) for s in signal_levels.split(',')]

        if not self.signal_thresholds or len(self.signal_thresholds) != 4:
            raise ValueError(f'Wrong configuration. Incorrect provided value of '
                             f'{self.tank_level_section}.tank-fill-percentage-levels: <{signal_levels}>. '
                             f'Expected comma-separated list of four integers')

        self.rest_app.add_url_rule('/', 'current',
                                   self.get_rest_response_current_reading)

    def provideName(self):
        return 'cesspit'

    def get_the_sensor_reference(self) -> str:
        return CESSPIT_THE_SENSOR_REFERENCE

    def is_reliable(self, current_level: int, current_readings_mean: float, last_reliable_reading: TankLevel) -> bool:
        # detect withdrawal:
        if abs(current_level - current_readings_mean) > self.max_acceptable_mode_mean_diff:
            return False

        # the decrease is always reliable
        if not last_reliable_reading or self._increase(current_level, last_reliable_reading.level) <= 0:
            return True

        # the increase is reliable if it does not exceed reliable-level-increase
        if self._increase(current_level, last_reliable_reading.level) < self.reliable_level_increase:
            return True

        # the increase is also reliable if the last reliable increase is in the past and the speed of increase
        # does not exceed reliable-level-increase-per-day

        return self._increase(current_level, last_reliable_reading.level) / \
               (datetime.now() - last_reliable_reading.timestamp).total_seconds() \
               < (self.reliable_level_increase_per_hour / (60 * 60))

    def react_on_level(self, fill_percentage):
        if fill_percentage < self.signal_thresholds[0]:
            self.led_signal.green_blink(int(fill_percentage/10)+1)
        elif fill_percentage < self.signal_thresholds[1]:
            self.led_signal.green_yellow()
        elif fill_percentage < self.signal_thresholds[2]:
            self.led_signal.violet()
        elif fill_percentage < self.signal_thresholds[3]:
            self.led_signal.red()
        else:
            self.led_signal.red_blink()

    def get_rest_response_current_reading(self):
        pessimistic_reading = self.get_last_reliable_reading() \
            if self.get_last_reliable_reading().level < self.get_last_stored_reading().level \
            else self.get_last_stored_reading()
        return self.jsonify(CesspitReadingJson(
            level_mm=pessimistic_reading.level,
            fill_perc=self.get_fill_percentage(pessimistic_reading.level),
            timestamp=pessimistic_reading.timestamp)
        )


if __name__ == '__main__':
    ServiceRunner(CesspitLevelService).run()
    exit()

