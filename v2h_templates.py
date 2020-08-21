# These are templates for validation_to_html.py
# Variables should be in curly braces

STYLE = '''
<style>
body {
  font-family: sans-serif;
  font-size: 12pt;
}
th {
  font-size: 10pt;
}
.errors {
  font-size: 10pt;
  color: darkred;
  margin-bottom: 1em;
}
.warnings {
  font-size: 10pt;
  color: darkblue;
  margin-bottom: 1em;
}
.bold {
  font-weight: bold;
}
.color0 {
  background: pink;
}
.color1 {
  background: lightgreen;
}
.hlink {
  color: #888;
  opacity: 0.5;
}
table {
    max-width: 900px;
}
tr:hover td:nth-child(n+2) {
    background: lightblue;
}
</style>
'''

INDEX_HEADER = '''
<!doctype html>
<html>
<head>
<title>Subway Validator</title>
<meta charset="utf-8">
(s)
</head>
<body>
<h1>Subway Validation Results</h1>
<p>Total good metro networks: {good_cities} of {total_cities}.</p>
<p><a href="render.html">View on the map</a></p>
<table cellspacing="3" cellpadding="2" style="margin-bottom: 1em;">
'''.replace('(s)', STYLE)

INDEX_CONTINENT = '''
<tr><td colspan="9">&nbsp;</td></tr>
<tr>
<th>Continent</th>
<th>Country</th>
<th>Good Cities</th>
<th>Subway Lines</th>
<th>Light Rail Lines</th>
<th>Stations</th>
<th>Interchanges</th>
<th>Errors</th>
<th>Warnings</th>
</tr>
<tr>
<td colspan="2" class="bold color{=cities}">{continent}</td>
<td class="color{=cities}">{good_cities} / {total_cities}</td>
<td class="color{=subwayl}">{subwayl_found} / {subwayl_expected}</td>
<td class="color{=lightrl}">{lightrl_found} / {lightrl_expected}</td>
<td class="color{=stations}">{stations_found} / {stations_expected}</td>
<td class="color{=transfers}">{transfers_found} / {transfers_expected}</td>
<td class="color{=errors}">{num_errors}</td>
<td class="color{=warnings}">{num_warnings}</td>
</tr>
{content}
'''

INDEX_COUNTRY = '''
<tr>
<td>&nbsp;</td>
<td class="bold color{=cities}"><a href="{file}">{country}</a></td>
<td class="color{=cities}">{good_cities} / {total_cities}</td>
<td class="color{=subwayl}">{subwayl_found} / {subwayl_expected}</td>
<td class="color{=lightrl}">{lightrl_found} / {lightrl_expected}</td>
<td class="color{=stations}">{stations_found} / {stations_expected}</td>
<td class="color{=transfers}">{transfers_found} / {transfers_expected}</td>
<td class="color{=errors}">{num_errors}</td>
<td class="color{=warnings}">{num_warnings}</td>
</tr>
'''

INDEX_FOOTER = '''
</table>
<p>Produced by <a href="https://github.com/mapsme/subways">Subway Preprocessor</a> on {date}.
See <a href="{google}">this spreadsheet</a> for the reference metro statistics and
<a href="https://en.wikipedia.org/wiki/List_of_metro_systems#List">this wiki page</a> for a list
of all metro systems.</p>
</body>
</html>
'''

COUNTRY_HEADER = '''
<!doctype html>
<html>
<head>
<title>Subway Validator: {country}</title>
<meta charset="utf-8">
(s)
</head>
<body>
<h1>Subway Validation Results for {country}</h1>
<p><a href="index.html">Return to the countries list</a>.</p>
<table cellspacing="3" cellpadding="2">
<tr>
<th>City</th>
{?subways}
<th>Subway Lines</th>
<th>Light Rail Lines</th>
{end}{?overground}
<th>Tram Lines</th>
<th>Bus Lines</th>
<th>T-Bus Lines</th>
<th>Other Lines</th>
{end}
<th>Stations</th>
<th>Interchanges</th>
<th>Unused Entrances</th>
</tr>
'''.replace('(s)', STYLE)

COUNTRY_CITY = '''
<tr id="{slug}">
<td class="bold color{good_cities}">
  {city}
  {?yaml}<a href="{yaml}" class="hlink" title="Download YAML">Y</a>{end}
  {?json}<a href="{json}" class="hlink" title="Download GeoJSON">J</a>{end}
  {?json}<a href="render.html#{slug}" class="hlink" title="View map" target="_blank">M</a>{end}
</td>
{?subways}
<td class="color{=subwayl}">sub: {subwayl_found} / {subwayl_expected}</td>
<td class="color{=lightrl}">lr: {lightrl_found} / {lightrl_expected}</td>
{end}{?overground}
<td class="color{=traml}">t: {traml_found} / {traml_expected}</td>
<td class="color{=busl}">b: {busl_found} / {busl_expected}</td>
<td class="color{=trolleybusl}">tb: {trolleybusl_found} / {trolleybusl_expected}</td>
<td class="color{=otherl}">o: {otherl_found} / {otherl_expected}</td>
{end}
<td class="color{=stations}">st: {stations_found} / {stations_expected}</td>
<td class="color{=transfers}">int: {transfers_found} / {transfers_expected}</td>
<td class="color{=entrances}">e: {unused_entrances}</td>
</tr>
<tr><td colspan="{?subways}6{end}{?overground}8{end}">
<div class="errors">
{errors}
</div><div class="warnings">
{warnings}
</div>
</td></tr>
'''

COUNTRY_FOOTER = '''
</table>
<p>Produced by <a href="https://github.com/mapsme/subways">Subway Preprocessor</a> on {date}.</p>
</body>
</html>
'''
