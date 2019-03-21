import logging
import math
import functools
from itertools import chain


"""A coordinate of a station precision of which we must take into account
is calculated as an average of somewhat 10 elements.
Taking machine epsilon 1e-15, averaging 10 numbers with close magnitudes
ensures relative precision of 1e-14."""
coord_isclose = functools.partial(math.isclose, rel_tol=1e-14)


def coords_eq(lon1, lat1, lon2, lat2):
    return coord_isclose(lon1, lon2) and coord_isclose(lat1, lat2)


def osm_id_comparator(el):
    """This function is used as key for sorting lists of
       OSM-originated objects
    """
    return (el['osm_type'], el['osm_id'])


def compare_stops(stop0, stop1):
    """Compares json of two stops in route"""
    stop_keys = ('name', 'int_name', 'id', 'osm_id', 'osm_type')
    stop0_props = tuple(stop0[k] for k in stop_keys)
    stop1_props = tuple(stop1[k] for k in stop_keys)

    if stop0_props != stop1_props:
        logging.debug("Different stops properties: %s, %s",
                      stop0_props, stop1_props)
        return False

    if not coords_eq(stop0['lon'], stop0['lat'],
                     stop1['lon'], stop1['lat']):
        logging.debug("Different stops coordinates: %s (%f, %f), %s (%f, %f)",
                      stop0_props, stop0['lon'], stop0['lat'],
                      stop1_props, stop1['lon'], stop1['lat'])
        return False

    entrances0 = sorted(stop0['entrances'], key=osm_id_comparator)
    entrances1 = sorted(stop1['entrances'], key=osm_id_comparator)
    if entrances0 != entrances1:
        logging.debug("Different stop entrances")
        return False

    exits0 = sorted(stop0['exits'], key=osm_id_comparator)
    exits1 = sorted(stop1['exits'], key=osm_id_comparator)
    if exits0 != exits1:
        logging.debug("Different stop exits")
        return False

    return True


def compare_transfers(transfers0, transfers1):
    """Compares two arrays of transfers of the form
       [(stop1_uid, stop2_uid, time), ...]
    """
    if len(transfers0) != len(transfers1):
        logging.debug("Different len(transfers): %d != %d",
                      len(transfers0), len(transfers1))
        return False

    transfers0 = [tuple([t[0], t[1], t[2]])
                      if t[0] < t[1] else
                  tuple([t[1], t[0], t[2]])
                      for t in transfers0]
    transfers1 = [tuple([t[0], t[1], t[2]])
                      if t[0] < t[1] else
                  tuple([t[1], t[0], t[2]])
                      for t in transfers1]

    transfers0.sort()
    transfers1.sort()

    diff_cnt = 0
    for tr0, tr1 in zip(transfers0, transfers1):
        if tr0 != tr1:
            if diff_cnt == 0:
                logging.debug("First pair of different transfers: %s, %s",
                              tr0, tr1)
            diff_cnt += 1
    if diff_cnt:
        logging.debug("Different transfers number = %d", diff_cnt)
        return False

    return True


def compare_networks(network0, network1):
    if network0['agency_id'] != network1['agency_id']:
        logging.debug("Different agency_id at route '%s'",
                      network0['network'])
        return False

    route_ids0 = sorted(x['route_id'] for x in network0['routes'])
    route_ids1 = sorted(x['route_id'] for x in network1['routes'])

    if route_ids0 != route_ids1:
        logging.debug("Different route_ids: %s != %s",
                      route_ids0, route_ids1)
        return False

    routes0 = sorted(network0['routes'], key=lambda x: x['route_id'])
    routes1 = sorted(network1['routes'], key=lambda x: x['route_id'])

    # Keys to compare routes. 'name' key is omitted since RouteMaster
    # can get its name from one of its Routes unpredictably.
    route_keys = ('type', 'ref', 'colour', 'route_id')

    for route0, route1 in zip(routes0, routes1):
        route0_props = tuple(route0[k] for k in route_keys)
        route1_props = tuple(route1[k] for k in route_keys)
        if route0_props != route1_props:
            logging.debug("Route props of '%s' are different: %s, %s",
                          route0['route_id'], route0_props, route1_props)
            return False

        itineraries0 = sorted(route0['itineraries'],
                              key=lambda x: tuple(chain(*x['stops'])))
        itineraries1 = sorted(route1['itineraries'],
                              key=lambda x: tuple(chain(*x['stops'])))

        for itin0, itin1 in zip(itineraries0, itineraries1):
            if itin0['interval'] != itin1['interval']:
                logging.debug("Different interval: %d != %d at route %s '%s'",
                              itin0['interval'], itin1['interval'],
                              route0['route_id'], route0['name'])
                return False
            if itin0['stops'] != itin1['stops']:
                logging.debug("Different stops at route %s '%s'",
                              route0['route_id'], route0['name'])
                return False

    return True
