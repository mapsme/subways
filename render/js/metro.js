const OSM_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const OSM_ATTRIB = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

var osm_layer = L.tileLayer(OSM_URL, {
    maxZoom: 18,
    attribution: OSM_ATTRIB,
    opacity: 0.5
});

var initialLocation = [55.7510888, 37.7642849];

var map = L.map('map').setView(initialLocation, 15).addLayer(osm_layer);

L.marker(initialLocation)
.addTo(map)
.bindPopup('Choose a city from the list at the top-right corner!')
.openPopup();


function slugify(name) {
    name = name.toLowerCase();
    name = name.replace(/ /g, '_');
    name = name.replace(/[^a-z0-9_-]+/g, '');
    return name;
}

// Inspired by http://ahalota.github.io/Leaflet.CountrySelect
L.CitySelect = L.Control.extend({
    options: {
        position: 'topright',
        title: 'City'
    },
    onAdd: function(map) {
        this.div = L.DomUtil.create('div');
        this.select = L.DomUtil.create('select', 'leaflet-countryselect', this.div);
        var that = this;

        var xhr = new XHR({
            method: 'get',
            url: 'cities.txt?',
            async: true,
            data: {},
            serialize: false,
            success: function (status, responseText, responseXML, statusText) {
                if (status == 200 && responseText) {
                    var cities = responseText.split("\n");
                    cities = cities.filter(city => city.length).sort();
                    
                    var content = '';

                    if (that.options.title.length > 0) {
                        content += '<option>' + that.options.title + '</option>';
                    }

                    for (var i = 0; i < cities.length; ++i){
                        city_name = cities[i].split(',')[0];
                        content += '<option value="' + city_name+ '">' + cities[i] + '</option>';
                    }
                    
                    that.select.innerHTML = content;
                }
            },
            error: function (status, responseText, responseXML, statusText) {
                console.log('Request was unsuccessful: ' + status + ', ' + statusText);
            }
        });

        this.select.onmousedown = L.DomEvent.stopPropagation;
        return this.div;
    },
    on: function(type, handler) {
        if (type == 'change') {
            this.onChange = handler;
            L.DomEvent.addListener(this.select, 'change', this._onChange, this);
        } else {
            console.log('CitySelect - cannot handle ' + type + ' events.')
        }
    },
    _onChange: function(e) {
        var selectedCity = this.select.options[this.select.selectedIndex].value;
        e.cityName = selectedCity;
        this.onChange(e);
    }
});


L.citySelect = function(id, options) {
    return new L.CitySelect(id, options);
};


var selector = L.citySelect({position: 'topright'}).addTo(map);
selector.on('change', function(e) {
    if (e.cityName === 'City')
        return;

    var cityName = slugify(e.cityName);

    var xhr = new XHR({
        method: 'get',
        url: cityName + '.geojson?',
        async: true,
        responseType: 'json',
        data: {},
        serialize: false,
        success: function (status, responseText, responseXML, statusText) {
            if (status == 200 && responseText) {

                var json = JSON.parse(responseText);
                var newCity = L.geoJSON(json, {
                    style: function(feature) {
                        if ('stroke' in feature.properties)
                            return {color: feature.properties.stroke};
                    },
                    pointToLayer: function (feature, latlng) {
                        return L.circleMarker(latlng, {
                             color: feature.properties['marker-color'],
                             //line-width: 1,
                             //weight: 1,
                             radius: 4
                        });
                    }
                });

                if (map.previousCity != null) {
                    map.removeLayer(map.previousCity);
                }
                map.previousCity = newCity;

                map.addLayer(newCity);
                map.fitBounds(newCity.getBounds());

            }

        },
        error: function (status, responseText, responseXML, statusText) {
            console.log('Request was unsuccessful: ' + status + ', ' + statusText);
        }
    });
});
