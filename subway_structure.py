import csv
import logging
import math
import urllib.parse
import urllib.request
from css_colours import normalize_colour
from collections import Counter, defaultdict


SPREADSHEET_ID = '1-UHDzfBwHdeyFxgC5cE_MaNQotF3-Y0r1nW9IwpIEj8'
MAX_DISTANCE_NEARBY = 150  # in meters
MAX_DISTANCE_STOP_TO_LINE = 50  # in meters
ALLOWED_STATIONS_MISMATCH = 0.02   # part of total station count
ALLOWED_TRANSFERS_MISMATCH = 0.07  # part of total interchanges count
MIN_ANGLE_BETWEEN_STOPS = 45  # in degrees

DEFAULT_MODES = set(('subway', 'light_rail'))
ALL_MODES = set(('subway', 'light_rail', 'monorail', 'train', 'tram',
                 'bus', 'trolleybus', 'aerialway', 'ferry'))
RAILWAY_TYPES = set(('rail', 'light_rail', 'subway', 'narrow_gauge',
                     'funicular', 'monorail', 'tram'))
CONSTRUCTION_KEYS = ('construction', 'proposed', 'construction:railway', 'proposed:railway')
NOWHERE_STOP = (0, 0)  # too far away from any metro system

transfers = []
used_entrances = set()


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
        if el['center']['lat'] == 0.0:
            # Some relations don't have centers. We need route_masters and stop_area_groups.
            if el['type'] == 'relation' and 'tags' in el and (
                    el['tags'].get('type') == 'route_master' or
                    el['tags'].get('public_transport') == 'stop_area_group'):
                return None
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
        u = ((p[0] - p1[0])*dp[0] + (p[1] - p1[1])*dp[1]) / d2
        res = (p1[0] + u*dp[0], p1[1] + u*dp[1])
        if res[0] < min(p1[0], p2[0]) or res[0] > max(p1[0], p2[0]):
            return None
        return res

    result = NOWHERE_STOP
    if len(line) < 2:
        return result
    d_min = MAX_DISTANCE_STOP_TO_LINE * 5
    # First, check vertices in the line
    for vertex in line:
        d = distance(p, vertex)
        if d < d_min:
            result = vertex
            d_min = d
    # And then calculate distances to each segment
    for seg in range(len(line)-1):
        # Check bbox for speed
        if not ((min(line[seg][0], line[seg+1][0]) - MAX_DISTANCE_STOP_TO_LINE <= p[0] <=
                 max(line[seg][0], line[seg+1][0]) + MAX_DISTANCE_STOP_TO_LINE) and
                (min(line[seg][1], line[seg+1][1]) - MAX_DISTANCE_STOP_TO_LINE <= p[1] <=
                 max(line[seg][1], line[seg+1][1]) + MAX_DISTANCE_STOP_TO_LINE)):
            continue
        proj = project_on_segment(p, line[seg], line[seg+1])
        if proj:
            d = distance(p, proj)
            if d < d_min:
                result = proj
                d_min = d
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
    def is_station(el, modes=DEFAULT_MODES):
        # public_transport=station is too ambigous and unspecific to use,
        # so we expect for it to be backed by railway=station.
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

    def __hash__(self):
        return hash(self.__repr__())

    def __eq__(self, other):
        if isinstance(other, Station):
            return self.id == other.id
        return False


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
        if el['tags'].get('railway') == 'platform':
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
            # Otherwise add nearby entrances and stop positions
            center = station.center
            for c_el in city.elements.values():
                c_id = el_id(c_el)
                if c_id in city.stop_areas:
                    continue
                c_center = el_center(c_el)
                if 'tags' not in c_el or not c_center:
                    continue
                if 'station' in c_el['tags']:
                    continue
                if StopArea.is_stop(c_el):
                    # Take care to not add other stations
                    if distance(center, c_center) <= MAX_DISTANCE_NEARBY:
                        self.stops.add(c_id)
                elif StopArea.is_stop(c_el):
                    # Take care to not add other stations
                    if distance(center, c_center) <= MAX_DISTANCE_NEARBY:
                        self.platforms.add(c_id)
                elif c_el['tags'].get('railway') == 'subway_entrance':
                    if distance(center, c_center) <= MAX_DISTANCE_NEARBY:
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

    def __hash__(self):
        return hash(self.__repr__())

    def __eq__(self, other):
        if isinstance(other, StopArea):
            return self.id == other.id and self.station == other.station
        return False


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
        self.seen_platform = False
        self.seen_station = False

    @staticmethod
    def get_member_type(el, role, modes=DEFAULT_MODES):
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
        el_type = RouteStop.get_member_type(el, role, city.modes)
        if el_type == 'platform':
            multiple_check = self.seen_platform
            self.seen_platform = True
        elif el_type == 'stop':
            multiple_check = self.seen_stop
            self.seen_stop = True
        if multiple_check:
            city.error_if(
                el_type == 'stop',
                'Multiple {}s for a station "{}" ({}) in a route relation'.format(
                    el_type, el['tags'].get('name', ''), el_id(el)), relation)

    def __repr__(self):
        return 'RouteStop(stop={}, pl_entry={}, pl_exit={}, stoparea={})'.format(
            self.stop, self.platform_entry, self.platform_exit, self.stoparea)


class Route:
    """The longest route for a city with a unique ref."""
    @staticmethod
    def is_route(el, modes=DEFAULT_MODES):
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

    def build_longest_line(self, relation, city):
        line_nodes = set()
        last_track = []
        track = []
        warned_about_holes = False
        for m in relation['members']:
            el = city.elements.get(el_id(m), None)
            if not el or not StopArea.is_track(el):
                continue
            if 'nodes' not in el or len(el['nodes']) < 2:
                city.error('Cannot find nodes in a railway', el)
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
                        city.warn('Hole in route rails near node {}'.format(
                            new_segment[0]), relation)
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

    def project_stops_on_line(self, city):
        projected = [project_on_line(x.stop, self.tracks) for x in self.stops]
        start = 0
        while start < len(self.stops) and distance(
                self.stops[start].stop, projected[start]) > MAX_DISTANCE_STOP_TO_LINE:
            start += 1
        end = len(self.stops) - 1
        while end > start and distance(
                self.stops[end].stop, projected[end]) > MAX_DISTANCE_STOP_TO_LINE:
            end -= 1
        tracks_start = []
        tracks_end = []
        for i in range(len(self.stops)):
            if i < start:
                tracks_start.append(self.stops[i].stop)
            elif i > end:
                tracks_end.append(self.stops[i].stop)
            elif projected[i] == NOWHERE_STOP:
                city.error('Stop "{}" {} is nowhere near the tracks'.format(
                    self.stops[i].stoparea.name, self.stops[i].stop), self.element)
            else:
                # We've got two separate stations with a good stretch of
                # railway tracks between them. Put these on tracks.
                d = round(distance(self.stops[i].stop, projected[i]))
                if d > MAX_DISTANCE_STOP_TO_LINE:
                    city.warn('Stop "{}" {} is {} meters from the tracks'.format(
                        self.stops[i].stoparea.name, self.stops[i].stop, d), self.element)
                else:
                    self.stops[i].stop = projected[i]
        if start >= len(self.stops):
            self.tracks = tracks_start
        elif tracks_start or tracks_end:
            self.tracks = tracks_start + self.tracks + tracks_end

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
        self.element = relation
        self.id = el_id(relation)
        if 'ref' not in relation['tags'] and 'ref' not in master_tags:
            city.warn('Missing ref on a route', relation)
        self.ref = relation['tags'].get('ref', master_tags.get(
            'ref', relation['tags'].get('name', None)))
        self.name = relation['tags'].get('name', None)
        if 'colour' not in relation['tags'] and 'colour' not in master_tags:
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
        self.mode = relation['tags']['route']
        self.interval = Route.get_interval(relation['tags']) or Route.get_interval(master_tags)
        if relation['tags'].get('public_transport:version') == '1':
            city.error('Public transport version is 1, which means the route '
                       'is an unsorted pile of objects', relation)
        self.is_circular = False
        # self.tracks would be a list of (lon, lat) for the longest stretch. Can be empty
        tracks, line_nodes = self.build_longest_line(relation, city)
        self.tracks = [el_center(city.elements.get(k)) for k in tracks]
        if None in self.tracks:
            self.tracks = []  # this should not happen
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
            k = el_id(m)
            if k in city.stations:
                st_list = city.stations[k]
                st = st_list[0]
                if len(st_list) > 1:
                    city.error('Ambigous station {} in route. Please use stop_position or split '
                               'interchange stations'.format(st.name), relation)
                    # city.error(', '.join([x.id for x in st_list]))
                el = city.elements[k]
                el_type = RouteStop.get_member_type(el, m['role'], city.modes)
                if el_type:
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
                                    (el_type == 'stop' and not seen_platforms) or
                                    (el_type == 'platform' and not seen_stops)):
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
                        if (el_type == 'stop' and seen_stops) or (
                                el_type == 'platform' and seen_platforms):
                            city.error('Found an out-of-place {}: "{}" ({})'.format(
                                el_type, el['tags'].get('name', ''), k), relation)
                            continue
                        # Find the matching stop starting with index repeat_pos
                        while (repeat_pos < len(self.stops) and
                               self.stops[repeat_pos].stoparea.id != st.id):
                            repeat_pos += 1
                        if repeat_pos >= len(self.stops):
                            city.error('Incorrect order of {}s at {}'.format(el_type, k),
                                       relation)
                            continue
                        stop = self.stops[repeat_pos]

                    stop.add(m, relation, city)
                    if repeat_pos is None:
                        seen_stops |= stop.seen_stop or stop.seen_station
                        seen_platforms |= stop.seen_platform

                    if check_stop_positions and StopArea.is_stop(el):
                        if k not in line_nodes:
                            city.error('Stop position "{}" ({}) is not on tracks'.format(
                                el['tags'].get('name', ''), k), relation)
                    continue

            if k not in city.elements:
                if 'stop' in m['role'] or 'platform' in m['role']:
                    city.error('{} {} {} for route relation is not in the dataset'.format(
                        m['role'], m['type'], m['ref']), relation)
                    raise Exception('Stop or platform {} {} in relation {} '
                                    'is not in the dataset for {}'.format(
                                        m['type'], m['ref'], relation['id'], city.name))
                continue
            el = city.elements[k]
            if 'tags' not in el:
                city.error('Untagged object in a route', relation)
                continue
            if 'stop' in m['role'] or 'platform' in m['role']:
                for k in CONSTRUCTION_KEYS:
                    if k in el['tags']:
                        city.error('An under construction {} in route'.format(m['role']), el)
                        continue
                if el['tags'].get('railway') in ('station', 'halt'):
                    city.error('Missing station={} on a {}'.format(self.mode, m['role']), el)
                else:
                    city.error('{} {} {} is not connected to a station in route'.format(
                        m['role'], m['type'], m['ref']), relation)
        if not self.stops:
            city.error('Route has no stops', relation)
        elif len(self.stops) == 1:
            city.error('Route has only one stop', relation)
        else:
            self.is_circular = self.stops[0].stoparea == self.stops[-1].stoparea
            self.project_stops_on_line(city)
            for si in range(len(self.stops)-2):
                angle = angle_between(self.stops[si].stop,
                                      self.stops[si+1].stop,
                                      self.stops[si+2].stop)
                if angle < MIN_ANGLE_BETWEEN_STOPS:
                    msg = 'Angle between stops around "{}" is too narrow, {} degrees'.format(
                        self.stops[si+1].stoparea.name, angle)
                    city.error_if(angle < 20, msg, relation)
            proj1 = find_segment(self.stops[1].stop, self.tracks)
            proj2 = find_segment(self.stops[min(len(self.stops)-1, 3)].stop, self.tracks)
            if proj1[0] and proj2[0] and (proj1[0] > proj2[0] or
                                          (proj1[0] == proj2[0] and proj1[1] > proj2[1])):
                city.warn('Tracks seem to go in the opposite direction to stops', relation)
                self.tracks.reverse()
            self.calculate_distances()

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
    def __init__(self, row):
        self.name = row[1]
        self.country = row[2]
        self.continent = row[3]
        if not row[0]:
            self.error('City {} does not have an id'.format(self.name))
        self.id = int(row[0] or '0')
        self.num_stations = int(row[4])
        self.num_lines = int(row[5] or '0')
        self.num_light_lines = int(row[6] or '0')
        self.num_interchanges = int(row[7] or '0')

        # Aquiring list of networks and modes
        networks = None if len(row) <= 9 else row[9].split(':')
        if not networks or len(networks[-1]) == 0:
            self.networks = []
        else:
            self.networks = set(filter(None, [x.strip() for x in networks[-1].split(';')]))
        if not networks or len(networks) < 2 or len(networks[0]) == 0:
            self.modes = DEFAULT_MODES
        else:
            self.modes = set([x.strip() for x in networks[0].split(',')])

        # Reversing bbox so it is (xmin, ymin, xmax, ymax)
        bbox = row[8].split(',')
        if len(bbox) == 4:
            self.bbox = [float(bbox[i]) for i in (1, 0, 3, 2)]
        else:
            self.bbox = None

        self.elements = {}   # Dict el_id → el
        self.stations = defaultdict(list)   # Dict el_id → list of stop areas
        self.routes = {}     # Dict route_ref → route
        self.masters = {}    # Dict el_id of route → route_master
        self.stop_areas = defaultdict(list)  # El_id → list of el_id of stop_area
        self.transfers = []  # List of lists of stop areas
        self.station_ids = set()  # Set of stations' uid
        self.stops_and_platforms = set()  # Set of stops and platforms el_id
        self.errors = []
        self.warnings = []

    def contains(self, el):
        center = el_center(el)
        if center:
            return (self.bbox[0] <= center[1] <= self.bbox[2] and
                    self.bbox[1] <= center[0] <= self.bbox[3])
        if 'tags' not in el:
            return False
        return 'route_master' in el['tags'] or 'public_transport' in el['tags']

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
                    stop_area = self.stop_areas[el_id(m)]
                    if el in stop_area:
                        if not warned_about_duplicates:
                            self.warn('Duplicate element in a stop area', el)
                            warned_about_duplicates = True
                    else:
                        stop_area.append(el)

    def get_validation_result(self):
        result = {
            'name': self.name,
            'country': self.country,
            'continent': self.continent,
            'stations_expected': self.num_stations,
            'subwayl_expected': self.num_lines,
            'lightrl_expected': self.num_light_lines,
            'transfers_expected': self.num_interchanges,
            'stations_found': self.found_stations,
            'subwayl_found': self.found_lines,
            'lightrl_found': self.found_light_lines,
            'transfers_found': self.found_interchanges,
            'unused_entrances': self.unused_entrances,
            'networks': self.found_networks,
        }
        result['warnings'] = self.warnings
        result['errors'] = self.errors
        return result

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

    def make_transfer(self, sag):
        transfer = set()
        for m in sag['members']:
            k = el_id(m)
            if k in self.stations:
                stoparea = self.stations[k][0]
                transfer.add(stoparea)
                if stoparea.transfer:
                    self.error('Stop area {} belongs to multiple interchanges'.format(k))
                stoparea.transfer = el_id(sag)
        if len(transfer) > 1:
            self.transfers.append(transfer)

    def is_good(self):
        return len(self.errors) == 0

    def extract_routes(self):
        # Extract stations
        processed_stop_areas = set()
        for el in self.elements.values():
            if Station.is_station(el, self.modes):
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
            self.error('Found {} entrances not used in routes or stop_areas: {}'.format(
                len(unused), format_elid_list(unused)))
        if not_in_sa:
            self.warn('{} subway entrances are not in stop_area relations'.format(len(not_in_sa)))

    def check_return_routes(self, rmaster):
        variants = {}
        have_return = set()
        for variant in rmaster:
            if len(variant) < 2:
                continue
            # Using transfer ids because a train can arrive at different stations within a transfer
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

    def validate(self):
        networks = Counter()
        unused_stations = set(self.station_ids)
        for rmaster in self.routes.values():
            networks[str(rmaster.network)] += 1
            self.check_return_routes(rmaster)
            for route in rmaster:
                for st in route.stops:
                    unused_stations.discard(st.stoparea.station.id)
        if unused_stations:
            self.unused_stations = len(unused_stations)
            self.warn('{} unused stations: {}'.format(
                self.unused_stations, format_elid_list(unused_stations)))
        self.count_unused_entrances()

        self.found_light_lines = len([x for x in self.routes.values() if x.mode != 'subway'])
        self.found_lines = len(self.routes) - self.found_light_lines
        if self.found_lines != self.num_lines:
            self.error('Found {} subway lines, expected {}'.format(
                self.found_lines, self.num_lines))
        if self.found_light_lines != self.num_light_lines:
            self.error('Found {} light rail lines, expected {}'.format(
                self.found_light_lines, self.num_light_lines))

        self.found_stations = len(self.station_ids) - len(unused_stations)
        if self.found_stations != self.num_stations:
            msg = 'Found {} stations in routes, expected {}'.format(
                self.found_stations, self.num_stations)
            self.error_if(not (0 <= (self.num_stations - self.found_stations) / self.num_stations <=
                               ALLOWED_STATIONS_MISMATCH), msg)

        self.found_interchanges = len(self.transfers)
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
    global transfers
    transfers = []
    stop_area_groups = []
    for el in elements:
        if (el['type'] == 'relation' and 'members' in el and
                el.get('tags', {}).get('public_transport') == 'stop_area_group'):
            stop_area_groups.append(el)

    stations = defaultdict(set)  # el_id -> list of station objects
    for city in cities:
        for el, st in city.stations.items():
            stations[el].update(st)

    for sag in stop_area_groups:
        transfer = set()
        for m in sag['members']:
            k = el_id(m)
            if k not in stations:
                continue
            transfer.update(stations[k])
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


def download_cities():
    url = 'https://docs.google.com/spreadsheets/d/{}/export?format=csv'.format(SPREADSHEET_ID)
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
            cities.append(City(row))
            if row[0].strip() in names:
                logging.warning('Duplicate city name in the google spreadsheet: %s', row[0])
            names.add(row[0].strip())
    return cities
