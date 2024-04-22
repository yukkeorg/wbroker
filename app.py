from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from bme280 import bme280
from bme280 import bme280_i2c

import os
import threading
import time
import pprint

I2C_ADDR = 0x76
I2C_BUS = 1

influx_url = "http://yukke-server.local:8086"
influx_token = os.environ.get("INFLUXDB_TOKEN")
influx_org = "yukkeorg"
influx_bucket = "yukkeorg"

lock = threading.Lock()

class InfluxWriter:
    def __init__(self, url=None, token=None, org=None, bucket=None):
        url = url if url is not None else influx_url
        token = token if token is not None else influx_token
        org = org if org is not None else influx_org 
        self.client = InfluxDBClient(url=url, token=token, org=org)
        self.write_api = self.client.write_api(wtite_options=SYNCHRONOUS)
        self.bucket = bucket if bucket is not None else influx_bucket

    def write(self, point, values):
        point = Point(point)
        for k, v in values.items():
            point.field(k, v)
        self.write_api.write(bucket=self.bucket, record=point)


class Mesurement:
    def __init__(self):
        self.data = None

        bme280_i2c.set_default_i2c_address(I2C_ADDR)
        bme280_i2c.set_default_bus(I2C_BUS)
        bme280.setup()

    def mesurement(self):
        with lock:
            self.data = bme280.read_all()

    def get_tupple(self):
        return (self.data.temperature, 
                self.data.humidity,
                self.data.pressure)


class MesurementThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True

        self.mesurement = Mesurement()
        self.writer = InfluxWriter()

    def run(self):
        tags = ["temperature", "humidity", "pressure"]
        while True:
            self.mesurement.mesurement()
            values = dict(zip(tags, self.mesurement.get_tupple()))
            self.writer.write("measurement", values)
            time.sleep(10)


def main():
    mesurement_thread = MesurementThread()
    mesurement_thread.start()
    mesurement_thread.join()


if __name__ == '__main__':
    main()
