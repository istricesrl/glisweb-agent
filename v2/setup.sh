#!/bin/bash

# installazione pacchetti
sudo apt-get install openjdk-17-jdk
sudo apt-get install libmtdev1
sudo apt-get install libgtk2.0-dev pkg-config
sudo apt-get install python3-opencv
sudo apt-get install libxcb-xinerama0
sudo apt-get install libxcb-cursor0
sudo apt-get install xcb
sudo apt-get install libxcb-image0
sudo apt-get install libxcb-keysyms1
sudo apt-get install libxcb-render-util0
sudo apt-get install libxcb-xkb1
sudo apt-get install libxkbcommon-x11-0
sudo apt-get install libopencv-*

# se non esiste l'ambiente virtuale lo crea
if [ ! -f pyenv.cfg ]; then
    python3 -m venv .
fi

# attiva l'ambiente virtuale
source bin/activate

# installa i pacchetti necessari
pip install pyqt5
pip install Flask
pip install opencv-python
pip install opencv-contrib-python
pip install opencv-python-headless
pip install opencv-contrib-python-headless
pip install numpy
pip install img2pdf
pip install ffmpeg-python
pip install imutils
