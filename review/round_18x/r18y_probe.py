"""r18y probe (P-R18X3, run on orca inside the cafe-pm image as `python r18y_probe.py VARIANT LOOPS PARALLEL OUTDIR`, cwd /app): LOOPS groups of three children at once on one table, as `tests/test_whatif.py` ADDER, reports every child's rc and stderr. VARIANT names are in `V`; DECISIONS 995 quotes their counts."""
import os, pathlib, shutil, subprocess, sys, time, concurrent.futures as cf

HEAD = """
import sys, time, pathlib, os
{imp}
table, go, tag = sys.argv[1:]
while not pathlib.Path(go).exists():
    time.sleep(0.01)
for i in range(12):{add}
def _threads():
    out = []
    for t in sorted(os.listdir('/proc/self/task')):
        try: out.append(open(f'/proc/self/task/{{t}}/comm').read().strip())
        except OSError: pass
    return out
sys.stderr.write('R18Y_DONE threads=%s\\n' % _threads()); sys.stderr.flush()
"""
ADD_W = '\n    whatif.add_rows(table, [dict(key=f"{tag}{i}", x=float(i), pad="p" * 400_000)])'
ADD_E = '''
    p = pathlib.Path(table); new = pd.DataFrame([dict(key=f"{tag}{i}", x=float(i), pad="p" * 400_000)])
    with E.locked(p):
        df = pd.concat([E.read_table(p)[lambda d: ~d["key"].isin(new["key"])], new], ignore_index=True) if p.exists() else new
        E.write_table(df, p)'''
ADD_P = '''
    import fcntl, uuid
    p = pathlib.Path(table); new = pd.DataFrame([dict(key=f"{tag}{i}", x=float(i), pad="p" * 400_000)])
    fd = os.open(str(p) + ".lock", os.O_RDWR | os.O_CREAT, 0o666); fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        df = pd.concat([pd.read_parquet(p)[lambda d: ~d["key"].isin(new["key"])], new], ignore_index=True) if p.exists() else new
        tmp = p.with_name("." + uuid.uuid4().hex[:12] + ".tmp"); df.to_parquet(tmp); os.replace(tmp, p)
    finally:
        os.close(fd)'''
ADD_R = '\n    df = pd.read_parquet(os.path.join(os.path.dirname(table), "src.parquet"))'
ADD_WR = '\n    pd.DataFrame([dict(key=f"{tag}{i}", x=float(i), pad="p" * 400_000)] * 20).to_parquet(table + tag)'
ADD_PR1 = ADD_P.replace("pd.read_parquet(p)", "pd.read_parquet(p, use_threads=False)")
SRC = 'os.path.join(os.path.dirname(table), "src.parquet")'
ADD_WFO = '\n    with open(table + tag, "wb") as fh:\n        pd.DataFrame([dict(key=f"{tag}{i}", x=float(i), pad="p" * 400_000)] * 20).to_parquet(fh)'
V = {
 "wfo": ("import pandas as pd", ADD_WFO),
 "rd_s005": ("import pandas as pd", ADD_R + "\ntime.sleep(0.005)"),
 "rd_s05": ("import pandas as pd", ADD_R + "\ntime.sleep(0.05)"),
 "rd_s25": ("import pandas as pd", ADD_R + "\ntime.sleep(0.25)"),
 "rd_fs": ("import pandas as pd, pyarrow.fs", '\n    df = pd.read_parquet(' + SRC + ', filesystem=pyarrow.fs.LocalFileSystem())'),
 "rd_fh": ("import pandas as pd, pyarrow.parquet as pq", '\n    with open(' + SRC + ', "rb") as fh:\n        df = pq.read_table(fh).to_pandas()'),
 "rd_pq": ("import pandas as pd, pyarrow.parquet as pq", '\n    df = pq.read_table(' + SRC + ').to_pandas()'),
 "rdE": ("import pandas as pd, pathlib\nfrom cafe.pm import emulator as E", '\n    df = E.read_table(pathlib.Path(' + SRC + '))'),
 "rd_t0": ("import pandas as pd", '\n    df = pd.read_parquet(' + SRC + ', use_threads=False)'),
 "rd_pb0": ("import pandas as pd", '\n    df = pd.read_parquet(' + SRC + ', pre_buffer=False)'),
 "rd_pf": ("import pandas as pd, pyarrow.parquet as pq", '\n    df = pq.ParquetFile(' + SRC + ').read(use_threads=False).to_pandas(use_threads=False)'),
 "rd_pft": ("import pandas as pd, pyarrow.parquet as pq", '\n    df = pq.ParquetFile(' + SRC + ').read().to_pandas()'),
 "rd_dsx": ("import pandas as pd, pyarrow.parquet as pq", '\n    df = pq.read_table(' + SRC + ', use_threads=False).to_pandas()'),
 "rd_cpu1": ("import pandas as pd, pyarrow\npyarrow.set_cpu_count(1); pyarrow.set_io_thread_count(1)", ADD_R),
 "rd_sleep": ("import pandas as pd", ADD_R + "\ntime.sleep(1.0)"),
 "rd": ("import pandas as pd", ADD_R),
 "wr": ("import pandas as pd", ADD_WR),
 "pd_sleep": ("import pandas as pd", ADD_P + "\ntime.sleep(1.0)"),
 "pd_r1": ("import pandas as pd", ADD_PR1),
 "base": ("import pandas as pd\nfrom cafe.pm import whatif", ADD_W),
 "emu": ("import pandas as pd\nfrom cafe.pm import emulator as E", ADD_E),
 "pd": ("import pandas as pd", ADD_P),
 "pa1": ("import pandas as pd, pyarrow\npyarrow.set_cpu_count(1); pyarrow.set_io_thread_count(1)\nfrom cafe.pm import whatif", ADD_W),
 "pdpa1": ("import pandas as pd, pyarrow\npyarrow.set_cpu_count(1); pyarrow.set_io_thread_count(1)", ADD_P),
 "imp_only": ("import pandas as pd\nfrom cafe.pm import whatif", "\n    pass"),
 "pd_imp_only": ("import pandas as pd, pyarrow.parquet", "\n    pass"),
}

def one(variant, k, out):
    imp, add = V[variant]
    src = HEAD.format(imp=imp, add=add)
    d = pathlib.Path(out) / f"{variant}_{k}"; shutil.rmtree(d, ignore_errors=True); d.mkdir(parents=True)
    table, go = d / "train.parquet", d / "go"
    if variant.startswith("rd"):
        import pandas as pd
        pd.DataFrame([dict(key=f"s{j}", x=float(j), pad="p" * 400_000) for j in range(36)]).to_parquet(d / "src.parquet")
    env = dict(os.environ, PYTHONFAULTHANDLER="1", PYTHONPATH="/app")
    procs = [subprocess.Popen([sys.executable, "-c", src, str(table), str(go), tag], cwd="/app", env=env, stderr=subprocess.PIPE, text=True) for tag in "abc"]
    go.write_text("")
    errs = [p.communicate(timeout=900)[1] for p in procs]
    rcs = [p.returncode for p in procs]
    rows = None
    try:
        import pandas as pd; rows = len(pd.read_parquet(table)) if table.exists() else 0
    except Exception as e: rows = f"unreadable {type(e).__name__}"
    bad = rcs != [0, 0, 0]
    if bad:
        (pathlib.Path(out) / f"FAIL_{variant}_{k}.txt").write_text(f"rcs={rcs} rows={rows} files={sorted(f.name for f in d.iterdir())}\n" + "\n=====\n".join(errs))
    shutil.rmtree(d, ignore_errors=True)
    return bad, rcs, rows

if __name__ == "__main__":
    variant, loops, par_, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    pathlib.Path(out).mkdir(parents=True, exist_ok=True)
    n = bad = 0; t0 = time.time()
    with cf.ThreadPoolExecutor(par_) as ex:
        for b, rcs, rows in ex.map(lambda k: one(variant, k, out), range(loops)):
            n += 1; bad += b
            if b: print("FAIL", rcs, "rows", rows, flush=True)
            if n % 10 == 0: print(f"{variant}: {n} loops, {bad} failing, {time.time()-t0:.0f}s", flush=True)
    print(f"RESULT {variant} loops={n} bad_loops={bad} children={3*n} secs={time.time()-t0:.0f}", flush=True)
