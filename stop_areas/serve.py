#!/usr/bin/env python3
from flask import Flask, request, make_response, render_template
from make_stop_areas import add_stop_areas, overpass_request

app = Flask(__name__)
app.debug = True


@app.route('/')
def form():
    return render_template('index.html')


@app.route('/process', methods=['GET'])
def convert():
    src = overpass_request(request.args.get('bbox'))
    if not src:
        return 'No data from overpass, sorry.'
    result = add_stop_areas(src)
    response = make_response(result)
    response.headers['Content-Disposition'] = 'attachment; filename="stop_areas.osm"'
    return response

if __name__ == '__main__':
    app.run()
