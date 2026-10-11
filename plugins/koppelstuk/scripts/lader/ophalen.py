# -*- coding: utf-8 -*-
# (c) M-IT Services. Gebruik alleen volgens de licentievoorwaarden.
import json
from . import LADER_VERSIE, MAX_ANTWOORD, PAKKET_URL, REDEN_403, RETRY_AFTER_S, TIJD_KERN_S
from .pakket import CODES, versie
from .transport import NETWERKFOUTEN, antwoord, kop, opener, verzoek
REDENEN_403 = ('geen_koppelingen', 'geen_klant', 'blokkade', 'licentie', 'geen_gebruiker', 'geen_basis')

class Uitkomst:

    def __init__(self, toestand, envelop=None, nieuwste=None, wacht=None, reden=''):
        self.toestand = toestand
        self.envelop = envelop
        self.nieuwste = nieuwste
        self.wacht = wacht
        self.reden = reden

    def __repr__(self):
        return f'Uitkomst({self.toestand}, reden={self.reden!r}, wacht={self.wacht})'

def _wacht(koppen):
    w = kop(koppen, 'Retry-After')
    try:
        return max(1, min(int(str(w).strip()), 3600))
    except (TypeError, ValueError):
        return RETRY_AFTER_S

def _json(data):
    try:
        d = json.loads(data.decode('utf-8'))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    return d if isinstance(d, dict) else None

class Ophaler:

    def __init__(self, url=PAKKET_URL, open_=None):
        self.url = url
        self._open = open_ or opener()

    def haal(self, token, heeft=None, weigering=None):
        kop_ = {'Authorization': 'Bearer ' + token, 'Koppelstuk-Lader': LADER_VERSIE, 'Accept': 'application/json', 'User-Agent': f'mit-koppelstuk-lader/{LADER_VERSIE}'}
        if heeft is not None:
            if versie(heeft) is None:
                raise ValueError('heeft: drie getallen')
            kop_['Koppelstuk-Heeft'] = heeft
        if weigering in CODES:
            kop_['Koppelstuk-Weigering'] = weigering
        try:
            status, koppen, data = antwoord(self._open, verzoek(self.url, 'GET', kop_), TIJD_KERN_S, MAX_ANTWOORD)
        except NETWERKFOUTEN as e:
            return Uitkomst('storing', reden=type(e).__name__)
        return self._vertaal(status, koppen, data, heeft is not None)

    @staticmethod
    def _vertaal(status, koppen, data, hercontrole):
        if status == 401:
            return Uitkomst('niet_aangemeld')
        if status == 403:
            reden = (_json(data) or {}).get('reden')
            reden = reden if reden in REDENEN_403 else 'onbekend'
            return Uitkomst(REDEN_403.get(reden, 'toegang'), reden=reden)
        if status == 409:
            return Uitkomst('te_oud')
        if status == 410:
            return Uitkomst('ingetrokken')
        if status == 429 or status >= 500:
            return Uitkomst('storing', wacht=_wacht(koppen), reden=f'http_{status}')
        if status != 200:
            return Uitkomst('storing', reden=f'http_{status}')
        if len(data) > MAX_ANTWOORD:
            return Uitkomst('storing', reden='te_groot')
        soort = (kop(koppen, 'Content-Type') or '').split(';')[0].strip().lower()
        d = _json(data) if soort == 'application/json' else None
        if d is None:
            return Uitkomst('storing', reden='geen_json')
        if hercontrole:
            if d.get('status') != 'ok':
                return Uitkomst('storing', reden='hercontrole')
            nieuwste = d.get('nieuwste')
            return Uitkomst('ok', nieuwste=nieuwste if versie(nieuwste) else None)
        return Uitkomst('pakket', envelop=d)
