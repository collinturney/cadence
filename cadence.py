#!/usr/bin/env python3

from charts import LineChart, ordered_pairs
from disco import MetricsReceiver
from metrics import Metric, MetricsDatabase

from datetime import datetime
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from lock import RWLock
import logging
import os
import signal
import sys
import threading
import time
import uvicorn


class Cadence(object):

    SAVE_FILE = "cadence.sqlite"

    def __init__(self, db):
        self.log = logging.getLogger(__name__)
        self.db = db
        self.load()
        self.running = True
        self.receiver = MetricsReceiver()
        self.db_updater = threading.Thread(target=self.db_update)
        self.db_updater.start()

    def load(self, db_file=SAVE_FILE):
        if os.path.exists(db_file):
            self.log.info(f"Loading dataset '{db_file}'")
            self.db.load(db_file)

    def save(self, db_file=SAVE_FILE):
        self.log.info(f"Saving dataset '{db_file}'")
        self.db.save(db_file)

    def db_update(self):
        while self.running:
            metric = self._get_metric()

            if metric is None:
                continue

            self._add_metric(metric)

    def _get_metric(self):
        try:
            return self.receiver.get_metric()
        except Exception:
            self.log.error("Error receiving metric", exc_info=True)

    def _add_metric(self, metric):
        try:
            time_ = datetime.fromtimestamp(metric.values.pop("_time", time.time()))
            for name, value in metric.values.items():
                metric = Metric(host=metric.host, name=name, value=value, time=time_)
                self.db.add_metric(metric)
        except Exception:
            self.log.error("Error receiving metric", exc_info=True)

    def shutdown(self):
        self.log.info("Shutting down")
        self.running = False
        self.db_updater.join()
        self.receiver.shutdown()


app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

db = MetricsDatabase()
cadence = Cadence(db)


@app.get("/status", response_class=PlainTextResponse)
async def status():
    return "OK"


@app.get("/api")
@app.get("/api/hosts")
async def api_hosts():
    return {"hosts": db.hosts()}


@app.get("/api/hosts/{host}")
@app.get("/api/hosts/{host}/metrics")
async def api_metrics(host: str):
    return {"metrics": db.names(host)}


@app.get("/api/hosts/{host}/metrics/{name}")
@app.get("/api/hosts/{host}/metrics/{name}/values")
async def api_values(host: str, name: str):
    return {"values": db.metrics(host, name)}


@app.get("/api/hosts/{host}/metrics/{name}/current")
async def api_current_value(host: str, name:str):
    metric = db.current(host, name)
    return {"value": metric.value, "time": metric.time}


@app.get("/api/hosts/{host}/metrics/{name}/chart")
async def api_chart(host: str, name: str):
    metrics = db.metrics(host, name)
    values, timestamps = ordered_pairs(metrics)
    return LineChart.render(host, name, values, timestamps)


@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
@app.get("/ui/hosts", response_class=HTMLResponse)
async def ui_hosts(request: Request):
    metrics = {host: db.names(host) for host in db.hosts()}
    params = {"request": request, "metrics": metrics}
    return templates.TemplateResponse("metrics.html", params)


@app.get("/ui/hosts/{host}/metrics/{name}/chart", response_class=HTMLResponse)
async def ui_chart(request: Request, host: str, name: str):
    summary = db.summary(host, name)
    params = {"request": request, "host": host, "name": name, "summary": summary}
    return templates.TemplateResponse("chart.html", params)


@app.on_event("shutdown")
def shutdown_event():
    cadence.save()
    cadence.shutdown()


if __name__ == "__main__":
    uvicorn.run("cadence:app", port=8000, log_level="info")
