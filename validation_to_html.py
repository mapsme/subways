#!/usr/bin/env python3
import datetime
import re
import os
import sys
import json
from subway_structure import SPREADSHEET_ID
from v2h_templates import *

date = datetime.datetime.now().strftime('%d.%m.%Y %H:%M')


class CityData:
    def __init__(self, city=None):
        self.city = city is not None
        self.data = {
            'good_cities': 0,
            'total_cities': 1 if city else 0,
            'num_errors': 0,
            'num_warnings': 0
        }
        if city:
            self.country = city['country']
            self.continent = city['continent']
            self.errors = city['errors']
            self.warnings = city['warnings']
            if not self.errors:
                self.data['good_cities'] = 1
            self.data['num_errors'] = len(self.errors)
            self.data['num_warnings'] = len(self.warnings)
            for k, v in city.items():
                if 'found' in k or 'expected' in k or 'unused' in k:
                    self.data[k] = v

    def not__get__(self, i):
        return self.data.get(i)

    def not__set__(self, i, value):
        self.data[i] = value

    def __add__(self, other):
        d = CityData()
        for k in self.data:
            d.data[k] = self.data.get(k, 0) + other.data.get(k, 0)
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


def osm_links(s):
    """Converts object mentions to HTML links."""
    def link(m):
        return '<a href="https://www.openstreetmap.org/{}/{}">{}</a>'.format(
            EXPAND_OSM_TYPE[m.group(1)[0]], m.group(2), m.group(0))
    s = RE_SHORT.sub(link, s)
    s = RE_FULL.sub(link, s)
    return s


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


if len(sys.argv) < 2:
    print('Reads a log from subway validator and prepares HTML files.')
    print('Usage: {} <validation.log> [<target_directory>]'.format(sys.argv[0]))
    sys.exit(1)

with open(sys.argv[1], 'r') as f:
    data = {c['name']: CityData(c) for c in json.load(f)}

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
index = open(os.path.join(path, 'index.html'), 'w', encoding='utf-8')
index.write(tmpl(INDEX_HEADER))

for continent in sorted(continents.keys()):
    content = ''
    for country in sorted(c_by_c[continent]):
        country_file_name = country.lower().replace(' ', '-') + '.html'
        content += tmpl(INDEX_COUNTRY, countries[country], file=country_file_name,
                        country=country, continent=continent)
        country_file = open(os.path.join(path, country_file_name), 'w', encoding='utf-8')
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
