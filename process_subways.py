#!/usr/bin/env python3
import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from processors import processor
from subway_io import (
    dump_yaml,
    load_xml,
    make_geojson,
    read_recovery_data,
    write_recovery_data,
)
from subway_structure import (
    CriticalValidationError,
    download_cities,
    find_transfers,
    get_unused_entrances_geojson,
    MODES_OVERGROUND,
    MODES_RAPID,
)


def overpass_request(overground, overpass_api, bboxes=None):
    query = '[out:json][timeout:1000];('
    if bboxes is None:
        bboxes = [None]
    modes = MODES_OVERGROUND if overground else MODES_RAPID
    for bbox in bboxes:
        bbox_part = '' if not bbox else '({})'.format(','.join(str(coord) for coord in bbox))
        query += '('
        for mode in modes:
            query += 'rel[route="{}"]{};'.format(mode, bbox_part)
        query += ');'
        query += 'rel(br)[type=route_master];'
        if not overground:
            query += 'node[railway=subway_entrance]{};'.format(bbox_part)
        query += 'rel[public_transport=stop_area]{};'.format(bbox_part)
        query += 'rel(br)[type=public_transport][public_transport=stop_area_group];'
    query += ');(._;>>;);out body center qt;'
    logging.debug('Query: %s', query)
    url = '{}?data={}'.format(overpass_api, urllib.parse.quote(query))
    response = urllib.request.urlopen(url, timeout=1000)
    if response.getcode() != 200:
        raise Exception('Failed to query Overpass API: HTTP {}'.format(response.getcode()))
    return json.load(response)['elements']


def multi_overpass(overground, overpass_api, bboxes):
    if not bboxes:
        return overpass_request(overground, overpass_api, None)
    SLICE_SIZE = 10
    result = []
    for i in range(0, len(bboxes) + SLICE_SIZE - 1, SLICE_SIZE):
        if i > 0:
            time.sleep(5)
        result.extend(overpass_request(overground, overpass_api, bboxes[i:i+SLICE_SIZE]))
    return result


def slugify(name):
    return re.sub(r'[^a-z0-9_-]+', '', name.lower().replace(' ', '_'))


def calculate_centers(elements):
    """Adds 'center' key to each way/relation in elements,
       except for empty ways or relations.
       Relies on nodes-ways-relations order in the elements list.
    """
    nodes = {}      # id(int) => (lat, lon)
    ways = {}       # id(int) => (lat, lon)
    relations = {}  # id(int) => (lat, lon)
    empty_relations = set()  # ids(int) of relations without members
                             # or containing only empty relations

    def calculate_way_center(el):
        # If element has been queried via overpass-api with 'out center;'
        # clause then ways already have 'center' attribute
        if 'center' in el:
            ways[el['id']] = (el['center']['lat'], el['center']['lon'])
            return
        center = [0, 0]
        count = 0
        for nd in el['nodes']:
            if nd in nodes:
                center[0] += nodes[nd][0]
                center[1] += nodes[nd][1]
                count += 1
        if count > 0:
            el['center'] = {'lat': center[0] / count, 'lon': center[1] / count}
            ways[el['id']] = (el['center']['lat'], el['center']['lon'])

    def calculate_relation_center(el):
        # If element has been queried via overpass-api with 'out center;'
        # clause then some relations already have 'center' attribute
        if 'center' in el:
            relations[el['id']] = (el['center']['lat'], el['center']['lon'])
            return True
        center = [0, 0]
        count = 0
        for m in el.get('members', []):
            if m['type'] == 'relation' and m['ref'] not in relations:
                if m['ref'] in empty_relations:
                    # Ignore empty child relations
                    continue
                else:
                    # Center of child relation is not known yet
                    return False
            member_container = (nodes if m['type'] == 'node' else
                                ways if m['type'] == 'way' else
                                relations)
            if m['ref'] in member_container:
                center[0] += member_container[m['ref']][0]
                center[1] += member_container[m['ref']][1]
                count += 1
        if count == 0:
            empty_relations.add(el['id'])
        else:
            el['center'] = {'lat': center[0] / count, 'lon': center[1] / count}
            relations[el['id']] = (el['center']['lat'], el['center']['lon'])
        return True

    relations_without_center = []

    for el in elements:
        if el['type'] == 'node':
            nodes[el['id']] = (el['lat'], el['lon'])
        elif el['type'] == 'way':
            if 'nodes' in el:
                calculate_way_center(el)
        elif el['type'] == 'relation':
            if not calculate_relation_center(el):
                relations_without_center.append(el)

    # Calculate centers for relations that have no one yet
    while relations_without_center:
        new_relations_without_center = []
        for rel in relations_without_center:
            if not calculate_relation_center(rel):
                new_relations_without_center.append(rel)
        if len(new_relations_without_center) == len(relations_without_center):
            break
        relations_without_center = new_relations_without_center

    if relations_without_center:
        logging.error("Cannot calculate center for the relations (%d in total): %s%s",
                      len(relations_without_center),
                      ', '.join(str(rel['id']) for rel in relations_without_center[:20]),
                      ", ..." if len(relations_without_center) > 20 else "")
    if empty_relations:
        logging.warning("Empty relations (%d in total): %s%s",
                        len(empty_relations),
                        ', '.join(str(x) for x in list(empty_relations)[:20]),
                        ", ..." if len(empty_relations) > 20 else "")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-i', '--source', help='File to write backup of OSM data, or to read data from')
    parser.add_argument('-x', '--xml', help='OSM extract with routes, to read data from')
    parser.add_argument('--overpass-api',
                        default='http://overpass-api.de/api/interpreter',
                        help="Overpass API URL")
    parser.add_argument(
        '-b', '--bbox', action='store_true',
        help='Use city boundaries to query Overpass API instead of querying the world')
    parser.add_argument('-q', '--quiet', action='store_true', help='Show only warnings and errors')
    parser.add_argument('-c', '--city', help='Validate only a single city or a country')
    parser.add_argument('-t', '--overground', action='store_true',
                        help='Process overground transport instead of subways')
    parser.add_argument('-e', '--entrances', type=argparse.FileType('w', encoding='utf-8'),
                        help='Export unused subway entrances as GeoJSON here')
    parser.add_argument('-l', '--log', type=argparse.FileType('w', encoding='utf-8'),
                        help='Validation JSON file name')
    parser.add_argument('-o', '--output', type=argparse.FileType('w', encoding='utf-8'),
                        help='Processed metro systems output')
    parser.add_argument('--cache', help='Cache file name for processed data')
    parser.add_argument('-r', '--recovery-path', help='Cache file name for error recovery')
    parser.add_argument('-d', '--dump', help='Make a YAML file for a city data')
    parser.add_argument('-j', '--geojson', help='Make a GeoJSON file for a city data')
    parser.add_argument('--crude', action='store_true',
                        help='Do not use OSM railway geometry for GeoJSON')
    options = parser.parse_args()

    if options.quiet:
        log_level = logging.WARNING
    else:
        log_level = logging.INFO
    logging.basicConfig(level=log_level, datefmt='%H:%M:%S',
                        format='%(asctime)s %(levelname)-7s  %(message)s')

    # Downloading cities from Google Spreadsheets
    cities = download_cities(options.overground)
    if options.city:
        cities = [c for c in cities if c.name == options.city or c.country == options.city]
    if not cities:
        logging.error('No cities to process')
        sys.exit(2)

    # Augment cities with recovery data
    recovery_data = None
    if options.recovery_path:
        recovery_data = read_recovery_data(options.recovery_path)
        for city in cities:
            city.recovery_data = recovery_data.get(city.name, None)

    logging.info('Read %s metro networks', len(cities))

    # Reading cached json, loading XML or querying Overpass API
    if options.source and os.path.exists(options.source):
        logging.info('Reading %s', options.source)
        with open(options.source, 'r') as f:
            osm = json.load(f)
            if 'elements' in osm:
                osm = osm['elements']
            calculate_centers(osm)
    elif options.xml:
        logging.info('Reading %s', options.xml)
        osm = load_xml(options.xml)
        calculate_centers(osm)
        if options.source:
            with open(options.source, 'w', encoding='utf-8') as f:
                json.dump(osm, f)
    else:
        if len(cities) > 10:
            logging.error('Would not download that many cities from Overpass API, '
                          'choose a smaller set')
            sys.exit(3)
        if options.bbox:
            bboxes = [c.bbox for c in cities]
        else:
            bboxes = None
        logging.info('Downloading data from Overpass API')
        osm = multi_overpass(options.overground, options.overpass_api, bboxes)
        calculate_centers(osm)
        if options.source:
            with open(options.source, 'w', encoding='utf-8') as f:
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
        try:
            c.extract_routes()
        except CriticalValidationError as e:
            logging.error("Critical validation error: %s", str(e))
        else:
            c.validate()
            if c.is_good():
                good_cities.append(c)

    logging.info('Finding transfer stations')
    transfers = find_transfers(osm, cities)

    good_city_names = set(c.name for c in good_cities)
    logging.info('%s good cities: %s', len(good_city_names),
                 ', '.join(sorted(good_city_names)))
    bad_city_names = set(c.name for c in cities) - good_city_names
    logging.info('%s bad cities: %s', len(bad_city_names),
                 ', '.join(sorted(bad_city_names)))

    if options.recovery_path:
        write_recovery_data(options.recovery_path, recovery_data, cities)

    if options.entrances:
        json.dump(get_unused_entrances_geojson(osm), options.entrances)

    if options.dump:
        if os.path.isdir(options.dump):
            for c in cities:
                with open(os.path.join(options.dump, slugify(c.name) + '.yaml'),
                          'w', encoding='utf-8') as f:
                    dump_yaml(c, f)
        elif len(cities) == 1:
            with open(options.dump, 'w', encoding='utf-8') as f:
                dump_yaml(cities[0], f)
        else:
            logging.error('Cannot dump %s cities at once', len(cities))

    if options.geojson:
        if os.path.isdir(options.geojson):
            for c in cities:
                with open(os.path.join(options.geojson, slugify(c.name) + '.geojson'),
                          'w', encoding='utf-8') as f:
                    json.dump(make_geojson(c, not options.crude), f)
        elif len(cities) == 1:
            with open(options.geojson, 'w', encoding='utf-8') as f:
                json.dump(make_geojson(cities[0], not options.crude), f)
        else:
            logging.error('Cannot make a geojson of %s cities at once', len(cities))

    if options.log:
        res = []
        for c in cities:
            v = c.get_validation_result()
            v['slug'] = slugify(c.name)
            res.append(v)
        json.dump(res, options.log, indent=2, ensure_ascii=False)

    if options.output:
        json.dump(processor.process(cities, transfers, options.cache),
                  options.output, indent=1, ensure_ascii=False)
