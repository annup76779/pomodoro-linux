#!/usr/bin/env python3
"""
Pomodoro AppIndicator for Ubuntu/Linux

A simple tray-based Pomodoro timer that supports 25+5 focus/break cycles,
lunch mode with a follow-up walk reminder, system notifications with sounds,
pause/resume, stop, and optional auto-pause when the screen locks.

Metadata
- Author: Anurag Pandey (GitHub: annup76779, Email: annup76779@gmail.com)
- License: MIT
- Version: 1.0.0
- Requires: GTK 3, AppIndicator3, libnotify (via python3-gi), GLib, Gio

Usage
Execute this script to start the indicator in the system tray. All configurable
options are stored in a JSON file at ~/.config/pomodoro_config.json and can also
be edited via the Settings window (tray menu → Settings).

Note
Time values in the configuration are stored in seconds. UI fields display and
accept minutes and are converted to seconds on save.
"""

__author__ = "Anurag Pandey"
__email__ = "annup76779@gmail.com"
__github__ = "annup76779"
__license__ = "MIT"
__version__ = "1.0.0"

import gi, os, json, subprocess
gi.require_version('Gtk', '3.0')
gi.require_version('AppIndicator3', '0.1')
gi.require_version('Notify', '0.7')
gi.require_version('GLib', '2.0')

from gi.repository import Gtk, AppIndicator3, GLib, Notify, Gio

CONFIG_FILE = os.path.expanduser("./pomodoro_config.json")

DEFAULTS = {
    "work": 25,
    "short_break": 5 * 60,
    "long_break": 10 * 60,
    "lunch": 45 * 60,
    "walk_after_lunch": 5 * 60,
    "pause_on_lock": True
}

sound_files = {
    "break": "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga",
    "lunch": "/usr/share/sounds/freedesktop/stereo/power-unplug.oga",
    "walk": "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga",
}

def load_config():
    """Load the application configuration from CONFIG_FILE.

    Returns a dict of configuration values. If the file does not exist
    or cannot be read/parsed, a copy of DEFAULTS is returned.
    """
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return DEFAULTS.copy()

def save_config(config):
    """Persist the configuration dict to CONFIG_FILE as JSON.

    Parameters:
    - config (dict): Configuration values to be saved. Time values are
      expected to be seconds.
    """
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

class SettingsWindow(Gtk.Window):
    """Settings dialog window allowing users to configure durations and behavior."""
    def __init__(self, app):
        """Initialize the settings window.

        Parameters:
        - app (PomodoroApp): The application instance providing config and notifications.
        """
        super().__init__(title="Pomodoro Settings")
        self.app = app
        self.set_border_width(10)

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        self.add(grid)

        self.entries = {}
        row = 0
        for key, label in [
            ("work", "Work (minutes)"),
            ("short_break", "Short Break (minutes)"),
            ("long_break", "Long Break (minutes)"),
            ("lunch", "Lunch (minutes)"),
            ("walk_after_lunch", "Walk After Lunch (minutes)")
        ]:
            lbl = Gtk.Label(label=label)
            entry = Gtk.Entry()
            entry.set_text(str(self.app.config[key] // 60))
            self.entries[key] = entry
            grid.attach(lbl, 0, row, 1, 1)
            grid.attach(entry, 1, row, 1, 1)
            row += 1

        # Checkbox for pause on lock
        self.pause_checkbox = Gtk.CheckButton(label="Pause on system lock/unlock")
        self.pause_checkbox.set_active(self.app.config.get("pause_on_lock", True))
        grid.attach(self.pause_checkbox, 0, row, 2, 1)
        row += 1

        save_btn = Gtk.Button(label="Save")
        save_btn.connect("clicked", self.on_save)
        grid.attach(save_btn, 0, row, 2, 1)

    def on_save(self, _):
        """Validate inputs, persist settings to disk, and close the window.

        Converts minute inputs to seconds and updates the running app config.
        Shows a notification on success or failure.
        """
        try:
            for key, entry in self.entries.items():
                self.app.config[key] = int(entry.get_text()) * 60
            self.app.config["pause_on_lock"] = self.pause_checkbox.get_active()
            save_config(self.app.config)
            self.app.notify("Settings Saved", "Durations updated")
            self.destroy()
        except:
            self.app.notify("Error", "Invalid input")

class PomodoroApp:
    """Main application class managing state, indicator UI, and timer logic."""
    def __init__(self):
        """Initialize the application, indicator, menu, notifications, and signals."""
        self.config = load_config()
        self.state = "stopped"
        self.remaining = self.config["work"]
        self.cycles = 0
        self.prev_state = None
        self.system_locked = False

        self.indicator = AppIndicator3.Indicator.new(
            "pomodoro-timer",
            "alarm-symbolic",
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

        self.menu = Gtk.Menu()
        self.build_menu()
        self.indicator.set_menu(self.menu)

        Notify.init("Pomodoro Timer")
        GLib.timeout_add_seconds(1, self.tick)

        # Listen for screen lock/unlock
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.signal_subscribe(
            None,
            "org.gnome.ScreenSaver",
            "ActiveChanged",
            "/org/gnome/ScreenSaver",
            None,
            Gio.DBusSignalFlags.NONE,
            self.on_screensaver_signal
        )

    def build_menu(self):
        """Create and attach all menu items to the AppIndicator tray menu."""
        start_item = Gtk.MenuItem(label="Start Work")
        start_item.connect("activate", self.start_work)
        self.menu.append(start_item)

        pause_item = Gtk.MenuItem(label="Pause / Resume")
        pause_item.connect("activate", self.toggle_pause)
        self.menu.append(pause_item)
        
        stop_item = Gtk.MenuItem(label="Stop Timer")
        stop_item.connect("activate", self.stop_timer)
        self.menu.append(stop_item)

        lunch_item = Gtk.MenuItem(label="Lunch Mode")
        lunch_item.connect("activate", self.start_lunch)
        self.menu.append(lunch_item)

        settings_item = Gtk.MenuItem(label="Settings")
        settings_item.connect("activate", self.open_settings)
        self.menu.append(settings_item)

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", Gtk.main_quit)
        self.menu.append(quit_item)

        self.menu.show_all()

    def open_settings(self, _):
        """Open the Settings window for adjusting timer durations and options."""
        win = SettingsWindow(self)
        win.show_all()

    def notify(self, title, message, sound=True):
        """Show a desktop notification and optionally play a sound.

        Parameters:
        - title (str): Notification title.
        - message (str): Notification body text.
        - sound (bool): Whether to play a short alert sound.
        """
        note = Notify.Notification.new(title, message, "dialog-information")
        note.show()
        if sound:
            subprocess.Popen(
                ["paplay", sound_files.get(self.state, "/usr/share/sounds/freedesktop/stereo/bell.oga")],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

    def start_work(self, _=None):
        """Begin a work session using the configured work duration."""
        self.state = "work"
        self.remaining = self.config["work"]
        self.notify("Work Started", f"Focus for {self.remaining//60} minutes")

    def start_break(self, long=False):
        """Start a short or long break depending on the 'long' flag.

        Parameters:
        - long (bool): If True, use long_break duration; otherwise short_break.
        """
        self.state = "break"
        self.remaining = self.config["long_break"] if long else self.config["short_break"]
        label = "Long Break" if long else "Short Break"
        self.notify(label, f"Take a {self.remaining//60} minute break!")

    def start_lunch(self, _=None):
        """Start lunch period using the configured lunch duration."""
        self.state = "lunch"
        self.remaining = self.config["lunch"]
        self.notify("Lunch Time", f"{self.remaining//60} minutes")

    def start_walk_after_lunch(self):
        """Start the post-lunch walk reminder session."""
        self.state = "walk"
        self.remaining = self.config["walk_after_lunch"]
        self.notify("Walk Break", f"Take a {self.remaining//60} minute walk!")
        
    def stop_timer(self, _=None):
        """Stop any running session and reset the indicator label."""
        self.state = "stopped"
        self.remaining = 0
        self.indicator.set_label("⏹ Stopped", "")
        self.notify("Timer Stopped", "You can start a new session when ready", sound=False)


    def toggle_pause(self, _):
        """Toggle between paused and the previous active state."""
        if self.state == "paused":
            self.state = self.prev_state
            self.notify("Resumed", "")
        else:
            self.prev_state = self.state
            self.state = "paused"
            self.notify("Paused", "")

    def on_screensaver_signal(self, bus, sender, path, iface, signal, params):
        """Handle GNOME ScreenSaver ActiveChanged events to auto-pause/resume.

        Respects the 'pause_on_lock' configuration. When the screen locks, the
        current state is saved and the timer is paused; on unlock, the previous
        state is restored and a notification is shown.
        """
        if not self.config.get("pause_on_lock", True):
            return  # ignore lock events if disabled

        locked = params.unpack()[0]
        if locked:
            if self.state not in ["stopped", "paused"]:
                self.prev_state = self.state
                self.state = "paused"
                self.system_locked = True
        else:
            if self.system_locked:
                self.system_locked = False
                if self.prev_state:
                    self.state = self.prev_state
                    self.notify("Resumed After Unlock", "")

    def tick(self):
        """Timer callback executed every second to update state and UI.

        Returns True to keep the GLib timeout active. Handles transitions between
        work/break/lunch/walk states and updates the AppIndicator label.
        """
        icons = {
            "work": "",
            "break": "☕",
            "lunch": "🍴",
            "walk": "🚶",
            "paused": "⏸",
        }

        if self.state in ["work", "break", "lunch", "walk"]:
            if self.remaining > 0:
                self.remaining -= 1
                mins, secs = divmod(self.remaining, 60)
                self.indicator.set_label(f"{icons.get(self.state, '⏲')} {mins:02d}:{secs:02d}", "")
            else:
                if self.state == "work":
                    self.cycles += 1
                    if self.cycles % 4 == 0:
                        self.start_break(long=True)
                    else:
                        self.start_break(long=False)
                elif self.state == "break":
                    self.start_work()
                elif self.state == "lunch":
                    self.start_walk_after_lunch()
                elif self.state == "walk":
                    self.start_work()
        elif self.state == "paused":
            self.indicator.set_label("⏸ Paused", "")
        else:
            self.indicator.set_label("Idle", "")
        return True

if __name__ == "__main__":
    PomodoroApp()
    Gtk.main()

