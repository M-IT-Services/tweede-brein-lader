# -*- coding: utf-8 -*-
# (c) M-IT Services. Gebruik alleen volgens de licentievoorwaarden.
import base64
import ctypes
import ctypes.wintypes
import hashlib
import http.client
import json
import os
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from . import CLIENT_ID, KERN_SCOPE, LOGIN, NOOIT
from .transport import GeenVerbinding
GRAPH_DEFAULT = 'https://graph.microsoft.com/.default'
KLUIS_FORMAAT = 2
GUID = re.compile('[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
TOESTEMMING = ('AADSTS65001', 'AADSTS90094', 'AADSTS90095')
TOEWIJZING = 'AADSTS50105'
_NOOIT_KLEIN = frozenset((n.lower() for n in NOOIT))

def kort(scope):
    return scope.rsplit('/', 1)[-1].lower()

def _toets(scopes):
    for s in scopes:
        if kort(s) in _NOOIT_KLEIN:
            raise RuntimeError(f'Verboden recht in de lijst: {s}')
    return ' '.join(dict.fromkeys(scopes))

def scope_authorize():
    return _toets(['openid', 'profile', 'offline_access', GRAPH_DEFAULT])

def scope_kern():
    return _toets(['openid', 'profile', 'offline_access', KERN_SCOPE])

def scope_graph():
    return _toets(['offline_access', GRAPH_DEFAULT])

def rechten_uit(res):
    scope = res.get('scope') if isinstance(res, dict) else None
    if not isinstance(scope, str) or not scope.split():
        return None
    rechten = frozenset((kort(s) for s in scope.split())) - {'.default'}
    return rechten or None

def datamap():
    kandidaten = [os.environ.get('KOPPELSTUK_DATA'), os.environ.get('CLAUDE_PLUGIN_DATA')]
    kandidaten = [k for k in kandidaten if k and '${' not in k and os.path.isabs(k)]
    pad = kandidaten[0] if kandidaten else os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'M-IT', 'Koppelstuk')
    os.makedirs(pad, exist_ok=True)
    return pad

class _Blob(ctypes.Structure):
    _fields_ = [('cbData', ctypes.wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

def _dpapi(data, versleutel):
    if sys.platform != 'win32':
        raise RuntimeError('Het koppelstuk bewaart zijn aanmelding alleen versleuteld, met Windows.')
    crypt32, kernel32 = (ctypes.windll.crypt32, ctypes.windll.kernel32)
    buf = ctypes.create_string_buffer(data, len(data))
    invoer, uitvoer = (_Blob(len(data), buf), _Blob())
    entropie = b'M-IT Koppelstuk'
    ebuf = ctypes.create_string_buffer(entropie, len(entropie))
    eblob = _Blob(len(entropie), ebuf)
    fn = crypt32.CryptProtectData if versleutel else crypt32.CryptUnprotectData
    if versleutel:
        ok = fn(ctypes.byref(invoer), 'M-IT Koppelstuk', ctypes.byref(eblob), None, None, 1, ctypes.byref(uitvoer))
    else:
        ok = fn(ctypes.byref(invoer), None, ctypes.byref(eblob), None, None, 1, ctypes.byref(uitvoer))
    if not ok:
        raise RuntimeError('Windows kon de aanmelding niet ' + ('versleutelen.' if versleutel else 'ontsleutelen.'))
    try:
        return ctypes.string_at(uitvoer.pbData, uitvoer.cbData)
    finally:
        kernel32.LocalFree(uitvoer.pbData)

class Kluis:
    POGINGEN = 10
    PAUZE_S = 0.05

    def __init__(self, pad=None, versleutel=None, ontsleutel=None):
        self.pad = pad or os.path.join(datamap(), 'aanmelding.bin')
        self._in = versleutel or (lambda b: _dpapi(b, True))
        self._uit = ontsleutel or (lambda b: _dpapi(b, False))
        self._slot = threading.Lock()

    def _herhaal(self, actie):
        for poging in range(self.POGINGEN):
            try:
                return actie()
            except PermissionError:
                if poging == self.POGINGEN - 1:
                    raise
                time.sleep(self.PAUZE_S)

    def _lees_bytes(self):
        with open(self.pad, 'rb') as f:
            return f.read()

    def lees(self):
        with self._slot:
            try:
                return json.loads(self._uit(self._herhaal(self._lees_bytes)))
            except FileNotFoundError:
                return {}
            except (OSError, ValueError, RuntimeError):
                return {}

    def schrijf(self, d):
        with self._slot:
            tijdelijk = self.pad + '.nieuw'
            with open(tijdelijk, 'wb') as f:
                f.write(self._in(json.dumps(d).encode('utf-8')))
            self._herhaal(lambda: os.replace(tijdelijk, self.pad))

    def weg(self):
        with self._slot:
            try:
                self._herhaal(lambda: os.remove(self.pad))
            except FileNotFoundError:
                pass
_ANTWOORDFOUTEN = (OSError, ValueError, http.client.HTTPException, RecursionError)

def _post(url, velden):
    data = urllib.parse.urlencode(velden).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=30) as r:
            uit = json.loads(r.read() or b'{}')
            return uit if isinstance(uit, dict) else {'error': 'geen_verbinding'}
    except urllib.error.HTTPError as e:
        try:
            uit = json.loads(e.read())
        except _ANTWOORDFOUTEN:
            uit = {}
        finally:
            e.close()
        if not isinstance(uit, dict) or 'error' not in uit:
            uit = {'error': f'http_{e.code}'}
        return uit
    except (urllib.error.URLError,) + _ANTWOORDFOUTEN:
        return {'error': 'geen_verbinding'}

def _claims(tok):
    try:
        p = tok.split('.')[1]
        p += '=' * (-len(p) % 4)
        uit = json.loads(base64.urlsafe_b64decode(p))
        return uit if isinstance(uit, dict) else {}
    except (AttributeError, IndexError, ValueError):
        return {}

def _schoon(tekst, lengte=100):
    return re.sub('[^\\w@.\\-+ ]', '', str(tekst or ''))[:lengte]

def _pkce():
    v = base64.urlsafe_b64encode(os.urandom(64)).decode().rstrip('=')
    c = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip('=')
    return (v, c)

def _aadsts(res):
    m = re.search('AADSTS\\d{4,6}', str(res.get('error_description') or ''))
    return m.group(0) if m else ''

class NietAangemeld(Exception):

    def __init__(self, code=''):
        super().__init__(code)
        self.code = code

class ToestemmingNodig(Exception):
    pass

class GeenToewijzing(Exception):
    pass

class TeVeelRechten(Exception):
    pass

class Aanmelding:

    def __init__(self, kluis=None, post=_post, open_browser=webbrowser.open, klok=time.time, wacht_browser=300):
        self.kluis = kluis or Kluis()
        self._post = post
        self._open = open_browser
        self._klok = klok
        self._wacht_browser = wacht_browser
        self._bezig = None
        self._url = ''
        self.fout = None
        self._slot = threading.RLock()

    def _kluis(self):
        c = self.kluis.lees()
        return c if c.get('formaat') == KLUIS_FORMAAT and c.get('refresh_token') else {}

    def aangemeld(self):
        return bool(self._kluis())

    def gegevens(self):
        c = self._kluis()
        return {'account': c.get('account', ''), 'tenant': c.get('tenant', '')}

    def rechten(self):
        r = ((self._kluis().get('tokens') or {}).get('graph') or {}).get('rechten')
        return frozenset(r) if isinstance(r, list) and all((isinstance(x, str) for x in r)) else None

    def bezig(self):
        return bool(self._bezig and self._bezig.is_alive())

    def token_kern(self, forceer=False):
        return self._token('kern', scope_kern(), forceer)

    def token_graph(self, forceer=False):
        return self._token('graph', scope_graph(), forceer)

    def _token(self, soort, scope, forceer):
        with self._slot:
            c = self._kluis()
            t = (c.get('tokens') or {}).get(soort) or {}
            if not forceer and t.get('access_token') and (t.get('verloopt', 0) > self._klok() + 120) and (soort != 'graph' or isinstance(t.get('rechten'), list)):
                return t['access_token']
            if not c.get('refresh_token'):
                raise NietAangemeld()
            res = self._vernieuw(c.get('tenant'), c['refresh_token'], scope)
            rechten = self._graph_antwoord(c.get('tenant'), res) if soort == 'graph' else None
            self._bewaar(soort, res, rechten=rechten)
            return res['access_token']

    def _vernieuw(self, tenant, refresh_token, scope):
        tenant = tenant if GUID.fullmatch(str(tenant or '')) else 'organizations'
        res = self._post(f'{LOGIN}/{tenant}/oauth2/v2.0/token', {'client_id': CLIENT_ID, 'grant_type': 'refresh_token', 'refresh_token': refresh_token, 'scope': scope})
        if 'access_token' not in res:
            self._fout(res)
        return res

    def _graph_antwoord(self, tenant, res):
        rechten = self._toets_antwoord(res)
        if rechten is None:
            nieuw = self._vernieuw(tenant, res.get('refresh_token') or self._kluis().get('refresh_token') or '', scope_graph())
            rechten = self._toets_antwoord(nieuw)
            if rechten is None:
                raise NietAangemeld('SCOPE')
            id_token = res.get('id_token')
            res.clear()
            res.update(nieuw)
            if id_token and (not res.get('id_token')):
                res['id_token'] = id_token
        return rechten

    @staticmethod
    def _toets_antwoord(res):
        rechten = rechten_uit(res)
        if rechten is not None and rechten & _NOOIT_KLEIN:
            raise TeVeelRechten(', '.join(sorted(rechten & _NOOIT_KLEIN)))
        return rechten

    def _fout(self, res):
        fout, code = (str(res.get('error') or ''), _aadsts(res))
        if fout == 'consent_required' or code in TOESTEMMING:
            raise ToestemmingNodig(code)
        if code == TOEWIJZING:
            raise GeenToewijzing(code)
        if fout in ('invalid_grant', 'interaction_required'):
            self.kluis.weg()
            raise NietAangemeld(code)
        if fout == 'geen_verbinding' or fout in ('temporarily_unavailable', 'http_429') or fout.startswith('http_5'):
            raise GeenVerbinding(fout)
        raise NietAangemeld(code)

    def _bewaar(self, soort, res, nieuw=False, rechten=None):
        c = {'formaat': KLUIS_FORMAAT, 'tokens': {}} if nieuw else self._kluis()
        if not c:
            raise NietAangemeld()
        c.setdefault('tokens', {})[soort] = {'access_token': res['access_token'], 'verloopt': self._klok() + int(res.get('expires_in', 3600))}
        if rechten is not None:
            c['tokens'][soort]['rechten'] = sorted(rechten)
        if res.get('refresh_token'):
            c['refresh_token'] = res['refresh_token']
        if res.get('id_token'):
            cl = _claims(res['id_token'])
            c['account'] = _schoon(cl.get('preferred_username') or cl.get('upn') or cl.get('email') or '?')
            c['tenant'] = cl.get('tid') if GUID.fullmatch(str(cl.get('tid') or '')) else ''
            c['oid'] = cl.get('oid') if GUID.fullmatch(str(cl.get('oid') or '')) else ''
        self.kluis.schrijf(c)

    def start(self, wacht=45, na=None):
        if self.bezig():
            return ('loopt', self._url)
        verifier, uitdaging = _pkce()
        staat = base64.urlsafe_b64encode(os.urandom(16)).decode().rstrip('=')
        antwoord = {}

        class Ontvanger(BaseHTTPRequestHandler):

            def do_GET(self):
                vraag = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if 'code' in vraag or 'error' in vraag:
                    antwoord.update({k: v[0] for k, v in vraag.items()})
                gelukt = 'code' in vraag
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write("<html><body style='font-family:Montserrat,Segoe UI,sans-serif;padding:3em;color:#222;background:#fff'><h2>{}</h2><p>{}</p></body></html>".format('Aangemeld bij het Tweede Brein.' if gelukt else 'Aanmelden is niet gelukt.', 'Je kunt dit tabblad sluiten en verder in Claude.' if gelukt else 'Ga terug naar Claude en probeer het opnieuw.').encode('utf-8'))

            def log_message(self, *a):
                pass
        server = HTTPServer(('127.0.0.1', 0), Ontvanger)
        server.timeout = 1
        omleiding = f'http://localhost:{server.server_address[1]}'
        self._url = f'{LOGIN}/organizations/oauth2/v2.0/authorize?' + urllib.parse.urlencode({'client_id': CLIENT_ID, 'response_type': 'code', 'redirect_uri': omleiding, 'response_mode': 'query', 'scope': scope_authorize(), 'state': staat, 'code_challenge': uitdaging, 'code_challenge_method': 'S256', 'prompt': 'select_account'})
        self.fout = None

        def wachten():
            eind = time.monotonic() + self._wacht_browser
            try:
                while not antwoord and time.monotonic() < eind:
                    server.handle_request()
            finally:
                server.server_close()
            if not antwoord or antwoord.get('state') != staat:
                self.fout = ('mislukt', '')
                return
            if antwoord.get('error'):
                tekst = antwoord.get('error', '') + ' ' + antwoord.get('error_description', '')
                code = (re.search('AADSTS\\d{4,6}', tekst) or [''])[0]
                if code == TOEWIJZING:
                    self.fout = ('toewijzing', code)
                else:
                    self.fout = ('toestemming' if 'consent' in tekst or code in TOESTEMMING else 'mislukt', code)
                return
            try:
                res = self._post(f'{LOGIN}/organizations/oauth2/v2.0/token', {'client_id': CLIENT_ID, 'grant_type': 'authorization_code', 'code': antwoord['code'], 'redirect_uri': omleiding, 'code_verifier': verifier, 'scope': scope_authorize()})
                with self._slot:
                    if 'access_token' not in res or 'id_token' not in res:
                        self._fout(res if 'access_token' not in res else {'error': 'geen_id_token'})
                    rechten = self._graph_antwoord(_claims(res['id_token']).get('tid'), res)
                    self._bewaar('graph', res, nieuw=True, rechten=rechten)
                    self.token_kern(forceer=True)
            except TeVeelRechten:
                self.fout = ('rechten', '')
                return
            except GeenToewijzing as e:
                self.fout = ('toewijzing', str(e))
                return
            except ToestemmingNodig as e:
                self.fout = ('toestemming', str(e))
                return
            except GeenVerbinding:
                self.fout = ('offline', '')
                return
            except NietAangemeld as e:
                self.fout = ('mislukt', e.code)
                return
            except Exception:
                traceback.print_exc(file=sys.stderr)
                self.fout = ('mislukt', '')
                return
            if na:
                na()
        self._bezig = threading.Thread(target=wachten, daemon=True, name='koppelstuk-aanmelden')
        self._bezig.start()
        try:
            self._open(self._url)
        except Exception:
            pass
        self._bezig.join(timeout=wacht)
        if self._bezig.is_alive():
            return ('loopt', self._url)
        if not self.fout and (not self.aangemeld()):
            self.fout = ('mislukt', '')
        return ('fout' if self.fout else 'klaar', self._url)

    def afmelden(self):
        with self._slot:
            self.kluis.weg()
