#!/usr/bin/env python3
import argparse
import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request

from subway_structure import (
    download_cities,
    find_transfers,
    get_unused_entrances_geojson,
)


def overpass_request(bboxes=None):
    query = '[out:json][timeout:1000];('
    if bboxes is None:
        bboxes = [None]
    for bbox in bboxes:
        bbox_part = '' if not bbox else '({})'.format(','.join(bbox))
        for t, k, v in (('rel', 'route', 'subway'),
                        ('rel', 'route', 'light_rail'),
                        ('rel', 'route_master', 'subway'),
                        ('rel', 'route_master', 'light_rail'),
                        ('rel', 'public_transport', 'stop_area'),
                        ('rel', 'public_transport', 'stop_area_group'),
                        ('node', 'railway', 'subway_entrance')):
            query += '{}["{}"="{}"]{};'.format(t, k, v, bbox_part)
    query += ');(._;>);out body center qt;'
    logging.debug('Query: %s', query)
    url = 'http://overpass-api.de/api/interpreter?data={}'.format(urllib.parse.quote(query))
    response = urllib.request.urlopen(url, timeout=1000)
    if response.getcode() != 200:
        raise Exception('Failed to query Overpass API: HTTP {}'.format(response.getcode()))
    return json.load(response)['elements']


def multi_overpass(bboxes):
    if not bboxes:
        return overpass_request(None)
    SLICE_SIZE = 10
    result = []
    for i in range(0, len(bboxes) + SLICE_SIZE - 1, SLICE_SIZE):
        if i > 0:
            time.sleep(5)
        result.append(overpass_request(bboxes[i:i+SLICE_SIZE]))
    return result


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


def dump_data(city, f):
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
                f.write(indent + str(k) + ': ')
                write_yaml(v, f, indent + '  ')
                if isinstance(v, (list, set, dict)):
                    f.write('\n')
        else:
            f.write(data)
            f.write('\n')

    stops = set()
    routes = []
    for route in city:
        rte = {
            'type': route.mode,
            'ref': route.ref,
            'name': route.name,
            'itineraries': []
        }
        for variant in route:
            v_stops = []
            for s in variant:
                if s.id == s.station.id:
                    v_stops.append('{} ({})'.format(s.station.name, s.station.id))
                else:
                    v_stops.append('{} ({}) in {} ({})'.format(s.station.name, s.station.id,
                                                               s.name, s.id))
            rte['itineraries'].append(v_stops)
            stops.update(v_stops)
        routes.append(rte)
    transfers = []
    for t in city.transfers:
        v_stops = ['{} ({})'.format(s.name, s.id) for s in t]
        transfers.append(v_stops)

    result = {
        'stations': sorted(stops),
        'transfers': transfers,
        'routes': sorted(routes, key=lambda r: r['ref']),
    }
    write_yaml(result, f)


def prepare_mapsme_data(transfers, cities):
    stops = {}  # el_id -> station data
    networks = []
    for city in cities:
        network = {'network': city.name, 'routes': []}
        for route in city:
            routes = {
                'type': route.mode,
                'ref': route.ref,
                'name': route.name,
                'route_id': 0,  # TODO
                'itineraries': []
            }
            for variant in route:
                stops = []
                # TODO
            network['routes'].append(routes)
        networks.append(network)
    # TODO: prepare a set of all stations
    c_transfers = []
    for t in transfers:
        # TODO: decouple transfers and add travel time
        pass
    result = {
        'stops': list(stops.values()),
        'transfers': c_transfers,
        'networks': networks
    }
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-i', '--source', help='File to write backup of OSM data, or to read data from')
    parser.add_argument('-x', '--xml', help='OSM extract with routes, to read data from')
    parser.add_argument(
        '-b', '--bbox', action='store_true',
        help='Use city boundaries to query Overpass API instead of querying the world')
    parser.add_argument('-q', '--quiet', action='store_true', help='Show only warnings and errors')
    parser.add_argument('-c', '--city', help='Validate only a single city')
    parser.add_argument('-e', '--entrances', type=argparse.FileType('w'),
                        help='Export unused subway entrances as GeoJSON here')
    parser.add_argument('-l', '--log', type=argparse.FileType('w'),
                        help='Validation JSON file name')
    parser.add_argument('-o', '--output', type=argparse.FileType('w'),
                        help='JSON file for MAPS.ME')
    parser.add_argument('-d', '--dump', type=argparse.FileType('w'),
                        help='Make a YAML file for a city data')
    options = parser.parse_args()

    if options.quiet:
        log_level = logging.WARNING
    else:
        log_level = logging.INFO
    logging.basicConfig(level=log_level, datefmt='%H:%M:%S',
                        format='%(asctime)s %(levelname)-7s  %(message)s')

    # Downloading cities from Google Spreadsheets
    cities = download_cities()
    if options.city:
        cities = [c for c in cities if c.name == options.city]
    if not cities:
        logging.error('No cities to process')
        sys.exit(2)
    logging.info('Read %s metro networks', len(cities))

    # Reading cached json, loading XML or querying Overpass API
    if options.source and os.path.exists(options.source):
        logging.info('Reading %s', options.source)
        with open(options.source, 'r') as f:
            osm = json.load(f)
            if 'elements' in osm:
                osm = osm['elements']
    elif options.xml:
        logging.info('Reading %s', options.xml)
        osm = load_xml(options.xml)
        if options.source:
            with open(options.source, 'w') as f:
                json.dump(osm, f)
    else:
        if options.bbox:
            bboxes = [c.bbox for c in cities]
        else:
            bboxes = None
        logging.info('Downloading data from Overpass API')
        osm = multi_overpass(bboxes)
        if options.source:
            with open(options.source, 'w') as f:
                json.dump(osm, f)
    logging.info('Downloaded %s elements, sorting by city', len(osm))

    # Sorting elements by city and prepare a dict
    for el in osm:
        for c in cities:
            if c.contains(el):
                c.add(el)

    logging.info('Building routes for each city')
    good_cities = []
    for c in cities:
        c.extract_routes()
        c.validate()
        if c.is_good():
            good_cities.append(c)

    logging.info('Finding transfer stations')
    transfers = find_transfers(osm, cities)

    logging.info('%s good cities: %s', len(good_cities), ', '.join([c.name for c in good_cities]))

    if options.log:
        res = [x.get_validation_result() for x in cities]
        json.dump(res, options.log)

    if options.entrances:
        json.dump(get_unused_entrances_geojson(osm), options.entrances)

    if options.dump:
        dump_data(cities[0], options.dump)

    # Finally, prepare a JSON file for MAPS.ME
    if options.output:
        json.dump(prepare_mapsme_data(transfers, good_cities), options.output)
