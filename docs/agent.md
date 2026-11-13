# Agents and the command line

Everything the copilot knows can be read, and sheets, tunes and tuning notes can be filed, through one door: `POST /api/cli` with a bearer token. A chat agent (on Telegram or anywhere else) with this door can debrief a session, recommend a setting change, file a tune the driver sends, and ask for a screenshot of the settings screen.

## Switching it on

Settings, group "Agent door": switch it on, generate a token, Save. The token is shown once. Rotating it stops the old one at once.

## The client

`agent-skill/gt7copilot` is a single file that needs only Python. It sends a command through the door and prints the JSON answer.

```sh
export GT7C_URL=http://machine:8765
export GT7C_TOKEN=...            # or ~/.config/gt7copilot.json: {"url": "...", "token": "..."}
./agent-skill/gt7copilot brief
./agent-skill/gt7copilot help
```

Without the client: `curl -H "Authorization: Bearer $GT7C_TOKEN" -d '{"argv":["brief"]}' $GT7C_URL/api/cli`.

On the machine that runs the stack the same commands work without a token: `docker compose exec copilot python3 -m gt7copilot brief`.

## The skill

`agent-skill/SKILL.md` follows the [Agent Skills](https://agentskills.io/specification) layout. It tells an agent which command to use for what, in what order to trust the sources, and the rules that keep it honest: numbers come from the copilot, one change at a time, never invent a tune. Copy the folder into the agent's skills.

## Commands, in short

| Command | Use |
|---|---|
| `brief [CAR]` | Everything about one car in one answer: specs, sheet, baselines, library tunes, earlier changes, advice |
| `debrief [SESSION]`, `advice` | After a session: laps, corners, car behaviour, what to change |
| `features` | Which optional parts are on and usable |
| `shot`, `shot-file IMAGE` | Read a settings or event screen: from the virtual phone, or from a picture file |
| `tune-set`, `tune-show`, `sheet-template` | The settings sheet on a car |
| `lib-add`, `lib-list`, `lib-show`, `lib-verdict` | The tune library |
| `know`, `know-add`, `experiments` | Tuning datapoints and what the driver's own changes did |
| `say "text"`, `hear "copilot, fuel"` | Speak through the copilot; try a voice command |

## A photo sent to the agent

A photo the driver sends to the agent (for example in a Telegram chat) is handed in with `shot-file`: the agent saves the attachment to a file and runs `gt7copilot shot-file /path/to/photo.jpg`. Over HTTP without the client, the picture goes base64-encoded in the command: `{"argv": ["shot-file", {"image_b64": "..."}]}`. The same holds for `tune-set`, `lib-add` and `know-add`: the client reads the file and sends its JSON; over HTTP the JSON object stands where the file name would be. The door never opens a file on the copilot's machine: a path there is refused ("send the JSON, not a path"). `features` shows under `screenshot_routes` which ways in are switched on; `shot-file` uses the `upload` route.

## What the token allows

Reading everything, filing sheets, tunes and datapoints, making the copilot speak, and reading screenshots when that part is on. It cannot change settings, read tokens and keys, or read files on the copilot's machine.
