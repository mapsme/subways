"""This utility allows one to check equivalency of generated city caches
   (defined by --cache command line parameter) of process_subways.py.

   Due to unordered nature of sets/dicts, two runs of process_subways.py
   even on the same input generate equivalent jsons,
   which cannot be compared with 'diff' command. The compare_jsons() function
   compares two city_cache.json taking into account possible shuffling of
   dict items and items of some lists, as well as system-specific subtleties.
   This utility is useful to ensure that code improvements which must not
   affect the process_subways.py output really doesn't change it.
"""

import sys
import json
import logging
from common import compare_stops, compare_transfers, compare_networks


def compare_jsons(cache0, cache1):
    """Compares two city caches"""

    city_names0 = sorted(cache0.keys())
    city_names1 = sorted(cache1.keys())
    if city_names0 != city_names1:
        logging.debug("Different list of city names!")
        return False

    for name in city_names0:
        city0 = cache0[name]
        city1 = cache1[name]
        if not compare_networks(city0['network'], city1['network']):
            return False

        stop_ids0 = sorted(city0['stops'].keys())
        stop_ids1 = sorted(city1['stops'].keys())
        if stop_ids0 != stop_ids1:
            logging.debug("Different stop_ids")
            return False
        stops0 = [v for k, v in sorted(city0['stops'].items())]
        stops1 = [v for k, v in sorted(city1['stops'].items())]
        for stop0, stop1 in zip(stops0, stops1):
            if not compare_stops(stop0, stop1):
                return False

        if not compare_transfers(city0['transfers'], city1['transfers']):
            return False

    return True


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: {} <cache1.json> <cache2.json>".format(sys.argv[0]))
        sys.exit()

    logging.basicConfig(level=logging.DEBUG)

    path0, path1 = sys.argv[1:3]

    j0 = json.load(open(path0, encoding='utf-8'))
    j1 = json.load(open(path1, encoding='utf-8'))

    equal = compare_jsons(j0, j1)

    print("The city caches are {}equal".format("" if equal else "NOT "))
