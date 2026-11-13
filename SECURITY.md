# Security

## Where to run it

GT7 Copilot is made for a home network. The driving pages (Home, Live, Cars, Tracks, Sessions, Screenshots) have no login: anyone who can reach the page can read the laps, name a track, ask the chat when Ask is on, mute the copilot, make it speak a test line and hand in a picture for reading (upload, and the share sheet when that route is on). Do not publish it to the internet as it is. For access from outside, put it behind a reverse proxy that signs people in, or a VPN.

The copilot speaks plain HTTP. On an untrusted network a proxy with TLS belongs in front of it, because the admin password and the tokens travel in the request.

## What the admin password protects

- Changing any setting, including the console address and every on/off switch.
- Setting, replacing and clearing keys and tokens.
- Seeing the virtual phone's web view password, and the phone's screen on the Phone page.
- Downloading the earpiece installer, which has the earpiece token written into it.

The first visit to the Settings tab sets the password. Until then anyone on the network can set it; set it right after the first start. To close that window, start the container with `GT7C_ADMIN_PASSWORD` set: that password is then the admin password from the first second and nobody can set another one from the page without it. It is compared as given (not hashed) until a password is saved on the Settings tab, which replaces it; anyone who can read the container's environment can read it.

A password set on the page is stored as a salted PBKDF2-SHA256 hash. Ten wrong attempts from one address lock sign-in for that address for five minutes; other addresses are not affected. Behind a reverse proxy every visitor has the proxy's address, so there the lock is shared. A sign-in lasts twelve hours or until the container restarts.

A lost password: delete the `admin` entry from `settings.json` in the data volume and restart the container.

## Requests from other websites

A web page from somewhere else, open in a browser on the home network, could otherwise send requests to the copilot. Everything that changes or starts something (settings, sign-in, speaking, muting, uploads, starting a screenshot read, Ask, naming a track) is a POST that needs the header `X-GT7C: 1`, which a browser does not let a foreign page send, or a token. The exception is `/share`, the Android share sheet, which is a plain form by nature and is off until switched on. The copilot sends no CORS headers, so a foreign page cannot read its answers either.

## Keys and tokens

- Stored in `settings.json` in the data volume, readable by the container's user only. They are not encrypted; a copy of the volume contains them.
- Never sent to the page after they are saved. A token made by the copilot is shown once.
- The share token (iPhone Shortcut, scripts) allows sending a picture for reading and nothing else.
- The earpiece token allows listening, status reports and sending speech. The agent token allows reading and filing, not settings, and it reads no files from the copilot's machine: sheets and pictures are sent in the request. See [docs/earpiece.md](docs/earpiece.md) and [docs/agent.md](docs/agent.md).

## The earpiece installer and the Windows task

The installer is made for the signed-in admin and contains the earpiece token; keep it like the token. The address written into it comes from the request and is refused unless it looks like a host name or address.

On Windows the earpiece runs as a scheduled task as SYSTEM (inside a remote session Windows hides the PC's sound devices from a user's own programs). The program and its settings are in `%LOCALAPPDATA%\GT7Copilot`, a folder the installing user can write, so that user, or anything running as that user, can change what SYSTEM runs. On a shared PC install it from an administrator account that others do not use. On a Mac it runs as the signed-in user. See [docs/earpiece.md](docs/earpiece.md).

## The virtual phone

Port 6080 shows the phone's screen, with signed-in Google and PlayStation accounts, behind a VNC password of at most eight characters. The stack publishes that port on the machine itself only (`127.0.0.1`); from the network the screen is reached through the copilot's Phone page, for the signed-in admin. See [docs/phone.md](docs/phone.md).

## What leaves the machine

- Telemetry, laps and the voice stay local.
- A screenshot goes to the vision model's address, and speech to the speech-to-text address, as set in Settings. With the bundled or self-hosted services these are local too.

## Reporting a problem

Open a private security advisory on the GitHub repository, or an issue without the details if that is not possible.
