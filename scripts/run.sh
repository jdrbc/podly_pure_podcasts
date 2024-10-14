#!/bin/bash

export FLASK_ENV=development
export PYTHONPATH=./src 
pipenv run flask --app src.app --debug run
# open on http://127.0.0.1:5000/ not http://localhost:5000