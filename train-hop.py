from rich.pretty import pprint
from collections import defaultdict
import datetime
import functools
from python_caltrain import Caltrain, TransitType

c = Caltrain()

# {"Station" : [(transportation_method, "Station it's coming from", arrival_time, time_taken)...]
incoming = defaultdict(list)

walking = [
    ("San Jose", "Tamien", 45),
    ("Sunnyvale", "Lawrence", 43),
    ("Mountain View", "San Antonio", 43),
    ("California Avenue", "Palo Alto", 36),
    ("Menlo Park", "Palo Alto", 25),
    ("Redwood City", "San Carlos", 45),
    ("San Carlos", "Belmont", 26),
    ("Hillsdale", "Belmont", 43),
    ("Hillsdale", "Hayward Park", 16),
    ("Hayward Park", "San Mateo", 27),
    ("San Mateo", "Burlingame", 30),
    ("San Bruno", "South San Francisco", 39),
    ("22Nd Street", "San Francisco", 30),
]
date = datetime.date(1, 1, 1)
for i in c.trains["114"].stops:
    for t in c.trains:
        if c.trains[t].kind in (
            TransitType.something_weird,
            TransitType.weekend_game_train,
        ):
            continue
        for s in c.trains[t].stops:
            if s == i:
                for j in c.trains[t].stops:
                    if j.name in (
                        "Gilroy",
                        "Blossom Hill",
                        "College Park",
                        "Morgan Hill",
                        "San Martin",
                        "Capitol",
                    ):
                        continue
                    incoming[i.name].append(
                        (
                            t,
                            j.name,
                            c.trains[t].stops[s].arrival,
                            (
                                datetime.datetime.combine(
                                    date, c.trains[t].stops[s].arrival
                                )
                                - datetime.datetime.combine(
                                    date, c.trains[t].stops[j].arrival
                                )
                            ).seconds
                            / 60,
                        )
                    )
                    if j == i:
                        break
            for w in walking:
                if s.name in w and i.name in w:
                    incoming[i.name].append(
                        (
                            "Walking",
                            w[0] if w[0] != i.name else w[1],
                            (
                                datetime.datetime.combine(
                                    date, c.trains[t].stops[s].arrival
                                )
                                + datetime.timedelta(minutes=w[2])
                            ).time(),
                            w[2],
                        )
                    )


incoming = {k: v for k, v in sorted(incoming.items(), key=lambda item: len(item[1]))}
for i in incoming:
    pprint((i, len(incoming[i])))
ugh = [
    "San Francisco",
    "22Nd Street",
    "Bayshore",
    "South San Francisco",
    "San Bruno",
    "Millbrae",
    "Burlingame",
    "San Mateo",
    "Hayward Park",
    "Hillsdale",
    "Belmont",
    "San Carlos",
    "Redwood City",
    "Menlo Park",
    "Palo Alto",
    "California Avenue",
    "San Antonio",
    "Mountain View",
    "Sunnyvale",
    "Lawrence",
    "Santa Clara",
    "San Jose Diridon",
    "Tamien",
]


@functools.cache
def topdown_dp(cur, now, mask):
    if mask == 0:
        return now  # * utility[cur]
    if now == 0:
        return 0
    ret = 0
    count = 0
    cur_cpy = mask
    while cur_cpy:
        count += cur_cpy & 1
        cur_cpy >>= 1
    print(count)
    if count < 24:
        return ret
    for i in incoming[cur]:
        ret = max(
            ret,
            datetime.timedelta(
                minutes=topdown_dp(
                    ugh.index(i[1]),
                    datetime.datetime.combine(date, i[2])
                    - datetime.timedelta(minutes=i[3]),
                    mask & ~(1 << cur),
                )
            )  # utility from previous
            + (now - datetime.datetime.combine(date, i[2])),
        )  # utility from spending time here
    if mask >> (cur + 1) & 1:
        # same as above but symmetricaxb
        return ret


incoming = {ugh.index(k): v for k, v in incoming.items()}
print(
    [
        topdown_dp(end_station, datetime.time(21, 50, 00), 2 * 2**24 - 1)
        for end_station in [ugh.index(i.name) for i in c.trains["114"].stops]
    ]
)

# answer = max([topdown_dp(end_station, datetime.time(21, 50, 00), 2*2**24-1) for end_station in [ugh.index(i.name) for i in c.trains["114"].stops]])
