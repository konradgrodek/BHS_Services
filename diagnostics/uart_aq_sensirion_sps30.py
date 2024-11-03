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
        _tab.add_row(_log_entry)

    return _tab


def frames(frames_list: list) -> Table:
    _tab = Table(show_header=False, show_edge=False)

    for frame in reversed(frames_list):
        if isinstance(frame, MOSIFrame) or isinstance(frame, MISOFrame):
            _tab.add_row(Text(repr(frame)))
        elif isinstance(frame, bytes) and len(frame) > 0:
            _tab.add_row(Text(str_bytes(frame), style=Style(color="red")))
        else:
            _tab.add_row(Text(f"~~~ NULL ~~~", style=Style(color="red")))

    return _tab


def update_layout(lout: Layout, console_height: int, actions_menu: dict, history: list, current: list,
                  requests: list, responses: list) -> Panel:
    lout["menu"].update(Panel(menu(actions_menu), title="Menu"))
    lout["info"].update(Panel(info(history, current), title="Log"))
    lout["request"].update(Panel(frames(requests), title="Requests"))
    lout["response"].update(Panel(frames(responses), title="Responses"))

    return Panel(
        lout,
        title="Sensirion SPS-30 sensor diagnostics tool",
        # height=console_height - 4
    )


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

    # console.print(Panel(layout, title="Sensirion SPS-30 sensor diagnostics"))
    try:
        sensor = ParticulateMatterSensor()
    except SHDLCError:
        console.print_exception()
        exit(1)

    the_log = [Text(f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} Port open for {str(sensor.device)}")]

    requests_history = list()
    responses_history = list()

    def collect_response(response: MISOFrame):
       responses_history.append(response)

    actions = {
        "W": ("Wake up", lambda: sensor.wake_up(collect_response)),
        "S": ("Start measurement", lambda: sensor.start_measurement(collect_response)),
        "M": ("Read measurement", lambda: sensor.read_measured_values(collect_response)),
        "P": ("Stop measurement", lambda: sensor.stop_measurement(collect_response)),
        "L": ("Sleep", lambda: sensor.sleep(collect_response)),
        "V": ("Read version", lambda: sensor.get_version(collect_response)),
        "R": ("Device register status", lambda: sensor.get_status(collect_response)),
        "I": ("Device serial number", lambda: sensor.get_serial_number(collect_response)),
        "T": ("Device type", lambda: sensor.get_product_type(collect_response)),
        "C": ("Start cleaning", lambda: sensor.start_fan_cleaning(collect_response)),
        "A": ("Read auto-cleaning int.", lambda: sensor.get_auto_cleaning_interval(collect_response)),
        "X": ("Reset", lambda: sensor.reset(collect_response)),
        "0": ("Exit", lambda: 0),
    }

    with Live(console=console, screen=True, auto_refresh=False) as live:
        while True:
            live.update(
                update_layout(
                    lout=layout,
                    console_height=console.size.height,
                    actions_menu=actions,
                    history=the_log,
                    current=[],
                    requests=requests_history,
                    responses=responses_history
                ),
                refresh=True
            )
            key = getch().upper()
            if key in actions:
                action = actions[key][1]()
                if isinstance(action, int):
                    exit(action)
                elif isinstance(action, str):
                    the_log.append(Text(f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} {action}"))
                else:  # CommandExecution
                    requests_history.append(action.get_mosi())
                    while True:
                        live.update(
                            update_layout(
                                lout=layout,
                                console_height=console.size.height,
                                actions_menu=actions,
                                history=the_log,
                                current=action.get_trace().collect_log(),
                                requests=requests_history,
                                responses=responses_history
                            ),
                            refresh=True
                        )
                        action.join(timeout=0.2)
                        if not action.is_alive():
                            try:
                                _trace = action.get_trace()
                                the_log.append(Text.assemble(
                                    f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} Command ",
                                    (f"0x{action.get_command().code:02X} {action.get_command().name}", "bold"),
                                    f" executed in {_trace.total_duration_ms()} [ms] "
                                    f"(write: {_trace.write_duration_ms()}, read: {_trace.read_duration_ms()} [ms])"
                                ))
                                action.raise_error()
                                try:
                                    result = action.get_miso().interpret_data()
                                    if len(result) > 0:
                                        the_log.append(Text(
                                            f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} {str(result)}",
                                            style=Style(color="green")
                                        ))
                                    else:
                                        the_log.append(Text(
                                            f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} "
                                            f"This command does not provide any data"
                                        ))
                                except SHDLCError as _x:
                                    the_log.append(Text(f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} {str(_x)}",
                                                        style=Style(color="red")))
                                except NotImplementedError:
                                    the_log.append(Text(f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} "
                                                        f"The result of the command has no interpretation",
                                                        style=Style(color="red")))

                            except SHDLCError as _x:
                                the_log.append(
                                    Text(f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} {str(_x)}",
                                         style=Style(
                                             color="orange3" if isinstance(_x, CommandNotAllowed)
                                             else "red"
                                         )))
                                if isinstance(_x, ResponseFrameError) or isinstance(_x, CommandNotAllowed):
                                    responses_history.append(_x.original_bytes_received)
                            break
            elif key.isprintable() or key != '[':  # I do not know how otherwise to ignore mouse wheel events
                the_log.append(Text(f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} Ignored command '{key}'",
                                    style=Style(color="orange1")))
