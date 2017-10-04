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

## Adding Stop Areas To OSM

To quickly add `stop_area` relations for the entire city, use the `make_stop_areas.py` script
from the `stop_area` directory. Give it a bounding box or a `.json` file download from Overpass API.
It would produce an JOSM XML file that you should manually check in JOSM. After that
just upload it.

## Author and License

All scripts were written by Ilya Zverev for MAPS.ME. Published under Apache Licence 2.0.
