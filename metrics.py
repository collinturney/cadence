#!/usr/bin/env python3

from sqlalchemy import create_engine, ForeignKey, MetaData, func
from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.orm import relationship, sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool
from datetime import datetime, timedelta
from lock import RWLock
import math

ModelBase = declarative_base()


class Metric(ModelBase):
    __tablename__ = "metrics"
    id = Column(Integer, primary_key=True)
    time = Column(DateTime, default=datetime.now)
    host = Column(String)
    name = Column(String)
    value = Column(Float)

    def __repr__(self):
        return f"{self.time} {self.host} {self.name}={self.value}"


class MetricsDatabase(object):
    def __init__(self, path="sqlite://"):
        connect_args = {"check_same_thread": False}
        self.db = create_engine(path, connect_args=connect_args, poolclass=StaticPool)

        ModelBase.metadata.create_all(self.db)
        Session = sessionmaker(bind=self.db)
        self.session = Session()
        self.lock = RWLock()

    def add_metric(self, metric):
        with self.lock.write_lock():
            self.session.add(metric)
            self._commit()

    def add_metrics(self, metrics):
        with self.lock.write_lock():
            self.session.bulk_save_objects(metrics)
            self._commit()

    def hosts(self):
        with self.lock.read_lock():
            rows = (self.session.query(Metric.host)
                    .distinct()
                    .order_by(Metric.host.asc())
                    .all())
        return [row[0] for row in rows]

    def names(self, host):
        with self.lock.read_lock():
            rows = (self.session.query(Metric.name)
                    .filter(Metric.host == host)
                    .distinct()
                    .order_by(Metric.name.asc())
                    .all())
        return [row[0] for row in rows]

    def metrics(self, host, name, **kwargs):
        days = int(kwargs.get("days", 7))
        start = datetime.now() - timedelta(days=days)
        with self.lock.read_lock():
            metrics = (self.session.query(Metric)
                       .filter(Metric.host == host,
                               Metric.name == name,
                               Metric.time >= start)
                       .order_by(Metric.time.asc())
                       .all())
        return self._downsample(metrics)

    def prune(self, days_to_keep=7):
        threshold_date = datetime.now() - timedelta(days=days_to_keep)
        with self.lock.write_lock():
            (self.session.query(Metric)
                .filter(Metric.time < threshold_date)
                .delete())
            self.db.raw_connection().execute("VACUUM")
            self._commit()

    def current(self, host, name):
        with self.lock.read_lock():
            row = (self.session.query(Metric.value)
                   .filter(Metric.host == host,
                           Metric.name == name)
                   .order_by(Metric.time.desc())
                   .limit(1)
                   .first())
        return row[0] if row else None

    def summary(self, host, name):
        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)
        one_day_ago = now - timedelta(days=1)
        one_week_ago = now - timedelta(weeks=1)

        summary = {}
        summary["current"] = self.current(host, name)

        with self.lock.read_lock():
            summary["hour"] = self._interval_stats(host, name, one_hour_ago, now)
            summary["day"] = self._interval_stats(host, name, one_day_ago, now)
            summary["week"] = self._interval_stats(host, name, one_week_ago, now)
        return summary

    def save(self, path):
        with self.lock.write_lock():
            out_db = create_engine(f"sqlite:///{path}")
            self._copy_db(self.db, out_db)
            out_db.dispose()

    def load(self, path):
        with self.lock.write_lock():
            in_db = create_engine(f"sqlite:///{path}")
            self._copy_db(in_db, self.db)
            in_db.dispose()

    def clear(self):
        with self.lock.write_lock():
            metadata = MetaData()
            metadata.reflect(bind=self.db)
            for table in reversed(metadata.sorted_tables):
                self.session.execute(table.delete())
            self._commit()

    def _downsample(self, metrics, target: int = 150):
        factor = math.ceil(max(len(metrics) / target, 1))

        if factor == 1:
            return metrics

        samples = []
        for chunk in self._chunks(metrics, factor):
            avg_value = sum([float(item.value) for item in chunk]) / len(chunk)
            avg_time = sum([item.time.timestamp() for item in chunk]) / len(chunk)
            samples.append(Metric(host=chunk[0].host,
                                  name=chunk[0].name,
                                  value=avg_value,
                                  time=datetime.fromtimestamp(avg_time)))
        return samples

    def _interval_stats(self, host, name, start, end):
        result = (self.session.query(
            func.round(func.min(Metric.value), 2).label("min"),
            func.round(func.max(Metric.value), 2).label("max"),
            func.round(func.avg(Metric.value), 2).label("avg"))
                  .filter(Metric.host == host,
                          Metric.name == name,
                          Metric.time.between(start, end))
                  .one())
        return dict(result._mapping)

    def _commit(self):
        try:
            self.session.commit()
        except:
            self.session.rollback()
            raise

    @staticmethod
    def _copy_db(source, dest):
        source_conn = source.raw_connection()
        dest_conn = dest.raw_connection()
        source_conn.backup(dest_conn.driver_connection)

    @staticmethod
    def _chunks(items, n):
        for i in range(0, len(items), n):
            yield items[i:i + n]
