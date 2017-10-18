#!/bin/bash
[ $# -lt 1 ] && echo 'Usage: $0 <planet.o5m> [<path_to_osmfilter>]' && exit 1
OSMFILTER=${2-./osmfilter}
QRELATIONS="route=subway =light_rail =monorail route_master=subway =light_rail =monorail public_transport=stop_area =stop_area_group"
QNODES="station=subway =light_rail =monorail railway=subway_entrance subway=yes light_rail=yes monorail=yes"
"$OSMFILTER" "$1" --keep= --keep-relations="$QRELATIONS" --keep-nodes="$QNODES" --drop-author -o=subways-$(date +%y%m%d).osm
