# Ask

A chat on every page of the copilot. The button sits in the bottom right corner once Ask is switched on.

Examples: "What should I change on the car next?", "Where am I losing the most time?", "Which of my cars is fastest at this track?", "How consistent was my last session?", "What does the rear anti-roll bar do?"

## How an answer is made

The model is not given the database or the telemetry, and it is told not to use what it knows about cars and tracks. For each question the app works out a set of facts, the same figures the pages show, and the model puts them into words:

- **Driving**: totals, the cars and tracks driven, the best lap in each car on each track, the latest sessions.
- **Cars**: the car on the page you are on, cars named in the question, or the car last driven. Its figures, the settings on it, the changes the laps ask for (with the value now and the value to try), what earlier changes did to the lap times, and tunes on file.
- **Tracks**: the track on the page or named in the question. Your cars ranked by best lap, and where the time goes corner by corner in the fastest one.
- **Session**: the session on the page, or the latest. Laps, consistency, the costliest corners, how the car behaved.
- **Guides**: when the question names a setting (camber, toe, anti-roll bar, differential and so on), the filed guide statements about it for the car's layout, each with its source.
- **Live**: what the car is doing now, when it is on track.

When the facts do not cover a question, the model is told to say what is missing rather than guess. It can still be wrong: check a change against the Suggested tune page, which shows the same numbers without a model in between.

## Taking a screenshot

"Take a screenshot" (or "grab the screenshot", "read the settings screen") in the chat does what the voice command and the buttons do: the newest PS5 capture is fetched through the virtual phone, read and filed, and the chat says what was read and shows the picture. It needs the virtual phone. A question about screenshots ("how do I take a screenshot?") is answered as a question.

Nothing is stored. The last few turns are kept in the browser so a follow-up question works, and are gone when the page is closed.

## Setting it up

Settings, group **Ask**: switch it on. It uses the model address and key of the Screenshots group. "Model for Ask" may name a different model at that address; empty means the vision model. A model of the size that reads the settings screens well also answers well; a very small model tends to ignore the rule about using only the facts.

Agents and the command line: `gt7copilot ask "what should I change next?"`.

## Who can ask

Anyone who can open the page, like the other driving pages. A question costs one model call; one question is answered at a time.
