# Scale ladder, RANS on the demo Seaglider (work in progress)

Branch scale-ladder. Script `review/workorder/rans_probe.py --levels 0 1 --iters 600 --speed-factor F`, table by `review/workorder/ladder_table.py`
(both read `result.json` under `~/cafe-worker/cafe/pmdata/runs/rans_ladder_<name>/` on orca). Same shape, label x-z5.29, grids and settings at every rung.
Solver nu = 1.19e-6 (cafe/cfd.py FLUIDS), equal to the pipeline's 1.19e-6. Re on L = speed x 1.8 m / nu.

## Rows as they finish (output of ladder_table.py, one line per case)

rans_ladder_ctl: Re 2.045e+05 U 0.13520 cells 315938/1284890 failed 0/0 it 600/600 s 890 drag 0.24758 (coarse 0.25789) cd 0.3739 GCI 0.0807 ratio 1.596 std_rel 0.0072/0.0061 scatter 0.1008 P 0.16791 V 0.07967 cf 0.00684/0.00294 ff(stl) 2.3556/5.4887 ff(1.6427) 2.3514/5.4789

rans_ladder_re80k: Re 8.019e+04 U 0.05302 cells 315994/1284246 failed 0/0 it 600/600 s 898 drag 0.04021 (coarse 0.04187) cd 0.3948 GCI 0.0805 ratio 1.596 std_rel 0.0036/0.0059 scatter 0.1157 P 0.02569 V 0.01452 cf 0.00889/0.00469 ff(stl) 1.9140/3.6295 ff(1.6427) 1.9106/3.6230

rans_ladder_re40k: Re 4.01e+04 U 0.02651 cells 315896/1284995 failed 0/0 it 271/600 s 790 drag 0.01153 (coarse 0.01140) cd 0.4530 GCI 0.0229 ratio 1.596 std_rel 0.0000/0.0052 scatter 0.1362 P 0.00651 V 0.00502 cf 0.01107/0.00663 ff(stl) 1.7643/2.9445 ff(1.6427) 1.7612/2.9393

