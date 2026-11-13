# Voice

## The copilot's voice

The calls are spoken by a local text-to-speech model (Kokoro) inside the copilot container. Nothing is sent anywhere. Each sentence is made once and kept in the data volume.

The calls can be heard in two places, also both at once:

- **The page.** Any browser on any device: open the page, press Start audio. Browsers only play sound after that press.
- **The earpiece.** A program on a Windows sim PC or a Mac that plays into one chosen audio device. See [earpiece.md](earpiece.md).

Settings, group "Copilot voice": on or off, corner calls per lap, and the voice name (any Kokoro voice, for example `bm_george`, `am_michael`).

## Voice control

Spoken commands come from the microphone of the earpiece. The earpiece cuts the sound into utterances and sends each to the copilot, which has it written down by a speech-to-text service and matches it against a short list of commands by rule.

Only sentences that start with the wake name are acted on. The default name is "copilot".

| Say | Answer |
|---|---|
| fuel | level, use per lap, laps left, whether a stop is needed |
| tyres | four temperatures |
| best lap, last lap, gap, which lap | times and position in the race |
| where am I losing time | the two costliest corners |
| what should I change | setting changes from the laps |
| take a screenshot | fetches and reads the newest PS5 capture (needs the virtual phone) |
| read my screenshots | reads every PS5 capture not read before and files one sheet per car |
| what should I set the rear differential at / front camber / brake balance / read me the suspension | the value on the car's sheet, and what to set it to when the laps ask for a change |
| read me the settings | every change the laps ask for |
| recommended fuel mix / lean or rich? | which fuel map to run, and why |
| how's the track? | its name, length, corners, your best lap there, where the time goes |
| I'm staying rich / I'm staying lean | noted: the fuel calls follow what you run (told, not asked) |
| I will pit on lap eight / in two laps / next lap | noted if the fuel reaches that lap; the countdown then follows your lap |
| let's race | acknowledged, with the track and the number of laps |
| repeat, quiet, talk, help | |

Commands can be tried without a microphone: `gt7copilot hear "copilot, fuel"`.

### Setting it up

1. Start the speech-to-text container: add `voice` to `COMPOSE_PROFILES` in `.env`, then `docker compose up -d`. The container starts without a model: the **Test** button next to the speech-to-text settings (step 2) has it downloaded, about 500 MB, which can take a few minutes. Without the test, the first spoken sentence starts the download and is lost.
2. Settings, group "Voice control": switch it on. The address of the bundled service is filled in already. Press "Test speech-to-text".
3. Install or update the earpiece.

Any service with an OpenAI-compatible `/v1/audio/transcriptions` endpoint can be used instead: enter its address, key and model name.

### Talking without the name, and open questions

With "No name needed while driving" on (Settings, Voice control), the wake name can be left out while the car is on track: "how is the fuel", "what should I change". Off the track the name is needed, so talk in the room is not taken for a command. Without the name the copilot only reacts to a fixed command or to a sentence that asks something; noise, single stray words and its own calls are ignored.

A question that is not a fixed command goes to the Ask model (group Ask must be on) and is answered in a sentence or two: "is the rear too soft?", "what time is it?". About the car and the laps it only uses the driver's own data.

### How a sentence is understood

With the Ask model on, the model says what a sentence of three words or more means, and the app answers: its own figures for read-outs, settings, fuel and pit plans, the model's words for everything else. Keyword rules handle one- and two-word requests and take over when the model is off. `tools/voice_eval.py` measures the model on about a hundred sentences; run it after changing the prompt or the model.

### The wake name

Speech-to-text writes an unusual name in many ways. The setting takes a comma-separated list: the name and every way it is written. A short invented name needs a long list; an ordinary word needs one or two entries.

### Known behaviour

- An open microphone puts Bluetooth earbuds into call mode, so the copilot's own voice sounds like a phone call.
- The earpiece does not listen while the copilot speaks.
