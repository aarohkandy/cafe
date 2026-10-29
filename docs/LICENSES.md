# Licences of what cafe/pm uses or can drive

Read this before enabling FluidX3D. It is an engineering summary, not legal advice; the licence text in each
project's repository is what binds. "Linking" below means importing a library into a process we distribute;
"running" means calling a program we do not distribute and reading its output files.

## FluidX3D — disabled by default

* Author: Moritz Lehmann (ProjectPhysX/FluidX3D). Custom licence, not an OSI licence.
* What the BRIEF (section 2.6) records and what to check in the repository's `LICENSE.md` before enabling: use is
  allowed for private, educational and research purposes; **commercial use and military use are not allowed**; modified
  versions must be **published**; the author must be credited.
* Consequence for us: `cafe/pm/stage3/fluidx3d.py` never builds, bundles or downloads FluidX3D. It runs a binary the lab
  has built itself, and only when `config["fluidx3d"]["enabled"]` is true *and* the path exists. A lab that enables it takes
  on the licence; the report says "FluidX3D backend" whenever it was used.
* The XLB backends below are the default and pass the same LBM receipts. FluidX3D adds speed and the free-surface (FSLBM) path.

## Default numerical stack

| Component | Licence | What it allows / asks |
|---|---|---|
| XLB 0.3.1 (Autodesk Research) | Apache-2.0 | Use, modify, redistribute, commercial use; keep notices; patent grant. |
| JAX / jaxlib | Apache-2.0 | As above. |
| NVIDIA Warp (`warp-lang` 1.12.1) | Apache-2.0 | As above. |
| NumPy, SciPy, h5py, `gsw` | BSD-3-Clause (SciPy: BSD) | Use and redistribute with the notice; no endorsement. |
| trimesh | MIT | Use and redistribute with the notice. |
| Gmsh (`gmsh` python wheel) | GPL-2.0-or-later (wheel metadata) | Running it from our code is fine. Redistributing a program that *links* Gmsh makes that program GPL. cafe calls it through the python module inside its own container image. |
| `pyconturb`, `pycoare`, `gliderflight`, `smt` | MIT, MIT, MIT, BSD-3-Clause | Permissive. |
| `arlpy` | BSD 3-clause | Permissive. |
| Capytaine | Apache-2.0 | Permissive. |
| `mannrs` 2.0.0 | **not stated in the installed package metadata** | Find the upstream licence before redistributing the wheel or code derived from it; using it internally in the lab image is unaffected. |

## Programs we run (copyleft; outputs are ours)

| Program | Licence | What it allows / asks |
|---|---|---|
| OpenFOAM v2506 (ESI/OpenCFD) | GPL-3.0-or-later | Run it for any purpose including commercial; the *results* are not covered. If we distribute OpenFOAM or a modified copy (the cafe image does), we must offer its source under the GPL. Trademark rules apply to the name. |
| CalculiX 2.21 (`ccx`) | GPL-2.0-or-later | Same: run freely; distributing the binary (image) carries the source offer. cafe only writes `.inp` files and reads `.dat/.frd`. |
| Acoustics Toolbox / Bellhop (via `arlpy`/`aubellhop`) | GPL-3.0 in the project's repository (check the copy you install; older distributions carry other terms) | Run it as an external program; a distributed image containing it carries the source offer. |
| ArduPilot SITL | GPL-3.0 | Run it as a separate process (as cafe does); modifications we distribute must be published under the GPL. |

## What this means for a deployment

1. Everything the lab runs internally (including with FluidX3D, if the lab accepts its licence for its use) needs no
   publication.
2. Handing the container image to another organisation redistributes OpenFOAM, CalculiX, Gmsh, Bellhop and ArduPilot: ship
   their source offers (the Dockerfile's package lists suffice for distro packages) and keep this file with the image.
3. Handing it over with FluidX3D inside is not allowed for commercial or military recipients under the licence summarised
   above; cafe's default image does not contain it.
