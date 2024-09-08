from typing import Any

import os
import threading
import time
import signal
import logging
from datetime import datetime

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

import smbus

from bme280 import bme280
from bme280 import bme280_i2c

SO1602A_ADDR = 0x3C
BME280_ADDR = 0x76
I2C_BUS = 1

logging.basicConfig(level=logging.INFO)

env_influx_url = os.environ.get("INFLUXDB_URL")
env_influx_token = os.environ.get("INFLUXDB_TOKEN")
env_influx_org = os.environ.get("INFLUXDB_ORG")
env_influx_bucket = os.environ.get("INFLUXDB_BUCKET")

lock = threading.Lock()


class InfluxWriter:
    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        org: str | None = None,
        bucket: str | None = None,
    ):
        url = url if url is not None else env_influx_url
        token = token if token is not None else env_influx_token
        org = org if org is not None else env_influx_org

        client = InfluxDBClient(url=url, token=token, org=org)

        self.write_api = client.write_api(wtite_options=SYNCHRONOUS)
        self.bucket = bucket if bucket is not None else env_influx_bucket

    def write(self, point: str, values: dict[str, Any]) -> None:
        p = Point(point)
        for k, v in values.items():
            p.field(k, v)
        self.write_api.write(bucket=self.bucket, record=p)


class SO1602ADisplay:
    def __init__(self, bus: int = I2C_BUS, addr: int = SO1602A_ADDR):
        self.i2c = smbus.SMBus(bus)
        self.addr = addr

    def __send_command(self, data: int) -> None:
        with lock:
            self.i2c.write_byte_data(self.addr, 0x00, data)

    def __send_data(self, data: bytes) -> None:
        with lock:
            for i in data:
                self.i2c.write_byte_data(self.addr, 0x40, i)

    def setup(self) -> None:
        self.all_clear()
        self.__send_command(0x0C)

    def put(self, data: str) -> None:
        self.__send_data(data.encode())

    def all_clear(self) -> None:
        self.__send_command(0x01)

    def return_home(self) -> None:
        self.__send_command(0x02)

    def return_home_fast(self) -> None:
        self.__send_command(0x80)

    return_first_line = return_home_fast

    def return_second_line(self) -> None:
        self.__send_command(0xA0)


class Bme280Sensor:
    def __init__(self):
        self.data = None
        bme280_i2c.set_default_i2c_address(BME280_ADDR)
        bme280_i2c.set_default_bus(I2C_BUS)

    def setup(self) -> None:
        bme280.setup()

    def measure(self) -> None:
        with lock:
            self.data = bme280.read_all()

    def get_dict(self) -> dict[str, Any]:
        return {
            "temperature": self.data.temperature,
            "humidity": self.data.humidity,
            "pressure": self.data.pressure,
        }


def calc_tdi(temperature: float, humidity: float) -> float:
    return 0.81 * temperature + 0.01 * humidity * (0.99 * temperature - 14.3) + 46.3


def measurement_thread(e: threading.Event, data: dict[str, Any]) -> None:
    sensor = Bme280Sensor()
    sensor.setup()

    while not e.is_set():
        sensor.measure()
        with lock:
            data.update(sensor.get_dict())

        if e.is_set():
            break

        time.sleep(1)


def display_thread(e: threading.Event, data: dict[str, Any]) -> None:
    display = SO1602ADisplay()
    display.setup()

    while not e.is_set():
        display.return_first_line()
        display.put(datetime.now().strftime("%Y/%m/%d %H:%M"))
        display.return_second_line()

        if data:
            tdi = calc_tdi(data["temperature"], data["humidity"])
            display.put(
                f"{data['temperature']:2.1f}C "
                f"{data['humidity']:2.1f}% "
                f"{tdi:4.0f}"
            )
        else:
            display.put("--.-C --.-% ----")

        if e.is_set():
            break

        time.sleep(2)


def send_data_thread(e: threading.Event, data: dict[str, Any]) -> None:
    writer = InfluxWriter()

    while not e.is_set():
        writer.write("measurement", data)

        if e.is_set():
            break

        time.sleep(10)


def control_thread() -> None:
    e = threading.Event()
    data: dict[str, Any] = {}
    threads = [
        threading.Thread(target=measurement_thread, args=(e, data)),
        threading.Thread(target=display_thread, args=(e, data)),
        threading.Thread(target=send_data_thread, args=(e, data)),
    ]

    def signal_sigint_handler(signum, frame):
        e.set()
        logging.info("Exiting...")

    signal.signal(signal.SIGINT, signal_sigint_handler)

    for t in threads:
        t.start()

    for t in threads:
        t.join()


def main() -> None:
    control_thread()


if __name__ == "__main__":
    main()
