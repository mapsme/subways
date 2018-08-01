#!/usr/bin/env python3
import json
import codecs
from lxml import etree
import sys
import kdtree
import math
import re
import urllib.parse
import urllib.request


QUERY = """
[out:json][timeout:250][bbox:{{bbox}}];
(
  relation["route"="tram"];
  relation["public_transport"="stop_area"];
  nwr["railway"="tram_stop"];
);
(._;>>;);
out meta center qt;
"""


def el_id(el):
    return el['type'][0] + str(el.get('id', el.get('ref', '')))


class StationWrapper:
    def __init__(self, st):
        if 'center' in st:
            self.coords = (st['center']['lon'], st['center']['lat'])
        elif 'lon' in st:
            self.coords = (st['lon'], st['lat'])
        else:
            raise Exception('Coordinates not found for station {}'.format(st))
        self.station = st

    def __len__(self):
        return 2

    def __getitem__(self, i):
        return self.coords[i]

    def distance(self, other):
        """Calculate distance in meters."""
        dx = math.radians(self[0] - other['lon']) * math.cos(
            0.5 * math.radians(self[1] + other['lat']))
        dy = math.radians(self[1] - other['lat'])
        return 6378137 * math.sqrt(dx*dx + dy*dy)


def overpass_request(bbox):
    url = 'http://overpass-api.de/api/interpreter?data={}'.format(
        urllib.parse.quote(QUERY.replace('{{bbox}}', bbox)))
    response = urllib.request.urlopen(url, timeout=1000)
    if response.getcode() != 200:
        raise Exception('Failed to query Overpass API: HTTP {}'.format(response.getcode()))
    reader = codecs.getreader('utf-8')
    return json.load(reader(response))['elements']


def is_part_of_stop(tags):
    if tags.get('public_transport') in ('platform', 'stop_position'):
        return True
    if tags.get('railway') == 'platform':
        return True
    return False


def add_stop_areas(src):
    if not src:
        raise Exception('Empty dataset provided to add_stop_areas')

    # Create a kd-tree out of tram stations
    stations = kdtree.create(dimensions=2)
    for el in src:
        if 'tags' in el and el['tags'].get('railway') == 'tram_stop':
            stations.add(StationWrapper(el))

    if stations.is_leaf:
        raise Exception('No stations found')

    elements = {}
    for el in src:
        if el.get('tags'):
            elements[el_id(el)] = el

    # Populate a list of nearby subway exits and platforms for each station
    MAX_DISTANCE = 50  # meters
    stop_areas = {}
    for el in src:
        # Only tram routes
        if 'tags' not in el or el['type'] != 'relation' or el['tags'].get('route') != 'tram':
            continue
        for m in el['members']:
            if el_id(m) not in elements:
                continue
            pel = elements[el_id(m)]
            if not is_part_of_stop(pel['tags']):
                continue
            if pel['tags'].get('railway') == 'tram_stop':
                continue
            coords = pel.get('center', pel)
            station = stations.search_nn((coords['lon'], coords['lat']))[0].data
            if station.distance(coords) < MAX_DISTANCE:
                k = (station.station['id'], station.station['tags'].get('name', None))
                if k not in stop_areas:
                    stop_areas[k] = {el_id(station.station): station.station}
                stop_areas[k][el_id(m)] = pel

    # Find existing stop_area relations for stations and remove these stations
    for el in src:
        if el['type'] == 'relation' and el['tags'].get('public_transport', None) == 'stop_area':
            found = False
            for m in el['members']:
                if found:
                    break
                for st in stop_areas:
                    if el_id(m) in stop_areas[st]:
                        del stop_areas[st]
                        found = True
                        break

    # Create OSM XML for new stop_area relations
    root = etree.Element('osm', version='0.6')
    rid = -1
    for st, members in stop_areas.items():
        rel = etree.SubElement(root, 'relation', id=str(rid))
        rid -= 1
        etree.SubElement(rel, 'tag', k='type', v='public_transport')
        etree.SubElement(rel, 'tag', k='public_transport', v='stop_area')
        if st[1]:
            etree.SubElement(rel, 'tag', k='name', v=st[1])
        for m in members.values():
            etree.SubElement(rel, 'member', ref=str(m['id']), type=m['type'], role='')

    # Add all downloaded elements
    for el in src:
        obj = etree.SubElement(root, el['type'])
        for a in ('id', 'type', 'user', 'uid', 'version', 'changeset', 'timestamp', 'lat', 'lon'):
            if a in el:
                obj.set(a, str(el[a]))
        if 'modified' in el:
            obj.set('action', 'modify')
        if 'tags' in el:
            for k, v in el['tags'].items():
                etree.SubElement(obj, 'tag', k=k, v=v)
        if 'members' in el:
            for m in el['members']:
                etree.SubElement(obj, 'member', ref=str(m['ref']),
                                 type=m['type'], role=m.get('role', ''))
        if 'nodes' in el:
            for n in el['nodes']:
                etree.SubElement(obj, 'nd', ref=str(n))

    return etree.tostring(root, pretty_print=True, encoding="utf-8")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Read a JSON from Overpass and output JOSM OSM XML with added stop_area relations')
        print('Usage: {} {{<export.json>|<bbox>}} [output.osm]'.format(sys.argv[0]))
        sys.exit(1)

    if re.match(r'^[-0-9.,]+$', sys.argv[1]):
        bbox = sys.argv[1].split(',')
        src = overpass_request(','.join([bbox[i] for i in (1, 0, 3, 2)]))
    else:
        with open(sys.argv[1], 'r') as f:
            src = json.load(f)['elements']

    result = add_stop_areas(src)

    if len(sys.argv) < 3:
        print(result.decode('utf-8'))
    else:
        with open(sys.argv[2], 'wb') as f:
            f.write(result)
