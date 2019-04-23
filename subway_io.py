import json
import logging


def _dumps_route_id(route_id):
    """Argument is a route_id that depends on route colour, ref. Name
    can be taken from route_master or be route's own, don't take it.
    (some of route attributes can be None). Functions makes it json-compatible -
    dumps to a string."""
    return json.dumps(route_id, ensure_ascii=False)


def _loads_route_id(route_id_dump):
    """Argument is a json-encoded identifier of a route.
    FunReturn a tuple of"""
    return tuple(json.loads(route_id_dump))


def read_recovery_data(path):
    """Recovery data is a json with data from previous transport builds.
    It helps to recover cities from some errors, e.g. by resorting
    shuffled stations in routes."""
    data = None
    try:
        with open(path, 'r') as f:
            try:
                data = json.load(f)
            except json.decoder.JSONDecodeError as e:
                logging.warning("Cannot load recovery data: {}".format(e))
    except FileNotFoundError:
        logging.warning("Cannot find recovery data file '{}'".format(path))

    if data is None:
        logging.warning("Continue without recovery data.")
        return {}
    else:
        data = {
            city_name: {_loads_route_id(route_id): route_data
                                 for route_id, route_data in routes.items()}
                    for city_name, routes in data.items()
        }
        return data


def write_recovery_data(path, current_data, cities):
    """Updates recovery data with good cities data and writes to file."""

    def make_city_recovery_data(city):
        routes = {}
        for route in city:
            # Recovery is based primarily on route/station names/refs.
            # If route's name/ref/colour changes, the route won't be used.
            route_id = (route.colour, route.ref)
            itineraries = []
            for variant in route:
                itin = {'stops': [],
                        'is_circular': variant.is_circular,
                        'name': variant.name,
                        'from': variant.element['tags'].get('from'),
                        'to': variant.element['tags'].get('to')}
                for stop in variant:
                    station = stop.stoparea.station
                    station_name = station.name
                    if station_name == '?':
                        station_name = station.int_name
                    # If a station has no name, the itinerary won't be used.
                    # But! If variant contains only one unnamed station, we can cope with it.
                    # if station_name is None:
                    #    itin = None
                    #    break
                    itin['stops'].append({
                        'oms_id': station.id,
                        'name': station_name,
                        'center': station.center
                    })
                if itin is not None:
                    itineraries.append(itin)
            routes[route_id] = itineraries
        return routes

    data = current_data
    for city in cities:
        if city.is_good():
            data[city.name] = make_city_recovery_data(city)

    try:
        data = {
            city_name: {_dumps_route_id(route_id): route_data
                        for route_id, route_data in routes.items()}
            for city_name, routes in data.items()
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning("Cannot write recovery data '%s'", path)
        logging.warning(str(e))

