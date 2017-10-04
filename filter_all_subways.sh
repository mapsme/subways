#!/bin/bash
[ $# -lt 1 ] && echo 'Usage: $0 <planet.o5m> [<path_to_osmfilter>]' && exit 1
OSMFILTER=${2-./osmfilter}
"$OSMFILTER" "$1" --keep= --keep-relations="route=subway or route=light_rail or route=monorail or route_master=subway or route_master=light_rail or route_master=monorail or public_transport=stop_area or public_transport=stop_area_group" --keep-nodes="station=subway or station=light_rail or station=monorail or railway=subway_entrance" --drop-author -o=subways-$(date +%y%m%d).osm
