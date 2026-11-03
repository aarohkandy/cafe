# The pre-mission pipeline image: the cafe image (OpenFOAM, CalculiX, gmsh, capytaine, gsw) plus requirements-pm.txt.
# Built separately so rebuilding it never touches the live app's image. `make` runs the Makefile targets CI calls.
FROM cafe
RUN apt-get update && apt-get install -y --no-install-recommends make && rm -rf /var/lib/apt/lists/*
COPY requirements-pm.txt /tmp/
RUN /venv/bin/pip install --no-cache-dir -r /tmp/requirements-pm.txt
# its own layer, so adding it did not rebuild the one above: the audit spreads the suite over the CPUs by file (cafe/pm/audit.py pytest_passes)
RUN /venv/bin/pip install --no-cache-dir pytest-xdist==3.6.1 execnet==2.1.1
