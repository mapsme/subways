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
from itertools import chain


def compare_jsons(result0, result1):

    def floats_eq(a, b):
        return abs(b - a) < 1e-13

    def coords_eq(lon1, lat1, lon2, lat2):
        return floats_eq(lon1, lon2) and floats_eq(lat1, lat2)

    def osm_id_comparator(el):
        return (el['osm_type'], el['osm_id'])

    network_names0 = sorted([x['network'] for x in result0['networks']])
    network_names1 = sorted([x['network'] for x in result1['networks']])

    if network_names0 != network_names1:
        print("Different list of network names!")
        return False

    networks0 = sorted(result0['networks'], key=lambda x: x['network'])
    networks1 = sorted(result1['networks'], key=lambda x: x['network'])

    # Keys to compare routes. 'name' key is omitted since RouteMaster
    # can get its name from one of its Routes unpredictably.
    route_keys = ('type', 'ref', 'colour', 'route_id')

    for network0, network1 in zip(networks0, networks1):
        if network0['agency_id'] != network1['agency_id']:
            print("Different agency_id:",
                  network0['network'], network1['network'])
            return False

        route_ids0 = sorted(x['route_id'] for x in network0['routes'])
        route_ids1 = sorted(x['route_id'] for x in network1['routes'])

        if route_ids0 != route_ids1:
            print("Different route_ids", route_ids0, route_ids1)
            return False

        routes0 = sorted(network0['routes'], key=lambda x: x['route_id'])
        routes1 = sorted(network1['routes'], key=lambda x: x['route_id'])

        for route0, route1 in zip(routes0, routes1):
            route0_props = tuple(route0[k] for k in route_keys)
            route1_props = tuple(route1[k] for k in route_keys)
            if route0_props != route1_props:
                print("Route props of ", route0['route_id'], route1['route_id'],
                      "are different:", route0_props, route1_props)
                return False

            itineraries0 = sorted(route0['itineraries'],
                                  key=lambda x: tuple(chain(*x['stops'])))
            itineraries1 = sorted(route1['itineraries'],
                                  key=lambda x: tuple(chain(*x['stops'])))

            for itin0, itin1 in zip(itineraries0, itineraries1):
                if itin0['interval'] != itin1['interval']:
                    print("Different interval:",
                          f"{itin0['interval']} != {itin1['interval']}"
                          f" at route {route0['name']} {route0['route_id']}")
                    return False
                if itin0['stops'] != itin1['stops']:
                    print(f"Different stops at route",
                          f"{route0['name']} {route0['route_id']}")
                    return False

    stop_ids0 = sorted(x['id'] for x in result0['stops'])
    stop_ids1 = sorted(x['id'] for x in result1['stops'])
    if stop_ids0 != stop_ids1:
        print("Different stop_ids")
        return False

    stops0 = sorted(result0['stops'], key=lambda x: x['id'])
    stops1 = sorted(result1['stops'], key=lambda x: x['id'])

    for stop0, stop1 in zip(stops0, stops1):
        stop0_props = tuple(stop0[k] for k in ('name', 'osm_id', 'osm_type'))
        stop1_props = tuple(stop1[k] for k in ('name', 'osm_id', 'osm_type'))
        if stop0_props != stop1_props:
            print("Different stops properties:", stop0_props, stop1_props)
            return False
        if not coords_eq(stop0['lon'], stop0['lat'],
                         stop1['lon'], stop1['lat']):
            print("Different stops coordinates:",
                  stop0_props, stop0['lon'], stop0['lat'],
                  stop1_props, stop1['lon'], stop1['lat'])
            return False

        entrances0 = sorted(stop0['entrances'], key=osm_id_comparator)
        entrances1 = sorted(stop1['entrances'], key=osm_id_comparator)
        if entrances0 != entrances1:
            print("Different stop entrances")
            return False

        exits0 = sorted(stop0['exits'], key=osm_id_comparator)
        exits1 = sorted(stop1['exits'], key=osm_id_comparator)
        if exits0 != exits1:
            print("Different stop exits")
            return False

    if len(result0['transfers']) != len(result1['transfers']):
        print("Different len(transfers):",
              len(result0['transfers']), len(result1['transfers']))
        return False

    transfers0 = [tuple(t) if t[0] < t[1] else tuple([t[1], t[0], t[2]])
                      for t in result0['transfers']]
    transfers1 = [tuple(t) if t[0] < t[1] else tuple([t[1], t[0], t[2]])
                      for t in result1['transfers']]

    transfers0.sort(key=lambda x: tuple(x))
    transfers1.sort(key=lambda x: tuple(x))

    diff_cnt = 0
    for i, (tr0, tr1) in enumerate(zip(transfers0, transfers1)):
        if tr0 != tr1:
            if i == 0:
                print("First pair of different transfers", tr0, tr1)
            diff_cnt += 1
    if diff_cnt:
        print("Different transfers number = ", diff_cnt)
        return False

    return True


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: {} <file1.json> <file2.json>".format(sys.argv[0]))
        sys.exit()

    path0, path1 = sys.argv[1:3]

    j0 = json.load(open(path0, encoding='utf-8'))
    j1 = json.load(open(path1, encoding='utf-8'))

    equal = compare_jsons(j0, j1)

    print("The results are {}equal".format("" if equal else "NOT "))