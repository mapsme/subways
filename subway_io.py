import json
import logging
from collections import OrderedDict


def load_xml(f):
    try:
        from lxml import etree
    except ImportError:
        import xml.etree.ElementTree as etree

    elements = []
    nodes = {}
    for event, element in etree.iterparse(f):
        if element.tag in ('node', 'way', 'relation'):
            el = {'type': element.tag, 'id': int(element.get('id'))}
            if element.tag == 'node':
                for n in ('lat', 'lon'):
                    el[n] = float(element.get(n))
                nodes[el['id']] = (el['lat'], el['lon'])
            tags = {}
            nd = []
            members = []
            for sub in element:
                if sub.tag == 'tag':
                    tags[sub.get('k')] = sub.get('v')
                elif sub.tag == 'nd':
                    nd.append(int(sub.get('ref')))
                elif sub.tag == 'member':
                    members.append({'type': sub.get('type'),
                                    'ref': int(sub.get('ref')),
                                    'role': sub.get('role', '')})
            if tags:
                el['tags'] = tags
            if nd:
                el['nodes'] = nd
            if members:
                el['members'] = members
            elements.append(el)
            element.clear()

    # Now make centers, assuming relations go after ways
    ways = {}
    relations = {}
    for el in elements:
        if el['type'] == 'way' and 'nodes' in el:
            center = [0, 0]
            count = 0
            for nd in el['nodes']:
                if nd in nodes:
                    center[0] += nodes[nd][0]
                    center[1] += nodes[nd][1]
                    count += 1
            if count > 0:
                el['center'] = {'lat': center[0]/count, 'lon': center[1]/count}
                ways[el['id']] = (el['center']['lat'], el['center']['lon'])
        elif el['type'] == 'relation' and 'members' in el:
            center = [0, 0]
            count = 0
            for m in el['members']:
                if m['type'] == 'node' and m['ref'] in nodes:
                    center[0] += nodes[m['ref']][0]
                    center[1] += nodes[m['ref']][1]
                    count += 1
                elif m['type'] == 'way' and m['ref'] in ways:
                    center[0] += ways[m['ref']][0]
                    center[1] += ways[m['ref']][1]
                    count += 1
            if count > 0:
                el['center'] = {'lat': center[0]/count, 'lon': center[1]/count}
                relations[el['id']] = (el['center']['lat'], el['center']['lon'])

    # Iterating again, now filling relations that contain only relations
    for el in elements:
        if el['type'] == 'relation' and 'members' in el:
            center = [0, 0]
            count = 0
            for m in el['members']:
                if m['type'] == 'node' and m['ref'] in nodes:
                    center[0] += nodes[m['ref']][0]
                    center[1] += nodes[m['ref']][1]
                    count += 1
                elif m['type'] == 'way' and m['ref'] in ways:
                    center[0] += ways[m['ref']][0]
                    center[1] += ways[m['ref']][1]
                    count += 1
                elif m['type'] == 'relation' and m['ref'] in relations:
                    center[0] += relations[m['ref']][0]
                    center[1] += relations[m['ref']][1]
                    count += 1
            if count > 0:
                el['center'] = {'lat': center[0]/count, 'lon': center[1]/count}
                relations[el['id']] = (el['center']['lat'], el['center']['lon'])
    return elements


_YAML_SPECIAL_CHARACTERS = "!&*{}[],#|>@`'\""
_YAML_SPECIAL_SEQUENCES = ("- ", ": ", "? ")

def _get_yaml_compatible_string(scalar):
    """Enclose string in single quotes in some cases"""
    string = str(scalar)
    if (string and
            (string[0] in _YAML_SPECIAL_CHARACTERS
             or any(seq in string for seq in _YAML_SPECIAL_SEQUENCES)
             or string.endswith(':'))):
        string = string.replace("'", "''")
        string = "'{}'".format(string)
    return string


def dump_yaml(city, f):
    def write_yaml(data, f, indent=''):
        if isinstance(data, (set, list)):
            f.write('\n')
            for i in data:
                f.write(indent)
                f.write('- ')
                write_yaml(i, f, indent + '  ')
        elif isinstance(data, dict):
            f.write('\n')
            for k, v in data.items():
                if v is None:
                    continue
                f.write(indent + _get_yaml_compatible_string(k) + ': ')
                write_yaml(v, f, indent + '  ')
                if isinstance(v, (list, set, dict)):
                    f.write('\n')
        else:
            f.write(_get_yaml_compatible_string(data))
            f.write('\n')

    INCLUDE_STOP_AREAS = False
    stops = set()
    routes = []
    for route in city:
        stations = OrderedDict([(sa.transfer or sa.id, sa.name) for sa in route.stop_areas()])
        rte = {
            'type': route.mode,
            'ref': route.ref,
            'name': route.name,
            'colour': route.colour,
            'infill': route.infill,
            'station_count': len(stations),
            'stations': list(stations.values()),
            'itineraries': {}
        }
        for variant in route:
            if INCLUDE_STOP_AREAS:
                v_stops = []
                for st in variant:
                    s = st.stoparea
                    if s.id == s.station.id:
                        v_stops.append('{} ({})'.format(s.station.name, s.station.id))
                    else:
                        v_stops.append('{} ({}) in {} ({})'.format(s.station.name, s.station.id,
                                                                   s.name, s.id))
            else:
                v_stops = ['{} ({})'.format(
                    s.stoparea.station.name,
                    s.stoparea.station.id) for s in variant]
            rte['itineraries'][variant.id] = v_stops
            stops.update(v_stops)
        routes.append(rte)
    transfers = []
    for t in city.transfers:
        v_stops = ['{} ({})'.format(s.name, s.id) for s in t]
        transfers.append(sorted(v_stops))

    result = {
        'stations': sorted(stops),
        'transfers': sorted(transfers, key=lambda t: t[0]),
        'routes': sorted(routes, key=lambda r: r['ref']),
    }
    write_yaml(result, f)


def make_geojson(city, tracks=True):
    transfers = set()
    for t in city.transfers:
        transfers.update(t)
    features = []
    stopareas = set()
    stops = set()
    for rmaster in city:
        for variant in rmaster:
            if not tracks:
                features.append({
                    'type': 'Feature',
                    'geometry': {
                        'type': 'LineString',
                        'coordinates': [s.stop for s in variant],
                    },
                    'properties': {
                        'ref': variant.ref,
                        'name': variant.name,
                        'stroke': variant.colour
                    }
                })
            elif variant.tracks:
                features.append({
                    'type': 'Feature',
                    'geometry': {
                        'type': 'LineString',
                        'coordinates': variant.tracks,
                    },
                    'properties': {
                        'ref': variant.ref,
                        'name': variant.name,
                        'stroke': variant.colour
                    }
                })
            for st in variant:
                stops.add(st.stop)
                stopareas.add(st.stoparea)

    for stop in stops:
        features.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': stop,
            },
            'properties': {
                'marker-size': 'small',
                'marker-symbol': 'circle'
            }
        })
    for stoparea in stopareas:
        features.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': stoparea.center,
            },
            'properties': {
                'name': stoparea.name,
                'marker-size': 'small',
                'marker-color': '#ff2600' if stoparea in transfers else '#797979'
            }
        })
    return {'type': 'FeatureCollection', 'features': features}



def _dumps_route_id(route_id):
    """Argument is a route_id that depends on route colour and ref. Name
    can be taken from route_master or can be route's own, we don't take it
    into consideration. Some of route attributes can be None. The function makes
    route_id json-compatible - dumps it to a string."""
    return json.dumps(route_id, ensure_ascii=False)


def _loads_route_id(route_id_dump):
    """Argument is a json-encoded identifier of a route.
    Return a tuple (colour, ref)."""
    return tuple(json.loads(route_id_dump))


def read_recovery_data(path):
    """Recovery data is a json with data from previous transport builds.
    It helps to recover cities from some errors, e.g. by resorting
    shuffled stations in routes."""
    data = None
    try:
        with open(path, 'r') as f:
            try:
                data = json.load(f)
            except json.decoder.JSONDecodeError as e:
                logging.warning("Cannot load recovery data: {}".format(e))
    except FileNotFoundError:
        logging.warning("Cannot find recovery data file '{}'".format(path))

    if data is None:
        logging.warning("Continue without recovery data.")
        return {}
    else:
        data = {
            city_name: {_loads_route_id(route_id): route_data
                                 for route_id, route_data in routes.items()}
                    for city_name, routes in data.items()
        }
        return data


def write_recovery_data(path, current_data, cities):
    """Updates recovery data with good cities data and writes to file."""

    def make_city_recovery_data(city):
        routes = {}
        for route in city:
            # Recovery is based primarily on route/station names/refs.
            # If route's ref/colour changes, the route won't be used.
            route_id = (route.colour, route.ref)
            itineraries = []
            for variant in route:
                itin = {'stations': [],
                        'name': variant.name,
                        'from': variant.element['tags'].get('from'),
                        'to': variant.element['tags'].get('to')}
                for stop in variant:
                    station = stop.stoparea.station
                    station_name = station.name
                    if station_name == '?' and station.int_name:
                        station_name = station.int_name
                    itin['stations'].append({
                        'oms_id': station.id,
                        'name': station_name,
                        'center': station.center
                    })
                if itin is not None:
                    itineraries.append(itin)
            routes[route_id] = itineraries
        return routes

    data = current_data
    for city in cities:
        if city.is_good():
            data[city.name] = make_city_recovery_data(city)

    try:
        data = {
            city_name: {_dumps_route_id(route_id): route_data
                        for route_id, route_data in routes.items()}
            for city_name, routes in data.items()
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning("Cannot write recovery data to '%s': %s", path, str(e))

