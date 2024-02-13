#!/bin/bash

./venv/bin/gunicorn --bind 0.0.0.0 'recorder:app'
