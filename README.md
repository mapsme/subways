# Subway Preprocessor

Here you see a list of scripts that can be used for preprocessing all the metro
systems in the world from OpenStreetMap. `subway_structure.py` produces
a list of disjunct systems that can be used for routing and for displaying
of metro maps.

## How To Validate

* Download or update a planet file in o5m format (using `osmconvert` and `osmupdate`).
* Use `filter_all_subways.sh` to extract a portion of data for all subways.
* Run `mapsme_subways.py -x filtered_data.osm` to build metro structures and receive a validation log.
* Run `validation_to_html.py` on that log to create readable HTML tables.

## Validation Script

There is a `process_subways.sh` in the `scripts` directory. The author uses it for
updating both the planet and a city he's working on. Here is an example of a script
for updating the London Underground network:

```bash
PLANET_PATH=$HOME/osm/planet
export OSMCTOOLS="$PLANET_PATH"
export PLANET="$PLANET_PATH/london.o5m"
export HTML_DIR=tmp_html
export BBOX=-0.681152,51.286758,0.334015,51.740636
export CITY="London"
export DUMP=london.yaml

scripts/process_subways.sh
```

The bounding box can be found in the
[Google Spreadsheet](https://docs.google.com/spreadsheets/d/1-UHDzfBwHdeyFxgC5cE_MaNQotF3-Y0r1nW9IwpIEj8/edit?usp=sharing).
If you are okay with rare updates, use [this website](http://osmz.ru/subways/).

## Adding Stop Areas To OSM

To quickly add `stop_area` relations for the entire city, use the `make_stop_areas.py` script
from the `stop_area` directory. Give it a bounding box or a `.json` file download from Overpass API.
It would produce an JOSM XML file that you should manually check in JOSM. After that
just upload it.

## Author and License

All scripts were written by Ilya Zverev for MAPS.ME. Published under Apache Licence 2.0.
