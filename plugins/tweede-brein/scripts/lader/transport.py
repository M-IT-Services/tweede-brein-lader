# -*- coding: utf-8 -*-
# (c) M-IT Services. Gebruik alleen volgens de licentievoorwaarden.
import http.client
import json
import re
import socket
import ssl
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from . import BESTANDHOST, GRAPH_BASIS, LADER_VERSIE, MAX_BESTAND, MAX_GRAPH, TIJD_BESTAND_MAX_S, TIJD_GRAPH_S
METHODES = ('GET', 'POST', 'PATCH', 'PUT')
VERBODEN_ACTIES = frozenset({'send', 'sendmail', 'reply', 'replyall', 'forward', 'accept', 'decline', 'tentativelyaccept', 'permanentdelete', 'delete', 'softdelete', 'undosoftdelete', 'snoozereminder', 'dismissreminder', 'invite', 'createlink', 'grant', 'copy', 'setreaction', 'unsetreaction', 'sendactivitynotification', 'restore', 'restoreversion', 'checkin', 'checkout', 'discardcheckout', 'preview'})
KLIK_SEGMENTEN = frozenset({'drive', 'drives', 'driveitem', 'sites', 'shares', 'workbook'})
SCHRIJF_VERBODEN = frozenset({'chats', 'chat', 'teams', 'team', 'channels', 'joinedteams', 'teamwork', 'permissions', 'calendarpermissions', 'mailboxsettings', 'messagerules', 'subscriptions', 'invitations', 'conversations', 'threads', 'posts', 'createuploadsession', 'groups'})
PATCH_VERBODEN = frozenset({'drive', 'drives', 'shares', 'driveitem', 'listitem', 'sites'})
CONFLICT_FAIL = [('@microsoft.graph.conflictBehavior', 'fail')]
NETWERKFOUTEN = (urllib.error.URLError, OSError, http.client.HTTPException, ValueError)
RESETFOUTEN = (ConnectionResetError, ConnectionAbortedError, ssl.SSLError, http.client.IncompleteRead)
_FUNCTIE = re.compile('[\\w.]+\\(.*\\)')

class TransportGeweigerd(Exception):
    pass

class TeGroot(TransportGeweigerd):
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

def _open(open_, req, tijd):
    try:
        r = open_.open(req, timeout=tijd)
        return (r, r.status, dict(r.headers.items()) if r.headers is not None else {})
    except urllib.error.HTTPError as e:
        return (e, e.code, dict(e.headers.items()) if e.headers is not None else {})

def _lees(r, max_bytes=None):
    try:
        data = r.read(max_bytes + 1) if max_bytes is not None else r.read()
    finally:
        r.close()
    return data or b''

def antwoord(open_, req, tijd, max_bytes=None):
    r, status, koppen = _open(open_, req, tijd)
    return (status, koppen, _lees(r, max_bytes))

def kop(koppen, naam):
    for k, v in (koppen or {}).items():
        if k.lower() == naam.lower():
            return v
    return None
_kop = kop

def _is_json(koppen):
    soort = (kop(koppen, 'Content-Type') or '').split(';')[0].strip().lower()
    return soort == 'application/json' or soort.endswith('+json')

def volledig(koppen, data):
    lengte = kop(koppen, 'Content-Length')
    if lengte is None:
        return True
    try:
        return int(str(lengte).strip()) == len(data)
    except ValueError:
        return False

def _paren(paren):
    sleutels = [str(k).lower() for k, _ in paren]
    if len(set(sleutels)) != len(sleutels):
        raise ValueError('dubbele sleutel')
    return dict(paren)

def gedecodeerd(pad):
    for _ in range(3):
        nieuw = urllib.parse.unquote(pad)
        if nieuw == pad:
            break
        pad = nieuw
    else:
        if urllib.parse.unquote(pad) != pad:
            raise ValueError('te vaak gecodeerd')
    if any((ord(c) < 32 or ord(c) == 127 or unicodedata.category(c) == 'Cf' for c in pad)):
        raise ValueError('stuurteken in het pad')
    return pad

def segment(deel):
    s = deel.lower()
    if _FUNCTIE.fullmatch(s):
        s = s.split('(', 1)[0]
    s = s.split(':', 1)[0]
    if _FUNCTIE.fullmatch(s):
        s = s.split('(', 1)[0]
    return s.strip(' .').rsplit('.', 1)[-1]

def segmenten(pad):
    return [segment(d) for d in gedecodeerd(pad).split('/')]

def verboden_segment(pad):
    try:
        return any((s in VERBODEN_ACTIES for s in segmenten(pad)))
    except ValueError:
        return True

def _ipv4_verbinding(adres, timeout=None, source_address=None):
    host, poort = adres
    fout = None
    for familie, soort, proto, _, sockadres in socket.getaddrinfo(host, poort, socket.AF_INET, socket.SOCK_STREAM):
        s = None
        try:
            s = socket.socket(familie, soort, proto)
            if isinstance(timeout, (int, float)):
                s.settimeout(timeout)
            if source_address:
                s.bind(source_address)
            s.connect(sockadres)
            return s
        except OSError as e:
            fout = e
            if s is not None:
                s.close()
    raise fout or OSError('geen IPv4-adres')

def verbinding(host, tijd, ipv4=False, context=None):
    v = http.client.HTTPSConnection(host, 443, timeout=tijd, context=context or ssl.create_default_context())
    if ipv4:
        v._create_connection = _ipv4_verbinding
    return v

class Transport:

    def __init__(self, open_=None, basis=GRAPH_BASIS, verbind=None, bestandhost=BESTANDHOST):
        self._open = open_ or opener()
        self._verbind = verbind or verbinding
        self._bestandhost = re.compile(bestandhost)
        d = urllib.parse.urlsplit(basis)
        self._basis, self._host, self._pad = (basis, d.hostname, d.path)
        self._lokaal = threading.local()

    @property
    def klik(self):
        return getattr(self._lokaal, 'klik', False)

    @klik.setter
    def klik(self, waarde):
        self._lokaal.klik = waarde is True

    def toets(self, methode, url, kop=None, body=None):
        if methode not in METHODES:
            raise TransportGeweigerd(f'methode {methode}')
        if not isinstance(url, str) or not url.startswith(self._basis) or any((c in url for c in ' \t\r\n\\')):
            raise TransportGeweigerd('alleen Microsoft Graph v1.0')
        d = urllib.parse.urlsplit(url)
        if d.scheme != 'https' or d.hostname != self._host or d.port is not None or d.username or d.password or d.fragment or (not d.path.startswith(self._pad)):
            raise TransportGeweigerd('alleen Microsoft Graph v1.0')
        try:
            pad = gedecodeerd(d.path)
        except ValueError:
            raise TransportGeweigerd('stuurteken of te vaak gecodeerd') from None
        delen = pad.split('/')
        norm = [segment(deel) for deel in delen]
        if any((deel in ('.', '..') for deel in delen)):
            raise TransportGeweigerd('pad met . of ..')
        if methode != 'GET' and any((s == '' for s in norm[1:])):
            raise TransportGeweigerd('leeg segment bij schrijven')
        if any((s in VERBODEN_ACTIES for s in norm)):
            raise TransportGeweigerd('versturen, delen, kopiëren of verwijderen')
        if any((deel.startswith('$') and (methode != 'GET' or deel.lower() == '$batch') for deel in delen)):
            raise TransportGeweigerd('batch of $-segment')
        if methode != 'GET' and any((s in SCHRIJF_VERBODEN for s in norm)):
            raise TransportGeweigerd('schrijven in Teams, groepen, rechten of instellingen')
        if methode == 'PATCH' and any((s in PATCH_VERBODEN for s in norm)):
            raise TransportGeweigerd('PATCH op bestanden of sites')
        if methode == 'PUT':
            self._toets_put(pad, delen, norm, d.query, kop, body)
        if not self.klik and self._vraagt_klik(methode, norm, body):
            raise TransportGeweigerd('zonder klik')

    @staticmethod
    def _toets_put(pad, delen, norm, query, kop, body):
        if norm[-1] != 'content' or delen[-1].lower() != 'content':
            raise TransportGeweigerd('PUT alleen op …/content')
        if not {'drive', 'drives'} & set(norm):
            raise TransportGeweigerd('PUT alleen op een drive')
        if body is not None and (not isinstance(body, (bytes, bytearray))):
            raise TransportGeweigerd('PUT zonder bytes')
        if body is not None and len(body) > MAX_BESTAND:
            raise TeGroot('PUT-body')
        if pad.count(':') == 2 and delen[-2].endswith(':'):
            if urllib.parse.parse_qsl(query, keep_blank_values=True) != CONFLICT_FAIL:
                raise TransportGeweigerd('PUT op een naam alleen met conflictBehavior=fail')
        elif ':' not in pad and len(delen) >= 3 and (norm[-3] == 'items'):
            if query:
                raise TransportGeweigerd('PUT op een item zonder query')
            waarde = _kop(kop, 'If-Match')
            if not isinstance(waarde, str) or waarde.strip() in ('', '*', '"*"'):
                raise TransportGeweigerd('PUT op een item alleen met If-Match')
        else:
            raise TransportGeweigerd('PUT alleen als …:/naam:/content of …/items/{id}/content')

    @staticmethod
    def _vraagt_klik(methode, norm, body):
        laatste = norm[-1]
        if methode == 'PUT':
            return True
        if methode != 'GET' and KLIK_SEGMENTEN & set(norm):
            return True
        if methode == 'POST' and laatste in ('children', 'cancel'):
            return True
        if methode == 'PATCH' and 'events' in norm:
            return True
        if methode == 'POST' and laatste == 'events':
            try:
                inhoud = json.loads(body, object_pairs_hook=_paren) if body else {}
            except (ValueError, TypeError, RecursionError):
                return True
            if not isinstance(inhoud, dict):
                return True
            return any((str(k).lower() == 'attendees' and bool(v) for k, v in inhoud.items()))
        return False

    @staticmethod
    def _bestand(methode, url):
        if methode != 'GET':
            return ''
        try:
            laatste = gedecodeerd(urllib.parse.urlsplit(url).path).split('/')[-1].lower()
        except ValueError:
            return ''
        return laatste if laatste in ('content', '$value') else ''

    def verzend(self, methode, url, kop, body, tijd=None):
        self.toets(methode, url, kop, body)
        soort = self._bestand(methode, url)
        bestand = bool(soort) or methode == 'PUT'
        t = TIJD_GRAPH_S
        if bestand and isinstance(tijd, (int, float)) and (not isinstance(tijd, bool)) and (tijd > 0):
            t = min(float(tijd), TIJD_BESTAND_MAX_S)
        try:
            r, status, koppen = _open(self._open, verzoek(url, methode, kop, body), t)
        except NETWERKFOUTEN as e:
            raise GeenVerbinding(type(e).__name__) from None
        if soort == 'content' and status == 302:
            r.close()
            return self._volg(_kop(koppen, 'Location'), t)
        limiet = MAX_BESTAND if soort and status == 200 and (not _is_json(koppen)) else MAX_GRAPH
        try:
            data = _lees(r, limiet)
        except NETWERKFOUTEN as e:
            raise GeenVerbinding(type(e).__name__) from None
        if 300 <= status < 400:
            raise TransportGeweigerd('omleiding')
        if len(data) > limiet:
            raise TeGroot('antwoord')
        if not volledig(koppen, data):
            raise GeenVerbinding('IncompleteRead')
        return (status, koppen, data)

    def _volg(self, plek, tijd):
        if not isinstance(plek, str) or any((c in plek for c in ' \t\r\n\\')) or any((ord(c) < 32 or ord(c) == 127 for c in plek)):
            raise TransportGeweigerd('omleiding zonder geldige Location')
        try:
            d = urllib.parse.urlsplit(plek)
            poort = d.port
        except ValueError:
            raise TransportGeweigerd('omleiding met een ongeldige host of poort') from None
        if d.scheme != 'https' or not d.hostname or (not self._bestandhost.fullmatch(d.hostname)) or (poort is not None) or ('@' in d.netloc) or d.fragment or (d.netloc.lower() != d.hostname):
            raise TransportGeweigerd('omleiding buiten BESTANDHOST')
        doel = (d.path or '/') + (f'?{d.query}' if d.query else '')
        for ipv4 in (False, True):
            v = self._verbind(d.hostname, tijd, ipv4)
            try:
                v.request('GET', doel, headers={'User-Agent': f'mit-koppelstuk-lader/{LADER_VERSIE}'})
                r = v.getresponse()
                status, koppen = (r.status, dict(r.getheaders()))
                if 300 <= status < 400:
                    raise TransportGeweigerd('tweede omleiding')
                limiet = MAX_BESTAND if status == 200 else MAX_GRAPH
                data = r.read(limiet + 1) or b''
                if len(data) <= limiet and (not volledig(koppen, data)):
                    raise http.client.IncompleteRead(data)
            except RESETFOUTEN as e:
                if ipv4:
                    raise GeenVerbinding(type(e).__name__) from None
                continue
            except TransportGeweigerd:
                raise
            except NETWERKFOUTEN as e:
                raise GeenVerbinding(type(e).__name__) from None
            finally:
                v.close()
            if len(data) > limiet:
                raise TeGroot('bestand')
            return (status, koppen, data)
        raise GeenVerbinding('geen antwoord')
