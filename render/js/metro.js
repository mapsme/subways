function slugify(name) {
    return name.toLowerCase()
                .replace(/ /g, '_')
                .replace(/[^a-z0-9_-]+/g, '');
}

function ajax(url, onSuccess, onError) {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', url);
    xhr.onload = function(e) {
        var responseText = e.target.responseText;
        if (xhr.status === 200) {
            onSuccess(responseText);
        } else if (onError) {
            onError(responseText, xhr.status);
        }
    };
    xhr.send();
}


var OSM_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
var OSM_ATTRIB = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

var osm_layer = L.tileLayer(OSM_URL, {
    maxZoom: 18,
    attribution: OSM_ATTRIB,
    opacity: 0.5
});

var initialLocation = [55.7510888, 37.7642849];

var map = L.map('map').setView(initialLocation, 15).addLayer(osm_layer);

var hint = L.marker(initialLocation, {opacity: 0})
 .addTo(map)
 .bindPopup('Choose a city from the list at the top-right corner!')
 .openPopup();


// Inspired by http://ahalota.github.io/Leaflet.CountrySelect
L.CitySelect = L.Control.extend({
    options: {
        position: 'topright',
        title: 'City'
    },
    onAdd: function(map) {
        this.div = L.DomUtil.create('div');
        this.select = L.DomUtil.create('select', 'leaflet-countryselect', this.div);
        this.select.onmousedown = L.DomEvent.stopPropagation;
        var that = this;

        ajax('cities.txt',
             function(responseText) {
                var cities = responseText.split("\n");
                cities = cities.filter(function(str) {
                                           return str.length > 0;
                                      })
                               .sort();

                var content = '';
                var title = that.options.title;

                if (title && title.length) {
                    content += '<option>' + title + '</option>';
                }

                for (var i = 0; i < cities.length; i++) {
                    // Remove country name which follows last comma and doesn't contain commas itself
                    var last_comma_index = cities[i].lastIndexOf(',');
                    var city_name = cities[i].substring(0, last_comma_index);
                    content += '<option value="' + city_name + '">' + cities[i] + '</option>';
                }

                that.select.innerHTML = content;
             }
        );

        return this.div;
    },
    on: function(type, handler) {
        if (type === 'change') {
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
    if (e.cityName === selector.options.title)
        return;

    if (hint !== null) {
        map.removeLayer(hint);
        hint = null;
    }

    var cityName = e.cityName;

    ajax(slugify(cityName) + '.geojson',
         function (responseText) {
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

            if (map.previousCity !== undefined) {
                map.removeLayer(map.previousCity);
            }
            map.previousCity = newCity;

            map.addLayer(newCity);
            map.fitBounds(newCity.getBounds());
         },
         function (statusText, status) {
            alert("Cannot fetch city data for " + cityName + ".\nError code: " + status);
         }
    );
});
