"""The job runner, separate from the API so restarting the API never kills a running job.

    python -m cafe.worker

Queue = status.json files with state "queued" under designs/, missions/, emulations/. Each job runs as
its own process (so it always uses the current code). Characterizations run one at a time (CFD takes
the CPUs); up to two missions at once; one emulation at a time (SITL ports are shared).
"""
import json, os, pathlib, subprocess, sys, time

WORK = pathlib.Path(os.environ.get("CAFE_WORK", "/work"))
KINDS = dict(designs=("cafe.hangar", 1), missions=("cafe.mission", 2), emulations=("cafe.emulator", 1))


def state(d):
    try:
        return json.loads((d / "status.json").read_text()).get("state")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def main():
    running = {k: {} for k in KINDS}
    # anything marked running when we start was orphaned by a restart: run it again
    for k in KINDS:
        for d in (WORK / k).glob("*"):
            if state(d) == "running":
                (d / "status.json").write_text(json.dumps(dict(state="queued", step="restarted", progress=0.0, updated=time.time())))
    while True:
        for k, (module, slots) in KINDS.items():
            for d, p in list(running[k].items()):
                if p.poll() is not None:
                    del running[k][d]
                    if state(d) in ("running", "queued"):     # the job died without saying why
                        (d / "status.json").write_text(json.dumps(dict(state="failed", error=f"job process exited ({p.returncode})")))
            queued = sorted((d for d in (WORK / k).glob("*") if state(d) == "queued" and d not in running[k]),
                            key=lambda p: p.stat().st_mtime)
            for d in queued[:max(0, slots - len(running[k]))]:
                (d / "status.json").write_text(json.dumps(dict(state="running", step="starting", progress=0.0, updated=time.time())))
                running[k][d] = subprocess.Popen([sys.executable, "-m", module, str(d)],
                                                 stdout=open(d / "job.out", "a"), stderr=subprocess.STDOUT)
        time.sleep(2)


if __name__ == "__main__":
    main()
