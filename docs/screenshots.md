# Reading settings screens

The telemetry does not contain the car's settings. The copilot gets them from a picture of the game's Car Settings screen, read by a vision model.

## What can be read

- **Car Settings, page 1:** tyres, suspension, differential, aerodynamics, ECU, ballast, transmission.
- **Car Settings, page 2:** brake balance and the fitted parts.
- **Event information:** track name, laps, fuel and tyre wear rates. The track is named from it.

The model only reads. Code then checks the result: values outside what the game allows are refused, and a sheet for a car other than the one last driven is filed only when the car on the screen can be matched by name. A page fills in or replaces what is already on file for the car, so the two pages can be sent one after the other.

## Setting it up

Settings, group "Screenshots":

1. Switch "Screenshot reading" on.
2. Enter the vision model's address (the base address of an OpenAI-compatible API, ending in `/v1`), a key if the service needs one, and the model name.
3. Press "Test the vision model". The test sends a small picture and shows the answer.

Any model that accepts images works in principle. Reading a dense settings screen without mistakes needs a capable one; the build was tested with a 35-billion-parameter open model served by vLLM, which read a full page in about four seconds with no differences from a hand-filed sheet apart from the toe direction icon.

## Getting a picture in

Every route ends in the same reader. Each has its own switch in Settings, group "Screenshots", and says so when it is off. The Screenshots page keeps every picture: when, by which route, what was read, filed or why not. While a session is live the copilot also says the result in one line.

| Route | Works on | Switch |
|---|---|---|
| Upload on the page | Any browser | On from the start |
| Share sheet | Android, Chrome, page on https | "Share sheet (Android)" |
| Shortcut | iPhone and iPad; any script | "Shortcut (iPhone) or script" + a share token |
| Watched folder | Anything that can put a file in a folder | "Watched folder" |
| Agent or command line | A chat agent, for example on Telegram | The agent door ([agent.md](agent.md)) |
| Virtual phone | The `phone` profile of the stack | "Virtual phone" ([phone.md](phone.md)) |

On the PS5, captures reach the PlayStation App only when "Auto-Upload" is on: Settings, Captures and Broadcasts, Captures, Auto-Upload. A phone photo of the television works as well.

### Upload on the page

Screenshots page, "Read a screen". JPEG, PNG or WebP, up to 12 MB.

### Share sheet (Android)

The page can be installed as an app. It then appears in the phone's share sheet, so a capture goes from the PlayStation App to the copilot in two taps.

1. The page must be reached over https (a reverse proxy with a certificate). Chrome does not install pages served over plain http, and without the install there is no share target.
2. Open the page in Chrome on the phone. Menu, "Install app" or "Add to Home screen".
3. In Settings, group "Screenshots", switch "Share sheet (Android)" on.
4. In the PlayStation App: Library, Captures, open the screenshot, Share, "GT7 Copilot". The phone shows a small page with the result.

iPhones have no share target for web pages; use the Shortcut. The share sheet route has no token: like the upload, anyone who can open the page can use it.

### Shortcut (iPhone)

A Shortcut posts the picture to the copilot. Unlike the share sheet it also works over plain http on the home network.

In Settings, group "Screenshots": switch "Shortcut (iPhone) or script" on and press Generate next to "Share token". The token is shown once. It may only send pictures.

In the Shortcuts app, make a new shortcut named "Send to Copilot":

1. Shortcut details (the "i" button): switch "Show in Share Sheet" on, and set the accepted types to Images only. At the top of the shortcut an action "Receive Images input from Share Sheet" appears. Set "If there's no input" to "Continue".
2. Add "If": "Shortcut Input" "has any value".
   - Inside the If: "Set Variable", name `Picture`, value "Shortcut Input".
   - Under "Otherwise": "Find Photos" with filter "Album is PS App" (the album the PlayStation App saves into; "Recents" works too), sorted by "Date Taken", "Latest First", limit 1. Then "Set Variable", name `Picture`, value "Photos".
3. After "End If" the variable `Picture` holds the shared image when there is one, and the newest photo of the album when there is not.
4. Add "Get Contents of URL":
   - URL: `http://<machine>:8765/api/shot` (the address is shown on the Settings tab)
   - Method: POST
   - Headers: `X-GT7C-Share` = the share token
   - Request Body: File, and choose the Picture variable
5. Add "Get Dictionary Value": get the value for `reply` in "Contents of URL".
6. Add "Speak Text" (or "Show Notification") with that value.

Using it:

- From the PlayStation App or Photos: Share, "Send to Copilot".
- With a headset on: "Hey Siri, Send to Copilot". With no shared picture the shortcut sends the newest photo of the album. The PlayStation App must have saved the capture to Photos first (open the capture, Download).

The same request from any script: `curl -H "X-GT7C-Share: $TOKEN" --data-binary @shot.jpg http://<machine>:8765/api/shot`. The answer is `{"ok": true|false, "reply": "..."}`. A form upload (`-F image=@shot.jpg`) is accepted too.

These steps were written from Apple's documentation of the Shortcuts actions and have not been run on a phone during the build; the request itself is covered by the tests.

### Watched folder

Switch "Watched folder" on. The default folder is `inbox` in the data volume; another full path can be set. A picture that appears there is read once its size has stopped changing for two seconds, then moved to `done`. One that cannot be filed moves to `failed`, with a text file of the same name saying why. Other files are left alone.

Ways to fill the folder: Syncthing on the phone syncing the PlayStation App's picture folder, a NAS photo app's upload folder, or any sync tool. To watch a folder outside the data volume, mount it into the container (see the commented line in `compose.yaml`) and enter its path in Settings.

While screenshot reading or the folder route is off, pictures stay where they are.

### Agent or command line

`gt7copilot shot-file picture.jpg`, or `gt7copilot shot` for the virtual phone. A chat agent that receives a photo saves it and runs `shot-file`. See [agent.md](agent.md).

### Virtual phone, by button or by voice

"Read new PS5 screenshots" on the Screenshots page, "Copilot, read my screenshots", or `gt7copilot shots-new`: the copilot goes through the PlayStation App's captures from the newest back to the first one it has already read and files what they show, one sheet per car. Capture both Car Settings pages of several cars, then read them in one go; a car that was never driven is added to Cars. "Look back at older ones" (`gt7copilot shots-new back`) goes through the whole list. Each capture takes about a quarter of a minute; the page shows the steps.

"Read the newest again" on the Screenshots page, "Fetch the newest PS5 capture" on the Phone page, or "Copilot, take a screenshot" reads only the newest capture, also when it was read before. See [phone.md](phone.md).
