"""sensors.py: w1_slave parsing, fake 1-Wire folder, payload, --once run."""
import json

import pytest

import sensors

GOOD = "72 01 4b 46 7f ff 0e 10 57 : crc=57 YES\n72 01 4b 46 7f ff 0e 10 57 t=23125\n"
BAD_CRC = "72 01 4b 46 7f ff 0e 10 57 : crc=00 NO\n72 01 4b 46 7f ff 0e 10 57 t=23125\n"
NEGATIVE = "5e ff 4b 46 7f ff 02 10 84 : crc=84 YES\n5e ff 4b 46 7f ff 02 10 84 t=-10125\n"
RESET_85 = "50 05 4b 46 7f ff 0c 10 1c : crc=1c YES\n50 05 4b 46 7f ff 0c 10 1c t=85000\n"


def make_w1(tmp_path, text, name="28-0123456789ab"):
    dev = tmp_path / name
    dev.mkdir()
    (dev / "w1_slave").write_text(text)
    return tmp_path


@pytest.mark.parametrize("text,expected", [
    (GOOD, 23.12),  # 23.125 rounded to 2 places (banker's rounding)
    (NEGATIVE, -10.12),
    (BAD_CRC, None),
    (RESET_85, None),
    ("", None),
    ("garbage", None),
    ("72 01 : crc=57 YES\n72 01 no temperature here\n", None),
    ("72 01 : crc=57 YES\n", None),
])
def test_parse_w1_slave(text, expected):
    assert sensors.parse_w1_slave(text) == expected


def test_parse_w1_slave_zero_and_tolerates_crlf():
    text = "aa : crc=aa YES\r\naa t=0\r\n"
    assert sensors.parse_w1_slave(text) == 0.0


def test_read_temp_from_fake_dir(tmp_path):
    assert sensors.read_temp(str(make_w1(tmp_path, GOOD))) == 23.12


def test_read_temp_ignores_non_ds18b20_devices(tmp_path):
    (tmp_path / "w1_bus_master1").mkdir()
    (tmp_path / "10-000000000000").mkdir()
    (tmp_path / "10-000000000000" / "w1_slave").write_text(GOOD)
    assert sensors.read_temp(str(tmp_path)) is None
    make_w1(tmp_path, GOOD)
    assert sensors.read_temp(str(tmp_path)) == 23.12


def test_read_temp_missing_dir(tmp_path):
    assert sensors.read_temp(str(tmp_path / "nope")) is None


def test_read_temp_bad_crc_is_null(tmp_path):
    assert sensors.read_temp(str(make_w1(tmp_path, BAD_CRC))) is None


def test_read_temp_retries_once(tmp_path, monkeypatch):
    w1 = make_w1(tmp_path, GOOD)
    results = iter([None, 24.5])
    calls = []

    def fake_parse(text):
        calls.append(text)
        return next(results)

    monkeypatch.setattr(sensors, "parse_w1_slave", fake_parse)
    assert sensors.read_temp(str(w1)) == 24.5
    assert len(calls) == 2


def test_read_temp_gives_up_after_one_retry(tmp_path, monkeypatch):
    w1 = make_w1(tmp_path, GOOD)
    calls = []
    monkeypatch.setattr(sensors, "parse_w1_slave", lambda t: calls.append(t))
    assert sensors.read_temp(str(w1)) is None
    assert len(calls) == 2


class FakeSensor:
    def __init__(self, value=None, exc=None):
        self.value, self.exc = value, exc

    @property
    def distance(self):
        if self.exc:
            raise self.exc
        return self.value


def test_read_distance():
    assert sensors.read_distance(None) is None
    assert sensors.read_distance(FakeSensor(0.4812)) == 48.1
    assert sensors.read_distance(FakeSensor(exc=RuntimeError("no echo"))) is None


def test_build_payload():
    p = sensors.build_payload(1764140000.1, 31.4, None)
    assert p == {"ts": 1764140000.1, "temp": 31.4, "distance": None}
    assert json.loads(json.dumps(p)) == p  # None -> null


def test_main_once_with_fake_w1(tmp_path, capsys):
    w1 = make_w1(tmp_path, GOOD)
    rc = sensors.main(["--w1-dir", str(w1), "--no-distance", "--no-mqtt", "--once"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["temp"] == 23.12 and payload["distance"] is None and payload["ts"] > 0
