"""SQLite index + one compressed file of frames per lap."""
import json, os, sqlite3, time
import numpy as np

ROOT = os.environ.get("GT7C_DATA", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY, started REAL, ended REAL, car INTEGER, track_id INTEGER, total_laps INTEGER, meta TEXT);
CREATE TABLE IF NOT EXISTS laps(id INTEGER PRIMARY KEY, session_id INTEGER, lap_no INTEGER, time_ms INTEGER, car INTEGER, track_id INTEGER,
  started REAL, first INTEGER, fuel_start REAL, fuel_end REAL, frames INTEGER, analysis TEXT);
CREATE TABLE IF NOT EXISTS tracks(id INTEGER PRIMARY KEY, name TEXT, length REAL, ref TEXT, corners TEXT, created REAL, ref_lap INTEGER);
CREATE TABLE IF NOT EXISTS tunes(id INTEGER PRIMARY KEY, car INTEGER, created REAL, source TEXT, sheet TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS library(id INTEGER PRIMARY KEY, car INTEGER, title TEXT, author TEXT, url TEXT, pp REAL, tyres TEXT, purpose TEXT,
  track TEXT, game_version TEXT, published TEXT, sheet TEXT, notes TEXT, added REAL, verdict TEXT, verdict_note TEXT);
CREATE TABLE IF NOT EXISTS shots(id INTEGER PRIMARY KEY, at REAL, kind TEXT, car INTEGER, summary TEXT, source TEXT, route TEXT, name TEXT,
  ok INTEGER, reply TEXT, mime TEXT, bytes INTEGER);
"""
# columns added after the first release: (table, column, type)
ADDED = [("sessions", "tune_id", "INTEGER"), ("sessions", "library_id", "INTEGER"), ("tunes", "library_id", "INTEGER"), ("shots", "cover", "INTEGER"), ("shots", "hash", "TEXT"), ("shots", "taken", "REAL"),
         ("tracks", "name_src", "TEXT")]      # who named the track: outline (the copilot, from where the car drove) | screen | you


class Store:
    def __init__(self, root=None):
        self.root = root or ROOT
        os.makedirs(os.path.join(self.root, "laps"), exist_ok=True)
        self.db = sqlite3.connect(os.path.join(self.root, "copilot.db"), check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for table, col, typ in ADDED:
            if col not in [r[1] for r in self.db.execute(f"PRAGMA table_info({table})")]:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        self.db.commit()

    def q(self, sql, *a):
        return [dict(r) for r in self.db.execute(sql, a).fetchall()]

    def x(self, sql, *a):
        cur = self.db.execute(sql, a); self.db.commit(); return cur.lastrowid

    def frames_path(self, lap_id):
        return os.path.join(self.root, "laps", f"{lap_id}.npz")

    def save_frames(self, lap_id, fr):
        np.savez_compressed(self.frames_path(lap_id), fr=fr)

    def load_frames(self, lap_id):
        return np.load(self.frames_path(lap_id))["fr"]

    # ---- screenshots: every picture that was read is kept, with what was seen on it ----
    def shot_path(self, shot_id, mime="image/jpeg"):
        ext = {"image/png": "png", "image/webp": "webp"}.get(mime, "jpg")
        return os.path.join(self.root, "shots", f"{shot_id}.{ext}")

    def save_shot(self, image, mime, kind=None, summary=None, source=None, car=None):
        sid = self.x("INSERT INTO shots(at,kind,car,summary,source,mime,bytes) VALUES(?,?,?,?,?,?,?)", time.time(), kind, car,
                     (summary or "")[:500] or None, source, mime, len(image))
        os.makedirs(os.path.join(self.root, "shots"), exist_ok=True)
        with open(self.shot_path(sid, mime), "wb") as f:
            f.write(image)
        return sid

    def delete_shot(self, shot_id):
        for r in self.q("SELECT mime FROM shots WHERE id=?", shot_id):
            try: os.remove(self.shot_path(shot_id, r["mime"]))
            except OSError: pass
        self.x("DELETE FROM shots WHERE id=?", shot_id)

    def tracks(self):
        out = []
        for r in self.q("SELECT * FROM tracks"):
            r["ref"] = np.asarray(json.loads(r["ref"])); r["corners"] = json.loads(r["corners"]); out.append(r)
        return out

    def track(self, tid):
        return next((t for t in self.tracks() if t["id"] == tid), None)

    def add_track(self, pts, length, corners, lap_id):
        return self.x("INSERT INTO tracks(name,length,ref,corners,created,ref_lap) VALUES(?,?,?,?,?,?)", None, length,
                      json.dumps(np.round(pts, 2).tolist()), json.dumps(corners), time.time(), lap_id)

    def best_lap(self, track_id, car):
        r = self.q("SELECT * FROM laps WHERE track_id=? AND car=? AND time_ms>0 AND first=0 ORDER BY time_ms LIMIT 1", track_id, car) or \
            self.q("SELECT * FROM laps WHERE track_id=? AND car=? AND time_ms>0 ORDER BY time_ms LIMIT 1", track_id, car)
        if r:
            r[0]["analysis"] = json.loads(r[0]["analysis"] or "null")
        return r[0] if r else None
