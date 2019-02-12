import json
import os
import itertools
from collections import defaultdict
from subway_structure import distance, el_center, Station


OSM_TYPES = {'n': (0, 'node'), 'w': (2, 'way'), 'r': (3, 'relation')}
ENTRANCE_PENALTY = 60  # seconds
SPEED_TO_ENTRANCE = 5  # km/h
SPEED_ON_TRANSFER = 3.5
SPEED_ON_LINE = 40
DEFAULT_INTERVAL = 2.5  # minutes
CLOSENESS_TO_CACHED_ELEMENT_THRESHOLD = 300  # meters


def process(cities, transfers, cache_name):
    def uid(elid, typ=None):
        t = elid[0]
        osm_id = int(elid[1:])
        if not typ:
            osm_id = (osm_id << 2) + OSM_TYPES[t][0]
        elif typ != t:
            raise Exception('Got {}, expected {}'.format(elid, typ))
        return osm_id << 1

    def format_colour(c):
        return c[1:] if c else None

    def find_exits_for_platform(center, nodes):
        exits = []
        min_distance = None
        for n in nodes:
            d = distance(center, (n['lon'], n['lat']))
            if not min_distance:
                min_distance = d * 2 / 3
            elif d < min_distance:
                continue
            too_close = False
            for e in exits:
                d = distance((e['lon'], e['lat']), (n['lon'], n['lat']))
                if d < min_distance:
                    too_close = True
                    break
            if not too_close:
                exits.append(n)
        return exits

    def is_cached_city_usable(city, city_cache_data):
        """Checks if cached stops and entrances still exist in osm data"""
        for stoparea_id, cached_stoparea in city_cache_data['stops'].items():
            station_id = cached_stoparea['osm_type'][0] + str(cached_stoparea['osm_id'])
            city_station = city.elements.get(station_id)
            if (not city_station or
                not Station.is_station(city_station, city.modes) or
                distance(el_center(city_station),
                         tuple(cached_stoparea[coord] for coord in ('lon', 'lat'))
                        ) > CLOSENESS_TO_CACHED_ELEMENT_THRESHOLD
            ):
                return False

            for cached_entrance in itertools.chain(cached_stoparea['entrances'],
                                                   cached_stoparea['exits']):
                entrance_id = cached_entrance['osm_type'][0] + str(cached_entrance['osm_id'])
                city_entrance = city.elements.get(entrance_id)
                if (not city_entrance or
                    distance(el_center(city_entrance),
                             tuple(cached_entrance[coord] for coord in ('lon', 'lat'))
                            ) > CLOSENESS_TO_CACHED_ELEMENT_THRESHOLD
                ):
                    pass  # TODO:
                          # really pass (take cached entances as they are)?
                          # Or return False?
                          # Or count broken entrances and leave only good?
                          # Or ignore all old entrances and use station point as entrance and exit?

        return True


    cache = {}
    if cache_name and os.path.exists(cache_name):
        with open(cache_name, 'r', encoding='utf-8') as f:
            cache = json.load(f)

    stop_areas = {}  # stoparea el_id -> StopArea instance
    stops = {}  # stoparea el_id -> stop jsonified data
    networks = []

    good_cities = [c for c in cities if c.is_good()]
    good_city_names = set(c.name for c in good_cities)
    recovered_city_names = set()

    for city_name, city_cached_data in cache.items():
        if city_name in good_city_names:
            continue
        # TODO: get a network, stops and transfers from cache
        city = [c for c in cities if c.name == city_name][0]
        if is_cached_city_usable(city, city_cached_data):
            stops.update(city_cached_data['stops'])
            networks.append(city_cached_data['network'])
            print("Taking {} from cache".format(city_name))
            recovered_city_names.add(city.name)

    platform_nodes = {}

    # One stoparea may participate in routes of different cities
    stop_cities = defaultdict(set)  # stoparea id -> city names

    for city in good_cities:
        network = {'network': city.name, 'routes': [], 'agency_id': city.id}
        cache[city.name] = {
            'network': network,
            'stops': {},  # stoparea el_id -> jsonified stop data
            'transfers': []  # list of tuples (stoparea1_uid, stoparea2_uid, time); uid1 < uid2
        }
        for route in city:
            routes = {
                'type': route.mode,
                'ref': route.ref,
                'name': route.name,
                'colour': format_colour(route.colour),
                'route_id': uid(route.id, 'r'),
                'itineraries': []
            }
            if route.infill:
                routes['casing'] = routes['colour']
                routes['colour'] = format_colour(route.infill)
            for i, variant in enumerate(route):
                itin = []
                for stop in variant:
                    stop_areas[stop.stoparea.id] = stop.stoparea
                    stop_cities[stop.stoparea.id].add(city.name)
                    itin.append([uid(stop.stoparea.id), round(stop.distance*3.6/SPEED_ON_LINE)])
                    # Make exits from platform nodes, if we don't have proper exits
                    if len(stop.stoparea.entrances) + len(stop.stoparea.exits) == 0:
                        for pl in stop.stoparea.platforms:
                            pl_el = city.elements[pl]
                            if pl_el['type'] == 'node':
                                pl_nodes = [pl_el]
                            elif pl_el['type'] == 'way':
                                pl_nodes = [city.elements.get('n{}'.format(n))
                                            for n in pl_el['nodes']]
                            else:
                                pl_nodes = []
                                for m in pl_el['members']:
                                    if m['type'] == 'way':
                                        if '{}{}'.format(m['type'][0], m['ref']) in city.elements:
                                            pl_nodes.extend(
                                                [city.elements.get('n{}'.format(n))
                                                 for n in city.elements['{}{}'.format(
                                                     m['type'][0], m['ref'])]['nodes']])
                            pl_nodes = [n for n in pl_nodes if n]
                            platform_nodes[pl] = find_exits_for_platform(
                                stop.stoparea.centers[pl], pl_nodes)

                routes['itineraries'].append({
                    'stops': itin,
                    'interval': round((variant.interval or DEFAULT_INTERVAL) * 60)
                })
            network['routes'].append(routes)
        networks.append(network)

    for stop_id, stop in stop_areas.items():
        st = {
            'name': stop.name,
            'int_name': stop.int_name,
            'lat': stop.center[1],
            'lon': stop.center[0],
            'osm_type': OSM_TYPES[stop.station.id[0]][1],
            'osm_id': int(stop.station.id[1:]),
            'id': uid(stop.id),
            'entrances': [],
            'exits': [],
        }
        for e_l, k in ((stop.entrances, 'entrances'), (stop.exits, 'exits')):
            for e in e_l:
                if e[0] == 'n':
                    st[k].append({
                        'osm_type': 'node',
                        'osm_id': int(e[1:]),
                        'lon': stop.centers[e][0],
                        'lat': stop.centers[e][1],
                        'distance': ENTRANCE_PENALTY + round(distance(
                            stop.centers[e], stop.center)*3.6/SPEED_TO_ENTRANCE)
                    })
        if len(stop.entrances) + len(stop.exits) == 0:
            if stop.platforms:
                for pl in stop.platforms:
                    for n in platform_nodes[pl]:
                        for k in ('entrances', 'exits'):
                            st[k].append({
                                'osm_type': n['type'],
                                'osm_id': n['id'],
                                'lon': n['lon'],
                                'lat': n['lat'],
                                'distance': ENTRANCE_PENALTY + round(distance(
                                    (n['lon'], n['lat']), stop.center)*3.6/SPEED_TO_ENTRANCE)
                            })
            else:
                for k in ('entrances', 'exits'):
                    st[k].append({
                        'osm_type': OSM_TYPES[stop.station.id[0]][1],
                        'osm_id': int(stop.station.id[1:]),
                        'lon': stop.centers[stop.id][0],
                        'lat': stop.centers[stop.id][1],
                        'distance': 60
                    })

        stops[stop_id] = st
        for city_name in stop_cities[stop_id]:
            cache[city_name]['stops'][stop_id] = st

    m_stops = list(stops.values())

    c_transfers = {}  # (stoparea1_uid, stoparea2_uid) -> time;  uid1 < uid2
    for t_set in transfers:
        t = list(t_set)
        for t_first in range(len(t) - 1):
            for t_second in range(t_first + 1, len(t)):
                stoparea1 = t[t_first]
                stoparea2 = t[t_second]
                if stoparea1.id in stops and stoparea2.id in stops:
                    uid1 = uid(stoparea1.id)
                    uid2 = uid(stoparea2.id)
                    uid1, uid2 = sorted([uid1, uid2])
                    transfer_time = (30 + round(distance(stoparea1.center,
                                                         stoparea2.center
                                                ) * 3.6/SPEED_ON_TRANSFER))
                    c_transfers[(uid1, uid2)] = transfer_time
                    # If a transfer is inside a good city, add it to the city's cache.
                    for city_name in (good_city_names &
                                      stop_cities[stoparea1.id] &
                                      stop_cities[stoparea2.id]):
                        cache[city_name]['transfers'].append((uid1, uid2, transfer_time))

    # Some transfers may be corrupted in not good cities.
    # Take them from recovered cities.
    for city_name in recovered_city_names:
        for stop1_uid, stop2_uid, transfer_time in cache[city_name]['transfers']:
            if (stop1_uid, stop2_uid) not in c_transfers:
                c_transfers[(stop1_uid, stop2_uid)] = transfer_time

    if cache_name:
        with open(cache_name, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)

    m_transfers = [(stop1_uid, stop2_uid, transfer_time)
                   for (stop1_uid, stop2_uid), transfer_time in c_transfers.items()]

    result = {
        'stops': m_stops,
        'transfers': m_transfers,
        'networks': networks
    }
    return result
