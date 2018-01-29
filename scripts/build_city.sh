#!/bin/bash
set -e -u
[ $# -lt 1 ] && echo "Usage: $0 <path_to_o5m> [<city_name> [<bbox>]]" && exit 1

export OSMCTOOLS="${OSMCTOOLS:-$HOME/osm/planet}"
export DUMP=html
export JSON=html
if [ -n "${2-}" ]; then
  export CITY="$2"
fi
if [ -n "${3-}" ]; then
  export BBOX="$3"
elif [ -n "${CITY-}" ]; then
  export BBOX="$(python3 -c 'import subway_structure; c = [x for x in subway_structure.download_cities() if x.name == "'$CITY'"]; print("{1},{0},{3},{2}".format(*c[0].bbox))')" || true
fi
"$(dirname "$0")/process_subways.sh" "$1"
