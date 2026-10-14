#!/bin/sh
# push source to homebase and rebuild the image
rsync -az --delete --exclude .git --exclude __pycache__ -e "ssh -i $HOME/.ssh/homebase_ed25519" ./ azureuser@100.108.213.121:work/cafe/src/
ssh -i ~/.ssh/homebase_ed25519 azureuser@100.108.213.121 'cd ~/work/cafe/src && docker build -q -t cafe . '
