from rich.console import Console
from rich.table import Table
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.style import Style
from getch import getch

import sys
sys.path.append('..')

from device.dev_serial_sps30 import *


# class Action:
#
#     def __init__(self, command_exe: CommandExecution):
#         self.command_exe = command_exe


def menu(actions_menu: dict) -> Table:
    _menu = Table()
    _menu.add_column("Key", style="red")
    _menu.add_column("Command", style="magenta")
    for _key in actions_menu:
        _menu.add_row(_key, actions_menu[_key][0])
    return _menu


def info(history: list, current: list) -> Table:
    _tab = Table(show_header=False, show_edge=False)

    for _log_entry in reversed(current):
        _tab.add_row(Text(_log_entry, style=Style(color="orange4")))
    for _log_entry in reversed(history):
        _tab.add_row(Text(_log_entry))

    return _tab


def frames(frames_list: list) -> Table:
    _tab = Table(show_header=False, show_edge=False)

    for frame in frames_list:
        _tab.add_row(Text(repr(frame)))

    return _tab


def update_layout(actions_menu: dict, history: list, current: list, requests: list, responses: list) -> Layout:
    layout["menu"].update(Panel(menu(actions_menu), title="Menu"))
    layout["info"].update(Panel(info(history, current), title="Log"))
    layout["request"].update(Panel(frames(requests), title="Requests"))
    layout["response"].update(Panel(frames(responses), title="Responses"))

    return layout


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

    console.print(Panel(layout, title="Sensirion SPS-30 sensor diagnostics"))
    try:
        sensor = ParticulateMatterSensor()
    except SHDLCError:
        console.print_exception()
        exit(1)

    the_log = [f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} Port open for {str(sensor.device)}"]

    requests_history = list()
    responses_history = list()

    def collect_response(response: MISOFrame):
        responses_history.append(response)

    actions = {
        "1": ("Wake up", lambda: sensor.wake_up(collect_response)),
        "2": ("Device information", lambda: "Device info not implemented"),
        "3": ("Device status", lambda: "Device status not implemented"),
        "4": ("Read version", lambda: "Read version not implemented"),
        "5": ("Device register status", lambda: "Not implemented"),
        "6": ("Start measurement", lambda: sensor.start_measurement(collect_response)),
        "7": ("Read measurement", lambda: "Not implemented"),
        "8": ("Stop measurement", lambda: "Not implemented"),
        "9": ("Sleep", lambda: "Not implemented"),
        "R": ("Reset", lambda: "Not implemented"),
        "0": ("Exit", lambda: 0),
    }

    while True:
        console.print(update_layout(actions_menu=actions, history=the_log, current=[],
                                    requests=requests_history, responses=responses_history))
        key = getch()
        if key in actions:
            action = actions[key][1]()
            if isinstance(action, int):
                exit(action)
            elif isinstance(action, str):
                the_log.append(f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} {action}")
            else:  # CommandExecution
                requests_history.append(action.get_mosi())
                while True:
                    console.print(
                        update_layout(actions_menu=actions, history=the_log, current=action.get_trace().collect_log(),
                                      requests=requests_history, responses=responses_history))
                    action.join(timeout=0.2)
                    if not action.is_alive():
                        try:
                            the_log.extend(action.get_trace().collect_log())
                            action.raise_error()
                        except SHDLCError as _x:
                            the_log.append(f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} {str(_x)}")
                        break





