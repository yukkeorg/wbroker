import os
import threading
import time
import signal
import logging

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

import smbus

from bme280 import bme280
from bme280 import bme280_i2c

SO1602A_ADDR = 0x3c
BME280_ADDR = 0x76
I2C_BUS = 1

logging.basicConfig(level=logging.INFO)

influx_url = os.environ.get("INFLUXDB_URL")
influx_token = os.environ.get("INFLUXDB_TOKEN")
influx_org = os.environ.get("INFLUXDB_ORG")
influx_bucket = os.environ.get("INFLUXDB_BUCKET")

lock = threading.Lock()


class InfluxWriter:
    def __init__(self, url=None, token=None, org=None, bucket=None):
        url = url if url is not None else influx_url
        token = token if token is not None else influx_token
        org = org if org is not None else influx_org

        client = InfluxDBClient(url=url, token=token, org=org)

        self.write_api = client.write_api(wtite_options=SYNCHRONOUS)
        self.bucket = bucket if bucket is not None else influx_bucket

    def write(self, point, values):
        point = Point(point)
        for k, v in values.items():
            point.field(k, v)
        self.write_api.write(bucket=self.bucket, record=point)


class SO1602ADisplay:
    def __init__(self, bus=I2C_BUS, addr=SO1602A_ADDR):
        self.i2c = smbus.SMBus(bus)
        self.addr = addr

    def __send_command(self, data: bytes):
        with lock:
            self.i2c.write_byte_data(self.addr, 0x00, data)

    def __send_data(self, data: bytes):
        with lock:
            for i in data:
                self.i2c.write_byte_data(self.addr, 0x40, i)

    def setup(self):
        self.all_clear()
        self.__send_command(0x0C)

    def put(self, data: str):
        self.__send_data(data.encode())

    def all_clear(self):
        self.__send_command(0x01)

    def return_home(self):
        self.__send_command(0x02)

    def return_home2(self):
        self.__send_command(0x80)


class Bme280Sensor:
    def __init__(self):
        self.data = None

        bme280_i2c.set_default_i2c_address(BME280_ADDR)
        bme280_i2c.set_default_bus(I2C_BUS)

    def setup(self):
        bme280.setup()

    def measure(self):
        with lock:
            self.data = bme280.read_all()

    def get_dict(self):
        return {
            "temperature": self.data.temperature,
            "humidity": self.data.humidity,
            "pressure": self.data.pressure
        }


def measurement_thread(e, data):
    sensor = Bme280Sensor()
    sensor.setup()

    while True:
        if e.is_set():
            break

        sensor.measure()
        with lock:
            data.update(sensor.get_dict())

        time.sleep(1)


def display_thread(e, data):
    display = SO1602ADisplay()
    display.setup()

    while True:
        if e.is_set():
            break

        if data:
            display.return_home2()
            display.put(
                f"{data['temperature']:2.0f}C "
                f"{data['humidity']:2.0f}% "
                f"{data['pressure']:4.0f}hPa"
            )
        time.sleep(5)


def send_data_thread(e, data):
    writer = InfluxWriter()

    while True:
        if e.is_set():
            break

        writer.write("measurement", data)
        time.sleep(10)


def main():
    e = threading.Event()
    data = {}
    threads = [
        threading.Thread(target=measurement_thread, args=(e, data), daemon=True),
        threading.Thread(target=display_thread, args=(e, data), daemon=True),
        threading.Thread(target=send_data_thread, args=(e, data), daemon=True),
    ]

    def signal_handler(signum, frame):
        e.set()
        logging.info("Exiting...")

    signal.signal(signal.SIGINT, signal_handler)

    for t in threads:
        t.start()

    for t in threads:
        t.join()


if __name__ == '__main__':
    main()
