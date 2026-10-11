# -*- coding: utf-8 -*-
# (c) M-IT Services. Gebruik alleen volgens de licentievoorwaarden.
import http.client
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from . import GRAPH_BASIS, TIJD_GRAPH_S
METHODES = ('GET', 'POST', 'PATCH')
VERBODEN_IN_PAD = re.compile('/(?:microsoft\\.graph\\.)?(send|sendMail|reply|replyAll|forward|accept|decline|tentativelyAccept|permanentDelete|delete|snoozeReminder|dismissReminder)(\\b|/|$)', re.I)
NETWERKFOUTEN = (urllib.error.URLError, OSError, http.client.HTTPException, ValueError)

class TransportGeweigerd(Exception):
    pass

class GeenVerbinding(Exception):
    pass

class _GeenOmleiding(urllib.request.HTTPRedirectHandler):

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def opener(context=None):
    return urllib.request.build_opener(_GeenOmleiding(), urllib.request.HTTPSHandler(context=context or ssl.create_default_context()))

def verzoek(url, methode, kop, body=None):
    req = urllib.request.Request(url, data=body, method=methode)
    for naam, waarde in kop.items():
        if naam.lower() == 'authorization':
            req.add_unredirected_header(naam, waarde)
        else:
            req.add_header(naam, waarde)
    return req

def antwoord(open_, req, tijd, max_bytes=None):
    try:
        r = open_.open(req, timeout=tijd)
        status, koppen = (r.status, r.headers)
    except urllib.error.HTTPError as e:
        r, status, koppen = (e, e.code, e.headers)
    try:
        data = r.read(max_bytes + 1) if max_bytes is not None else r.read()
    finally:
        r.close()
    return (status, dict(koppen.items()) if koppen is not None else {}, data or b'')

def kop(koppen, naam):
    for k, v in koppen.items():
        if k.lower() == naam.lower():
            return v
    return None

class Transport:

    def __init__(self, open_=None, basis=GRAPH_BASIS):
        self._open = open_ or opener()
        d = urllib.parse.urlsplit(basis)
        self._basis, self._host, self._pad = (basis, d.hostname, d.path)

    def toets(self, methode, url):
        if methode not in METHODES:
            raise TransportGeweigerd(f'methode {methode}')
        if not isinstance(url, str) or not url.startswith(self._basis) or any((c in url for c in ' \t\r\n\\')):
            raise TransportGeweigerd('alleen Microsoft Graph v1.0')
        d = urllib.parse.urlsplit(url)
        if d.scheme != 'https' or d.hostname != self._host or d.port is not None or d.username or d.password or d.fragment or (not d.path.startswith(self._pad)):
            raise TransportGeweigerd('alleen Microsoft Graph v1.0')
        delen = [urllib.parse.unquote(deel) for deel in d.path.split('/')]
        if any((deel in ('.', '..') for deel in delen)):
            raise TransportGeweigerd('pad met . of ..')
        if VERBODEN_IN_PAD.search(d.path) or VERBODEN_IN_PAD.search(urllib.parse.unquote(d.path)):
            raise TransportGeweigerd('versturen of verwijderen')
        if any((deel.startswith('$') and (methode != 'GET' or deel.lower() == '$batch') for deel in delen)):
            raise TransportGeweigerd('batch of $-segment')

    def verzend(self, methode, url, kop, body):
        self.toets(methode, url)
        try:
            status, koppen, data = antwoord(self._open, verzoek(url, methode, kop, body), TIJD_GRAPH_S)
        except NETWERKFOUTEN as e:
            raise GeenVerbinding(type(e).__name__) from None
        if 300 <= status < 400:
            raise TransportGeweigerd('omleiding')
        return (status, koppen, data)
