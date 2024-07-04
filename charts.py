#!/usr/bin/env python3


class LineChart(object):
    @staticmethod
    def get_coordinates(metrics):
        x = []
        y = []

        for metric in metrics:
            x.append(metric.time)
            y.append(float(metric.value))

        return (x, y)

    @staticmethod
    def render(host_name, metric_name, metrics):
        x, y = LineChart.get_coordinates(metrics)

        return {
            "data": [{
                "type": "scatter",
                "mode": "lines",
                "x": x,
                "y": y,
                "name": metric_name,
                "line": {
                    "color": "blue"
                }
            }],
            "layout": [{
                "title": f"{host_name} - {metric_name}",
                "xaxis": {
                    "type": "time",
                    "title": "time"
                },
                "yaxis": {
                    "title": metric_name
                }
            }]
        }
