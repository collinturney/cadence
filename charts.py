#!/usr/bin/env python3


def ordered_pairs(metrics):
    values = []
    timestamps = []

    for metric in metrics:
        values.append(float(metric.value))
        timestamps.append(metric.ts)

    return (values, timestamps)


class LineChart(object):
    @staticmethod
    def render(host, metric, values, timestamps):
        data = {
            "type": "scatter",
            "mode": "lines",
            "x": timestamps,
            "y": values,
            "name": metric,
            "line": {
                "color": "blue"
            }
        }

        layout = {
            "title": f"{host} - {metric}",
            "xaxis": {
                "type": "time",
                "title": "time"
            },
            "yaxis": {
                "title": metric
            }
        }

        chart = {
            "data": [data],
            "layout": [layout]
        }

        return chart
