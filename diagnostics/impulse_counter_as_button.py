import sys
sys.path.append('../')

from device.buttons import StatelessButton
from rich.table import Table
from rich.live import Live
from os import system
from time import sleep
from collections import deque, Counter


if __name__ == '__main__':

    system('clear')

    _pin_buttons = [5]
    _colors = {5: 'red', 6: 'green'}

    readings = deque(maxlen=30)
    counters = Counter([_pin for _pin in _pin_buttons])

    def update_table() -> Table:
        table = Table(title=f'Detected signals (low)')
        table.add_column('Pin')
        table.add_column('Id')
        table.add_column('Duration [s]')
        readings_c = list(readings)
        for r in readings_c:
            table.add_row(f'[{_colors[r[0]]}]{r[0]}', str(r[1]), f'{r[2]:.3f}')
        return table

    def button_pressed(duration: float, pin: int):
        readings.append((pin, counters[pin], duration))
        counters[pin] += 1

    buttons = [StatelessButton(pin=_pin, button_pressed_handler=button_pressed) for _pin in _pin_buttons]

    with Live(update_table(), refresh_per_second=4) as live:
        while 1 == 1:
            sleep(0.2)
            live.update(update_table())
