"""Reads review rans_ladder_* result.json files and prints the ladder's table, the steadiness of the form factor and its log-log slope.
  bin/pmx.sh python review/workorder/ladder_table.py /data/runs/rans_ladder_ctl /data/runs/rans_ladder_re80k ...   (ordered by Reynolds number on print)"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import rans_probe  # noqa: E402


def main(dirs: list) -> int:
    rows = []
    for d in dirs:
        r = json.loads((pathlib.Path(d) / "result.json").read_text())
        rows.append((r["info"]["re_length"], pathlib.Path(d).name, r))
    rows.sort(reverse=True)
    for re, name, r in rows:
        i, g, f, c, s = r["info"], r["grids"], r["grids"]["fine"], r["grids"]["coarse"], r["summary"]
        print(f"{name}: Re {re:.4g} U {i['speed_ms']:.5f} cells {c['cells']}/{f['cells']} failed {c['failed_checks']}/{f['failed_checks']} "
              f"it {c['iterations']}/{f['iterations']} s {s['total_seconds']:.0f} drag {f['drag_n']:.5f} (coarse {c['drag_n']:.5f}) cd {f['cd']:.4f} "
              f"GCI {s['gci']:.4f} ratio {s['refinement_ratio']:.3f} std_rel {c.get('drag_tail_std_rel', float('nan')):.4f}/"
              f"{f.get('drag_tail_std_rel', float('nan')):.4f} scatter {f['scatter']:.4f} P {f.get('drag_pressure_tail_mean_n', float('nan')):.5f} "
              f"V {f.get('drag_viscous_tail_mean_n', float('nan')):.5f} cf {s['cf_ittc57']:.5f}/{s['cf_blasius']:.5f} "
              f"ff(stl) {s['ff_ittc57']:.4f}/{s['ff_blasius']:.4f} ff(1.6427) {s['ff_ittc57_on_s_wet_other']:.4f}/{s['ff_blasius_on_s_wet_other']:.4f}")
    if len(rows) < 3:
        return 0
    for key in ("ff_ittc57", "ff_blasius", "ff_ittc57_on_s_wet_other", "ff_blasius_on_s_wet_other"):
        ff = [r["summary"][key] for _, _, r in rows]
        m = sum(ff) / len(ff)
        b, se = rans_probe.loglog_slope([re for re, _, _ in rows], ff)
        print(f"{key}: mean {m:.4f} max|ff/mean-1| {max(abs(v / m - 1) for v in ff):.4f} slope {b:+.4f} +- {se:.4f} (n={len(ff)})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
