from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.layout import Layout
from rich.panel import Panel
from rich.align import Align

import sys
sys.path.append('..')

from device.dev_serial_sps30 import *


if __name__ == "__main__":
    console = Console()
    console.clear()

    the_sensor = ParticulateMatterMeter()
    measurements = deque(maxlen=console.height-14)

    layout = Layout("root")
    layout.split(
        Layout(name="Tally", size=8),
        Layout(name="Measurements")
    )

    def print_all() -> Layout:
        tally = Table(show_header=False)
        tally.add_row("Serial no", the_sensor.get_serial_number())
        tally.add_row("Firmware ver.", (lambda x, y: f"{x}.{y}")(*the_sensor.get_firmware_ver()))
        tally.add_row("Hardware rev.", f"{the_sensor.get_hardware_rev()}")
        tally.add_row("Protocol ver.", (lambda x, y: f"{x}.{y}")(*the_sensor.get_protocol_ver()))

        layout["Tally"].update(Panel(Align(tally, align="center"), title="Tally"))

        results = Table()
        results.add_column("Time")
        results.add_column("PM 1.0 \[ug/m3]")
        results.add_column("PM 2.5 \[ug/m3]")
        results.add_column("PM 4.0 \[ug/m3]")
        results.add_column("PM 10 \[ug/m3]")
        results.add_column("PM 0.5 \[#/cm3]")
        results.add_column("PM 1.0 \[#/cm3]")
        results.add_column("PM 2.5 \[#/cm3]")
        results.add_column("PM 4 \[#/cm3]")
        results.add_column("PM 10 \[#/cm3]")
        results.add_column("Typ. size \[um]")

        for m in reversed(list(measurements)):
            if isinstance(m, Measurement):
                results.add_row(
                    m.timestamp.strftime('%H:%M:%S'),
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

        layout["Measurements"].update(Panel(results, title="Measurements"))
        return layout

    the_sensor.continuous_measurement(measurements)
    with Live(console=console, screen=True, auto_refresh=True) as live:
        while True:
            live.update(print_all(), refresh=True)
            sleep(0.1)
