#!/usr/bin/python3

from service.tank_level import *


class WaterTankLevelService(TankLevelService):

    def __init__(self):
        TankLevelService.__init__(self)

        self.rest_app.add_url_rule('/', 'current',
                                   self.get_rest_response_current_reading)

    def provideName(self):
        return 'water-tank'

    def get_the_sensor_reference(self) -> str:
        return WATER_TANK_THE_SENSOR_REFERENCE

    def is_reliable(self, current_level: int, current_readings_mean: float, last_reliable_reading: TankLevel) -> bool:
        return True

    def get_rest_response_current_reading(self):
        _reading = self.get_last_reliable_reading()
        return self.jsonify(
            WaterLevelReadingJson(
                level_mm=_reading.level,
                fill_perc=self.get_fill_percentage(_reading.level),
                timestamp=_reading.timestamp)
        )


if __name__ == '__main__':
    ServiceRunner(WaterTankLevelService).run()
    exit()
