"""This utility allows one to check equivalency of outputs (defined
   by --output command line parameter) of process_subways.py.

   Due to unordered nature of sets/dicts, two runs of process_subways.py
   even on the same input generate equivalent jsons,
   which cannot be compared with 'diff' command. The compare_jsons() function
   compares two osm_subways.json taking into account possible shuffling of
   dict items and items of some lists, as well as system-specific subtleties.
   This utility is useful to ensure that code improvements which must not
   affect the process_subways.py output really doesn't change it.
"""

import sys
import json
import logging
from common import compare_stops, compare_transfers, compare_networks


def compare_jsons(result0, result1):
    """Compares two objects which are results of subway generation"""

    network_names0 = sorted([x['network'] for x in result0['networks']])
    network_names1 = sorted([x['network'] for x in result1['networks']])
    if network_names0 != network_names1:
        logging.debug("Different list of network names!")
        return False
    networks0 = sorted(result0['networks'], key=lambda x: x['network'])
    networks1 = sorted(result1['networks'], key=lambda x: x['network'])
    for network0, network1 in zip(networks0, networks1):
        if not compare_networks(network0, network1):
            return False

    stop_ids0 = sorted(x['id'] for x in result0['stops'])
    stop_ids1 = sorted(x['id'] for x in result1['stops'])
    if stop_ids0 != stop_ids1:
        logging.debug("Different stop_ids")
        return False
    stops0 = sorted(result0['stops'], key=lambda x: x['id'])
    stops1 = sorted(result1['stops'], key=lambda x: x['id'])
    for stop0, stop1 in zip(stops0, stops1):
        if not compare_stops(stop0, stop1):
            return False

    if not compare_transfers(result0['transfers'], result1['transfers']):
        return False

    return True


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: {} <file1.json> <file2.json>".format(sys.argv[0]))
        sys.exit()

    logging.basicConfig(level=logging.DEBUG)

    path0, path1 = sys.argv[1:3]

    j0 = json.load(open(path0, encoding='utf-8'))
    j1 = json.load(open(path1, encoding='utf-8'))

    equal = compare_jsons(j0, j1)

    print("The results are {}equal".format("" if equal else "NOT "))
