# The console and its telemetry

Gran Turismo 7 sends telemetry to any machine on the local network that asks for it. Nothing has to be switched on in the game.

## How it works

1. The copilot sends a one-byte "heartbeat" to the console on UDP port 33739, once a second while packets arrive and every five seconds otherwise.
2. While the game is on track, in a race or a replay, the console answers with about 60 packets a second.
3. The answers go to UDP port **33740** on the machine that sent the heartbeat. The port is fixed; it is not the port the heartbeat came from.

Menus and paused races send nothing, or packets that are skipped.

## The address

The console's address is under Settings, Network, View Connection Status on the PS5. A fixed address (a DHCP reservation on the router) avoids having to change it later.

On the copilot's Settings tab:

- **Test** sends a heartbeat to the address on the form and waits four seconds for telemetry. The game must be on track.
- **Find the console** asks the whole network and reports who answers. A container on Docker's default network cannot do this; it needs `network_mode: host` (see the comment in `compose.yaml`).

## Packet type

Type B adds the steering angle and is the default. If packets arrive but cannot be read for five seconds, the copilot falls back to type A by itself and says so in its log.

## Firewalls and networks

- From the copilot to the console: UDP 33739.
- From the copilot to the console: UDP 9302, for the Live tab's PlayStation tile (On / Rest mode / Off). The answer is a reply to the question, so no extra rule is needed for the way back. If this port is blocked the tile says Off until telemetry arrives.
- From the console to the copilot: UDP 33740. A firewall between two home networks (for example a separate network for consoles) needs a rule for this direction; it is not seen as a reply to the heartbeat because the port differs.
- With Docker's default network the port is published by `compose.yaml`. Only one program on the machine can listen on 33740.
- On Kubernetes the pod's outgoing address must be the address the Service receives on. Pinning the pod to one node and giving the Service that node's address as an external IP works.

## More than one console

One copilot follows one console.
