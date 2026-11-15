"""The rig check: what the earpiece reads from SimHub (settings files, its log about the USB board). Read-only, plain
files, so it runs anywhere. The file shapes follow a real SimHub 9.x install (14 Nov 2026)."""
import json, os, sys, tempfile, time
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "earpiece")]
import earpiece as E

fails = 0
def ok(cond, what):
    global fails
    print(("ok   " if cond else "FAIL ") + what); fails += 0 if cond else 1

d = tempfile.mkdtemp(); common = os.path.join(d, "PluginsData", "Common"); os.makedirs(common); os.makedirs(os.path.join(d, "Logs"))
GT7 = "f8c6bb7e-347b-42b4-a7b8-bca16495e688"
motors = {"activeProfileId": GT7, "LastGameProfiles": {"granturismo7": GT7}, "IsMuted": False, "GlobalGain": 50.0,
          "OutputManager": {"ArduinoSettings": {"IsEnabled": True, "ArduinoPluginDisabled": False, "MaxChannels": 12, "Name": "Arduino motors and fans",
                            "GlobalChannelsSettings": {"Custom": {"MapsStore": "0;0;100;Front Left;;|1;0;100;Rear Left;;|2;0;100;Front Right;;|3;0;100;Rear Right;;|4;0;100;;;"}}}},
          "Profiles": [{"Name": "Default profile", "ProfileId": "x", "EffectsContainers": []},
                       {"Name": "GT7 - tuned", "ProfileId": GT7, "GlobalGain": 50.0, "UseProfileGain": False, "EffectsContainers": [
                           {"ContainerType": "ABSActiveEffectContainer", "IsEnabled": False, "Gain": 80.0},
                           {"ContainerType": "TCActiveEffectContainer", "IsEnabled": True, "Gain": 30.0},
                           {"ContainerType": "AccelerationGforceContainer", "IsEnabled": True, "Gain": 50.0},
                           {"ContainerType": "WheelsSlipContainer", "IsEnabled": True, "Gain": 85.238}]}]}
wind = {"IsEnabled": True, "activeProfileId": "w", "OutputSettings": {"ArduinoOutput": {"IsEnabled": True, "ChannelMappings": [{"Role": 0}] * 6 + [{"Role": 2}, {"Role": 3}]}},
        "Profiles": [{"Name": "Default profile", "ProfileId": "w", "GlobalGain": 100, "StaticWindSettings": {"IsEnabled": True, "IsActive": True},
                      "DynamicWindSettings": {"IsEnabled": True, "MaximumSpeed": 200.0, "MinGain": 0.0, "MaxGain": 100.0}}]}
json.dump(motors, open(os.path.join(common, "ShakeITMotorsSettingsV2.json"), "w", encoding="utf-8-sig"))
json.dump(wind, open(os.path.join(common, "WindSettings.json"), "w", encoding="utf-8-sig"))
now = time.mktime(time.strptime("2026-11-14 19:30:00", "%Y-%m-%d %H:%M:%S"))
log = """[2026-11-14 17:00:00,001] INFO - Creating plugin manager with plugins : SerialDashPlugin
[2026-11-14 17:00:05,001] INFO - Connected to device on COM4 named Old Board (@9600bps)
[2026-11-14 18:00:11,001] INFO - Creating plugin manager with plugins : SerialDashPlugin, ShakeITMotorsV3Plugin
[2026-11-14 18:00:19,929] INFO - Connected to device on COM3 named EliteDrive FPU8 (@115200bps)
  "PortName": "COM3",
[2026-11-14 18:20:43,471] INFO - Game disconnected
[2026-11-14 19:11:26,620] INFO - Game disconnected
[2026-11-14 19:11:26,640] INFO - Game connected
[2026-11-14 19:19:07,087] INFO - Game disconnected
[2026-11-14 19:20:00,000] ERROR - System.Runtime.InteropServices.COMException (0x80070490): Element not found.
"""
open(os.path.join(d, "Logs", "SimHub.txt"), "w").write(log)

r = E.simhub_rig(d, None, ports={"COM1": "a", "COM3": "b"}, now=now)
L, m, f = r["log"], r["motors"], r["fans"]
ok(L["board"]["port"] == "COM3" and L["board"]["name"] == "EliteDrive FPU8" and L["board"]["baud"] == 115200, "the board SimHub connected to since its last start")
ok(L["started"] == time.mktime(time.strptime("2026-11-14 18:00:11", "%Y-%m-%d %H:%M:%S")), "...and when SimHub started (an older start is forgotten)")
ok(L["problems"] == [], "an audio error that has nothing to do with the board is not a board problem")
ok(L["game"]["connected"] is False and L["game"]["drops_hour"] == 2, "game data: last state, and drop-outs in the last hour")
ok(m["profile"] == "GT7 - tuned" and m["gain"] == 50.0 and not m["muted"] and m["output"]["enabled"], "motors: the active GT7 profile, level, output on")
ok([e["name"] for e in m["effects"]] == ["TC Active", "Acceleration G-force", "Wheels Slip"] and m["effects"][2]["gain"] == 85, "motors: only the effects switched on, named for people")
ok(m["channels"] == ["Front Left", "Rear Left", "Front Right", "Rear Right"], "motors: the named channels")
ok(f["enabled"] and f["output"]["channels"] == 2 and f["speed_wind"] and f["full_at_kmh"] == 200.0 and f["static_wind"], "fans: on, two fans, with speed, full at 200 km/h")

open(os.path.join(d, "Logs", "SimHub.txt"), "a").write("[2026-11-14 19:25:00,000] ERROR - Arduino on COM3: port disconnected\n")
ok(E.simhub_log(os.path.join(d, "Logs", "SimHub.txt"), now)["problems"][-1]["text"].startswith("Arduino on COM3"), "a board error after it connected is reported")
motors["IsMuted"] = True; json.dump(motors, open(os.path.join(common, "ShakeITMotorsSettingsV2.json"), "w", encoding="utf-8-sig"))
ok(E.simhub_motors(os.path.join(common, "ShakeITMotorsSettingsV2.json"))["muted"] is True, "muted motors are seen")
ok(E.simhub_rig(os.path.join(d, "nothing-here"), None, ports={})["motors"] is None, "no SimHub folder: nothing, no crash")
print("rig: all passed" if not fails else f"rig: {fails} FAILED"); sys.exit(1 if fails else 0)
