# OpenFOAM (CFD) + CalculiX (FEA) + gmsh (meshing) + the cafe app, one image.
FROM opencfd/openfoam-run:2506
RUN apt-get update && apt-get install -y --no-install-recommends \
        calculix-ccx python3-venv libglu1-mesa libgl1 libxcursor1 libxinerama1 libxft2 libxrender1 libgomp1 zstd \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt
RUN /venv/bin/pip install --no-cache-dir capytaine
ENV PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1
ENTRYPOINT []
WORKDIR /app
COPY cafe /app/cafe
CMD ["uvicorn", "cafe.app:app", "--host", "0.0.0.0", "--port", "8000"]
