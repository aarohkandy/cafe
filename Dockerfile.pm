# The pre-mission pipeline image: the cafe image (OpenFOAM, CalculiX, gmsh, capytaine, gsw) plus requirements-pm.txt.
# Built separately so rebuilding it never touches the live app's image. `make` runs the Makefile targets CI calls.
FROM cafe
RUN apt-get update && apt-get install -y --no-install-recommends make && rm -rf /var/lib/apt/lists/*
COPY requirements-pm.txt /tmp/
RUN /venv/bin/pip install --no-cache-dir -r /tmp/requirements-pm.txt
