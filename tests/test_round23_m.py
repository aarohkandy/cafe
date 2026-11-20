"""Round 23, merge items (the lead's rulings after batches A to D were merged).

1. `budget.bench_sortie_rate`: batch D made a zero `sortie_min` or `mission_days` a PlanError; before round 23 a 0 meant "not scaled" (None), and `make bench`
   may store it. NaN, inf and negative stay refused.
2. L17 prints the tilt clamp (35 deg) and the exceedance (42 deg); they are the shipped `platforms/quad_uas.yaml`'s figures, which a lab can edit, so the
   text says so and a test reads the file."""
import math
import pathlib

import pytest
import yaml

from cafe.pm import budget, credibility as cr
from cafe.pm.budget import PlanError

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("sm,days", [(0, 6.0), (0.0, 6.0), (-0.0, 6.0), (120.0, 0), (120.0, 0.0), (120.0, -0.0), (0, 0)], ids=repr)
def test_a_zero_sortie_minutes_or_days_is_not_scaled_and_not_an_error(sm, days):
    assert budget.bench_sortie_rate(dict(sortie_min=sm, mission_days=days)) is None


@pytest.mark.parametrize("name", ["sortie_min", "mission_days"])
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, -1, -1e-300, True, False, "5", [1.0], 10 ** 400, -(10 ** 400)], ids=repr)
def test_a_sortie_figure_that_is_not_finite_or_is_negative_is_a_plan_error(name, bad):
    e = dict(sortie_min=120.0, mission_days=6.0)
    e[name] = bad
    with pytest.raises(PlanError, match=f"a stage1 entry's {name} is"):
        budget.bench_sortie_rate(e)


def test_a_zero_benchmark_figure_leaves_the_uas_cost_unscaled_with_the_note():
    from cafe.pm import config, stage1
    m = config.load_mission(config.ROOT / "missions" / "tepex_c_demo.yaml")
    t = budget.throughput()
    t = dict(t, stage1={k: dict(v) for k, v in t["stage1"].items()})
    t["stage1"]["uas"]["sortie_min"] = 0
    p = budget.plan("quick", 0, m, thr=t, vehicle_classes=stage1._classes(m), workers=6)
    assert ("UAS stage-1 cost is not scaled by sortie-minutes: the benchmark entry's sortie_min or mission_days is absent or 0 and its mission cannot be read; "
            "re-run `python bench/throughput.py stage1`") in p["notes"]


def test_l17_names_the_shipped_file_and_its_two_numbers_are_the_files():
    """The text prints 35 and 42; they are `limits.max_tilt_deg` and `limits.tilt_exceedance_deg` of the shipped quad_uas.yaml (read, not typed)."""
    li = yaml.safe_load((ROOT / "platforms/quad_uas.yaml").read_text())["limits"]
    text = {x["id"]: x for x in cr.LIMITATIONS}["L17"]["text"]
    assert text == (f"in the shipped quad_uas.yaml the UAS controller clamps the commanded tilt at {li['max_tilt_deg']['value']:g} deg, "
                    f"below the {li['tilt_exceedance_deg']['value']:g} deg of attitude exceedance")
    row = next(r for r in (ROOT / "docs/CREDIBILITY.md").read_text().splitlines() if r.startswith("| L17 |"))
    assert row.split("|")[2].strip() == text
