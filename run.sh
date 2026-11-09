#!/bin/sh
# run a command in the cafe image on homebase with source + data mounted: ./run.sh python -m cafe.env
# The synced cafe/ has no .git: CAFE_GIT_SHA and CAFE_GIT_DIRTY from this checkout are how the results it stamps name their commit (a stamp that names none is not counted, round 13 M-24).
rsync -az --exclude __pycache__ -e "ssh -i $HOME/.ssh/homebase_ed25519" cafe/ azureuser@100.108.213.121:work/cafe/src/cafe/
ssh -i ~/.ssh/homebase_ed25519 azureuser@100.108.213.121 "docker run --rm -u 1000:1000 -e CAFE_GIT_SHA=$(git rev-parse HEAD 2>/dev/null) -e CAFE_GIT_DIRTY=$(if [ -n "$(git status --porcelain 2>/dev/null)" ]; then echo 1; else echo 0; fi) --cpus 6 --memory 16g -v \$HOME/work/cafe/src:/app -v \$HOME/work/cafe/data:/work -v \$HOME/data/uwincm:/data/uwincm:ro cafe $*"
