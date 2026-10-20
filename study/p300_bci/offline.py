"""Offline tools for a P300 session folder (no app needed).

    ~/.venvs/musemonitor/bin/python study/p300_bci/offline.py check  <session folder>
    ~/.venvs/musemonitor/bin/python study/p300_bci/offline.py timing <session folder>
    ~/.venvs/musemonitor/bin/python study/p300_bci/offline.py report <session folder> [--lang vi|en]
    ~/.venvs/musemonitor/bin/python study/p300_bci/offline.py erp    <session folder> [--preset default|li2020]
                                    [--timeline fit|online] [--channels TP9,TP10] [--csv erp.csv]

``erp`` cuts epochs at the stimulus ONSET (Qt paint time), never at key presses, and prints why epochs were rejected.
Incomplete sessions are analysed but labelled. Response-assisted sessions are labelled as such.
"""
import argparse
import csv
import json
import sys
from dataclasses import replace
from pathlib import Path

if __package__ in (None, ""):                       # run as a script: import the sibling modules directly
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import epochs, report, session, timing           # noqa: E401
else:
    from . import epochs, report, session, timing


def cmd_check(folder):
    ok, findings = session.check(folder)
    print("OK — complete and consistent" if ok else "Findings:\n  " + "\n  ".join(findings))
    return 0 if ok else 1


def cmd_timing(folder):
    path = Path(folder) / "timing.json"
    if not path.exists(): print("no timing.json (the session did not close normally)"); return 1
    rep = json.loads(path.read_text(encoding="utf-8"))
    print(rep.get("note", ""))
    for group in ("measured", "estimated", "not_measured"):
        print(f"\n[{group}]")
        for k, v in (rep.get(group) or {}).items():
            if k == "timeline_counters": continue
            print(f"  {k}: {v}")
    return 0


def cmd_erp(folder, preset_name, timeline, channels, out_csv):
    s = session.load(folder)
    preset = epochs.PRESETS[preset_name]
    if channels: preset = replace(preset, name=f"{preset.name}+custom", channels=tuple(channels))
    res = epochs.analyse_session(s, preset, timing.fit_timeline, timeline=timeline)
    print(f"preset {preset.name} ({preset.note or 'custom'})")
    print(f"timeline: {timeline} · mode: {res['mode']}" + (" · INCOMPLETE session" if res["incomplete"] else ""))
    print("epochs:", res["counts"])
    for name in ("target", "nontarget"):
        mean, _, n = res["erp"][name]
        if n:
            i = int(abs(mean[0]).argmax())
            print(f"  {name}: n={n}, largest |mean| {mean[0][i]:+.2f} µV at {res['times'][i] * 1000:+.0f} ms")
        else:
            print(f"  {name}: no epochs kept")
    if out_csv:
        with open(out_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time_s", "target_mean_uv", "target_sem_uv", "nontarget_mean_uv", "nontarget_sem_uv"])
            t, nt = res["erp"]["target"], res["erp"]["nontarget"]
            for i, tt in enumerate(res["times"]):
                cell = lambda x, j: "" if x[2] == 0 else f"{x[j][0][i]:.4f}"
                w.writerow([f"{tt:.4f}", cell(t, 0), cell(t, 1), cell(nt, 0), cell(nt, 1)])
        print("wrote", out_csv)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("check", "timing", "erp", "report"))
    ap.add_argument("folder")
    ap.add_argument("--preset", default="default", choices=sorted(epochs.PRESETS))
    ap.add_argument("--timeline", default="fit", choices=("fit", "online"))
    ap.add_argument("--channels", help="comma-separated channel names (overrides the preset's)")
    ap.add_argument("--csv", help="write the ERP to this CSV file")
    ap.add_argument("--lang", default="vi", choices=("vi", "en"), help="report language")
    a = ap.parse_args(argv)
    if a.command == "check": return cmd_check(a.folder)
    if a.command == "timing": return cmd_timing(a.folder)
    if a.command == "report":
        print("wrote", report.write(a.folder, lang=a.lang)); return 0
    return cmd_erp(a.folder, a.preset, a.timeline, a.channels.split(",") if a.channels else None, a.csv)


if __name__ == "__main__":
    sys.exit(main())
