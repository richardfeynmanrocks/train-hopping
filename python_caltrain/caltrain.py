# -*- coding: utf-8 -*-

import csv
from collections import defaultdict, namedtuple
from datetime import datetime, timedelta
import pkg_resources
import re
from zipfile import ZipFile
from enum import Enum, unique
from io import TextIOWrapper

Train = namedtuple("Train", ["name", "kind", "direction", "stops", "service_windows"])
Station = namedtuple("Station", ["name", "zone"])
Stop = namedtuple(
    "Stop", ["arrival", "arrival_day", "departure", "departure_day", "stop_number"]
)
ServiceWindow = namedtuple(
    "ServiceWindow", ["id", "name", "start", "end", "days", "removed"]
)

_BASE_DATE = datetime(1970, 1, 1, 0, 0, 0, 0)


class Trip(namedtuple("Trip", ["departure", "arrival", "duration", "train"])):
    def __str__(self):
        return "[{kind} {name}] Departs: {departs}, Arrives: {arrives} ({duration})".format(
            kind=self.train.kind,
            name=self.train.name,
            departs=self.departure,
            arrives=self.arrival,
            duration=self.duration,
        )

    def __unicode__(self):
        return unicode(self.__str__())

    def __repr__(self):
        return (
            "Trip(departure={departure}, arrival={arrival}, duration={duration}, "
            "train=Train(name={train}))".format(
                departure=repr(self.departure),
                arrival=repr(self.arrival),
                duration=repr(self.duration),
                train=self.train.name,
            )
        )


def _sanitize_name(name):
    """
    Pre-sanitization to increase the likelihood of finding
    a matching station.

    :param name: the station name
    :type name: str or unicode

    :returns: sanitized station name
    """
    return (
        "".join(re.split("[^A-Za-z0-9]", name)).lower().replace("station", "").strip()
    )


def _resolve_time(t):
    """
    Resolves the time string into datetime.time. This method
    is needed because Caltrain arrival/departure time hours
    can exceed 23 (e.g. 24, 25), to signify trains that arrive
    after 12 AM. The 'day' variable is incremented from 0 in
    these situations, and the time resolved back to a valid
    datetime.time (e.g. 24:30:00 becomes days=1, 00:30:00).

    :param t: the time to resolve
    :type t: str or unicode

    :returns: tuple of days and datetime.time
    """
    hour, minute, second = [int(x) for x in t.split(":")]
    day, hour = divmod(hour, 24)
    r = _BASE_DATE + timedelta(hours=hour, minutes=minute, seconds=second)
    return day, r.time()


def _resolve_duration(start, end):
    """
    Resolves the duration between two times. Departure/arrival
    times that exceed 24 hours or cross a day boundary are correctly
    resolved.

    :param start: the time to resolve
    :type start: Stop
    :param end: the time to resolve
    :type end: Stop

    :returns: tuple of days and datetime.time
    """
    start_time = _BASE_DATE + timedelta(
        hours=start.departure.hour,
        minutes=start.departure.minute,
        seconds=start.departure.second,
        days=start.departure_day,
    )
    end_time = _BASE_DATE + timedelta(
        hours=end.arrival.hour,
        minutes=end.arrival.minute,
        seconds=end.arrival.second,
        days=end.departure_day,
    )
    return end_time - start_time


_STATIONS_RE = re.compile(r"^(.+) Caltrain( Station)?$")

_RENAME_MAP = {
    "SO. SAN FRANCISCO": "SOUTH SAN FRANCISCO",
    "MT VIEW": "MOUNTAIN VIEW",
    "CALIFORNIA AVE": "CALIFORNIA AVENUE",
}

_DEFAULT_GTFS_FILE = "data/GTFSTransitData_ct.zip"
_ALIAS_MAP_RAW = {
    "SAN FRANCISCO": ("SF", "SAN FRAN"),
    "SOUTH SAN FRANCISCO": (
        "S SAN FRANCISCO",
        "SOUTH SF",
        "SOUTH SAN FRAN",
        "S SAN FRAN",
        "S SAN FRANCISCO",
        "S SF",
        "SO SF",
        "SO SAN FRANCISCO",
        "SO SAN FRAN",
    ),
    "22ND ST": (
        "TWENTY-SECOND STREET",
        "TWENTY-SECOND ST",
        "22ND STREET",
        "22ND",
        "TWENTY-SECOND",
        "22",
    ),
    "MOUNTAIN VIEW": "MT VIEW",
    "CALIFORNIA AVENUE": (
        "CAL AVE",
        "CALIFORNIA",
        "CALIFORNIA AVE",
        "CAL",
        "CAL AV",
        "CALIFORNIA AV",
    ),
    "REDWOOD CITY": "REDWOOD",
    "SAN JOSE DIRIDON": ("DIRIDON", "SAN JOSE", "SJ DIRIDON", "SJ"),
    "COLLEGE PARK": "COLLEGE",
    "BLOSSOM HILL": "BLOSSOM",
    "MORGAN HILL": "MORGAN",
    "HAYWARD PARK": "HAYWARD",
    "MENLO PARK": "MENLO",
}

_ALIAS_MAP = {}

for k, v in _ALIAS_MAP_RAW.items():
    if not isinstance(v, list) and not isinstance(v, tuple):
        v = (v,)
    for x in v:
        _ALIAS_MAP[_sanitize_name(x)] = _sanitize_name(k)


@unique
class Direction(Enum):
    north = 0
    south = 1


@unique
class TransitType(Enum):
    shuttle = 0
    local = 1
    limited = 2
    baby_bullet = 3
    weekend_game_train = 4
    something_weird = 5

    @staticmethod
    def from_trip_id(trip_id):
        if trip_id[0] == "s":
            return TransitType.shuttle
        if trip_id[0] == "7":
            return TransitType.baby_bullet
        if trip_id[0] == "1":
            return TransitType.local
        if trip_id[0] in ("3", "4", "5"):
            return TransitType.limited
        if trip_id[0] == "2":
            return TransitType.weekend_game_train
        else:
            return TransitType.something_weird

    def __str__(self):
        return self.name.replace("_", " ").title()


class UnexpectedGTFSLayoutError(Exception):
    pass


class UnknownStationError(Exception):
    pass


class Caltrain(object):
    def __init__(self, gtfs_path=None):

        self.version = None
        self.trains = {}
        self.stations = {}
        self._unambiguous_stations = {}
        self._service_windows = {}
        self._fares = {}

        self.load_from_gtfs(gtfs_path)

    def load_from_gtfs(self, gtfs_path=None):
        """
        Loads a GTFS zip file and builds the data model from it.
        If not specified, the internally stored GTFS zip file from
        Caltrain is used instead.

        :param gtfs_path: the path of the GTFS zip file to load
        :type gtfs_path: str or unicode
        """
        # Use the default path if not specified.
        if gtfs_path is None:
            gtfs_handle = pkg_resources.resource_stream(__name__, _DEFAULT_GTFS_FILE)
        else:
            gtfs_handle = open(gtfs_path, "rb")

        with gtfs_handle as f:
            self._load_from_gtfs(f)

    def _load_from_gtfs(self, handle):
        z = ZipFile(handle)

        self.trains, self.stations = {}, {}
        self._service_windows, self._fares = defaultdict(list), {}

        # -------------------
        # 1. Record fare data
        # -------------------

        fare_lookup = {}

        # Create a map if (start, dest) -> price
        with z.open("fare_attributes.txt", "r") as csvfile:
            fare_reader = csv.DictReader(TextIOWrapper(csvfile))
            for r in fare_reader:
                fare_lookup[r["fare_id"]] = tuple(int(x) for x in r["price"].split("."))

        # Read in the fare IDs from station X to station Y.
        with z.open("fare_rules.txt", "r") as csvfile:
            fare_reader = csv.DictReader(TextIOWrapper(csvfile))
            for r in fare_reader:
                if r["origin_id"] == "" or r["destination_id"] == "":
                    continue
                k = (int(r["origin_id"]), int(r["destination_id"]))
                self._fares[k] = fare_lookup[r["fare_id"]]

        # ------------------------
        # 2. Record calendar dates
        # ------------------------

        # Record the days when certain trains are active.
        with z.open("calendar.txt", "r") as csvfile:
            calendar_reader = csv.reader(TextIOWrapper(csvfile))
            next(calendar_reader)  # skip the header
            for r in calendar_reader:
                self._service_windows[r[0]].append(
                    ServiceWindow(
                        id=r[0],
                        name=r[1],
                        start=datetime.strptime(r[-2], "%Y%m%d").date(),
                        end=datetime.strptime(r[-1], "%Y%m%d").date(),
                        days=set(i for i, j in enumerate(r[2:9]) if int(j) == 1),
                        removed=False,
                    )
                )

        # Find special events/holiday windows where trains are active.
        with z.open("calendar_dates.txt", "r") as csvfile:
            calendar_reader = csv.reader(TextIOWrapper(csvfile))
            next(calendar_reader)  # skip the header
            for r in calendar_reader:
                when = datetime.strptime(r[1], "%Y%m%d").date()
                self._service_windows[r[0]].insert(
                    0,
                    ServiceWindow(
                        id=r[0],
                        name=r[1],
                        start=when,
                        end=when,
                        days={when.weekday()},
                        removed=r[-1] == "2",
                    ),
                )

        # ------------------
        # 3. Record stations
        # ------------------
        with z.open("stops.txt", "r") as csvfile:
            trip_reader = csv.DictReader(TextIOWrapper(csvfile))
            for r in trip_reader:
                # From observation, non-numeric stop IDs are useless information
                # that should be skipped.
                if not r["stop_id"].isdigit():
                    continue
                regex_go_brrr = _STATIONS_RE.match(r["stop_name"])
                if regex_go_brrr == None:
                    continue
                stop_name = regex_go_brrr.group(1).strip().upper()
                self.stations[r["stop_id"]] = {
                    "name": _RENAME_MAP.get(stop_name, stop_name).title(),
                    "zone": int(r["zone_id"]) if r["zone_id"] else -1,
                }

        # ---------------------------
        # 4. Record train definitions
        # ---------------------------
        with z.open("trips.txt", "r") as csvfile:
            train_reader = csv.DictReader(TextIOWrapper(csvfile))
            for r in train_reader:
                train_dir = int(r["direction_id"])
                transit_type = TransitType.from_trip_id(r["trip_id"])
                service_windows = self._service_windows[r["service_id"]]
                self.trains[r["trip_id"]] = Train(
                    name=r["trip_short_name"] if r["trip_short_name"] else r["trip_id"],
                    kind=transit_type,
                    direction=Direction(train_dir),
                    stops={},
                    service_windows=service_windows,
                )

        self.stations = dict(
            (k, Station(v["name"], v["zone"])) for k, v in self.stations.items()
        )

        # -----------------------
        # 5. Record trip stations
        # -----------------------
        with z.open("stop_times.txt", "r") as csvfile:
            stop_times_reader = csv.DictReader(TextIOWrapper(csvfile))
            for r in stop_times_reader:
                stop_id = r["stop_id"]
                train = self.trains[r["trip_id"]]
                arrival_day, arrival = _resolve_time(r["arrival_time"])
                departure_day, departure = _resolve_time(r["departure_time"])
                train.stops[self.stations[stop_id]] = Stop(
                    arrival=arrival,
                    arrival_day=arrival_day,
                    departure=departure,
                    departure_day=departure_day,
                    stop_number=int(r["stop_sequence"]),
                )

        # For display
        self.stations = dict(
            ("_".join(re.split("[^A-Za-z0-9]", v.name)).lower(), v)
            for _, v in self.stations.items()
        )

        # For station lookup by string
        self._unambiguous_stations = dict(
            (k.replace("_", ""), v) for k, v in self.stations.items()
        )

    def get_station(self, name):
        """
        Attempts to resolves a station name from a string into an
        actual station. An UnknownStationError is thrown if no
        Station can be derived

        :param name: the name to resolve
        :type name: str or unicode

        :returns: the resolved Station object
        """
        sanitized = _sanitize_name(name)
        sanitized = _ALIAS_MAP.get(sanitized, sanitized)
        station = self._unambiguous_stations.get(sanitized, None)
        if station:
            return station
        else:
            raise UnknownStationError(name)

    def fare_between(self, a, b):
        """
        Returns the fare to travel between stations a and b. Caltrain fare
        is always dependent on the distance and not the train type.

        :param a: the starting station
        :type a: str or unicode or Station
        :param b: the destination station
        :type b: str or unicode or Station

        :returns: tuple of the dollar and cents cost
        """
        a = self.get_station(a) if not isinstance(a, Station) else a
        b = self.get_station(b) if not isinstance(b, Station) else b
        return self._fares[(a.zone, b.zone)]

    def next_trips(self, a, b, after=None):
        """
        Returns a list of possible trips to get from stations a to b
        following the after date. These are ordered from soonest to
        latest and terminate at the end of the Caltrain's 'service day'.

        :param a: the starting station
        :type a: str or unicode or Station
        :param b: the destination station
        :type b: str or unicode or Station
        :param after: the time to find the next trips after
                      (default datetime.now())
        :type after: datetime

        :returns: a list of possible trips
        """

        if after is None:
            after = datetime.now()

        a = self.get_station(a) if not isinstance(a, Station) else a
        b = self.get_station(b) if not isinstance(b, Station) else b

        possibilities = []

        for name, train in self.trains.items():

            should_skip = set()

            for sw in train.service_windows:
                in_time_window = (
                    sw.start <= after.date() <= sw.end and after.weekday() in sw.days
                )
                stops_at_stations = a in train.stops and b in train.stops

                if not in_time_window or not stops_at_stations or sw.id in should_skip:
                    continue

                if sw.removed:
                    should_skip.add(sw.id)
                    continue

                stop_a = train.stops[a]
                stop_b = train.stops[b]

                # Check to make sure this train is headed in the right direction.
                if stop_a.stop_number > stop_b.stop_number:
                    continue

                # Check to make sure this train has not left yet.
                if stop_a.departure < after.time():
                    continue

                possibilities.append(
                    Trip(
                        departure=stop_a.departure,
                        arrival=stop_b.arrival,
                        duration=_resolve_duration(stop_a, stop_b),
                        train=train,
                    )
                )

        possibilities.sort(key=lambda x: x.departure)
        return possibilities
