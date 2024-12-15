from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.style import Style
from getch import getch

import sys
sys.path.append('..')

from device.dev_serial_sps30 import *


if __name__ == "__main__":
    console = Console()
    console.clear()

    the_sensor = ParticulateMatterMeter()

    tally = Table(title="Tally", show_header=False)
    tally.add_row("Serial no", the_sensor.get_serial_number())
    tally.add_row("Firmware ver.", (lambda x, y: f"{x}.{y}")(*the_sensor.get_firmware_ver()))
    tally.add_row("Hardware rev.", f"{the_sensor.get_hardware_rev()}")
    tally.add_row("Protocol ver.", (lambda x, y: f"{x}.{y}")(*the_sensor.get_protocol_ver()))

    console.print(tally)

    results = Table(title="Measurements")
    results.add_column("PM 1.0 [ug/m3]")
    results.add_column("PM 2.5 [ug/m3]")
    results.add_column("PM 4.0 [ug/m3]")
    results.add_column("PM 10 [ug/m3]")
    results.add_column("PM 0.5 [#/cm3]")
    results.add_column("PM 1.0 [#/cm3]")
    results.add_column("PM 2.5 [#/cm3]")
    results.add_column("PM 4 [#/cm3]")
    results.add_column("PM 10 [#/cm3]")
    results.add_column("Typ. size [um]")

    measurements = deque()
    the_sensor.continuous_measurement(measurements)
    with Live(console=console, screen=True, auto_refresh=False) as live:
        while True:
            try:
                m = measurements.popleft()
                if isinstance(m, Measurement):
                    results.add_row(
                        f"{m.mass_concentration_pm_1_0_ug_m3}",
                        f"{m.mass_concentration_pm_2_5_ug_m3}",
                        f"{m.mass_concentration_pm_4_0_ug_m3}",
                        f"{m.mass_concentration_pm_10_ug_m3}",
                        f"{m.number_concentration_pm_0_5_per_cm3}",
                        f"{m.number_concentration_pm_1_0_per_cm3}",
                        f"{m.number_concentration_pm_2_5_per_cm3}",
                        f"{m.number_concentration_pm_4_0_per_cm3}",
                        f"{m.number_concentration_pm_10_per_cm3}",
                        f"{m.typical_particle_size_um}"
                    )
                    live.update(results, refresh=True)
            except IndexError:
                sleep(0.1)
