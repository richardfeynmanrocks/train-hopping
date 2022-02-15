from rich.pretty import pprint

from python_caltrain import Caltrain

c = Caltrain()
pprint(c.trains["111"].stops)
