import random

import sys
sys.path.append('..')

from device.dev_serial_sps30 import *


class TestData:

    def to_bytes(self) -> bytes:
        raise NotImplementedError()

    def data(self) -> namedtuple:
        raise NotImplementedError()


class TestEmptyData(TestData):

    def to_bytes(self) -> bytes:
        return bytes([])

    def data(self) -> namedtuple:
        return Empty()


class TestDataMeasurement(TestData):
    CONCENTRATION = list(range(0, 65535))
    WEIGHTS = [1 / (3 * c) if c > 0 else 1 / 5 for c in CONCENTRATION]

    def __init__(self):
        _mass, _number, _size = random.choices(self.CONCENTRATION, weights=self.WEIGHTS, k=3)
        def _generate_next(x): return min(65535, max(0, x + random.randint(-x // 10, x // 10)))
        self.measurement = Measurement(
            mass_concentration_pm_1_0_ug_m3=_mass,
            mass_concentration_pm_2_5_ug_m3=_generate_next(_mass),
            mass_concentration_pm_4_0_ug_m3=_generate_next(_mass),
            mass_concentration_pm_10_ug_m3=_generate_next(_mass),
            number_concentration_pm_0_5_per_cm3=_number,
            number_concentration_pm_1_0_per_cm3=_generate_next(_number),
            number_concentration_pm_2_5_per_cm3=_generate_next(_number),
            number_concentration_pm_4_0_per_cm3=_generate_next(_number),
            number_concentration_pm_10_per_cm3=_generate_next(_number),
            typical_particle_size_um=_size,
            timestamp=datetime.now()
        )

    def to_bytes(self) -> bytes:
        def _to_bytes(x: int): return x.to_bytes(2, byteorder='big')
        return _to_bytes(self.measurement.mass_concentration_pm_1_0_ug_m3) + \
            _to_bytes(self.measurement.mass_concentration_pm_2_5_ug_m3) + \
            _to_bytes(self.measurement.mass_concentration_pm_4_0_ug_m3) + \
            _to_bytes(self.measurement.mass_concentration_pm_10_ug_m3) + \
            _to_bytes(self.measurement.number_concentration_pm_0_5_per_cm3) + \
            _to_bytes(self.measurement.number_concentration_pm_1_0_per_cm3) + \
            _to_bytes(self.measurement.number_concentration_pm_2_5_per_cm3) + \
            _to_bytes(self.measurement.number_concentration_pm_4_0_per_cm3) + \
            _to_bytes(self.measurement.number_concentration_pm_10_per_cm3) + \
            _to_bytes(self.measurement.typical_particle_size_um)

    def data(self) -> namedtuple:
        return self.measurement


class TestDataAutoCleanInterval(TestData):

    def __init__(self, interval_s = -1):
        self.auto_clean_interval = AutoCleanInterval(
            interval_s=random.randint(60*60*24, 60*60*24*7) if interval_s < 0 else interval_s
        )

    def to_bytes(self) -> bytes:
        return self.auto_clean_interval.interval_s.to_bytes(4, byteorder='big')

    def data(self) -> namedtuple:
        return self.auto_clean_interval


class TestDataDeviceInfo(TestData):

    def __init__(self, device_info: str = None):
        self.device_info = DeviceInfo(
            info=reduce(lambda x, y: x + y, random.choices('ABCDEFGH0123456789', k=16))
            if device_info is None else device_info
        )

    def to_bytes(self) -> bytes:
        # null-terminated ascii string
        return self.device_info.info.encode('ascii')+bytes([0])

    def data(self) -> namedtuple:
        return self.device_info


class TestDataVersions(TestData):

    def __init__(self, firmware=None, hardware=None, protocol=None):
        self.versions = Versions(
            firmware=(random.randint(0, 255), random.randint(0, 255)) if firmware is None else firmware,
            hardware=random.randint(0, 255) if hardware is None else hardware,
            protocol=(random.randint(0, 255), random.randint(0, 255)) if protocol is None else protocol
        )

    def to_bytes(self) -> bytes:
        return bytes([
            self.versions.firmware[0],
            self.versions.firmware[1],
            0,
            self.versions.hardware,
            0,
            self.versions.protocol[0],
            self.versions.protocol[1]
        ])

    def data(self) -> namedtuple:
        return self.versions


class TestDataDeviceStatus(TestData):

    def __init__(self, speed_warning=-1, laser_error=-1, fan_error=-1):
        s, l, f = (
            random.randint(0, 1) if speed_warning < 0 else speed_warning,
            random.randint(0, 1) if laser_error < 0 else laser_error,
            random.randint(0, 1) if fan_error < 0 else fan_error,
        )

        self.device_status = DeviceStatus(
            speed_warning=s,
            laser_error=l,
            fan_error=f,
            register=f"{s*2**21+l*2**5+f*2**4:b}"
        )

    def to_bytes(self) -> bytes:
        return int(self.device_status.register, base=2).to_bytes(4, byteorder='big')+bytes([0])

    def data(self) -> namedtuple:
        return self.device_status


class SimulatedResponseFrame:

    def __init__(self, command: Command = None, data: TestData = None, state: int = 0):
        if command is None:
            command = random.choice(COMMANDS)
        if state is None:
            state = 0
        if data is None:
            # generate fake data
            if command in (CMD_START, CMD_STOP, CMD_SLEEP, CMD_WAKEUP, CMD_CLEAN, CMD_RESET):
                data = TestEmptyData()
            if command == CMD_MEASURE:
                data = TestDataMeasurement()
            if command == CMD_INFO:
                data = TestDataDeviceInfo()
            if command == CMD_VERSION:
                data = TestDataVersions()
            if command == CMD_STATUS:
                data = TestDataDeviceStatus()
            if command == CMD_SET_AUTO_CLEAN:
                # FIXME how to distinguish SET from GET?
                data = TestEmptyData()

        self.command = command
        self.data = data
        self.state = state

    def get_frame_bytes(self) -> bytes:
        data_bytes = self.data.to_bytes()
        _not_stuffed_frame_content = bytes([FRAME_SLAVE_ADR, self.command.code, self.state, len(data_bytes)]) + data_bytes

        _stuffed_frame_content = [FRAME_SLAVE_ADR, self.command.code, self.state] + \
                                 stuffing(bytes([len(data_bytes)])) + stuffing(data_bytes)

        return bytes(
            [FRAME_START] +
            _stuffed_frame_content +
            stuffing(bytes([checksum(_not_stuffed_frame_content)])) +
            [FRAME_STOP]
        )

