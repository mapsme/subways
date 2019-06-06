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
        query += ');rel(br)[type=route_master];'
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
    elif options.xml:
        logging.info('Reading %s', options.xml)
        osm = load_xml(options.xml)
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
        c.extract_routes()
        c.validate()
        if c.is_good():
            good_cities.append(c)

    logging.info('Finding transfer stations')
    transfers = find_transfers(osm, cities)

    logging.info('%s good cities: %s', len(good_cities),
                 ', '.join(sorted([c.name for c in good_cities])))

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
        json.dump(res, options.log, ensure_ascii=False)

    if options.output:
        json.dump(processor.process(cities, transfers, options.cache),
                  options.output, indent=1, ensure_ascii=False)
