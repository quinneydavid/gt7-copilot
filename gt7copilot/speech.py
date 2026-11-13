"""Words for the copilot: numbers a voice can read, and the calls. Plain instructions only, like a real co-driver:
no jokes, no character."""

ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "x x twenty thirty forty fifty sixty seventy eighty ninety".split()


def words(n):
    n = int(round(n))
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])
    if n < 1000:
        return ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " and " + words(n % 100))
    return str(n)


def one_dp(x):
    """12.4 -> 'twelve point four', 10.0 -> 'ten'."""
    x = round(float(x), 1); whole, tenth = int(x), int(round((x % 1) * 10)) % 10
    return words(whole) + (f" point {words(tenth)}" if tenth else "")


def gap(sec):
    """0.12 -> 'a tenth', 0.34 -> 'three tenths', 1.25 -> 'one point two seconds'."""
    sec = abs(sec)
    if sec < 0.05:
        return "nothing"
    if sec < 0.95:
        t = max(1, int(round(sec * 10)))
        return "a tenth" if t == 1 else f"{words(t)} tenths"
    return f"{words(int(sec))} point {words(int(round((sec % 1) * 10)) % 10)} seconds"


def lap_time(ms):
    """105049 -> 'one forty five point zero'."""
    s = ms / 1000.0
    m, sec = int(s // 60), s % 60
    whole, tenth = int(sec), int((sec % 1) * 10)
    secs = ("oh " + words(whole)) if (m and whole < 10) else words(whole)
    return (words(m) + " " if m else "") + f"{secs} point {words(tenth)}"


def pre_corner(a):
    n = words(a["n"])
    c = a["cause"]
    if c == "incident":
        return f"Turn {n}. Careful. You lost {gap(a['loss'])} here last lap."
    if c == "brake_early":
        return f"Turn {n}. Brake {words(a['metres'])} metres later."
    if c == "brake_late":
        return f"Turn {n}. Brake {words(a['metres'])} metres earlier. You overshot it."
    if c == "apex_slow":
        t = a.get("target") or a.get("ref_min_speed")      # the next step up, not the all-time best
        tgt = f" Target {words(t)}." if t else ""     # always say the unit: "four more" meant nothing
        return f"Turn {n}. {words(a['kmh']).capitalize()} kilometres an hour faster at the apex.{tgt}"
    if c == "throttle_late":
        return f"Turn {n}. Back on the power {words(a['metres'])} metres sooner."
    if c == "exit_slow":
        return f"Turn {n}. Exit {words(a['kmh'])} kilometres an hour faster."
    return f"Turn {n}. You lost {gap(a['loss'])} here."


def verdict(n, vs_ref, vs_last):
    """vs_ref / vs_last: seconds against the best / the previous lap in turn n (negative = faster)."""
    t = f"Turn {words(n)}"
    if vs_ref <= 0.03:
        return f"{t}. Matched your best."
    if vs_last <= -0.05:
        return f"{t}. Better. {gap(vs_last).capitalize()} gained."
    return f"{t}. Still {gap(vs_ref)} down."


def lap_line(ms, best_before):
    if best_before is None:
        return f"Lap time, {lap_time(ms)}."
    d = (ms - best_before) / 1000.0
    if d < 0:
        return f"New best. {lap_time(ms)}."
    if d < 0.05:
        return f"{lap_time(ms)}. Matched your best."
    return f"{lap_time(ms)}. {gap(d).capitalize()} off your best."


def tune_line(lib_tune, lib_count, sheet_on_file):
    """Said once as a session starts: which tune the copilot thinks is on the car, or that the library has some for it."""
    if lib_tune:
        who = f" by {lib_tune['author']}" if lib_tune.get("author") else ""
        proven = " It has worked for you before." if lib_tune.get("verdict") == "good" else ""
        return f"You are on the {lib_tune['title']} tune{who}.{proven}"
    if lib_count and not sheet_on_file:
        return f"I have {words(lib_count)} {'tune' if lib_count == 1 else 'tunes'} on file for this car. Ask me after the session."
    return None
