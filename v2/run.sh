#!/bin/bash

# elimino i log
rm -f ./*.log

# attivo l'ambiente virtuale
source bin/activate

# lancio l'applicazione
python3 src/glisweb-agent.py & 2>&1 > ./run.log
