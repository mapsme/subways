#!/bin/bash
# Still times out, do not use unless you want to be blocked for some hours on Overpass API
TIMEOUT=2000
QUERY='[out:json][timeout:'$TIMEOUT'];(rel["route"="subway"];rel["route"="light_rail"];rel["public_transport"="stop_area"];rel["public_transport"="stop_area_group"];node["station"="subway"];node["station"="light_rail"];node["railway"="subway_entrance"];);(._;>;);out body center qt;'
http http://overpass-api.de/api/interpreter "data==$QUERY" --timeout $TIMEOUT > subways-$(date +%y%m%d).json
http https://overpass-api.de/api/status | grep available
