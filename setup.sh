#!/bin/bash
sudo apt install python3-venv python3-pyaudio python3-soundfile libopenblas-dev
python3 -m venv venv
venv/bin/pip install -r requirements.txt
