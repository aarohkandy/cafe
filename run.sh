#!/bin/sh
# run a command in the cafe image on homebase with source + data mounted: ./run.sh python -m cafe.env
rsync -az --exclude __pycache__ -e "ssh -i $HOME/.ssh/homebase_ed25519" cafe/ azureuser@100.108.213.121:work/cafe/src/cafe/
ssh -i ~/.ssh/homebase_ed25519 azureuser@100.108.213.121 "docker run --rm -u 1000:1000 --cpus 6 --memory 16g -v \$HOME/work/cafe/src:/app -v \$HOME/work/cafe/data:/work -v \$HOME/data/uwincm:/data/uwincm:ro cafe $*"
