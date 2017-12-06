#!/bin/bash
set -e -u

if [ $# -lt 1 -a -z "${PLANET-}" ]; then
  echo "This script updates a planet or an extract, processes metro networks in it"
  echo "and produses a set of HTML files with validation results."
  echo
  echo "Usage: $0 <planet.o5m>"
  echo
  echo "Variable reference:"
  echo "- PLANET: path for the source o5m file (the entire planet or an extract)"
  echo "- CITY: name of a city to process"
  echo "- BBOX: bounding box of an extract; x1,y1,x2,y2"
  echo "- DUMP: file name to dump city data"
  echo "- MAPSME: file name for maps.me json output"
  echo "- OSMCTOOLS: path to osmconvert and osmupdate binaries"
  echo "- PYTHON: python 3 executable"
  echo "- GIT_PULL: set to 1 to update the scripts"
  echo "- TMPDIR: path to temporary files"
  echo "- HTML_DIR: target path for generated HTML files"
  echo "- SERVER: server name and path to upload HTML files (e.g. ilya@osmz.ru:/var/www/)"
  echo "- SERVER_KEY: rsa key to supply for uploading the files"
  echo "- REMOVE_HTML: set to 1 to remove HTML_DIR after uploading"
  exit 1
fi

[ -n "${WHAT-}" ] && echo WHAT

PLANET="${PLANET:-${1-}}"
[ ! -f "$PLANET" ] && echo "Cannot find planet file $PLANET" && exit 2
OSMCTOOLS="${OSMCTOOLS:-$HOME/osmctools}"
if [ ! -f "$OSMCTOOLS/osmupdate" ]; then
  if which osmupdate > /dev/null; then
    OSMCTOOLS="$(dirname "$(which osmupdate)")"
  else
    echo "Please compile osmctools to $OSMCTOOLS"
    exit 1
  fi
fi
PYTHON=${PYTHON:-python3}
# This will fail if there is no python
"$PYTHON" --version > /dev/null
SUBWAYS_PATH="$(dirname "$0")/.."
[ ! -f "$SUBWAYS_PATH/process_subways.py" ] && echo "Please clone the subways repo to $SUBWAYS_PATH" && exit 2
TMPDIR="${TMPDIR:-$SUBWAYS_PATH}"

# Downloading the latest version of the subways script


if [ -n "${GIT_PULL-}" ]; then (
  cd "$SUBWAYS_PATH"
  git pull origin master
) fi


# Updating the planet file

PLANET_ABS="$(cd "$(dirname "$PLANET")"; pwd)/$(basename "$PLANET")"
(
  cd "$OSMCTOOLS" # osmupdate requires osmconvert in a current directory
  ./osmupdate --drop-author --out-o5m "$PLANET_ABS" ${BBOX+"-b=$BBOX"} "$PLANET_ABS.new.o5m" && mv "$PLANET_ABS.new.o5m" "$PLANET_ABS" || true
)

# Filtering it

FILTERED_DATA="$TMPDIR/subways.osm"
QRELATIONS="route=subway =light_rail =monorail =train route_master=subway =light_rail =monorail =train public_transport=stop_area =stop_area_group"
QNODES="railway=station station=subway =light_rail =monorail railway=subway_entrance subway=yes light_rail=yes monorail=yes train=yes"
"$OSMCTOOLS/osmfilter" "$PLANET" --keep= --keep-relations="$QRELATIONS" --keep-nodes="$QNODES" --drop-author "-o=$FILTERED_DATA"

# Running the validation

VALIDATION="$TMPDIR/validation.json"
"$PYTHON" "$SUBWAYS_PATH/process_subways.py" -q -x "$FILTERED_DATA" -l "$VALIDATION" ${MAPSME+-o "$MAPSME"} ${CITY+-c "$CITY"} ${DUMP+-d "$DUMP"} ${JSON+-j "$JSON"}
rm "$FILTERED_DATA"

# Preparing HTML files

if [ -z "${HTML_DIR-}" ]; then
  HTML_DIR="$SUBWAYS_PATH/html"
  REMOVE_HTML=1
fi

mkdir -p $HTML_DIR
rm -f "$HTML_DIR"/*.html
"$PYTHON" "$SUBWAYS_PATH/validation_to_html.py" "$VALIDATION" "$HTML_DIR"
rm "$VALIDATION"

# Uploading files to the server

if [ -n "${SERVER-}" ]; then
  scp -q ${SERVER_KEY+-i "$SERVER_KEY"} "$HTML_DIR"/* "$SERVER"
  [ -n "${REMOVE_HTML-}" ] && rm -r "$HTML_DIR"
fi
