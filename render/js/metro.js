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

// Array of slugified city names
var cityNames = [];

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
                    var lastCommaIndex = cities[i].lastIndexOf(',');
                    var cityName = cities[i].substring(0, lastCommaIndex);
                    cityName = slugify(cityName);
                    content += '<option value="' + cityName + '">' + cities[i] + '</option>';
                    cityNames.push(cityName);
                }

                that.select.innerHTML = content;

                var hash = window.location.hash;
                if (hash && hash[0] === '#')
                    hash = hash.substring(1);
                var cityName = decodeURI(hash);
                if (cityName)
                    chooseCity(cityName);
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
    chooseCity(e.cityName);
});


function chooseCity(cityName)
{
    var index = cityNames.indexOf(cityName);
    if (index === -1) {
        setCityLayer(null);
        window.location.hash = '';
        selector.select.selectedIndex = 0;
        return;
    }
     
    // The function may be triggered by city name in URL hash on page load or by
    // city selection by user. We need synchronize URL hash and selected option.
    window.location.hash = cityName;
    selector.select.value = cityName;

    if (hint !== null) {
        map.removeLayer(hint);
        hint = null;
    }

    ajax(cityName + '.geojson',
        function (responseText) {
            var json = JSON.parse(responseText);
            var cityLayer = L.geoJSON(json, {
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

            setCityLayer(cityLayer);
         },
         function (statusText, status) {
            alert("Cannot fetch city data for " + cityName + ".\nError code: " + status);
         }
    );
}

function setCityLayer(cityLayer) {
    if (map.cityLayer) {
        map.removeLayer(map.cityLayer);
    }
    if (cityLayer) {
        map.addLayer(cityLayer);
        map.fitBounds(cityLayer.getBounds());
    }
    map.cityLayer = cityLayer;
}
