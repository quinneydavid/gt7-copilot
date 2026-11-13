"""Turns the packet stream into sessions and laps, stores them, and feeds listeners (the copilot)."""
import json, time
import numpy as np
from . import analysis as A, library as L
from . import circuits as CI
from .packet import C, F_ON_TRACK, F_PAUSED, F_LOADING

SESSION_GAP = 300.0         # seconds with no on-track data = new session
MIN_LAP_FRAMES = 60 * 15    # ignore "laps" shorter than 15 s
STANDING_KMH = 80.0         # a lap that starts slower than this is a standing start or an out-lap: not a reference
                            # (a rolling start crosses the line at ~150 km/h and is a fair lap: real laps, 11 Nov 2026)


class Collector:
    def __init__(self, store, log=print):
        self.store, self.log = store, log
        self.listeners = []                 # objects with on_frame(c, row, meta) / on_lap(c, lap) / on_session(c)
        self.session = None; self.track = None; self.ref = None
        self.buf = []; self.lap_no = None; self.meta = {}; self.last_wall = 0.0; self.last_ms = None
        self.live = False; self.car = None; self.session_laps = []; self.row = None; self.best_zones = None
        self.guess = None                   # the track this looks like, while the first lap is not done yet
        self.track_news = None              # a track the copilot has just named from its outline (said once)
        self.tune = None; self.lib_tune = None; self.lib_count = 0     # sheet on file / library tune on the car / tunes on file for the car

    # ---- stream -------------------------------------------------------------------------------------------------
    def feed(self, row, meta, wall=None):
        wall = wall or time.time()
        fl = meta["flags"]
        self.meta = meta
        if not fl & F_ON_TRACK or fl & (F_PAUSED | F_LOADING):
            self.live = False
            return
        self.live = True; self.row = row
        lap = meta["lap"]
        if (self.session is None or meta["car"] != self.car or wall - self.last_wall > SESSION_GAP
                or (self.lap_no is not None and lap < self.lap_no)):
            self._new_session(meta, wall)
        self.last_wall = wall
        if lap != self.lap_no:
            if self.lap_no is not None and self.lap_no >= 1 and lap == self.lap_no + 1:
                self._finish_lap(meta["last_ms"])
            self.buf = []; self.lap_no = lap
        if lap >= 1:
            self.buf.append(row)
            if self.track is None and len(self.buf) % 300 == 0:          # every five seconds until the track is known
                self._guess()
        for l in self.listeners:
            l.on_frame(self, row, meta)

    def _new_session(self, meta, wall):
        if self.session and not self.session_laps:       # a restart or a menu hop: nothing was driven, keep no trace of it
            self.store.x("DELETE FROM sessions WHERE id=? AND NOT EXISTS (SELECT 1 FROM laps WHERE session_id=?)", self.session, self.session)
        elif self.session:
            self.store.x("UPDATE sessions SET ended=? WHERE id=?", self.last_wall, self.session)
        self.guess = None
        self.car = meta["car"]; self.track = None; self.ref = None; self.best_zones = None; self.buf = []; self.lap_no = None; self.session_laps = []
        self.session = self.store.x("INSERT INTO sessions(started,car,total_laps,meta) VALUES(?,?,?,?)", wall, self.car,
                                    meta["total_laps"], json.dumps(dict(gear_ratios=meta["gear_ratios"], top_ratio=meta["top_ratio"],
                                                                        rpm_alert=meta["rpm_alert"], fuel_cap=meta["fuel_cap"])))
        try:                                             # which tune is on the car (never worth losing a session over)
            self.tune, self.lib_tune = L.on_car(self.store, self.car, meta["gear_ratios"])
            self.lib_count = self.store.q("SELECT COUNT(*) n FROM library WHERE car=?", self.car)[0]["n"]
            self.store.x("UPDATE sessions SET tune_id=?, library_id=? WHERE id=?", self.tune and self.tune["id"],
                         self.lib_tune and self.lib_tune["id"], self.session)
        except Exception as e:
            self.tune = self.lib_tune = None; self.lib_count = 0; self.log(f"tune lookup failed: {e!r}")
        self.log(f"session {self.session} car {self.car} tune {self.lib_tune and self.lib_tune['title']}")
        for l in self.listeners:
            l.on_session(self)

    # ---- laps ---------------------------------------------------------------------------------------------------
    def _finish_lap(self, time_ms):
        if len(self.buf) < MIN_LAP_FRAMES:
            return
        fr = np.asarray(self.buf, dtype=np.float64)
        first = 1 if float(fr[0, C["speed"]]) * 3.6 < STANDING_KMH else 0     # standing start or out-lap
        if time_ms is None or time_ms <= 0:
            time_ms = int(A.lap_time_axis(fr)[-1] * 1000)
        lap_id = self.store.x("INSERT INTO laps(session_id,lap_no,time_ms,car,started,first,fuel_start,fuel_end,frames) VALUES(?,?,?,?,?,?,?,?,?)",
                              self.session, self.lap_no, int(time_ms), self.car, time.time(), first,
                              float(fr[0, C["fuel"]]), float(fr[-1, C["fuel"]]), len(fr))
        self.store.save_frames(lap_id, fr)
        if self.track is None:
            self._identify_track(fr, lap_id)
        an = A.analyse_lap(fr, self.track) if self.track else None
        self.store.x("UPDATE laps SET track_id=?, analysis=? WHERE id=?", self.track and self.track["id"], json.dumps(an), lap_id)
        pit = bool(np.any(np.diff(fr[:, C["fuel"]]) > 0.05))        # fuel went up during the lap: a pit stop
        if pit and an:
            an["summary"]["pit"] = "stop"
            self.store.x("UPDATE laps SET analysis=? WHERE id=?", json.dumps(an), lap_id)
            prev = self.session_laps[-1] if self.session_laps else None
            if prev and prev.get("analysis") and not prev.get("pit"):       # the lap before it ended in the pit lane
                prev["pit"] = "in"; prev["analysis"]["summary"]["pit"] = "in"
                self.store.x("UPDATE laps SET analysis=? WHERE id=?", json.dumps(prev["analysis"]), prev["id"])
        lap = dict(id=lap_id, lap_no=self.lap_no, time_ms=int(time_ms), first=first, analysis=an, pit="stop" if pit else None,
                   fuel_start=float(fr[0, C["fuel"]]), fuel_end=float(fr[-1, C["fuel"]]))
        self.session_laps.append(lap)
        if self.track:
            self._references()
        self.log(f"lap {self.lap_no} {A.fmt_time(time_ms)} track {self.track and (self.track['name'] or self.track['id'])}")
        for l in self.listeners:
            l.on_lap(self, lap)

    def _guess(self):
        """Which track this looks like, from the part of the lap driven so far (the name comes at the line)."""
        try:
            xz = np.asarray(self.buf)[::30][:, [C["x"], C["z"]]]
            driven = float(np.hypot(np.diff(xz[:, 0]), np.diff(xz[:, 1])).sum())
            self.guess = CI.guess([tuple(p) for p in xz], driven)
        except Exception as e:
            self.guess = None; self.log(f"track guess failed: {e!r}")

    def _name_from_outline(self, pts, length):
        """A track without a name: name it when its lap fits a known outline. A name typed or read from a screen wins later."""
        if self.track.get("name"):
            return
        try:
            found = CI.name_lap([tuple(p) for p in pts[::4][:, [0, 2]]], length)
        except Exception as e:
            self.log(f"track naming failed: {e!r}"); return
        if found:
            self.store.x("UPDATE tracks SET name=?, name_src='outline' WHERE id=?", found["name"], self.track["id"])
            self.track["name"] = found["name"]; self.track["name_src"] = "outline"; self.track_news = found["name"]
            self.log(f"track {self.track['id']} named from its outline: {found['name']} (on {found['on']}, cover {found['cover']})")

    def _identify_track(self, fr, lap_id):
        pts, length = A.path_of(fr)
        closed = float(np.hypot(pts[0, 0] - pts[-1, 0], pts[0, 2] - pts[-1, 2])) < 120
        for t in self.store.tracks():
            if A.same_track(pts, length, t["ref"], t["length"]):
                self.track = t
                break
        else:
            if not closed:                              # e.g. a grid start well behind the line: wait for a full lap
                return
            tid = self.store.add_track(pts, length, A.detect_corners(pts), lap_id)
            self.track = self.store.track(tid)
            self.log(f"new track {tid}: {length:.0f} m, {len(self.track['corners'])} corners")
        self.guess = None
        if closed:
            self._name_from_outline(pts, length)
        self.store.x("UPDATE sessions SET track_id=? WHERE id=?", self.track["id"], self.session)
        self._references()

    def _references(self):
        """The best lap on this track in this car, and the best attempt at each corner across all its laps."""
        self.ref = self.store.best_lap(self.track["id"], self.car)
        try:
            rows = self.store.q("SELECT analysis FROM laps WHERE track_id=? AND car=? AND analysis IS NOT NULL", self.track["id"], self.car)
            zones = [a["zones"] for a in (json.loads(r["analysis"] or "null") for r in rows) if a and a.get("zones") and not a["summary"].get("pit")]
            self.best_zones = A.best_zones(zones) if zones else None
        except Exception as e:
            self.best_zones = None; self.log(f"best corners failed: {e!r}")

    def state(self):
        m = self.meta; r = self.row
        now = r and self.live and dict(kmh=round(r[C["speed"]] * 3.6), gear=int(r[C["gear"]]), rpm=int(r[C["rpm"]]), fuel=round(r[C["fuel"]], 1),
                                       thr=round(r[C["thr"]] * 100), brk=round(r[C["brk"]] * 100),
                                       tyres=[round(r[C["tt_" + w]]) for w in ("fl", "fr", "rl", "rr")]) or None
        return dict(track_guess=None if self.track else self.guess, live=self.live, now=now, car=self.car, session=self.session, lap=self.lap_no, total_laps=m.get("total_laps"),
                    track=self.track and dict(id=self.track["id"], name=self.track["name"], length=round(self.track["length"]),
                                              corners=len(self.track["corners"])),
                    tune=dict(on_file=bool(self.tune), library=self.lib_tune and dict(id=self.lib_tune["id"], title=self.lib_tune["title"],
                                                                                     author=self.lib_tune["author"]), in_library=self.lib_count),
                    best_ms=self.ref and self.ref["time_ms"], laps=[dict(lap=l["lap_no"], ms=l["time_ms"]) for l in self.session_laps])


def name_tracks(store, log=print):
    """Tracks already driven but never named: name the ones whose reference lap fits a known outline (run at start)."""
    done = 0
    for t in store.tracks():
        if t.get("name"):
            continue
        try:
            ref = np.asarray(t["ref"]); closed = float(np.hypot(ref[0, 0] - ref[-1, 0], ref[0, 2] - ref[-1, 2])) < 120
            found = closed and CI.name_lap([tuple(p) for p in ref[::4][:, [0, 2]]], t["length"])
        except Exception as e:
            log(f"track {t['id']}: naming failed: {e!r}"); continue
        if found:
            store.x("UPDATE tracks SET name=?, name_src='outline' WHERE id=?", found["name"], t["id"]); done += 1
            log(f"track {t['id']} named from its outline: {found['name']}")
    return done
