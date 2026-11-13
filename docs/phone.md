# The virtual phone

A PS5 screenshot reaches the outside world through the PlayStation App. The `phone` profile runs an Android emulator with that app, and a small fetcher that opens the app, downloads the newest capture and hands it to the copilot. The driver presses the Create button; nothing else.

This part is optional. Uploading a picture on the Screenshots page does the same job by hand.

## Before using it

- **PlayStation Network terms.** The fetcher operates the PlayStation App automatically. Automated use of the app may be against the PlayStation Network terms of service. Whether to use this part with a given account is the account holder's decision.
- **It can break.** The fetcher finds most things by their on-screen labels, but the download button inside the picture viewer has no label and is tapped by position. That position was proven on PlayStation App 26.10 at 720x1600. An app update can move it.
- **Google's terms.** The Android SDK, the emulator and the system image are downloaded from Google on first start, under Google's licence terms. Nothing of Google's is in this project's image. `ANDROID_LICENSES=accept` in `.env` records the acceptance.

## What it needs

- An x86-64 Linux host with hardware virtualisation: `/dev/kvm` must exist. It does not run on Kubernetes nodes without nested virtualisation, on Windows or macOS hosts, or on ARM.
- About 9 GB of memory, 4 CPU cores and 7 GB of disk. The container may use up to `PHONE_CPUS` cores of the host (default 4; Docker refuses to start it when the host has fewer) and the emulated phone has `PHONE_CORES` cores (default 4). Both are set in `.env`; a host with more cores can give it more, for example `PHONE_CPUS=8` and `PHONE_CORES=6`.

## Setting it up

1. In `.env`: `COMPOSE_PROFILES=phone` (or `phone,voice`), `ANDROID_LICENSES=accept`, and `KVM_GID` if the group of `/dev/kvm` is not 994 (`stat -c %g /dev/kvm`).
2. `docker compose up -d`. The first start downloads about 4 GB and builds the phone; `docker compose logs -f phone` shows progress.
3. Open the phone's screen: sign in on the copilot's Settings page, then open the Phone page. (Directly, on the machine that runs the stack only: `http://127.0.0.1:6080`, with the password shown on the Settings page, Screenshots group.)
4. On the phone: sign in to Google Play, install the PlayStation App, sign in to PlayStation Network. See the notes below.
5. On the PS5: Settings, Captures and Broadcasts, Captures, Auto-Upload on.
6. On the copilot's Settings tab, Screenshots group: switch "Virtual phone" on and press "Test the virtual phone". Address and token are filled in already.

## Notes from the build

- **Passkeys.** A PlayStation account that signs in with a passkey offers a QR code for another device. That needs Bluetooth, which the emulator does not have; the QR code disappears and the sign-in times out. What worked: install the passkey manager (for example 1Password) on the virtual phone, make it the passkey provider in Android's settings, and sign in with the passkey stored there.
- **Screen lock.** Android refuses passkeys until the phone has a PIN. Set one, sign in, and then leave the phone unlocked. The fetcher reports a locked phone and does not try to unlock it.
- **Sleep.** A sleeping phone shows a black web view. The container keeps the phone on mains power with the screen always on.
- **Graphics.** The default software renderer crashed the emulator when the app opened its sign-in page. The stack uses `swangle_indirect`, which did not.
- **IPv6.** The phone container is on a second network (`phone6`) that has IPv6 on purpose: without an IPv6 address the emulator's radio service uses a whole CPU core for ever. Docker on the host must therefore be able to make an IPv6 network. The rest of the stack does not need it; that network is only made with the `phone` profile.

## Using it

- Voice: "Copilot, take a screenshot".
- Page: Phone page or Screenshots page, "Fetch the newest PS5 capture".
- Agent or command line: `gt7copilot shot`.

A fetch takes about half a minute. If the newest capture is one page of the Car Settings screen and the one before it is the other page of the same car, both are used.

## The Phone page

The copilot passes the phone's web view through to its own Phone page, so the phone is used where everything else is, also when the copilot is behind https. Only the signed-in admin sees it: without the admin's sign-in the copilot refuses every request for the phone's screen.

Two settings, Screenshots group: "Virtual phone screen address" (in the compose stack `http://phone:6080`, filled in already) and "Virtual phone screen password" (in the compose stack read from the shared volume; elsewhere enter it once, or leave it empty and the screen asks).

## Keeping it private

Port 6080 is the phone's screen, with a signed-in Google and PlayStation account behind a short VNC password. The stack publishes it on the machine itself only (`127.0.0.1:6080`); from anywhere else the screen is reached through the copilot's Phone page, which needs the admin's sign-in. Do not change that to a port open on the network. The fetcher's port (6081) is not published; the copilot reaches it inside the stack with a token made on first start.
