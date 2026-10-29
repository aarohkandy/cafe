# cafe pre-mission pipeline. Every target runs where it is invoked (inside the cafe-pm image or an equivalent env);
# from a laptop, prefix with ./pm.sh to run it on homebase:  ./pm.sh make acceptance
MISSION ?= missions/tepex_c_demo.yaml
GPUS    ?= 0
RUNS    ?= runs
PY      ?= python

.PHONY: install bench fetch run quick overnight ci receipts audit acceptance broken report clean-runs

install:            ## the pipeline image (docker) - the only supported install
	docker build -t cafe . && docker build -f Dockerfile.pm -t cafe-pm .

bench:              ## measure this machine; writes config/throughput.json, which the planner reads
	$(PY) bench/throughput.py all

fetch:              ## data for the mission box + window (resumable, hash-checked)
	$(PY) -m cafe.pm fetch --mission $(MISSION)

ci: MISSION := missions/ci_fixture.yaml
ci: CI_DATA ?= /tmp/cafe_ci_data
ci:                 ## every stage at toy resolution on CPU, < 10 min, from the synthetic environment (tests/fixtures/ci_env), no network
	$(PY) -m tests.fixtures.ci_env.make $(CI_DATA) $(MISSION)
	CAFE_DATA=$(CI_DATA) CAFE_OFFLINE=1 $(PY) -m cafe.pm run --mission $(MISSION) --budget ci --gpus 0 --out $(RUNS)/ci

quick:
	$(PY) -m cafe.pm run --mission $(MISSION) --budget quick --gpus $(GPUS) --out $(RUNS)/quick

overnight:
	$(PY) -m cafe.pm run --mission $(MISSION) --budget overnight --gpus $(GPUS) --out $(RUNS)/overnight

receipts:           ## every receipt, existing app + pre-mission; non-zero exit on any failure
	$(PY) -m cafe.pm receipts

broken:             ## the deliberately broken configuration must FAIL a receipt (exit 0 = it failed as required)
	$(PY) -m cafe.pm receipts --broken tests/fixtures/broken/wave_direction.yaml

audit:
	$(PY) -m cafe.pm.audit $(wildcard $(RUNS)/quick $(RUNS)/overnight $(RUNS)/4h)

acceptance:         ## brief section 5.3: quick + overnight (+ 4h when GPUS>0), golden diff, reproducibility, broken config
	$(PY) -m cafe.pm acceptance --mission $(MISSION) --gpus $(GPUS) --out $(RUNS)

report:
	$(PY) -m cafe.pm report --run $(RUNS)/quick --open
