from rich.console import Console
from rich.table import Table
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.style import Style
from getch import getch
from datetime import datetime
from device.dev_serial_sps30 import *


# class Action:
#
#     def __init__(self, command_exe: CommandExecution):
#         self.command_exe = command_exe




ACTIONS = {
    "1": ("Wake up", lambda: "Wake up not implemented"),
    "2": ("Device information", lambda: "Device info not implemented"),
    "3": ("Device status", lambda: "Device status not implemented"),
    "4": ("Read version", lambda: "Read version not implemented"),
    "5": ("Device register status", lambda: "Not implemented"),
    "6": ("Start measurement", lambda: "Not implemented"),
    "7": ("Read measurement", lambda: "Not implemented"),
    "8": ("Stop measurement", lambda: "Not implemented"),
    "9": ("Sleep", lambda: "Not implemented"),
    "R": ("Reset", lambda: "Not implemented"),
    "0": ("Exit", exit),
}


def menu() -> Table:
    _menu = Table()
    _menu.add_column("Key", style="red")
    _menu.add_column("Command", style="magenta")
    for _key in ACTIONS:
        _menu.add_row(_key, ACTIONS[_key][0])
    return _menu


LOG = [f"{datetime.now().strftime('%H:%M:%S')} Ready!"]


def info() -> Table:
    _tab = Table(show_header=False, show_edge=False)

    for _log in reversed(LOG):
        _tab.add_row(Text(_log, style=Style(color="orange4")))

    return _tab


if __name__ == "__main__":
    console = Console()
    console.clear()

    layout = Layout(name="root")
    layout.split_column(
        Layout(name="upper"),
        Layout(name="lower")
    )
    layout["upper"].split_row(
        Layout(name="menu"),
        Layout(name="info", ratio=3)
    )
    layout["lower"].split_column(
        Layout(name="request"),
        Layout(name="response")
    )

    def update_layout() -> Layout:
        layout["menu"].update(Panel(menu(), title="Menu"))
        layout["info"].update(Panel(info(), title="Log"))
        return layout

    console.print(Panel(layout, title="Sensirion SPS-30 sensor diagnostics"))

    while True:
        console.print(update_layout())
        key = getch()
        if key in ACTIONS:
            LOG.append(f"{datetime.now().strftime('%H:%M:%S')} {ACTIONS[key][1]()}")



