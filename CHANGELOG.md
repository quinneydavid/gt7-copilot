# Changelog

## 0.13.3
Page layout only.

- Live: the tiles are five to a row on a desktop (seven before), and names in a tile (status, car, track, tune) are set in smaller type than numbers, so a car name no longer wraps over three lines.
- Track: the Corners table fits its card on a desktop and no longer scrolls sideways there.
- Every page can be scrolled until its last card is clear of the Ask button.
- README: what the copilot does, with tuning from a screenshot and talking to it described first.

## 0.13.2
- The two GitHub workflow files failed to load (a colon inside two unquoted step names), so 0.13.1 was never tested or built there. No change to the app. This is the first version with published images.

## 0.13.1
The first version published on GitHub. Fixes from a review before publication; no new features.

Security:

- **The agent door reads no files.** `tune-set`, `lib-add`, `know-add` and `shot-file` sent through `POST /api/cli` with a file name instead of the JSON opened that file on the copilot's machine, so a holder of the agent token could file `settings.json` as a sheet and read it back. Over the network a path is now refused ("send the JSON, not a path"). The command line on the machine itself, and the agents' client, read files as before and send their content.
- **The earpiece installer needs the admin's sign-in.** `/earpiece/setup.ps1` and `/earpiece/setup-mac.sh` were handed to anyone, with the earpiece token inside. They are now downloaded from the Settings page while signed in. The address written into the script is refused unless it looks like a host name or address.
- **Requests from other websites are refused.** Speaking a line, muting and typed voice commands were GET requests, and uploads had no check, so a page from elsewhere open in a browser on the home network could trigger them. `/api/say`, `/api/enable` and `/api/heartext` are now POST only, and they, `/api/screenshot` and `/api/screenshots/read` need the header `X-GT7C: 1` (the page and the command line send it) or the agent token. `/api/shot` (share token) and `/share` are unchanged.
- **Sign-in lockout per address.** Ten wrong passwords lock out the address they came from, not everybody: one client on the network can no longer keep the admin out.
- **The virtual phone's web view** (port 6080) is published on the machine itself only. From the network it is reached through the Phone page, for the signed-in admin.
- `GT7C_ADMIN_PASSWORD` is documented: set at first start, it closes the window in which anyone on the network could choose the admin password.
- Documented plainly: the Windows earpiece runs as SYSTEM from a folder the installing user can write (docs/earpiece.md, SECURITY.md). A new Windows install has `start_simhub` off.

Other:

- compose: the phone container's CPU limit is `PHONE_CPUS` (default 4, was a fixed 8 that Docker refuses on a smaller host) and `PHONE_CORES` defaults to 4. IPv6 is on a network of the phone's own, so the stack without the phone starts on a host where Docker has no IPv6. After updating, run `docker compose down` once before `docker compose up -d`: the old network has to go (the volumes stay).
- The image has a health check, and carries the licence and `THIRD-PARTY-NOTICES.md`, a new file with the licences of the bundled data and of what the image contains.
- `gt7copilot.__version__` exists (the release workflow reads it) and is in the start line of the log. CI also builds the phone image.
- A sheet filed through the command line or the agent door is marked `agent` (was `bot`; old rows keep their mark).
- The README has pictures of the page, made from simulated data. `tools/demo` holds what makes them: `sim.py`, a simulated car that sends telemetry like a console (also a way to try the copilot without a PlayStation), `make_demo.py`, which fills a data folder with demo sessions, and `shots.py`, which takes the pictures again. None of it is in the image.
- `tools/voice_eval.py` takes the model as an argument and defaults to a local address. Two test suites that had fallen behind the code pass again.

Found when the stack was first run from a clean copy:

- **The bundled speech-to-text container has no model when it starts**, and does not fetch one by itself. The copilot now asks it to download the model named on the Settings tab: when "Test speech-to-text" is pressed, or at the first sentence if the test was skipped.

## 0.13.0
The voice no longer guesses from single words.

- **The model decides what a sentence means.** Until now keyword rules went first, and each new phrasing found a new hole: "I'm tired" was taken for a tyre stop, "did you get the screenshot?" fetched a new one, "is the fuel going to last" was filed as a pit plan. With the Ask model on, every sentence of three words or more goes to the model, which names what is meant (a fuel read-out, a setting, a pit plan with its lap, an order for a screenshot, something told, small talk, not for the copilot) and answers the open ones itself. The figures still come from the app: read-outs, settings, fuel verdict and pit logic are the same code as before. One or two words ("fuel", "be quiet") stay with the instant rules, and the rules remain the fallback when the model is off or does not answer.
- Measured on the local model with `tools/voice_eval.py` (about a hundred sentences with the meaning each should get): 98 of 102 right in 0.65 s each, against about 70 with the rules; with the open microphone all ten room-talk sentences ignored and all eight race sentences answered. Where the model answers itself although the app has the exact answer (fuel map, worst corner, a named setting), the app's answer is used.
- Earpiece 0.3.4: a call is held for up to two and a half seconds while the driver is speaking, instead of talking over them and making the microphone deaf in the middle of their sentence.

## 0.12.4
- Voice: a question of more than four words that only contains a fixed command's word goes to the model ("what tyres should I be on?" had been answered with the tyre temperatures). Short read-outs ("tyres", "how is the fuel") stay fixed.
- Voice: a sentence that starts by telling something and ends with a question ("actually it is raining, what should I do?") is remembered for the session like any other thing the driver tells.

## 0.12.3
From the transcript of a real race with the open microphone and the model answering.

- The radio's manner: it is "Copilot", answers like a friend on the radio, takes small talk and off-topic questions, never tells the driver to focus, and answers only what was asked ("what's the time" gets the time).
- What it cannot see, it no longer makes up: weather, rain, other cars, positions, damage, tyre wear. Told "it's raining", it believes the driver, gives one practical tip and remembers it for the session.
- Fuel questions are answered from the app's own fuel verdict instead of the model's arithmetic.
- "talk" and "quiet" only act on a short request, and "talk" only when the copilot is muted: "How's my speed, copilot?" had been answered "Talking again." three times.
- The name at the end of a sentence counts ("how's my speed, copilot"). A mis-heard name followed by a comma and a fixed command counts too ("Pollock, can you hear me?").
- In a conversation (the twelve seconds after an answer) a statement needs no name either.
- A model's answer is spoken sentence by sentence, so the first words come sooner.

## 0.12.2
- Voice, the name by its sound: speech-to-text keeps finding new ways to write "Copilot" ("Kaupala", "Coppola", "Hi pilot"). When none of the known spellings fits, the first word or two are compared by their consonants, so these count as the name without a list of every spelling.
- Voice, a conversation: for twelve seconds after the name was said or an answer given, the next sentence needs no name. "Copilot." - "Yes?" - "Can you hear me?" - "Yes. I hear you."

## 0.12.1
- Voice: a longer question that only contains a fixed command's word ("which of my cars is fastest at Big Willow") is answered by the model instead of triggering that command's read-out. Short requests ("fuel?", "what's my best lap") stay with the fixed commands.

## 0.12.0
- **Talk to it.** A spoken question that is not one of the fixed commands is answered by the Ask model in a sentence or two: about the car, its settings, the laps, fuel and tyres from the driver's own data and the car's state at that moment; anything else (the time, a general question) briefly from what the model knows. It remembers the last few exchanges for a follow-up. Needs Ask switched on; without it the answer stays "Say again?".
- **No name needed while driving** (Settings, Voice control, off by default; `GT7C_VOICE_OPEN_LIVE`). While the car is on track, commands and questions are taken without the wake name. What speech-to-text makes of noise ("Thank you.", "Bye."), single stray words, sentences that ask nothing and the copilot's own calls coming back through the microphone are ignored. Off the track the name is still needed.

## 0.11.3
- Voice, the name: "Coppola", "Hi pilot", "Pilot" and a few more ways speech-to-text wrote "Copilot" are heard as the name, and the name is given to the speech-to-text service as a spelling hint.
- Voice: "can you hear me?", "are you there?", "radio check" are answered "Yes. I hear you." The name alone is answered "Yes?" at most once in twenty seconds.

## 0.11.2
- `GT7C_TRUST_DOOR=1`: for an installation where a sign-in (single sign-on, a proxy with a login) already stands in front of every way to the page. Everyone who comes through the page's door is then the admin: Settings, the phone's screen and the admin buttons open without the copilot's own password. The earpiece and the agent door never count as the admin. Leave it off when the page is open on the network.

## 0.11.1
- A track's page always has its Name / Rename button; naming a track no longer needs the admin sign-in. An empty name takes the name away, and the copilot may then name the track again from its outline.

## 0.11.0
- **Tracks name themselves.** The game sends no track name, but its coordinates are fixed per track. The copilot now lays the driven line over 85 known outlines (`data/circuits.json`, from the circuit inventory of zetetos/gt-telemetry, MIT) and names a new track when the first full lap is done, layout and direction included ("Autodrome Lago Maggiore - East (Reverse)"). It says so once: "Track recognised. ...". During that first lap the Live page shows which track it looks like, without the layout, as soon as only one track still fits. Tracks driven earlier and never named get their names at the next start.
- A name from an event screenshot replaces a name from the outline; a name typed on the track's page is never replaced. A track that fits no outline is left "not named yet", as before.
- `tools/build_circuits.py` rebuilds the outline file from a checkout of the source.

## 0.10.2
- Reading a sheet: a Front/Rear Torque Distribution of 0:100 is accepted (three digits were refused).
- Reading a sheet: a differential value of 0 (what the game shows at the end without a driven axle, for example the front of a mid-engined car) is filed as "no value there". It was taken for a misread and the whole first page of such a car was refused.

## 0.10.1
From the first real use of 0.10.0 and the voice log of a real race.

- Reading new screenshots: a capture is now recognised by the picture alone. The PlayStation App names every download after the time of the download and writes that time into the file, so neither the name nor the file as a whole said whether a capture had been read; the first real run read seven old ones again. Pictures already kept get their fingerprint on the first run.
- Reading a sheet: a value the reader leaves out keeps what is on file. A differential read as empty had blanked the differential on the sheet.
- Virtual phone: the fetcher scrolls the captures list, so captures past the seventh are reached (up to thirty); the later captures of a batch are taken from the list as it stands (about 10 s each instead of 16).
- Voice, the name: "Go pilot", "No pilots", "Copilots" and a leading "Right," / "So," are heard as the name.
- Voice, telling the copilot the plan: "I'm staying rich" / "I'm staying lean" (it answers what that means for the fuel and stops asking for the lean map when you stay rich), "I will pit on lap eight" / "in two laps" / "next lap" (it checks the fuel reaches that lap, then counts down to your lap instead of its own), "I need to pit for tyres", "let's race".
- Voice, new questions: "recommended fuel mix" / "lean or rich?" (which map and why), "how's the track?" (name, length, corners, your best, where the time goes).
- Earpiece 0.3.3: the microphone is deaf while the copilot speaks (it had been sending the copilot's own calls back as speech); silence is no longer logged.

## 0.10.0
- **Read new PS5 screenshots**: one button on the Screenshots page (and "Copilot, read my screenshots", `gt7copilot shots-new`). Press Create on the settings screens of as many cars as you like, then read them in one go: the copilot goes through the PlayStation App's captures from the newest back to the first one it has already read, reads each, and files one sheet per car (both pages when both were captured). The car is taken from the name on the screen, so a car that was never driven is added to Cars with its figures. Event screens are noted. The page shows each step and links to the cars filed. "Look back at older ones" goes through the whole list and reads what was never read. A capture is recognised by its id in the app and by the picture itself, so nothing is read twice; the time the console wrote into the picture is kept.
- **Ask for a setting by voice**: "Copilot, what should I set the rear differential at?", "front camber?", "what is the brake balance?", "read me the suspension". The answer is the value on the car's sheet and, when the laps ask for a change, what to set it to. "Copilot, read me the settings" reads every suggested change. Not driving, it answers for the car whose sheet was filed last.
- Virtual phone: the fetcher reaches the twelfth capture in the list (was the sixth).

## 0.9.2
- Live: SimHub has its own tile. It shows whether SimHub is running on the sim PC, whether it is set to Gran Turismo 7, and whether it is receiving the car's data. Red when it is not running; yellow when it is set to another game, does not answer, or gets no data while the car is on track.
- Live: a PlayStation tile. The copilot asks the console every ten seconds whether it is on (the question the PlayStation App asks, UDP port 9302): On, Rest mode, or Off after three questions without an answer. It also says whether Gran Turismo 7 is sending data. `gt7copilot status` carries the same as `console`.
- Earpiece 0.3.2: an open microphone that delivers nothing for five seconds is opened again; what was heard without the wake name is noted in the log.
- Earpiece (Windows): asks SimHub's own local web API (`simhub_api` in `earpiece.json`, default `http://127.0.0.1:8888`) for the game and the data state, and reports them. Run the installer again to update.

## 0.9.1
- Ask: "take a screenshot" in the chat fetches the newest PS5 capture through the virtual phone, reads it, files it, and shows the picture with what was read.

## 0.9.0
- **Ask**: a chat on every page. A question in plain words is answered by the configured model from facts the app works out itself: totals, the car and track on the page (or named in the question, or last driven), the settings on the car, the changes the laps ask for with their numbers, what earlier changes did, the latest session, and sourced guide statements about settings the question names. The model is told to use nothing else and to say what is missing. Nothing is stored. Off until switched on in Settings (group Ask); uses the model address and key of the Screenshots group, with its own model name if wanted. Also `gt7copilot ask "..."` for agents.
- Virtual phone: a fetch no longer restarts the PlayStation App when it is already on its captures list. It pulls the list down to reload it and takes the picture from there (about 15 s instead of 26 s). `GRAB_FRESH=1` on the phone container brings the restart back for every fetch.

## 0.8.0
The page was rebuilt around what a driver looks for: a car, a track, a session.

- **Home**: laps, distance and time driven, most driven cars and tracks, laps per day, the latest sessions, the best lap in each car on each track, and what to change next on the car last driven.
- **Cars**: one card per car, with a search over every car in the game. A car's page has its figures and best laps, its settings laid out like the game's Car Settings screen (both pages), every sheet saved with what changed, what those changes did to the lap times, the suggested tune (the sheet with the changes the laps ask for, from any recent session), the library tunes, and its sessions. The Garage and Tunes tabs are gone; their content is here.
- **Tracks**: every track driven, with its outline. A track's page has the map with corner numbers, the cars driven there ranked by best lap, the fastest car and the tune that set the time, suggested changes from the laps there, corner figures, events seen, and the sessions. The admin can name a track on the page.
- **Sessions**: grouped by day, filtered by car and track. Tune advice moved to the car's page; a session links to it.
- **Screenshots**: every picture the copilot reads is now kept (`shots/` in the data folder) and shown with what it was, which car, how it came in and what was done with it. The admin can delete a picture or make it a car's picture.
- **Phone**: the virtual phone's screen inside the page, for the signed-in admin. Two new settings: the phone's screen address and its password. The copilot passes the phone's web view through, so the page works over https and the phone's port no longer has to be opened in a browser.
- One dark look throughout. Audio controls moved to the Live page; the top bar shows whether the car is on track.
- New data calls for the page: `/api/overview`, `/api/cars`, `/api/car`, `/api/tracks`, `/api/track`, `/api/shots`, `/api/phone`.

## 0.7.0
The first version prepared for release: one stack, settings on the page, no file to edit.

- Screenshot inbox: one reader, more ways in, each with its own switch. The page installs as an app and appears in the Android share sheet (https only); an iPhone Shortcut or a script posts to `/api/shot` with a share token; a watched folder reads pictures that a sync drops in and moves them to `done` or `failed`. The Garage tab lists the last results, and the copilot says the result while a session is live.
- Earpiece for Mac: the same program with a macOS layer, installed by `setup-mac.sh` from the Settings tab as a LaunchAgent of the signed-in user. Not yet run on a real Mac.
- The earpiece program is 0.3.0. The Settings group is now called "Earpiece".

## 0.6.0 (not published)

- Named GT7 Copilot. Python package `gt7copilot`, wake name "copilot" (a setting).
- Settings tab: console address with Test and Find, voice, voice control, screenshots, virtual phone, PC earpiece and agent door. Each optional part has an on/off switch and says so when it is off. Settings are stored in the data volume and apply without a restart. An admin password protects them.
- Screenshots without the virtual phone: upload a picture on the Garage tab, or `gt7copilot shot-file`. `gt7copilot shot` fetches through the phone. `gt7copilot features` lists what is on.
- One `compose.yaml`: the copilot, the virtual phone (profile `phone`) and speech-to-text (profile `voice`). The phone's token and web view password are made by the stack.
- A dependency-free client for agents (`agent-skill/gt7copilot`).
- The virtual phone asks for `ANDROID_LICENSES=accept` before downloading the Android SDK.
- Environment variables are first-start defaults only; the console address has no built-in default.
- A screenshot that cannot be filed (wrong screen, value outside the game's limits, unknown car) is reported as a failure to the page and to agents.

## 0.5.x and earlier
Private development: telemetry recorder, track recognition, corner analysis, spoken calls, fuel and pit strategy, tune advice from car behaviour, tune library, tuning datapoints, PC earpiece, voice control, PS5 screenshot reading through a virtual phone.
