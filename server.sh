#!/bin/bash

uvicorn cadence:app --host 0.0.0.0 --log-config=log_config.yaml
