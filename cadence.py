#!/usr/bin/env python3

from charts import LineChart
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
    def __init__(self):
        self.log = logging.getLogger(__name__)
        self.running = True
        self._db = MetricsDatabase()
        self.receiver = MetricsReceiver()
        self.cleanup_time = time.time()
        self.db_updater = threading.Thread(target=self.db_update)
        self.db_updater.start()

    def db_update(self):
        while self.running:
            metric = self._get_metric()

            if metric is None:
                continue

            self._add_metric(metric)

            if time.time() - self.cleanup_time > 3600:
                self.log.info("Cleaning up")
                self._db.prune()
                self.cleanup_time = time.time()

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

    @property
    def db(self):
        return self._db


app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

cadence = Cadence()


@app.get("/status", response_class=PlainTextResponse)
async def status():
    return "OK"


@app.get("/api")
@app.get("/api/hosts")
async def api_hosts():
    return {"hosts": cadence.db.host_names()}


@app.get("/api/hosts/{host_name}")
@app.get("/api/hosts/{host_name}/metrics")
async def api_metrics(host_name: str):
    return {"metrics": cadence.db.metric_names(host_name)}


@app.get("/api/hosts/{host_name}/metrics/{metric_name}")
@app.get("/api/hosts/{host_name}/metrics/{metric_name}/current")
async def api_current_value(host_name: str, metric_name: str):
    metric = cadence.db.current(host_name, metric_name)
    return {"value": metric.value, "time": metric.time}


@app.get("/api/hosts/{host_name}/metrics/{metric_name}/values")
async def api_values(host_name: str, metric_name: str):
    return {"values": cadence.db.metrics(host_name, metric_name)}


@app.get("/api/hosts/{host_name}/metrics/{metric_name}/chart")
async def api_chart(host_name: str, metric_name: str):
    metrics = cadence.db.metrics(host_name, metric_name)
    return LineChart.render(host_name, metric_name, metrics)


@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
@app.get("/ui/hosts", response_class=HTMLResponse)
async def ui_hosts(request: Request):
    hosts = cadence.db.host_names()
    host_metrics = {host: cadence.db.metric_names(host) for host in hosts}
    params = {"request": request, "host_metrics": host_metrics}
    return templates.TemplateResponse("metrics.html", params)


@app.get("/ui/hosts/{host_name}/metrics/{metric_name}/chart", response_class=HTMLResponse)
async def ui_chart(request: Request, host_name: str, metric_name: str):
    summary = cadence.db.summary(host_name, metric_name)
    params = {"request": request, "host": host_name, "metric": metric_name, "summary": summary}
    return templates.TemplateResponse("chart.html", params)


@app.on_event("shutdown")
def shutdown_event():
    cadence.shutdown()


if __name__ == "__main__":
    uvicorn.run("cadence:app", port=8000, log_level="info")
