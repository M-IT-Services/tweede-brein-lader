# -*- coding: utf-8 -*-
# (c) M-IT Services. Gebruik alleen volgens de licentievoorwaarden.
import base64
import binascii
import hashlib
import json
import os
import re
import sys
from . import API, DOMEIN, DREMPEL, KLIK_VERPLICHT, LADER_TOOLS, LADER_VERSIE, MAX_BESTANDEN, MAX_BUNDEL, MIN_PAKKET, SLEUTELS, ed25519
from .laden import laad, uitladen
CODES = ('handtekening', 'opbouw', 'terugrol', 'laden', 'grens')
VERSIE = re.compile('(0|[1-9][0-9]{0,5})\\.(0|[1-9][0-9]{0,5})\\.(0|[1-9][0-9]{0,5})')
PYTHON = re.compile('3\\.(0|[1-9][0-9]?)')
BESTAND = re.compile('koppelstuk/[a-z_][a-z0-9_]*[.]py')
TOOLNAAM = re.compile('[a-z][a-z0-9_]{0,63}')
VERBODEN_WOORD = re.compile('send|verstu|verzend|delete|verwijder|forward|doorst', re.I)
KLIK = 'anthropic/requiresUserInteraction'

class Weigering(Exception):

    def __init__(self, code, detail=''):
        if code not in CODES:
            raise ValueError(code)
        super().__init__(f'{code}: {detail}')
        self.code = code
        self.detail = detail

class LaderTeOud(Exception):
    pass

def versie(tekst):
    if isinstance(tekst, str) and VERSIE.fullmatch(tekst):
        return tuple((int(d) for d in tekst.split('.')))
    return None

def _geheel(w):
    return isinstance(w, int) and (not isinstance(w, bool))

def _b64(tekst):
    if not isinstance(tekst, str):
        raise ValueError('geen tekst')
    ruw = tekst.encode('ascii')
    data = base64.b64decode(ruw, validate=True)
    if base64.b64encode(data) != ruw:
        raise ValueError('niet canoniek')
    return data

def _lees_pakket(pakketbytes):
    return json.loads(pakketbytes.decode('utf-8'))

class Gecontroleerd:

    def __init__(self, versie, sha256, bestanden, bron_commit, datum):
        self.versie = versie
        self.sha256 = sha256
        self.bestanden = bestanden
        self.bron_commit = bron_commit
        self.datum = datum

def controleer(envelop, sleutels=SLEUTELS, drempel=DREMPEL, vloer=None, min_pakket=MIN_PAKKET, python=sys.version_info):
    if not isinstance(envelop, dict) or not _geheel(envelop.get('formaat')) or envelop['formaat'] != 1:
        raise Weigering('handtekening', 'envelop: formaat')
    if versie(envelop.get('versie')) is None:
        raise Weigering('handtekening', 'envelop: versie')
    handtekeningen = envelop.get('handtekeningen')
    if not isinstance(handtekeningen, list) or not 1 <= len(handtekeningen) <= 4:
        raise Weigering('handtekening', 'envelop: aantal handtekeningen')
    try:
        pakketbytes = _b64(envelop.get('pakket'))
        sigs = [_b64(s) for s in handtekeningen]
    except (ValueError, binascii.Error, UnicodeEncodeError):
        raise Weigering('handtekening', 'envelop: base64') from None
    if any((len(s) != 64 for s in sigs)):
        raise Weigering('handtekening', 'envelop: handtekening is geen 64 bytes')
    bericht = DOMEIN + pakketbytes
    geldig = sum((1 for sleutel in dict.fromkeys(sleutels) if any((ed25519.verify(sleutel, s, bericht) for s in sigs))))
    if drempel < 1 or geldig < drempel:
        raise Weigering('handtekening', 'handtekening klopt niet')
    try:
        bundel = _lees_pakket(pakketbytes)
    except (UnicodeDecodeError, ValueError):
        raise Weigering('opbouw', 'geen geldige JSON in UTF-8') from None
    if not isinstance(bundel, dict):
        raise Weigering('opbouw', 'geen object')
    if bundel.get('soort') != 'koppelstuk-pakket' or bundel.get('pakket') != 'koppelstuk':
        raise Weigering('opbouw', 'soort of pakket')
    if not _geheel(bundel.get('formaat')) or bundel['formaat'] != 1:
        raise Weigering('opbouw', 'formaat')
    v = versie(bundel.get('versie'))
    if v is None or bundel['versie'] != envelop['versie']:
        raise Weigering('opbouw', 'versie')
    if versie(bundel.get('min_lader')) is None or not isinstance(bundel.get('min_python'), str) or (not PYTHON.fullmatch(bundel['min_python'])) or (not _geheel(bundel.get('api'))):
        raise Weigering('opbouw', 'min_lader, min_python of api')
    for veld in ('bron_commit', 'datum'):
        if not isinstance(bundel.get(veld, ''), str):
            raise Weigering('opbouw', veld)
    if bundel['api'] != API:
        raise LaderTeOud(f"api {bundel['api']}")
    if versie(bundel['min_lader']) > versie(LADER_VERSIE):
        raise LaderTeOud(f"min_lader {bundel['min_lader']}")
    if tuple((int(d) for d in bundel['min_python'].split('.'))) > tuple(python[:2]):
        raise LaderTeOud(f"min_python {bundel['min_python']}")
    bestanden = bundel.get('bestanden')
    if not isinstance(bestanden, dict) or not 1 <= len(bestanden) <= MAX_BESTANDEN:
        raise Weigering('opbouw', 'aantal bestanden')
    totaal = 0
    for naam, bron in bestanden.items():
        if not BESTAND.fullmatch(naam) or not isinstance(bron, str):
            raise Weigering('opbouw', f'bestandsnaam {naam[:80]!r}')
        totaal += len(bron.encode('utf-8', 'surrogatepass'))
    if 'koppelstuk/__init__.py' not in bestanden:
        raise Weigering('opbouw', 'geen __init__.py')
    if totaal > MAX_BUNDEL:
        raise Weigering('opbouw', 'te groot')
    sha = hashlib.sha256(pakketbytes).hexdigest()
    if v < versie(min_pakket):
        raise Weigering('terugrol', f"{bundel['versie']} is lager dan {min_pakket}")
    if vloer:
        vv, vsha = vloer
        if v < vv:
            raise Weigering('terugrol', f"{bundel['versie']} is lager dan de vloer")
        if v == vv and sha != vsha:
            raise Weigering('terugrol', 'zelfde versie, andere inhoud')
    return Gecontroleerd(bundel['versie'], sha, dict(bestanden), bundel.get('bron_commit', ''), bundel.get('datum', ''))

class Geladen:

    def __init__(self, lader, module, toolset, tools, versie, sha256):
        self.lader = lader
        self.module = module
        self.toolset = toolset
        self.tools = tools
        self.versie = versie
        self.sha256 = sha256

    def uit(self):
        uitladen(self.lader)

def laad_en_toets(g, omgeving):
    try:
        lader, module = laad(g.bestanden)
    except (Exception, SystemExit) as e:
        raise Weigering('laden', type(e).__name__) from None
    try:
        if getattr(module, '__version__', None) != g.versie or getattr(module, 'API', None) != API:
            raise Weigering('laden', 'versie of api in de code')
        toolset = module.maak(omgeving)
        tools = toolset.lijst()
    except Weigering:
        uitladen(lader)
        raise
    except (Exception, SystemExit) as e:
        uitladen(lader)
        raise Weigering('laden', type(e).__name__) from None
    try:
        toets_tools(tools)
    except Weigering:
        uitladen(lader)
        raise
    return Geladen(lader, module, toolset, tools, g.versie, g.sha256)

def toets_tools(tools):
    if not isinstance(tools, list) or not tools:
        raise Weigering('grens', 'lege toollijst')
    gezien = set()
    for t in tools:
        if not isinstance(t, dict):
            raise Weigering('grens', 'geen tooldefinitie')
        naam = t.get('name')
        if not isinstance(naam, str) or not TOOLNAAM.fullmatch(naam):
            raise Weigering('grens', f'ongeldige naam {str(naam)[:80]!r}')
        if naam in LADER_TOOLS or naam in gezien:
            raise Weigering('grens', f'naambotsing {naam}')
        if VERBODEN_WOORD.search(naam):
            raise Weigering('grens', f'verboden woord in {naam}')
        schema = t.get('inputSchema')
        if not isinstance(schema, dict) or not isinstance(schema.get('properties'), dict) or (not isinstance(schema.get('required', []), list)) or (not isinstance(t.get('description'), str)):
            raise Weigering('grens', f'schema van {naam}')
        ann, meta = (t.get('annotations', {}), t.get('_meta', {}))
        if not isinstance(ann, dict) or not isinstance(meta, dict):
            raise Weigering('grens', f'annotaties van {naam}')
        klik = meta.get(KLIK) is True
        if ann.get('openWorldHint', True) is not False and (not klik):
            raise Weigering('grens', f'{naam} gaat naar buiten zonder klik')
        if naam in KLIK_VERPLICHT and (not klik):
            raise Weigering('grens', f'{naam} zonder klik')
        gezien.add(naam)

class Vloer:

    def __init__(self, pad):
        self.pad = pad

    def lees(self):
        try:
            with open(self.pad, 'rb') as f:
                d = json.loads(f.read().decode('utf-8'))
            v = versie(d.get('versie'))
            sha = d.get('sha256')
            if v is None or not isinstance(sha, str) or (not re.fullmatch('[0-9a-f]{64}', sha)):
                raise ValueError('onvolledig')
            return (v, sha)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, AttributeError) as e:
            sys.stderr.write(f'koppelstuk: vloer onleesbaar ({type(e).__name__}); MIN_PAKKET geldt\n')
            return None

    def schrijf(self, versie_tekst, sha256):
        oud = self.lees()
        if oud and oud[0] > versie(versie_tekst):
            return
        tijdelijk = self.pad + '.nieuw'
        with open(tijdelijk, 'wb') as f:
            f.write(json.dumps({'versie': versie_tekst, 'sha256': sha256}).encode('utf-8'))
        os.replace(tijdelijk, self.pad)
