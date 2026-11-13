#!/usr/bin/env python3
"""Rebuild data/carspecs.csv and data/stockpp.csv (run after a GT7 update that adds cars).
  carspecs: the official car list on gran-turismo.com (drivetrain, power, weight, PP, class). Its ids are the car codes
            the telemetry feed sends.
  stockpp:  ddm999/gt7info, PP of the unmodified car on each tyre compound.
Also refreshes data/cars.csv and data/maker.csv (names for cars the official list does not have)."""
import csv, io, os, re, sys, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://www.gran-turismo.com"
INFO = "https://raw.githubusercontent.com/ddm999/gt7info/web-new/_data/db/"


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read().decode("utf-8")


def official():
    page = get(SITE + "/gb/gt7/carlist/")
    index = get(SITE + re.search(r'src="(/common/dist/gt7/carlist/assets/index-[^"]+\.js)"', page).group(1))
    cars = get(SITE + "/common/dist/gt7/carlist/assets/" + re.search(r"\./(cars\.gb-[\w-]+\.js)", index).group(1))
    tuners = get(SITE + "/common/dist/gt7/carlist/assets/" + re.search(r"\./(tuners\.gb-[\w-]+\.js)", index).group(1))
    makers = dict(re.findall(r"(tnr\d+):\{[^}]*?name:`([^`]*)`", tuners))
    out = []
    for m in re.finditer(r"car(\d+):\{(.*?)\}", cars):
        d = {k: a or b for k, a, b in re.findall(r"(\w+):(?:`([^`]*)`|(-?[\d.]+))", m.group(2))}
        pp = re.search(r"[\d.]+", d.get("performancePoint", ""))
        num = lambda k: d[k] if float(d.get(k, -1)) > 0 else ""
        out.append(dict(code=int(m.group(1)), name=d["nameLong"], maker=makers.get(d.get("manufacturerId"), ""),
                        drivetrain=d["driveTrain"] if d["driveTrain"] in ("FF", "FR", "MR", "RR", "4WD") else "",
                        aspiration=d.get("aspirationShort", ""), power_hp=num("power_v"), torque_kgfm=num("torque_v"),
                        weight_kg=num("weight_v"), pp_stock=pp.group(0) if pp else "", car_class=d.get("carClass", "")))
    return sorted(out, key=lambda r: r["code"])


def main():
    rows = official()
    if len(rows) < 500:
        sys.exit(f"only {len(rows)} cars parsed: the site layout changed, nothing written")
    with open(os.path.join(BASE, "data/carspecs.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0])); w.writeheader(); w.writerows(rows)
    for name, target in (("cars", "cars"), ("maker", "maker"), ("stockperf", "stockpp")):
        text = get(INFO + name + ".csv")
        if len(list(csv.reader(io.StringIO(text)))) < 50:
            sys.exit(f"{name}.csv from gt7info looks empty, not written")
        open(os.path.join(BASE, f"data/{target}.csv"), "w", encoding="utf-8").write(text)
    print(f"{len(rows)} cars with specs written")


if __name__ == "__main__":
    main()
