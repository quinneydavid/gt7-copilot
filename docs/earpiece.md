# The earpiece

A small program for a Windows sim PC or a Mac. It plays the copilot's calls into one chosen audio device (for example one earbud) without a browser, keeps that device connected, and sends the microphone to the copilot for voice control. The system's default audio device is not touched, so game sound stays where it is.

The Windows version runs on the build's own sim PC. The Mac version was written from the documentation and has not yet been run on a real Mac; the parts that do not need one are covered by the tests.

## Installing on Windows

1. On the copilot's Settings tab, group "Earpiece": switch it on and generate a token. Save.
2. On the sim PC, open the copilot's page, sign in on Settings and download the Windows installer there. The download has the copilot's address and the token filled in, which is why it is only handed to the signed-in admin. Treat the file like the token and delete it after installing.
3. Run it in an administrator PowerShell:

   ```
   powershell -ExecutionPolicy Bypass -File "$HOME\Downloads\gt7copilot-earpiece-setup.ps1"
   ```

The installer installs Python if it is missing, puts the program in `%LOCALAPPDATA%\GT7Copilot` and registers the scheduled task "GT7 Copilot earpiece", which runs as SYSTEM from boot. Running the installer again updates the program. The Live tab shows an "Earpiece" tile within ten seconds, and a "SimHub" tile: running or not, the game it is set to, and whether it is receiving the car's data.

To remove it: `Unregister-ScheduledTask "GT7 Copilot earpiece"` and delete the folder.

## Installing on a Mac

1. On the copilot's Settings tab, group "Earpiece": switch it on and generate a token. Save.
2. On the Mac, open the copilot's page, sign in on Settings and download the Mac installer there. The download has the copilot's address and the token filled in, which is why it is only handed to the signed-in admin. Treat the file like the token and delete it after installing.
3. Run it in Terminal, as the user who drives and without `sudo`:

   ```
   bash ~/Downloads/gt7copilot-earpiece-setup-mac.sh
   ```

The installer needs Python 3. It uses Homebrew's, python.org's or the one from Apple's command line tools. When none is there it stops and names the command to install one (`brew install python`); it installs nothing system-wide by itself. It then:

- puts the program and its own Python environment (`sounddevice`, `numpy`) in `~/Library/Application Support/GT7Copilot`,
- asks for the name of the playback device (part of the name as shown under System Settings, Sound),
- registers the LaunchAgent `com.gt7copilot.earpiece`, which starts at sign-in and is restarted if it stops.

Running the installer again updates the program and keeps the device and voice choices.

To remove it: `bash ~/Downloads/gt7copilot-earpiece-setup-mac.sh uninstall`. By hand: `launchctl bootout gui/$(id -u)/com.gt7copilot.earpiece`, then delete `~/Library/LaunchAgents/com.gt7copilot.earpiece.plist`, `~/Library/Application Support/GT7Copilot` and `~/Library/Logs/GT7Copilot`.

### Why a LaunchAgent

On a Mac the sound devices and the microphone permission belong to the signed-in user's session. A system daemon has neither, so the earpiece runs as an agent of the user and only while that user is signed in.

### Microphone permission

With `voice` on, macOS asks once whether Python may use the microphone. The answer is under System Settings, Privacy & Security, Microphone. Without the permission the earpiece still plays the calls; the microphone delivers silence and no commands arrive. If no question appears, run `doctor` (below) once from Terminal and check that list. How macOS attributes the request for a program started by launchd is the main untested point of the Mac version.

### Picking the device, and Bluetooth

```
"$HOME/Library/Application Support/GT7Copilot/venv/bin/python" "$HOME/Library/Application Support/GT7Copilot/earpiece.py" doctor
```

lists the playback devices and microphones the Mac can open and marks the ones whose name matches `device`. Change `device` in `earpiece.json` and restart: `launchctl kickstart -k gui/$(id -u)/com.gt7copilot.earpiece`.

macOS connects a paired earbud by itself when it is taken out of its case. With the small tool `blueutil` installed (`brew install blueutil`) the earpiece also asks Bluetooth to connect it, as `connect_when` says. Without `blueutil` it only waits.

Differences from Windows: the device's volume is not set (`volume` is ignored), and there is no SimHub.

## Why a system task (Windows)

Inside a Remote Desktop session Windows shows only "Remote Audio" and hides the PC's own sound devices, Bluetooth earbuds included. A task that runs as SYSTEM keeps them. The cost: a system task cannot start desktop programs, so the earpiece only reports whether SimHub is running.

What this means for the PC's security: the task runs as SYSTEM, but the program, its Python environment and `earpiece.json` are in `%LOCALAPPDATA%\GT7Copilot`, a folder the installing user can write. Whoever can write there (that user, or a program running as that user) can change what SYSTEM runs at the next start. On a sim PC with one user who is an administrator anyway, this adds nothing. On a shared PC, install it from an administrator account that others do not use, or do not install it there.

## Configuration

`earpiece.json`, in `%LOCALAPPDATA%\GT7Copilot` on Windows and `~/Library/Application Support/GT7Copilot` on a Mac:

| Key | Meaning |
|---|---|
| `device` | Part of the playback device's name. Default "AirPods". |
| `volume` | Windows only: the device's volume, 0 to 1, set each time it connects. `null` leaves it alone. |
| `voice` | `true` = listen on the device's microphone for voice control. A new install takes this from the copilot's Voice control setting. |
| `connect_when` | `always`, `live` (only while the game sends data) or `never`: when to ask the system to connect the device (on a Mac this needs `blueutil`). |
| `start_simhub`, `simhub_path` | Windows only: start the program at `simhub_path` when SimHub is not running. Off in a new install, and without effect in the system task the installer sets up (it only works when the earpiece is run by hand inside a sign-in). |
| `simhub_api` | Windows only: the address of SimHub's own web API, asked for the game SimHub is set to and whether data arrives. Default `http://127.0.0.1:8888`; empty = only check that the program runs. |

The log is `earpiece.log`: in the same folder on Windows, in `~/Library/Logs/GT7Copilot` on a Mac.

## Trouble

On Windows:

```
%LOCALAPPDATA%\GT7Copilot\venv\Scripts\python.exe %LOCALAPPDATA%\GT7Copilot\earpiece.py doctor
```

prints what the PC looks like to the earpiece. Run inside Remote Desktop it shows only Remote Audio; the running task's own picture is in the copilot's `/api/state` under `earpiece_diag`.

- **Silent on the first run.** The device's Windows volume was zero or muted. The `volume` setting fixes that on every connect.
- **Recording and playing.** The microphone runs in its own process. On the build PC, playing failed while the same process held the microphone open.

## What the token allows

The earpiece may listen to the call stream, fetch audio, report its own status and send speech. It cannot read laps, change settings or make the copilot speak.
