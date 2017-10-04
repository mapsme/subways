#!/usr/bin/env python3
import datetime
import re
import os
import sys
from subway_structure import download_cities, SPREADSHEET_ID
from v2h_templates import *

date = datetime.datetime.now().strftime('%d.%m.%Y %H:%M')


class CityData:
    REGEXPS = (
        ('subwayl', re.compile(r'Found (\d+) subway lines, expected (\d+)')),
        ('lightrl', re.compile(r'Found (\d+) light rail.*expected (\d+)')),
        ('stations', re.compile(r'Found (\d+) stations.*expected (\d+)')),
        ('transfers', re.compile(r'Found (\d+) interch.*expected (\d+)')),
    )

    def __init__(self, city=None):
        self.city = city is not None
        if city:
            self.country = city.country
            self.continent = city.continent
            self.errors = []
            self.warnings = []
        self.data = {
            'stations_expected': city.num_stations if city else 0,
            'subwayl_expected': city.num_lines if city else 0,
            'lightrl_expected': city.num_light_lines if city else 0,
            'transfers_expected': city.num_interchanges if city else 0,
            'unused_entrances': 0,
            'good_cities': 1 if city else 0,
            'total_cities': 1 if city else 0,
            'num_errors': 0,
            'num_warnings': 0
        }
        for k, _ in CityData.REGEXPS:
            self.data[k+'_found'] = self.data[k+'_expected']

    def __get__(self, i):
        return self.data[i]

    def __set__(self, i, value):
        self.data[i] = value

    def __add__(self, other):
        d = CityData()
        for k in d.data:
            d.data[k] = self.data[k] + other.data[k]
        return d

    def format(self, s):
        def test_eq(v1, v2):
            return '1' if v1 == v2 else '0'

        for k in self.data:
            s = s.replace('{'+k+'}', str(self.data[k]))
        for k in ('subwayl', 'lightrl', 'stations', 'transfers'):
            s = s.replace('{='+k+'}',
                          test_eq(self.data[k+'_found'], self.data[k+'_expected']))
        s = s.replace('{=cities}',
                      test_eq(self.data['good_cities'], self.data['total_cities']))
        s = s.replace('{=entrances}', test_eq(self.data['unused_entrances'], 0))
        for k in ('errors', 'warnings'):
            s = s.replace('{='+k+'}', test_eq(self.data['num_'+k], 0))
        return s

    def add_warning(self, msg):
        self.warnings.append(msg)
        self.data['num_warnings'] += 1

    def add_error(self, msg):
        for k, reg in CityData.REGEXPS:
            m = reg.search(msg)
            if m:
                self.data[k+'_found'] = int(m[1])
                self.data[k+'_expected'] = int(m[2])
        m = re.search(r'Found (\d+) unused subway e', msg)
        if m:
            self.data['unused_entrances'] = int(m[1])
        self.errors.append(msg)
        self.data['num_errors'] += 1
        self.data['good_cities'] = 0


def tmpl(s, data=None, **kwargs):
    if data:
        s = data.format(s)
    if kwargs:
        for k, v in kwargs.items():
            s = s.replace('{'+k+'}', v)
    s = s.replace('{date}', date)
    google_url = 'https://docs.google.com/spreadsheets/d/{}/edit?usp=sharing'.format(SPREADSHEET_ID)
    s = s.replace('{google}', google_url)
    return s


EXPAND_OSM_TYPE = {'n': 'node', 'w': 'way', 'r': 'relation'}
RE_SHORT = re.compile(r'([nwr])(\d+)')
RE_FULL = re.compile(r'(node|way|relation) (\d+)')
LOG_LINE = re.compile(r'^(\d\d:\d\d:\d\d)\s+([A-Z]+)\s+([^:]+):\s+(.+?)\s*$')


def osm_links(s):
    """Converts object mentions to HTML links."""
    def link(m):
        return '<a href="https://www.openstreetmap.org/{}/{}">{}</a>'.format(EXPAND_OSM_TYPE[m[1][0]], m[2], m[0])
    s = RE_SHORT.sub(link, s)
    s = RE_FULL.sub(link, s)
    return s


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


if len(sys.argv) < 2:
    print('Reads a log from subway validator and prepares HTML files.')
    print('Usage: {} <validation.log> [<target_directory>]'.format(sys.argv[0]))
    sys.exit(1)

cities = {c.name: c for c in download_cities()}
data = {c.name: CityData(c) for c in cities.values()}

last_city = None
with open(sys.argv[1], 'r') as f:
    for line in f:
        m = LOG_LINE.match(line)
        if m:
            level = m.group(2)
            if level == 'INFO':
                continue
            city_name = m.group(3)
            msg = m.group(4)
            if city_name not in data:
                raise Exception('City {} not found in the cities list'.format(city_name))
            city = data[city_name]
            if level == 'WARNING':
                city.add_warning(msg)
            elif level == 'ERROR':
                city.add_error(msg)

countries = {}
continents = {}
c_by_c = {}  # continent → set of countries
for c in data.values():
    countries[c.country] = c + countries.get(c.country, CityData())
    continents[c.continent] = c + continents.get(c.continent, CityData())
    if c.continent not in c_by_c:
        c_by_c[c.continent] = set()
    c_by_c[c.continent].add(c.country)

date = datetime.datetime.now().strftime('%d.%m.%Y %H:%M')
path = '.' if len(sys.argv) < 3 else sys.argv[2]
index = open(os.path.join(path, 'index.html'), 'w')
index.write(tmpl(INDEX_HEADER))

for continent in sorted(continents.keys()):
    content = ''
    for country in sorted(c_by_c[continent]):
        country_file_name = country.lower().replace(' ', '-') + '.html'
        content += tmpl(INDEX_COUNTRY, countries[country], file=country_file_name,
                        country=country, continent=continent)
        country_file = open(os.path.join(path, country_file_name), 'w')
        country_file.write(tmpl(COUNTRY_HEADER, country=country, continent=continent))
        for name, city in sorted(data.items()):
            if city.country == country:
                e = '<br>'.join([osm_links(esc(e)) for e in city.errors])
                w = '<br>'.join([osm_links(esc(w)) for w in city.warnings])
                country_file.write(tmpl(COUNTRY_CITY, city,
                                        city=name, country=country, continent=continent,
                                        errors=e, warnings=w))
        country_file.write(tmpl(COUNTRY_FOOTER, country=country, continent=continent))
        country_file.close()
    index.write(tmpl(INDEX_CONTINENT, continents[continent],
                     content=content, continent=continent))

index.write(tmpl(INDEX_FOOTER))
index.close()
