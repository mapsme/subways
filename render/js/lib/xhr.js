/**
 * XHR.js - A vanilla javascript wrapper for the XMLHttpRequest object.
 * @version 0.1.1
 * @author George Raptis (https://github.com/georapbox)
 *
 * The MIT License (MIT)
 *
 * Copyright (c) 2014 George Raptis
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */
(function (name, context, definition) {
	if (typeof module !== 'undefined' && module.exports) {
        module.exports = definition();
	} else if (typeof define === 'function' && define.amd) {
		define(definition);
	} else {
		context[name] = definition();
	}
}('XHR', this, function () {
	var helpers = {
		extend: function() {
			'use strict';
			for (var i = 1, l = arguments.length; i < l; i += 1) {
				for (var key in arguments[i]) {
					if (arguments[i].hasOwnProperty(key)) {
						if (arguments[i][key] && arguments[i][key].constructor && arguments[i][key].constructor === Object) {
							arguments[0][key] = arguments[0][key] || {};
							helpers.extend(arguments[0][key], arguments[i][key]);
						} else {
							arguments[0][key] = arguments[i][key];
						}
					}
				}
			}
			return arguments[0];
		},

		encodeUrl: function (url) {
			var domain = url.substring(0, url.indexOf('?') + 1),
				search = url.substring(url.indexOf('?') + 1),
				vars = search ? search.split('&') : [],
				varsLen = vars.length,
				encodedUrl = domain,
				pair,
				i;

			for (i = 0; i < varsLen; i += 1) {
				pair = vars[i].split('=');
				encodedUrl += encodeURIComponent(pair[0]) + '=' + encodeURIComponent(pair[1]) + '&';
			}

			encodedUrl = encodedUrl.substring(0, encodedUrl.length - 1);
			return encodedUrl;
		},

		serialize: function (form) {
			var parts = [],
				field = null,
				i,
				len,
				j,
				optLen,
				option,
				optValue;

			for (i = 0, len = form.elements.length; i < len; i += 1) {
				field = form.elements[i];

				switch (field.type) {
					case 'select-one':
					case 'select-multiple':
						if (field.name.length) {
							for (j = 0, optLen = field.options.length; j < optLen; j += 1) {
								option = field.options[j];

								if (option.selected) {
									optValue = '';

									if (option.hasAttribute) {
										optValue = (option.hasAttribute('value') ? option.value : option.text);
									} else {
										optValue = (option.attributes.value.specified ? option.value : option.text);
									}

									parts.push(encodeURIComponent(field.name) + '=' + encodeURIComponent(optValue));
								}
							}
						}
					break;
					case undefined:    // fieldset
					case 'file':       // file input
					case 'submit':     // submit button
					case 'reset':      // reset button
					case 'button':     // custom button
					break;
					case 'radio':      // radio button
					case 'checkbox':   // checkbox
						if (!field.checked) {
							break;
						}
						/* falls through */
					default:
						// Don't include form fields without names.
						if (field.name.length) {
							parts.push(encodeURIComponent(field.name) + '=' + encodeURIComponent(field.value));
						}
				}
			}
			return parts.join('&');
		}
	};

	var XHR = function (options) {
		var that = this,
			defaults,
			xhr,
			i,
			customHeadersLen,
			customHeadersItem;

		// Define default options.
		defaults = {
			method: 'get',                                       // Type of request.
			url: '',                                             // Request url (relative path).
			async: true,                                         // Defines if request is asynchronous or not.
			serialize: false,                                    // Defines if forms data sent in a POST request should be serialized.
			data: null,                                          // Data to be sent as the body of the request. Default is "null" for browser compatibility issues.
			contentType: 'application/x-www-form-urlencoded',    // Sets the Content Type of the request.
			responseType: 'xml',
			customHeaders: [],                                   // Set custom request headers. Default value is empty array.
			success: function () {},                             // Callback function to handle success.
			error: function () {}                                // Callback function to handle errors.
		};

		// Extend the default options with user's specified ones.
		options = helpers.extend({}, defaults, options);

		that.method = options.method;
		that.url = options.url;
		that.async = options.async;
		that.serialize = options.serialize;
		that.data = options.data;
		that.contentType = options.contentType;
		that.responseType = options.responseType;
		that.customHeaders = options.customHeaders;
		that.success = options.success;
		that.error = options.error;
		that.progressEvent = {};

		customHeadersLen = that.customHeaders.length;

		// Create a new XMLHttpRequest.
		xhr = new XMLHttpRequest();

		// onreadystatechange event
		xhr.onreadystatechange = function () {
			// if request is completed, handle success or error states.
			if (xhr.readyState === 4) {
				if (xhr.status >= 200 && xhr.status < 300 || xhr.status === 304) {
					that.success(xhr.status, xhr.responseText, xhr.responseXML, xhr.statusText);
				} else {
					that.error(xhr.status, xhr.responseText, xhr.responseXML, xhr.statusText);
				}
			}
		};

		// onprogress event
		xhr.onprogress = function (event) {
			if (event.lengthComputable){
				that.progressEvent = {
					bubbles: event.bubbles,
					cancelable: event.cancelable,
					currentTarget: event.currentTarget,
					defaultPrevented: event.defaultPrevented,
					eventPhase: event.eventPhase,
					explicitOriginalTarget: event.explicitOriginalTarget,
					isTrusted: event.isTrusted,
					lengthComputable: event.lengthComputable,
					loaded: event.loaded,
					originalTarget: event.originalTarget,
					target: event.target,
					timeStamp: event.timeStamp,
					total: event.total,
					type: event.type
				};

				return that.progressEvent;
			}
		};

		// Encode URL in case of a "GET" request.
		if (that.method === 'get') {
			that.url = helpers.encodeUrl(that.url);
		}

		// Prepare the request to be sent.
		xhr.open(that.method, that.url, that.async);

		// Set "Content-Type".
		if (that.contentType !== false) {
			xhr.setRequestHeader('Content-Type', that.contentType);
		}

        // Set custom headers.
		if (customHeadersLen > 0) {
			for (i = 0; i < customHeadersLen; i += 1) {
				customHeadersItem = that.customHeaders[i];

				if (typeof customHeadersItem === 'object') {
					for (var prop in customHeadersItem) {
						if (customHeadersItem.hasOwnProperty(prop)) {
							xhr.setRequestHeader(prop, customHeadersItem[prop]);
						}
					}
				} else {
					throw new Error('Property "customHeader" expects an array of objects for value.');
				}
			}
		}

        // Serialize form if option set to "true".
		if (that.serialize === true) {
			that.data = helpers.serialize(that.data);
		}

		// Send data.
		xhr.send(that.data);

		return that;
	};

	return XHR;
}));
