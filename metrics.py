#!/usr/bin/env python3

from sqlalchemy import create_engine, ForeignKey, MetaData
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship, sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool
from datetime import datetime, timedelta
from lock import RWLock
import math

ModelBase = declarative_base()


class Metric(ModelBase):
    __tablename__ = "metrics"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, default=datetime.now)
    host = Column(String)
    name = Column(String)
    value = Column(String)

    def __repr__(self):
        return f"{self.ts} {self.host} {self.name}={self.value}"


class MetricsDatabase(object):
    def __init__(self, path="sqlite://"):
        connect_args = {"check_same_thread": False}
        self.db = create_engine(path, connect_args=connect_args, poolclass=StaticPool)

        ModelBase.metadata.create_all(self.db)
        Session = sessionmaker(bind=self.db)
        self.session = Session()
        self.lock = RWLock()

    def add_metric(self, metric):
        with self.lock.write_locked():
            self.session.add(metric)
            self.session.commit()

    def add_metrics(self, metrics):
        with self.lock.write_locked():
            self.session.bulk_save_objects(metrics)
            self.session.commit()

    def hosts(self):
        with self.lock.read_locked():
            rows = (self.session.query(Metric.host)
                    .distinct()
                    .order_by(Metric.host.asc())
                    .all())
            return [row[0] for row in rows]

    def names(self, host):
        with self.lock.read_locked():
            rows = (self.session.query(Metric.name)
                    .filter(Metric.host == host)
                    .distinct()
                    .order_by(Metric.name.asc())
                    .all())
            return [row[0] for row in rows]

    def metrics(self, host, name, **kwargs):
        days = int(kwargs.get("days", 7))
        start = datetime.now() - timedelta(days=days)
        with self.lock.read_locked():
            metrics = (self.session.query(Metric)
                       .filter(Metric.host == host,
                               Metric.name == name,
                               Metric.ts >= start)
                       .order_by(Metric.ts.asc())
                       .all())
        return self._downsample(metrics)

    def save(self, path):
        with self.lock.write_locked():
            out_db = create_engine(f"sqlite:///{path}")
            self._copy_db(self.db, out_db)
            out_db.dispose()

    def load(self, path):
        with self.lock.write_locked():
            in_db = create_engine(f"sqlite:///{path}")
            self._copy_db(in_db, self.db)
            in_db.dispose()

    def clear(self):
        with self.lock.write_locked():
            metadata = MetaData()
            metadata.reflect(bind=self.db)
            for table in reversed(metadata.sorted_tables):
                self.session.execute(table.delete())
            self.session.commit()

    def _downsample(self, metrics, target: int = 150):
        factor = math.ceil(max(len(metrics) / target, 1))

        if factor == 1:
            return metrics

        samples = []
        for chunk in self._chunks(metrics, factor):
            avg_v = sum([float(item.value) for item in chunk]) / len(chunk)
            avg_t = sum([item.ts.timestamp() for item in chunk]) / len(chunk)
            avg_ts = datetime.fromtimestamp(avg_t)
            metric = Metric(host=chunk[0].host, name=chunk[0].name, value=avg_v, ts=avg_ts)
            samples.append(metric)
        return samples

    @staticmethod
    def _copy_db(source, dest):
        source_conn = source.raw_connection()
        dest_conn = dest.raw_connection()
        source_conn.backup(dest_conn.driver_connection)

    @staticmethod
    def _chunks(items, n):
        for i in range(0, len(items), n):
            yield items[i:i + n]
