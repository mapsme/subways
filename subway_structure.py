import csv
import logging
import math
import urllib.parse
import urllib.request
from css_colours import normalize_colour
from collections import Counter, defaultdict


SPREADSHEET_ID = '1-UHDzfBwHdeyFxgC5cE_MaNQotF3-Y0r1nW9IwpIEj8'
MAX_DISTANCE_TO_ENTRANCES = 300  # in meters
MAX_DISTANCE_STOP_TO_LINE = 50  # in meters
ALLOWED_STATIONS_MISMATCH = 0.02   # part of total station count
ALLOWED_TRANSFERS_MISMATCH = 0.07  # part of total interchanges count
ALLOWED_ANGLE_BETWEEN_STOPS = 45  # in degrees
DISALLOWED_ANGLE_BETWEEN_STOPS = 20  # in degrees

# If an object was moved not too far compared to previous script run,
# it is likely the same object
DISPLACEMENT_TOLERANCE = 300  # in meters

MODES_RAPID = set(('subway', 'light_rail', 'monorail', 'train'))
MODES_OVERGROUND = set(('tram', 'bus', 'trolleybus', 'aerialway', 'ferry'))
DEFAULT_MODES_RAPID = set(('subway', 'light_rail'))
DEFAULT_MODES_OVERGROUND = set(('tram',))  # TODO: bus and trolleybus?
ALL_MODES = MODES_RAPID | MODES_OVERGROUND
RAILWAY_TYPES = set(('rail', 'light_rail', 'subway', 'narrow_gauge',
                     'funicular', 'monorail', 'tram'))
CONSTRUCTION_KEYS = ('construction', 'proposed', 'construction:railway', 'proposed:railway')
NOWHERE_STOP = (0, 0)  # too far away from any metro system

used_entrances = set()


class CriticalValidationError(Exception):
    """Is thrown if an error occurs
    that prevents further validation of a city."""


def el_id(el):
    if not el:
        return None
    if 'type' not in el:
        raise Exception('What is this element? {}'.format(el))
    return el['type'][0] + str(el.get('id', el.get('ref', '')))


def el_center(el):
    if not el:
        return None
    if 'lat' in el:
        return (el['lon'], el['lat'])
    elif 'center' in el:
        return (el['center']['lon'], el['center']['lat'])
    return None


def distance(p1, p2):
    if p1 is None or p2 is None:
        raise Exception('One of arguments to distance({}, {}) is None'.format(p1, p2))
    dx = math.radians(p1[0] - p2[0]) * math.cos(
        0.5 * math.radians(p1[1] + p2[1]))
    dy = math.radians(p1[1] - p2[1])
    return 6378137 * math.sqrt(dx*dx + dy*dy)


def is_near(p1, p2):
    return (p1[0] - 1e-8 <= p2[0] <= p1[0] + 1e-8 and
            p1[1] - 1e-8 <= p2[1] <= p1[1] + 1e-8)


def project_on_line(p, line):
    def project_on_segment(p, p1, p2):
        dp = (p2[0] - p1[0], p2[1] - p1[1])
        d2 = dp[0]*dp[0] + dp[1]*dp[1]
        if d2 < 1e-14:
            return None
        # u is the position of projection of p point on line p1p2
        # regarding point p1 and (p2-p1) direction vector
        u = ((p[0] - p1[0])*dp[0] + (p[1] - p1[1])*dp[1]) / d2
        if not 0 <= u <= 1:
            return None
        return u

    result = {
        # In the first approximation, position on rails is the index of the
        # closest vertex of line to the point p. Fractional value means that
        # the projected point lies on a segment between two vertices. More than
        # one value can occur if a route follows the same tracks more than once.
        'positions_on_rails': None,
        'projected_point': None  # (lon, lat)
    }

    if len(line) < 2:
        return result
    d_min = MAX_DISTANCE_STOP_TO_LINE * 5
    closest_to_vertex = False
    # First, check vertices in the line
    for i, vertex in enumerate(line):
        d = distance(p, vertex)
        if d < d_min:
            result['positions_on_rails'] = [i]
            result['projected_point'] = vertex
            d_min = d
            closest_to_vertex = True
        elif vertex == result['projected_point']:
            # Repeated occurrence of the track vertex in line, like Oslo Line 5
            result['positions_on_rails'].append(i)
    # And then calculate distances to each segment
    for seg in range(len(line)-1):
        # Check bbox for speed
        if not ((min(line[seg][0], line[seg+1][0]) - MAX_DISTANCE_STOP_TO_LINE <= p[0] <=
                 max(line[seg][0], line[seg+1][0]) + MAX_DISTANCE_STOP_TO_LINE) and
                (min(line[seg][1], line[seg+1][1]) - MAX_DISTANCE_STOP_TO_LINE <= p[1] <=
                 max(line[seg][1], line[seg+1][1]) + MAX_DISTANCE_STOP_TO_LINE)):
            continue
        u = project_on_segment(p, line[seg], line[seg+1])
        if u:
            projected_point = (
                line[seg][0] + u * (line[seg+1][0] - line[seg][0]),
                line[seg][1] + u * (line[seg+1][1] - line[seg][1])
            )
            d = distance(p, projected_point)
            if d < d_min:
                result['positions_on_rails'] = [seg + u]
                result['projected_point'] = projected_point
                d_min = d
                closest_to_vertex = False
            elif projected_point == result['projected_point']:
                # Repeated occurrence of the track segment in line, like Oslo Line 5
                if not closest_to_vertex:
                    result['positions_on_rails'].append(seg + u)
    return result


def find_segment(p, line, start_vertex=0):
    """Returns index of a segment and a position inside it."""
    EPS = 1e-9
    for seg in range(start_vertex, len(line)-1):
        if is_near(p, line[seg]):
            return seg, 0
        if line[seg][0] == line[seg+1][0]:
            if not (p[0]-EPS <= line[seg][0] <= p[0]+EPS):
                continue
            px = None
        else:
            px = (p[0] - line[seg][0]) / (line[seg+1][0] - line[seg][0])
        if px is None or (0 <= px <= 1):
            if line[seg][1] == line[seg+1][1]:
                if not (p[1]-EPS <= line[seg][1] <= p[1]+EPS):
                    continue
                py = None
            else:
                py = (p[1] - line[seg][1]) / (line[seg+1][1] - line[seg][1])
            if py is None or (0 <= py <= 1):
                if py is None or px is None or (px-EPS <= py <= px+EPS):
                    return seg, px or py
    return None, None


def distance_on_line(p1, p2, line, start_vertex=0):
    """Calculates distance via line between projections
    of points p1 and p2. Returns a TUPLE of (d, vertex):
    d is the distance and vertex is the number of the second
    vertex, to continue calculations for the next point."""
    line_copy = line
    seg1, pos1 = find_segment(p1, line, start_vertex)
    if seg1 is None:
        # logging.warn('p1 %s is not projected, st=%s', p1, start_vertex)
        return None
    seg2, pos2 = find_segment(p2, line, seg1)
    if seg2 is None:
        if line[0] == line[-1]:
            line = line + line[1:]
            seg2, pos2 = find_segment(p2, line, seg1)
        if seg2 is None:
            # logging.warn('p2 %s is not projected, st=%s', p2, start_vertex)
            return None
    if seg1 == seg2:
        return distance(line[seg1], line[seg1+1]) * abs(pos2-pos1), seg1
    if seg2 < seg1:
        # Should not happen
        raise Exception('Pos1 %s is after pos2 %s', seg1, seg2)
    d = 0
    if pos1 < 1:
        d += distance(line[seg1], line[seg1+1]) * (1-pos1)
    for i in range(seg1+1, seg2):
        d += distance(line[i], line[i+1])
    if pos2 > 0:
        d += distance(line[seg2], line[seg2+1]) * pos2
    return d, seg2 % len(line_copy)


def angle_between(p1, c, p2):
    a = round(abs(math.degrees(math.atan2(p1[1]-c[1], p1[0]-c[0]) -
                               math.atan2(p2[1]-c[1], p2[0]-c[0]))))
    return a if a <= 180 else 360-a


def format_elid_list(ids):
    msg = ', '.join(sorted(ids)[:20])
    if len(ids) > 20:
        msg += ', ...'
    return msg


class Station:
    @staticmethod
    def get_modes(el):
        mode = el['tags'].get('station')
        modes = [] if not mode else [mode]
        for m in ALL_MODES:
            if el['tags'].get(m) == 'yes':
                modes.append(m)
        return set(modes)

    @staticmethod
    def is_station(el, modes):
        # public_transport=station is too ambiguous and unspecific to use,
        # so we expect for it to be backed by railway=station.
        if 'tram' in modes and el.get('tags', {}).get('railway') == 'tram_stop':
            return True
        if el.get('tags', {}).get('railway') not in ('station', 'halt'):
            return False
        for k in CONSTRUCTION_KEYS:
            if k in el['tags']:
                return False
        # Not checking for station=train, obviously
        if 'train' not in modes and Station.get_modes(el).isdisjoint(modes):
            return False
        return True

    def __init__(self, el, city):
        """Call this with a railway=station node."""
        if not Station.is_station(el, city.modes):
            raise Exception(
                'Station object should be instantiated from a station node. Got: {}'.format(el))

        self.id = el_id(el)
        self.element = el
        self.modes = Station.get_modes(el)
        self.name = el['tags'].get('name', '?')
        self.int_name = el['tags'].get('int_name', el['tags'].get('name:en', None))
        try:
            self.colour = normalize_colour(el['tags'].get('colour', None))
        except ValueError as e:
            self.colour = None
            city.warn(str(e), el)
        self.center = el_center(el)
        if self.center is None:
            raise Exception('Could not find center of {}'.format(el))

    def __repr__(self):
        return 'Station(id={}, modes={}, name={}, center={})'.format(
            self.id, ','.join(self.modes), self.name, self.center)


class StopArea:
    @staticmethod
    def is_stop(el):
        if 'tags' not in el:
            return False
        if el['tags'].get('railway') == 'stop':
            return True
        if el['tags'].get('public_transport') == 'stop_position':
            return True
        return False

    @staticmethod
    def is_platform(el):
        if 'tags' not in el:
            return False
        if el['tags'].get('railway') in ('platform', 'platform_edge'):
            return True
        if el['tags'].get('public_transport') == 'platform':
            return True
        return False

    @staticmethod
    def is_track(el):
        if el['type'] != 'way' or 'tags' not in el:
            return False
        return el['tags'].get('railway') in RAILWAY_TYPES

    def __init__(self, station, city, stop_area=None):
        """Call this with a Station object."""

        self.element = stop_area or station.element
        self.id = el_id(self.element)
        self.station = station
        self.stops = set()      # set of el_ids of stop_positions
        self.platforms = set()  # set of el_ids of platforms
        self.exits = set()      # el_id of subway_entrance for leaving the platform
        self.entrances = set()  # el_id of subway_entrance for entering the platform
        self.center = None      # lon, lat of the station centre point
        self.centers = {}       # el_id -> (lon, lat) for all elements
        self.transfer = None    # el_id of a transfer relation

        self.modes = station.modes
        self.name = station.name
        self.int_name = station.int_name
        self.colour = station.colour

        if stop_area:
            self.name = stop_area['tags'].get('name', self.name)
            self.int_name = stop_area['tags'].get(
                'int_name', stop_area['tags'].get('name:en', self.int_name))
            try:
                self.colour = normalize_colour(
                    stop_area['tags'].get('colour')) or self.colour
            except ValueError as e:
                city.warn(str(e), stop_area)

            # If we have a stop area, add all elements from it
            warned_about_tracks = False
            for m in stop_area['members']:
                k = el_id(m)
                m_el = city.elements.get(k)
                if m_el and 'tags' in m_el:
                    if Station.is_station(m_el, city.modes):
                        if k != station.id:
                            city.error('Stop area has multiple stations', stop_area)
                    elif StopArea.is_stop(m_el):
                        self.stops.add(k)
                    elif StopArea.is_platform(m_el):
                        self.platforms.add(k)
                    elif m_el['tags'].get('railway') == 'subway_entrance':
                        if m_el['type'] != 'node':
                            city.warn('Subway entrance is not a node', m_el)
                        if m_el['tags'].get('entrance') != 'exit' and m['role'] != 'exit_only':
                            self.entrances.add(k)
                        if m_el['tags'].get('entrance') != 'entrance' and m['role'] != 'entry_only':
                            self.exits.add(k)
                    elif StopArea.is_track(m_el):
                        if not warned_about_tracks:
                            city.error('Tracks in a stop_area relation', stop_area)
                            warned_about_tracks = True
        else:
            # Otherwise add nearby entrances
            center = station.center
            for c_el in city.elements.values():
                if c_el.get('tags', {}).get('railway') == 'subway_entrance':
                    c_id = el_id(c_el)
                    if c_id not in city.stop_areas:
                        c_center = el_center(c_el)
                        if c_center and distance(center, c_center) <= MAX_DISTANCE_TO_ENTRANCES:
                            if c_el['type'] != 'node':
                                city.warn('Subway entrance is not a node', c_el)
                            etag = c_el['tags'].get('entrance')
                            if etag != 'exit':
                                self.entrances.add(c_id)
                            if etag != 'entrance':
                                self.exits.add(c_id)

        if self.exits and not self.entrances:
            city.error('Only exits for a station, no entrances', stop_area or station.element)
        if self.entrances and not self.exits:
            city.error('No exits for a station', stop_area or station.element)

        for el in self.get_elements():
            self.centers[el] = el_center(city.elements[el])

        """Calculates the center point of the station. This algorithm
        cannot rely on a station node, since many stop_areas can share one.
        Basically it averages center points of all platforms
        and stop positions."""
        if len(self.stops) + len(self.platforms) == 0:
            self.center = station.center
        else:
            self.center = [0, 0]
            for sp in self.stops | self.platforms:
                spc = self.centers[sp]
                for i in range(2):
                    self.center[i] += spc[i]
            for i in range(2):
                self.center[i] /= len(self.stops) + len(self.platforms)

    def get_elements(self):
        result = set([self.id, self.station.id])
        result.update(self.entrances)
        result.update(self.exits)
        result.update(self.stops)
        result.update(self.platforms)
        return result

    def __repr__(self):
        return 'StopArea(id={}, name={}, station={}, transfer={}, center={})'.format(
            self.id, self.name, self.station, self.transfer, self.center)


class RouteStop:
    def __init__(self, stoparea):
        self.stoparea = stoparea
        self.stop = None  # Stop position (lon, lat), possibly projected
        self.distance = 0  # In meters from the start of the route
        self.platform_entry = None  # Platform el_id
        self.platform_exit = None  # Platform el_id
        self.can_enter = False
        self.can_exit = False
        self.seen_stop = False
        self.seen_platform_entry = False
        self.seen_platform_exit = False
        self.seen_station = False

    @property
    def seen_platform(self):
        return self.seen_platform_entry or self.seen_platform_exit

    @staticmethod
    def get_actual_role(el, role, modes):
        if StopArea.is_stop(el):
            return 'stop'
        elif StopArea.is_platform(el):
            return 'platform'
        elif Station.is_station(el, modes):
            if 'platform' in role:
                return 'platform'
            else:
                return 'stop'
        return None

    def add(self, member, relation, city):
        el = city.elements[el_id(member)]
        role = member['role']

        if StopArea.is_stop(el):
            if 'platform' in role:
                city.warn('Stop position in a platform role in a route', el)
            if el['type'] != 'node':
                city.error('Stop position is not a node', el)
            self.stop = el_center(el)
            if 'entry_only' not in role:
                self.can_exit = True
            if 'exit_only' not in role:
                self.can_enter = True

        elif Station.is_station(el, city.modes):
            if el['type'] != 'node':
                city.warn('Station in route is not a node', el)

            if not self.seen_stop and not self.seen_platform:
                self.stop = el_center(el)
                self.can_enter = True
                self.can_exit = True

        elif StopArea.is_platform(el):
            if 'stop' in role:
                city.warn('Platform in a stop role in a route', el)
            if 'exit_only' not in role:
                self.platform_entry = el_id(el)
                self.can_enter = True
            if 'entry_only' not in role:
                self.platform_exit = el_id(el)
                self.can_exit = True
            if not self.seen_stop:
                self.stop = el_center(el)

        else:
            city.error('Not a stop or platform in a route relation', el)

        multiple_check = False
        actual_role = RouteStop.get_actual_role(el, role, city.modes)
        if actual_role == 'platform':
            if role == 'platform_entry_only':
                multiple_check = self.seen_platform_entry
                self.seen_platform_entry = True
            elif role == 'platform_exit_only':
                multiple_check = self.seen_platform_exit
                self.seen_platform_exit = True
            else:
                if role != 'platform' and 'stop' not in role:
                    city.warn("Platform with invalid role '{}' in a route".format(role), el)
                multiple_check = self.seen_platform
                self.seen_platform_entry = True
                self.seen_platform_exit = True
        elif actual_role == 'stop':
            multiple_check = self.seen_stop
            self.seen_stop = True
        if multiple_check:
            city.error_if(
                actual_role == 'stop',
                'Multiple {}s for a station "{}" ({}) in a route relation'.format(
                    actual_role, el['tags'].get('name', ''), el_id(el)), relation)

    def __repr__(self):
        return 'RouteStop(stop={}, pl_entry={}, pl_exit={}, stoparea={})'.format(
            self.stop, self.platform_entry, self.platform_exit, self.stoparea)


class Route:
    """The longest route for a city with a unique ref."""
    @staticmethod
    def is_route(el, modes):
        if el['type'] != 'relation' or el.get('tags', {}).get('type') != 'route':
            return False
        if 'members' not in el:
            return False
        if el['tags'].get('route') not in modes:
            return False
        for k in CONSTRUCTION_KEYS:
            if k in el['tags']:
                return False
        if 'ref' not in el['tags'] and 'name' not in el['tags']:
            return False
        return True

    @staticmethod
    def get_network(relation):
        for k in ('network:metro', 'network', 'operator'):
            if k in relation['tags']:
                return relation['tags'][k]
        return None

    @staticmethod
    def get_interval(tags):
        v = None
        for k in ('interval', 'headway'):
            if k in tags:
                v = tags[k]
                break
            else:
                for kk in tags:
                    if kk.startswith(k+':'):
                        v = tags[kk]
                        break
        if not v:
            return None
        try:
            return float(v)
        except ValueError:
            return None

    def build_longest_line(self, relation):
        line_nodes = set()
        last_track = []
        track = []
        warned_about_holes = False
        for m in relation['members']:
            el = self.city.elements.get(el_id(m), None)
            if not el or not StopArea.is_track(el):
                continue
            if 'nodes' not in el or len(el['nodes']) < 2:
                self.city.error('Cannot find nodes in a railway', el)
                continue
            nodes = ['n{}'.format(n) for n in el['nodes']]
            if m['role'] == 'backward':
                nodes.reverse()
            line_nodes.update(nodes)
            if not track:
                is_first = True
                track.extend(nodes)
            else:
                new_segment = list(nodes)  # copying
                if new_segment[0] == track[-1]:
                    track.extend(new_segment[1:])
                elif new_segment[-1] == track[-1]:
                    track.extend(reversed(new_segment[:-1]))
                elif is_first and track[0] in (new_segment[0], new_segment[-1]):
                    # We can reverse the track and try again
                    track.reverse()
                    if new_segment[0] == track[-1]:
                        track.extend(new_segment[1:])
                    else:
                        track.extend(reversed(new_segment[:-1]))
                else:
                    # Store the track if it is long and clean it
                    if not warned_about_holes:
                        self.city.warn('Hole in route rails near node {}'.format(
                            track[-1]), relation)
                        warned_about_holes = True
                    if len(track) > len(last_track):
                        last_track = track
                    track = []
                is_first = False
        if len(track) > len(last_track):
            last_track = track
        # Remove duplicate points
        last_track = [last_track[i] for i in range(0, len(last_track))
                      if i == 0 or last_track[i-1] != last_track[i]]
        return last_track, line_nodes

    def project_stops_on_line(self):
        projected = [project_on_line(x.stop, self.tracks) for x in self.stops]
        start = 0
        while (start < len(self.stops) and
                (
                    projected[start]['projected_point'] is None or
                    distance(
                       self.stops[start].stop,
                       projected[start]['projected_point']
                    ) > MAX_DISTANCE_STOP_TO_LINE
                )
        ):
            start += 1
        end = len(self.stops) - 1
        while (end > start and
                (
                    projected[end]['projected_point'] is None or
                    distance(
                        self.stops[end].stop,
                        projected[end]['projected_point']
                    ) > MAX_DISTANCE_STOP_TO_LINE
                )
        ):
            end -= 1
        tracks_start = []
        tracks_end = []
        stops_on_longest_line = []
        for i, route_stop in enumerate(self.stops):
            if i < start:
                tracks_start.append(route_stop.stop)
            elif i > end:
                tracks_end.append(route_stop.stop)
            elif projected[i]['projected_point'] is None:
                self.city.error('Stop "{}" {} is nowhere near the tracks'.format(
                    route_stop.stoparea.name, route_stop.stop), self.element)
            else:
                projected_point = projected[i]['projected_point']
                # We've got two separate stations with a good stretch of
                # railway tracks between them. Put these on tracks.
                d = round(distance(route_stop.stop, projected_point))
                if d > MAX_DISTANCE_STOP_TO_LINE:
                    self.city.warn('Stop "{}" {} is {} meters from the tracks'.format(
                        route_stop.stoparea.name, route_stop.stop, d), self.element)
                else:
                    route_stop.stop = projected_point
                route_stop.positions_on_rails = projected[i]['positions_on_rails']
                stops_on_longest_line.append(route_stop)
        if start >= len(self.stops):
            self.tracks = tracks_start
        elif tracks_start or tracks_end:
            self.tracks = tracks_start + self.tracks + tracks_end
        return stops_on_longest_line

    def calculate_distances(self):
        dist = 0
        vertex = 0
        for i, stop in enumerate(self.stops):
            if i > 0:
                direct = distance(stop.stop, self.stops[i-1].stop)
                d_line = distance_on_line(self.stops[i-1].stop, stop.stop, self.tracks, vertex)
                if d_line and direct-10 <= d_line[0] <= direct*2:
                    vertex = d_line[1]
                    dist += round(d_line[0])
                else:
                    dist += round(direct)
            stop.distance = dist

    def __init__(self, relation, city, master=None):
        if not Route.is_route(relation, city.modes):
            raise Exception('The relation does not seem a route: {}'.format(relation))
        master_tags = {} if not master else master['tags']
        self.city = city
        self.element = relation
        self.id = el_id(relation)
        if 'ref' not in relation['tags'] and 'ref' not in master_tags:
            city.warn('Missing ref on a route', relation)
        self.ref = relation['tags'].get('ref', master_tags.get(
            'ref', relation['tags'].get('name', None)))
        self.name = relation['tags'].get('name', None)
        self.mode = relation['tags']['route']
        if 'colour' not in relation['tags'] and 'colour' not in master_tags and self.mode != 'tram':
            city.warn('Missing colour on a route', relation)
        try:
            self.colour = normalize_colour(relation['tags'].get(
                'colour', master_tags.get('colour', None)))
        except ValueError as e:
            self.colour = None
            city.warn(str(e), relation)
        try:
            self.infill = normalize_colour(relation['tags'].get(
                'colour:infill', master_tags.get('colour:infill', None)))
        except ValueError as e:
            self.infill = None
            city.warn(str(e), relation)
        self.network = Route.get_network(relation)
        self.interval = Route.get_interval(relation['tags']) or Route.get_interval(master_tags)
        if relation['tags'].get('public_transport:version') == '1':
            city.error('Public transport version is 1, which means the route '
                       'is an unsorted pile of objects', relation)
        self.is_circular = False
        # self.tracks would be a list of (lon, lat) for the longest stretch. Can be empty
        tracks, line_nodes = self.build_longest_line(relation)
        self.tracks = [el_center(city.elements.get(k)) for k in tracks]
        if None in self.tracks:  # usually, extending BBOX for the city is needed
            self.tracks = []
            for n in filter(lambda x: x not in city.elements, tracks):
                city.error('The dataset is missing the railway tracks node {}'.format(n), relation)
                break
        check_stop_positions = len(line_nodes) > 50  # arbitrary number, of course
        self.stops = []  # List of RouteStop
        stations = set()  # temporary for recording stations
        seen_stops = False
        seen_platforms = False
        repeat_pos = None
        for m in relation['members']:
            if 'inactive' in m['role']:
                continue
            k = el_id(m)
            if k in city.stations:
                st_list = city.stations[k]
                st = st_list[0]
                if len(st_list) > 1:
                    city.error('Ambiguous station {} in route. Please use stop_position or split '
                               'interchange stations'.format(st.name), relation)
                el = city.elements[k]
                actual_role = RouteStop.get_actual_role(el, m['role'], city.modes)
                if actual_role:
                    if m['role'] and actual_role not in m['role']:
                        city.warn("Wrong role '{}' for {} {}".format(m['role'], actual_role, k), relation)
                    if repeat_pos is None:
                        if not self.stops or st not in stations:
                            stop = RouteStop(st)
                            self.stops.append(stop)
                            stations.add(st)
                        elif self.stops[-1].stoparea.id == st.id:
                            stop = self.stops[-1]
                        else:
                            # We've got a repeat
                            if ((seen_stops and seen_platforms) or
                                    (actual_role == 'stop' and not seen_platforms) or
                                    (actual_role == 'platform' and not seen_stops)):
                                # Circular route!
                                stop = RouteStop(st)
                                self.stops.append(stop)
                                stations.add(st)
                            else:
                                repeat_pos = 0
                    if repeat_pos is not None:
                        if repeat_pos >= len(self.stops):
                            continue
                        # Check that the type matches
                        if (actual_role == 'stop' and seen_stops) or (
                                actual_role == 'platform' and seen_platforms):
                            city.error('Found an out-of-place {}: "{}" ({})'.format(
                                actual_role, el['tags'].get('name', ''), k), relation)
                            continue
                        # Find the matching stop starting with index repeat_pos
                        while (repeat_pos < len(self.stops) and
                               self.stops[repeat_pos].stoparea.id != st.id):
                            repeat_pos += 1
                        if repeat_pos >= len(self.stops):
                            city.error('Incorrect order of {}s at {}'.format(actual_role, k),
                                       relation)
                            continue
                        stop = self.stops[repeat_pos]

                    stop.add(m, relation, city)
                    if repeat_pos is None:
                        seen_stops |= stop.seen_stop or stop.seen_station
                        seen_platforms |= stop.seen_platform

                    if check_stop_positions and StopArea.is_stop(el):
                        if k not in line_nodes:
                            city.warn('Stop position "{}" ({}) is not on tracks'.format(
                                el['tags'].get('name', ''), k), relation)
                    continue

            if k not in city.elements:
                if 'stop' in m['role'] or 'platform' in m['role']:
                    city.error('{} {} {} for route relation is not in the dataset'.format(
                        m['role'], m['type'], m['ref']), relation)
                    raise CriticalValidationError(
                        'Stop or platform {} {} in relation {} '
                        'is not in the dataset for {}'.format(
                            m['type'], m['ref'], relation['id'], city.name))
                continue
            el = city.elements[k]
            if 'tags' not in el:
                city.error('Untagged object in a route', relation)
                continue

            is_under_construction = False
            for ck in CONSTRUCTION_KEYS:
                if ck in el['tags']:
                    city.error('An under construction {} {} in route. Consider '
                               'setting \'inactive\' role or removing construction attributes'
                               .format(m['role'] or 'feature', k), relation)
                    is_under_construction = True
                    break
            if is_under_construction:
                continue

            if Station.is_station(el, city.modes):
                # A station may be not included into this route due to previous
                # 'stop area has multiple stations' error. No other error message is needed.
                pass
            elif el['tags'].get('railway') in ('station', 'halt'):
                city.error('Missing station={} on a {}'.format(self.mode, m['role']), el)
            else:
                actual_role = RouteStop.get_actual_role(el, m['role'], city.modes)
                if actual_role:
                    city.error('{} {} {} is not connected to a station in route'.format(
                        actual_role, m['type'], m['ref']), relation)
                elif not StopArea.is_track(el):
                    city.error('Unknown member type for {} {} in route'.format(m['type'], m['ref']), relation)
        if not self.stops:
            city.error('Route has no stops', relation)
        elif len(self.stops) == 1:
            city.error('Route has only one stop', relation)
        else:
            self.is_circular = self.stops[0].stoparea == self.stops[-1].stoparea
            stops_on_longest_line = self.project_stops_on_line()
            self.check_and_recover_stops_order(stops_on_longest_line)
            self.calculate_distances()

    def check_stops_order_by_angle(self):
        disorder_warnings = []
        disorder_errors = []
        for si in range(len(self.stops) - 2):
            angle = angle_between(self.stops[si].stop,
                                  self.stops[si + 1].stop,
                                  self.stops[si + 2].stop)
            if angle < ALLOWED_ANGLE_BETWEEN_STOPS:
                msg = 'Angle between stops around "{}" is too narrow, {} degrees'.format(
                    self.stops[si + 1].stoparea.name, angle)
                if angle < DISALLOWED_ANGLE_BETWEEN_STOPS:
                    disorder_errors.append(msg)
                else:
                    disorder_warnings.append(msg)
        return disorder_warnings, disorder_errors

    def check_stops_order_on_tracks_direct(self, stop_sequence):
        """ Checks stops order on tracks, following stop_sequence
            in direct order only.
        :param stops_sequence: list of RouteStop that belong to the
        longest contiguous sequence of tracks in a route.
        :return: error message on the first order violation or None.
        """
        allowed_order_violations = 1 if self.is_circular else 0
        max_position_on_rails = -1
        for route_stop in stop_sequence:
            positions_on_rails = route_stop.positions_on_rails
            suitable_occurrence = 0
            while (suitable_occurrence < len(positions_on_rails) and
                   positions_on_rails[suitable_occurrence] < max_position_on_rails):
                suitable_occurrence += 1
            if suitable_occurrence == len(positions_on_rails):
                if allowed_order_violations > 0:
                    suitable_occurrence -= 1
                    allowed_order_violations -= 1
                else:
                    return 'Stops on tracks are unordered near "{}" {}'.format(
                                route_stop.stoparea.name,
                                route_stop.stop
                    )
            max_position_on_rails = positions_on_rails[suitable_occurrence]

    def check_stops_order_on_tracks(self, stops_sequence):
        """ Checks stops order on tracks, trying direct and reversed
            order of stops in the stop_sequence.
        :param stops_sequence: list of RouteStop that belong to the
        longest contiguous sequence of tracks in a route.
        :return: error message on the first order violation or None.
        """
        error_message = self.check_stops_order_on_tracks_direct(stops_sequence)
        if error_message:
            error_message_reversed = self.check_stops_order_on_tracks_direct(reversed(stops_sequence))
            if error_message_reversed is None:
                error_message = None
                self.city.warn('Tracks seem to go in the opposite direction to stops', self.element)
        return error_message

    def check_stops_order(self, stops_on_longest_line):
        angle_disorder_warnings, angle_disorder_errors = self.check_stops_order_by_angle()
        disorder_on_tracks_error = self.check_stops_order_on_tracks(stops_on_longest_line)
        disorder_warnings = angle_disorder_warnings
        disorder_errors = angle_disorder_errors
        if disorder_on_tracks_error:
            disorder_errors.append(disorder_on_tracks_error)
        return disorder_warnings, disorder_errors

    def check_and_recover_stops_order(self, stops_on_longest_line):
        disorder_warnings, disorder_errors = self.check_stops_order(stops_on_longest_line)
        if disorder_warnings or disorder_errors:
            resort_success = False
            if self.city.recovery_data:
                resort_success = self.try_resort_stops()
                if resort_success:
                    for msg in disorder_warnings:
                        self.city.warn(msg, self.element)
                    for msg in disorder_errors:
                        self.city.warn("Fixed with recovery data: " + msg, self.element)

            if not resort_success:
                for msg in disorder_warnings:
                    self.city.warn(msg, self.element)
                for msg in disorder_errors:
                    self.city.error(msg, self.element)

    def try_resort_stops(self):
        """Precondition: self.city.recovery_data is not None.
        Return success of station order recovering."""
        self_stops = {} # station name => RouteStop
        for stop in self.stops:
            station = stop.stoparea.station
            stop_name = station.name
            if stop_name == '?' and station.int_name:
                stop_name = station.int_name
            # We won't programmatically recover routes with repeating stations:
            # such cases are rare and deserves manual verification
            if stop_name in self_stops:
                return False
            self_stops[stop_name] = stop

        route_id = (self.colour, self.ref)
        if route_id not in self.city.recovery_data:
            return False

        stop_names = list(self_stops.keys())
        suitable_itineraries = []
        for itinerary in self.city.recovery_data[route_id]:
            itinerary_stop_names = [stop['name'] for stop in itinerary['stations']]
            if not (len(stop_names) == len(itinerary_stop_names) and
                    sorted(stop_names) == sorted(itinerary_stop_names)):
                continue
            big_station_displacement = False
            for it_stop in itinerary['stations']:
                name = it_stop['name']
                it_stop_center = it_stop['center']
                self_stop_center = self_stops[name].stoparea.station.center
                if distance(it_stop_center, self_stop_center) > DISPLACEMENT_TOLERANCE:
                    big_station_displacement = True
                    break
            if not big_station_displacement:
                suitable_itineraries.append(itinerary)

        if len(suitable_itineraries) == 0:
            return False
        elif len(suitable_itineraries) == 1:
            matching_itinerary = suitable_itineraries[0]
        else:
            from_tag = self.element['tags'].get('from')
            to_tag = self.element['tags'].get('to')
            if not from_tag and not to_tag:
                return False
            matching_itineraries = [
                itin for itin in suitable_itineraries
                    if from_tag and itin['from'] == from_tag or
                       to_tag and itin['to'] == to_tag
            ]
            if len(matching_itineraries) != 1:
                return False
            matching_itinerary = matching_itineraries[0]
        self.stops = [self_stops[stop['name']] for stop in matching_itinerary['stations']]
        return True

    def __len__(self):
        return len(self.stops)

    def __getitem__(self, i):
        return self.stops[i]

    def __iter__(self):
        return iter(self.stops)

    def __repr__(self):
        return ('Route(id={}, mode={}, ref={}, name={}, network={}, interval={}, '
                'circular={}, num_stops={}, line_length={} m, from={}, to={}').format(
                    self.id, self.mode, self.ref, self.name, self.network, self.interval,
                    self.is_circular, len(self.stops), self.stops[-1].distance,
                    self.stops[0], self.stops[-1])


class RouteMaster:
    def __init__(self, master=None):
        self.routes = []
        self.best = None
        self.id = el_id(master)
        self.has_master = master is not None
        self.interval_from_master = False
        if master:
            self.ref = master['tags'].get('ref', master['tags'].get('name', None))
            try:
                self.colour = normalize_colour(master['tags'].get('colour', None))
            except ValueError:
                self.colour = None
            try:
                self.infill = normalize_colour(master['tags'].get('colour:infill', None))
            except ValueError:
                self.colour = None
            self.network = Route.get_network(master)
            self.mode = master['tags'].get('route_master', None)  # This tag is required, but okay
            self.name = master['tags'].get('name', None)
            self.interval = Route.get_interval(master['tags'])
            self.interval_from_master = self.interval is not None
        else:
            self.ref = None
            self.colour = None
            self.infill = None
            self.network = None
            self.mode = None
            self.name = None
            self.interval = None

    def add(self, route, city):
        if not self.network:
            self.network = route.network
        elif route.network and route.network != self.network:
            city.error('Route has different network ("{}") from master "{}"'.format(
                route.network, self.network), route.element)

        if not self.colour:
            self.colour = route.colour
        elif route.colour and route.colour != self.colour:
            city.warn('Route "{}" has different colour from master "{}"'.format(
                route.colour, self.colour), route.element)

        if not self.infill:
            self.infill = route.infill
        elif route.infill and route.infill != self.infill:
            city.warn('Route "{}" has different infill colour from master "{}"'.format(
                route.infill, self.infill), route.element)

        if not self.ref:
            self.ref = route.ref
        elif route.ref != self.ref:
            city.warn('Route "{}" has different ref from master "{}"'.format(
                route.ref, self.ref), route.element)

        if not self.name:
            self.name = route.name

        if not self.mode:
            self.mode = route.mode
        elif route.mode != self.mode:
            city.error('Incompatible PT mode: master has {} and route has {}'.format(
                self.mode, route.mode), route.element)
            return

        if not self.interval_from_master and route.interval:
            if not self.interval:
                self.interval = route.interval
            else:
                self.interval = min(self.interval, route.interval)

        if not self.has_master and (not self.id or self.id > route.id):
            self.id = route.id

        self.routes.append(route)
        if not self.best or len(route.stops) > len(self.best.stops):
            self.best = route

    def stop_areas(self):
        """Returns a list of all stations on all route variants."""
        seen_ids = set()
        for route in self.routes:
            for stop in route:
                st = stop.stoparea
                if st.id not in seen_ids:
                    seen_ids.add(st.id)
                    yield st

    def __len__(self):
        return len(self.routes)

    def __getitem__(self, i):
        return self.routes[i]

    def __iter__(self):
        return iter(self.routes)

    def __repr__(self):
        return 'RouteMaster(id={}, mode={}, ref={}, name={}, network={}, num_variants={}'.format(
            self.id, self.mode, self.ref, self.name, self.network, len(self.routes))


class City:
    def __init__(self, row, overground=False):
        self.errors = []
        self.warnings = []
        self.name = row[1]
        self.country = row[2]
        self.continent = row[3]
        if not row[0]:
            self.error('City {} does not have an id'.format(self.name))
        self.id = int(row[0] or '0')
        self.overground = overground
        if not overground:
            self.num_stations = int(row[4])
            self.num_lines = int(row[5] or '0')
            self.num_light_lines = int(row[6] or '0')
            self.num_interchanges = int(row[7] or '0')
        else:
            self.num_tram_lines = int(row[4] or '0')
            self.num_trolleybus_lines = int(row[5] or '0')
            self.num_bus_lines = int(row[6] or '0')
            self.num_other_lines = int(row[7] or '0')

        # Aquiring list of networks and modes
        networks = None if len(row) <= 9 else row[9].split(':')
        if not networks or len(networks[-1]) == 0:
            self.networks = []
        else:
            self.networks = set(filter(None, [x.strip() for x in networks[-1].split(';')]))
        if not networks or len(networks) < 2 or len(networks[0]) == 0:
            if self.overground:
                self.modes = DEFAULT_MODES_OVERGROUND
            else:
                self.modes = DEFAULT_MODES_RAPID
        else:
            self.modes = set([x.strip() for x in networks[0].split(',')])

        # Reversing bbox so it is (xmin, ymin, xmax, ymax)
        bbox = row[8].split(',')
        if len(bbox) == 4:
            self.bbox = [float(bbox[i]) for i in (1, 0, 3, 2)]
        else:
            self.bbox = None

        self.elements = {}   # Dict el_id → el
        self.stations = defaultdict(list)   # Dict el_id → list of StopAreas
        self.routes = {}     # Dict route_ref → route
        self.masters = {}    # Dict el_id of route → route_master
        self.stop_areas = defaultdict(list)  # El_id → list of el_id of stop_area
        self.transfers = []  # List of lists of stop areas
        self.station_ids = set()  # Set of stations' uid
        self.stops_and_platforms = set()  # Set of stops and platforms el_id
        self.recovery_data = None

    def log_message(self, message, el):
        if el:
            tags = el.get('tags', {})
            message += ' ({} {}, "{}")'.format(
                el['type'], el.get('id', el.get('ref')),
                tags.get('name', tags.get('ref', '')))
        return message

    def warn(self, message, el=None):
        msg = self.log_message(message, el)
        self.warnings.append(msg)

    def error(self, message, el=None):
        msg = self.log_message(message, el)
        self.errors.append(msg)

    def error_if(self, is_error, message, el=None):
        if is_error:
            self.error(message, el)
        else:
            self.warn(message, el)

    def contains(self, el):
        center = el_center(el)
        if center:
            return (self.bbox[0] <= center[1] <= self.bbox[2] and
                    self.bbox[1] <= center[0] <= self.bbox[3])
        return False

    def add(self, el):
        if el['type'] == 'relation' and 'members' not in el:
            return
        self.elements[el_id(el)] = el
        if el['type'] == 'relation' and 'tags' in el:
            if el['tags'].get('type') == 'route_master':
                for m in el['members']:
                    if m['type'] == 'relation':
                        if el_id(m) in self.masters:
                            self.error('Route in two route_masters', m)
                        self.masters[el_id(m)] = el
            elif el['tags'].get('public_transport') == 'stop_area':
                warned_about_duplicates = False
                for m in el['members']:
                    stop_areas = self.stop_areas[el_id(m)]
                    if el in stop_areas:
                        if not warned_about_duplicates:
                            self.warn('Duplicate element in a stop area', el)
                            warned_about_duplicates = True
                    else:
                        stop_areas.append(el)

    def make_transfer(self, sag):
        transfer = set()
        for m in sag['members']:
            k = el_id(m)
            el = self.elements.get(k)
            if not el:
                # A sag member may validly not belong to the city while
                # the sag does - near the city bbox boundary
                continue
            if 'tags' not in el:
                self.error('An untagged object {} in a stop_area_group'.format(k), sag)
                continue
            if (el['type'] != 'relation' or
                    el['tags'].get('type') != 'public_transport' or
                    el['tags'].get('public_transport') != 'stop_area'):
                continue
            if k in self.stations:
                stoparea = self.stations[k][0]
                transfer.add(stoparea)
                if stoparea.transfer:
                    self.error('Stop area {} belongs to multiple interchanges'.format(k))
                stoparea.transfer = el_id(sag)
        if len(transfer) > 1:
            self.transfers.append(transfer)

    def extract_routes(self):
        # Extract stations
        processed_stop_areas = set()
        for el in self.elements.values():
            if Station.is_station(el, self.modes):
                # See PR https://github.com/mapsme/subways/pull/98 
                if el['type'] == 'relation' and el['tags'].get('type') != 'multipolygon':
                    self.error("A railway station cannot be a relation of type '{}'".format(
                                      el['tags'].get('type')), el)
                    continue
                st = Station(el, self)
                self.station_ids.add(st.id)
                if st.id in self.stop_areas:
                    stations = []
                    for sa in self.stop_areas[st.id]:
                        stations.append(StopArea(st, self, sa))
                else:
                    stations = [StopArea(st, self)]

                for station in stations:
                    if station.id not in processed_stop_areas:
                        processed_stop_areas.add(station.id)
                        for st_el in station.get_elements():
                            self.stations[st_el].append(station)

                        # Check that stops and platforms belong to single stop_area
                        for sp in station.stops | station.platforms:
                            if sp in self.stops_and_platforms:
                                self.warn('A stop or a platform {} belongs to multiple '
                                          'stations, might be correct'.format(sp))
                            else:
                                self.stops_and_platforms.add(sp)

        # Extract routes
        for el in self.elements.values():
            if Route.is_route(el, self.modes):
                if el['tags'].get('access') in ('no', 'private'):
                    continue
                route_id = el_id(el)
                master = self.masters.get(route_id, None)
                if self.networks:
                    network = Route.get_network(el)
                    if master:
                        master_network = Route.get_network(master)
                    else:
                        master_network = None
                    if network not in self.networks and master_network not in self.networks:
                        continue

                route = Route(el, self, master)
                k = el_id(master) if master else route.ref
                if k not in self.routes:
                    self.routes[k] = RouteMaster(master)
                self.routes[k].add(route, self)

                # Sometimes adding a route to a newly initialized RouteMaster can fail
                if len(self.routes[k]) == 0:
                    del self.routes[k]

            # And while we're iterating over relations, find interchanges
            if (el['type'] == 'relation' and
                    el.get('tags', {}).get('public_transport', None) == 'stop_area_group'):
                self.make_transfer(el)

        # Filter transfers, leaving only stations that belong to routes
        used_stop_areas = set()
        for rmaster in self.routes.values():
            for route in rmaster:
                used_stop_areas.update([s.stoparea for s in route.stops])
        new_transfers = []
        for transfer in self.transfers:
            new_tr = [s for s in transfer if s in used_stop_areas]
            if len(new_tr) > 1:
                new_transfers.append(new_tr)
        self.transfers = new_transfers

    def __iter__(self):
        return iter(self.routes.values())

    def is_good(self):
        return len(self.errors) == 0

    def get_validation_result(self):
        result = {
            'name': self.name,
            'country': self.country,
            'continent': self.continent,
            'stations_found': getattr(self, 'found_stations', 0),
            'transfers_found': getattr(self, 'found_interchanges', 0),
            'unused_entrances': getattr(self, 'unused_entrances', 0),
            'networks': getattr(self, 'found_networks', 0)
        }
        if not self.overground:
            result.update({
                'subwayl_expected': self.num_lines,
                'lightrl_expected': self.num_light_lines,
                'subwayl_found': getattr(self, 'found_lines', 0),
                'lightrl_found': getattr(self, 'found_light_lines', 0),
                'stations_expected': self.num_stations,
                'transfers_expected': self.num_interchanges,
            })
        else:
            result.update({
                'stations_expected': 0,
                'transfers_expected': 0,
                'busl_expected': self.num_bus_lines,
                'trolleybusl_expected': self.num_trolleybus_lines,
                'traml_expected': self.num_tram_lines,
                'otherl_expected': self.num_other_lines,
                'busl_found': getattr(self, 'found_bus_lines', 0),
                'trolleybusl_found': getattr(self, 'found_trolleybus_lines', 0),
                'traml_found': getattr(self, 'found_tram_lines', 0),
                'otherl_found': getattr(self, 'found_other_lines', 0)
            })
        result['warnings'] = self.warnings
        result['errors'] = self.errors
        return result

    def count_unused_entrances(self):
        global used_entrances
        stop_areas = set()
        for el in self.elements.values():
            if (el['type'] == 'relation' and 'tags' in el and
                    el['tags'].get('public_transport') == 'stop_area' and
                    'members' in el):
                stop_areas.update([el_id(m) for m in el['members']])
        unused = []
        not_in_sa = []
        for el in self.elements.values():
            if (el['type'] == 'node' and 'tags' in el and
                    el['tags'].get('railway') == 'subway_entrance'):
                i = el_id(el)
                if i in self.stations:
                    used_entrances.add(i)
                if i not in stop_areas:
                    not_in_sa.append(i)
                    if i not in self.stations:
                        unused.append(i)
        self.unused_entrances = len(unused)
        self.entrances_not_in_stop_areas = len(not_in_sa)
        if unused:
            self.warn('Found {} entrances not used in routes or stop_areas: {}'.format(
                len(unused), format_elid_list(unused)))
        if not_in_sa:
            self.warn('{} subway entrances are not in stop_area relations: {}'.format(
                len(not_in_sa), format_elid_list(not_in_sa)))

    def check_return_routes(self, rmaster):
        variants = {}
        have_return = set()
        for variant in rmaster:
            if len(variant) < 2:
                continue
            # Using transfer ids because a train can arrive at different stations within a transfer
            # But disregard transfer that may give an impression of a circular route
            # (for example, Simonis / Elisabeth station and route 2 in Brussels)
            if variant[0].stoparea.transfer == variant[-1].stoparea.transfer:
                t = (variant[0].stoparea.id, variant[-1].stoparea.id)
            else:
                t = (variant[0].stoparea.transfer or variant[0].stoparea.id,
                     variant[-1].stoparea.transfer or variant[-1].stoparea.id)
            if t in variants:
                continue
            variants[t] = variant.element
            tr = (t[1], t[0])
            if tr in variants:
                have_return.add(t)
                have_return.add(tr)

        if len(variants) == 0:
            self.error('An empty route master {}. Please set construction:route '
                       'if it is under construction'.format(rmaster.id))
        elif len(variants) == 1:
            self.error_if(not rmaster.best.is_circular, 'Only one route in route_master. '
                          'Please check if it needs a return route', rmaster.best.element)
        else:
            for t, rel in variants.items():
                if t not in have_return:
                    self.warn('Route does not have a return direction', rel)

    def validate_lines(self):
        self.found_light_lines = len([x for x in self.routes.values() if x.mode != 'subway'])
        self.found_lines = len(self.routes) - self.found_light_lines
        if self.found_lines != self.num_lines:
            self.error('Found {} subway lines, expected {}'.format(
                self.found_lines, self.num_lines))
        if self.found_light_lines != self.num_light_lines:
            self.error('Found {} light rail lines, expected {}'.format(
                self.found_light_lines, self.num_light_lines))

    def validate_overground_lines(self):
        self.found_tram_lines = len([x for x in self.routes.values() if x.mode == 'tram'])
        self.found_bus_lines = len([x for x in self.routes.values() if x.mode == 'bus'])
        self.found_trolleybus_lines = len([x for x in self.routes.values()
                                           if x.mode == 'trolleybus'])
        self.found_other_lines = len([x for x in self.routes.values()
                                      if x.mode not in ('bus', 'trolleybus', 'tram')])
        if self.found_tram_lines != self.num_tram_lines:
            self.error_if(self.found_tram_lines == 0, 'Found {} tram lines, expected {}'.format(
                self.found_tram_lines, self.num_tram_lines))

    def validate(self):
        networks = Counter()
        self.found_stations = 0
        unused_stations = set(self.station_ids)
        for rmaster in self.routes.values():
            networks[str(rmaster.network)] += 1
            if not self.overground:
                self.check_return_routes(rmaster)
            route_stations = set()
            for sa in rmaster.stop_areas():
                route_stations.add(sa.transfer or sa.id)
                unused_stations.discard(sa.station.id)
            self.found_stations += len(route_stations)
        if unused_stations:
            self.unused_stations = len(unused_stations)
            self.warn('{} unused stations: {}'.format(
                self.unused_stations, format_elid_list(unused_stations)))
        self.count_unused_entrances()
        self.found_interchanges = len(self.transfers)

        if self.overground:
            self.validate_overground_lines()
        else:
            self.validate_lines()

            if self.found_stations != self.num_stations:
                msg = 'Found {} stations in routes, expected {}'.format(
                    self.found_stations, self.num_stations)
                self.error_if(not (0 <=
                                   (self.num_stations - self.found_stations) / self.num_stations <=
                                   ALLOWED_STATIONS_MISMATCH), msg)

            if self.found_interchanges != self.num_interchanges:
                msg = 'Found {} interchanges, expected {}'.format(
                    self.found_interchanges, self.num_interchanges)
                self.error_if(self.num_interchanges != 0 and not
                              ((self.num_interchanges - self.found_interchanges) /
                               self.num_interchanges <= ALLOWED_TRANSFERS_MISMATCH), msg)

        self.found_networks = len(networks)
        if len(networks) > max(1, len(self.networks)):
            n_str = '; '.join(['{} ({})'.format(k, v) for k, v in networks.items()])
            self.warn('More than one network: {}'.format(n_str))


def find_transfers(elements, cities):
    transfers = []
    stop_area_groups = []
    for el in elements:
        if (el['type'] == 'relation' and 'members' in el and
                el.get('tags', {}).get('public_transport') == 'stop_area_group'):
            stop_area_groups.append(el)

    # StopArea.id uniquely identifies a StopArea.
    # We must ensure StopArea uniqueness since one stop_area relation may result in
    # several StopArea instances at inter-city interchanges.
    stop_area_ids = defaultdict(set)  # el_id -> set of StopArea.id
    stop_area_objects = dict()  # StopArea.id -> one of StopArea instances
    for city in cities:
        for el, st in city.stations.items():
            stop_area_ids[el].update(sa.id for sa in st)
            stop_area_objects.update((sa.id, sa) for sa in st)

    for sag in stop_area_groups:
        transfer = set()
        for m in sag['members']:
            k = el_id(m)
            if k not in stop_area_ids:
                continue
            transfer.update(stop_area_objects[sa_id] for sa_id in stop_area_ids[k])
        if len(transfer) > 1:
            transfers.append(transfer)
    return transfers


def get_unused_entrances_geojson(elements):
    global used_entrances
    features = []
    for el in elements:
        if (el['type'] == 'node' and 'tags' in el and
                el['tags'].get('railway') == 'subway_entrance'):
            if el_id(el) not in used_entrances:
                geometry = {'type': 'Point', 'coordinates': el_center(el)}
                properties = {k: v for k, v in el['tags'].items()
                              if k not in ('railway', 'entrance')}
                features.append({'type': 'Feature', 'geometry': geometry, 'properties': properties})
    return {'type': 'FeatureCollection', 'features': features}


def download_cities(overground=False):
    url = 'https://docs.google.com/spreadsheets/d/{}/export?format=csv{}'.format(
        SPREADSHEET_ID, '&gid=1881416409' if overground else '')
    response = urllib.request.urlopen(url)
    if response.getcode() != 200:
        raise Exception('Failed to download cities spreadsheet: HTTP {}'.format(response.getcode()))
    data = response.read().decode('utf-8')
    r = csv.reader(data.splitlines())
    next(r)  # skipping the header
    names = set()
    cities = []
    for row in r:
        if len(row) > 8 and row[8]:
            cities.append(City(row, overground))
            if row[0].strip() in names:
                logging.warning('Duplicate city name in the google spreadsheet: %s', row[0])
            names.add(row[0].strip())
    return cities
