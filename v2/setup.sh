#!/bin/bash

# installazione pacchetti
apt-get install openjdk-17-jdk
apt-get install libmtdev1

# se non esiste l'ambiente virtuale lo crea
if [ ! -f pyenv.cfg ]; then
    python3 -m venv .
fi

# attiva l'ambiente virtuale
source bin/activate

# installa i pacchetti necessari
pip install pyqt5
