# -*- coding: utf-8 -*-
# (c) M-IT Services. Gebruik alleen volgens de licentievoorwaarden.
import datetime as dt
import hashlib
import json
import os
import sys
import threading
import time
import traceback
from . import DREMPEL, HANDMATIG_PER_S, HERCONTROLE_S, LADER_TOOLS, LADER_VERSIE, MIN_PAKKET, RETRY_AFTER_S, SLEUTELS, STORINGSMARGE_S, WACHT_AANMELDEN_S, WACHT_LIJST_S, ZINNEN
from . import pakket
from .aanmelden import Aanmelding, NietAangemeld, ToestemmingNodig, datamap
from .ophalen import Ophaler
from .transport import GeenVerbinding, Transport, TransportGeweigerd
PROTOCOLLEN = ('2025-06-18', '2025-03-26', '2024-11-05')
INSTRUCTIES = 'Koppelstuk van het Tweede Brein (M-IT Services): de eigen Outlook van de medewerker. Volg de werkwijze voor Koppelingen uit kern_start. Zie je alleen aanmelden, aanmeldstatus en afmelden, roep dan aanmeldstatus aan en geef de zin door.'
LEES = {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False}
SCHRIJF = {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}
_LEEG = {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}
LADER_TOOLDEFS = [{'name': 'aanmelden', 'description': 'Meld de medewerker aan bij Microsoft met het eigen account. Opent een venster in de browser.', 'inputSchema': _LEEG, 'annotations': SCHRIJF}, {'name': 'aanmeldstatus', 'description': 'Laat zien of en als wie de medewerker is aangemeld, en of het koppelstuk werkt.', 'inputSchema': _LEEG, 'annotations': LEES}, {'name': 'afmelden', 'description': 'Haalt de aanmelding van deze laptop weg. Er verandert niets in de postbus.', 'inputSchema': _LEEG, 'annotations': SCHRIJF}]
assert tuple((t['name'] for t in LADER_TOOLDEFS)) == LADER_TOOLS
ZIN_BIJ = {'niet_aangemeld': 'aanmelden', 'bezig': 'start', 'offline': 'offline', 'storing': 'storing', 'licentie': 'licentie', 'toegang': 'toegang', 'te_oud': 'te_oud', 'toestemming': 'toestemming'}

def _tekst(t, fout=False):
    return {'content': [{'type': 'text', 'text': str(t)}], 'isError': fout}

def _vingerafdruk(lijst):
    return hashlib.sha256(json.dumps(lijst, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()

def _cet(ts):
    utc = dt.datetime.fromtimestamp(ts, dt.timezone.utc)

    def laatste_zondag(maand):
        d = dt.date(utc.year, maand, 31)
        d -= dt.timedelta(days=(d.weekday() - 6) % 7)
        return dt.datetime(d.year, d.month, d.day, 1, 0, tzinfo=dt.timezone.utc)
    zomer = laatste_zondag(3) <= utc < laatste_zondag(10)
    return (utc + dt.timedelta(hours=2 if zomer else 1)).strftime('%H:%M')

class Omgeving:

    def __init__(self, token_graph, verzend):
        self.token_graph = token_graph
        self.verzend = verzend

class Sessie:

    def __init__(self, aanmelding=None, ophaler=None, transport=None, vloer=None, klok=time.time, uit=None, sleutels=SLEUTELS, drempel=DREMPEL, min_pakket=MIN_PAKKET, wacht_lijst=WACHT_LIJST_S, wacht_aanmelden=WACHT_AANMELDEN_S):
        self.aanmelding = aanmelding or Aanmelding()
        self.ophaler = ophaler or Ophaler()
        self.transport = transport or Transport()
        self.vloer = vloer or pakket.Vloer(os.path.join(datamap(), 'pakket-stand.json'))
        self.klok = klok
        self._uit = uit or sys.stdout
        self.sleutels, self.drempel, self.min_pakket = (sleutels, drempel, min_pakket)
        self.wacht_lijst, self.wacht_aanmelden = (wacht_lijst, wacht_aanmelden)
        self._schrijfslot = threading.Lock()
        self._pakketslot = threading.RLock()
        self._staat = threading.RLock()
        self.geladen = None
        self.toestand = 'niet_aangemeld'
        self.reden = ''
        self.laatste_ok = None
        self.laatste_poging = None
        self.volgende = None
        self._na_retry = False
        self.geen_poging = False
        self._na_intrekken = False
        self._sessie = 0
        self.nieuwste = None
        self._handmatig = None
        self._ronde_draad = None
        self._klaar = threading.Event()
        self._klaar.set()
        self._gemeld = None
        self._melding_uit = False
        self._stop = threading.Event()

    def start(self, klok_draad=True):
        if self.aanmelding.aangemeld():
            self._ronde(self._ophalen_en_laden)
        if klok_draad:
            threading.Thread(target=self._klok_loop, daemon=True, name='koppelstuk-klok').start()

    def _klok_loop(self):
        while not self._stop.wait(30):
            try:
                self.tik()
            except Exception:
                traceback.print_exc(file=sys.stderr)

    def stop(self):
        self._stop.set()

    def _ronde(self, functie, achtergrond=True):
        with self._staat:
            if self._ronde_draad is not None and self._ronde_draad.is_alive():
                return False
            if self.geladen is None and functie == self._ophalen_en_laden:
                self.toestand = 'bezig'
            self._klaar.clear()
            draad = threading.Thread(target=self._ronde_loop, args=(functie,), daemon=True, name='koppelstuk-ronde')
            self._ronde_draad = draad
            draad.start()
        if not achtergrond:
            draad.join()
        return True

    def _ronde_loop(self, functie):
        try:
            functie()
        except Exception:
            traceback.print_exc(file=sys.stderr)
            try:
                with self._staat:
                    nu = self.klok()
                    verlopen = self.geladen is not None and nu - (self.laatste_ok or 0) > STORINGSMARGE_S
                    if self.geladen is None and self.toestand == 'bezig':
                        self.toestand = 'storing'
                        if self.volgende is None and (not self.geen_poging):
                            self.volgende = nu + HERCONTROLE_S
                if verlopen:
                    self._uitladen('storing')
            except Exception:
                traceback.print_exc(file=sys.stderr)
        finally:
            self._klaar.set()

    def ronde_loopt(self):
        d = self._ronde_draad
        return d is not None and d.is_alive()

    def wacht(self, tijd=10):
        return self._klaar.wait(tijd)

    def _haal(self, heeft=None, weigering=None):
        try:
            return self._haal_ruw(heeft, weigering)
        except Exception:
            traceback.print_exc(file=sys.stderr)
            return 'storing'

    def _haal_ruw(self, heeft, weigering):
        try:
            token = self.aanmelding.token_kern()
        except NietAangemeld:
            return 'niet_aangemeld'
        except ToestemmingNodig:
            return 'toestemming'
        except GeenVerbinding:
            return 'offline'
        uit = self.ophaler.haal(token, heeft=heeft, weigering=weigering)
        if uit.toestand == 'niet_aangemeld':
            try:
                token = self.aanmelding.token_kern(forceer=True)
            except NietAangemeld:
                return 'niet_aangemeld'
            except ToestemmingNodig:
                return 'toestemming'
            except GeenVerbinding:
                return 'offline'
            uit = self.ophaler.haal(token, heeft=heeft)
        return uit

    def _ophalen_en_laden(self):
        with self._staat:
            self.laatste_poging = self.klok()
            sessie = self._sessie
        uit = self._haal()
        if self._sessie != sessie:
            return
        t = uit if isinstance(uit, str) else uit.toestand
        if t == 'pakket':
            self._laad(uit.envelop, sessie)
        elif t in ('offline', 'storing'):
            self._zonder_pakket(t, getattr(uit, 'wacht', None))
        else:
            self._uitladen('storing' if t == 'ingetrokken' else t)
            if t != 'ingetrokken':
                with self._staat:
                    self.volgende = None
            else:
                self._zonder_pakket('storing', None)
        if not isinstance(uit, str) and uit.reden:
            sys.stderr.write(f'koppelstuk: kern {uit.toestand} ({uit.reden})\n')

    def _zonder_pakket(self, toestand, wacht):
        with self._staat:
            self.toestand = toestand
            nu = self.klok()
            if not self._na_retry:
                self._na_retry = True
                self.volgende = nu + (wacht or RETRY_AFTER_S)
            else:
                self.volgende = nu + HERCONTROLE_S

    def _laad(self, envelop, sessie):
        omgeving = Omgeving(self.aanmelding.token_graph, self.transport.verzend)
        try:
            with self._pakketslot:
                if self._sessie != sessie:
                    return
                g = pakket.controleer(envelop, self.sleutels, self.drempel, self.vloer.lees(), self.min_pakket)
                oud = self.geladen
                nieuw = pakket.laad_en_toets(g, omgeving)
                with self._staat:
                    self.geladen = nieuw
                    self.toestand, self.reden = ('geladen', '')
                    self.laatste_ok = self.klok()
                    self.volgende, self._na_retry, self._na_intrekken = (None, False, False)
                if oud is not None and oud.lader is not nieuw.lader:
                    oud.uit()
        except pakket.Weigering as w:
            sys.stderr.write(f'koppelstuk: pakket geweigerd ({w.code})\n')
            if w.code == 'terugrol' and self._na_intrekken:
                self._uitladen('storing')
                self._zonder_pakket('storing', None)
                return
            with self._staat:
                self.geen_poging = True
            self._uitladen('controle', w.code)
            self._meld_weigering(envelop, w.code)
            return
        except pakket.LaderTeOud:
            self._uitladen('te_oud')
            return
        try:
            self.vloer.schrijf(g.versie, g.sha256)
        except OSError as e:
            sys.stderr.write(f'koppelstuk: vloer niet bijgewerkt ({type(e).__name__})\n')
        self._meld()

    def _meld_weigering(self, envelop, code):
        v = envelop.get('versie') if isinstance(envelop, dict) else None
        try:
            self.ophaler.haal(self.aanmelding.token_kern(), heeft=v if pakket.versie(v) else MIN_PAKKET, weigering=code)
        except Exception:
            pass

    def _uitladen(self, toestand, reden='', meld=True):
        with self._pakketslot:
            with self._staat:
                oud, self.geladen = (self.geladen, None)
                self.toestand, self.reden = (toestand, reden)
            if oud is not None:
                oud.uit()
        if meld:
            self._meld()

    def _hercontrole(self):
        g = self.geladen
        if g is None:
            return
        with self._staat:
            self.laatste_poging = self.klok()
            sessie = self._sessie
        uit = self._haal(heeft=g.versie)
        if self._sessie != sessie:
            return
        t = uit if isinstance(uit, str) else uit.toestand
        if t == 'ok':
            with self._staat:
                self.laatste_ok = self.klok()
                self.nieuwste = uit.nieuwste
        elif t in ('licentie', 'toegang', 'niet_aangemeld', 'toestemming', 'te_oud'):
            self._uitladen(t)
            with self._staat:
                self.volgende = None
        elif t == 'ingetrokken':
            with self._staat:
                self._na_intrekken = True
            self._uitladen('bezig', meld=False)
            self._ophalen_en_laden()
            self._meld()
        elif self.klok() - (self.laatste_ok or 0) > STORINGSMARGE_S:
            toestand = 'offline' if t == 'offline' else 'storing'
            self._uitladen(toestand)
            self._zonder_pakket(toestand, getattr(uit, 'wacht', None))

    def tik(self):
        if self.ronde_loopt() or self.aanmelding.bezig():
            return
        nu = self.klok()
        if self.geladen is not None:
            if nu - (self.laatste_poging or 0) >= HERCONTROLE_S or nu - (self.laatste_ok or 0) > STORINGSMARGE_S:
                self._ronde(self._hercontrole, achtergrond=False)
        elif self.volgende is not None and nu >= self.volgende and (not self.geen_poging) and self.aanmelding.aangemeld():
            with self._staat:
                self.volgende = None
            self._ronde(self._ophalen_en_laden, achtergrond=False)

    def _na_aanmelden(self):
        with self._staat:
            self._na_retry = False
            self.volgende = None
            geladen = self.geladen is not None
        if not geladen and (not self.geen_poging):
            self._ronde(self._ophalen_en_laden)

    def _probeer_handmatig(self):
        if self.geladen is not None or self.geen_poging or (not self.aanmelding.aangemeld()):
            return
        if not self.ronde_loopt():
            nu = self.klok()
            with self._staat:
                if self._handmatig is not None and nu - self._handmatig < HANDMATIG_PER_S:
                    return
                self._handmatig = nu
            self._ronde(self._ophalen_en_laden)
        self._klaar.wait(self.wacht_lijst)

    def lijst(self):
        with self._staat:
            return LADER_TOOLDEFS + (list(self.geladen.tools) if self.geladen else [])

    def _tools_list(self):
        if self.geladen is None and self.ronde_loopt():
            self._klaar.wait(self.wacht_lijst)
        with self._staat:
            lijst = self.lijst()
            self._gemeld, self._melding_uit = (_vingerafdruk(lijst), False)
        return {'tools': lijst}

    def _meld(self):
        with self._staat:
            if self._gemeld is None or self._melding_uit or _vingerafdruk(self.lijst()) == self._gemeld:
                return
            self._melding_uit = True
        self.schrijf({'jsonrpc': '2.0', 'method': 'notifications/tools/list_changed'})

    def _zin(self):
        with self._staat:
            toestand, reden = (self.toestand, self.reden)
        if toestand == 'controle':
            return ZINNEN['controle'].format(reden=reden.upper())
        if not self.aanmelding.aangemeld() and toestand != 'toestemming':
            return ZINNEN['aanmelden']
        return ZINNEN[ZIN_BIJ.get(toestand, 'storing')]

    def status_tekst(self):
        if self.aanmelding.bezig():
            return 'Aanmelden loopt: rond het af in de browser.'
        g, wie = (self.geladen, self.aanmelding.gegevens())
        if g is None:
            zin = self._zin()
            if wie['account'] and self.aanmelding.aangemeld() and (self.toestand != 'niet_aangemeld'):
                return f"Aangemeld als {wie['account']}. {zin}"
            return zin
        tekst = f"Aangemeld als {wie['account'] or '?'} (organisatie {wie['tenant'] or '?'}). Koppelstuk {g.versie} met lader {LADER_VERSIE}. Laatste controle: {_cet(self.laatste_ok)} (Nederlandse tijd)."
        n = pakket.versie(self.nieuwste)
        if n and n > pakket.versie(g.versie):
            tekst += f' Versie {self.nieuwste} staat klaar; die geldt vanaf een nieuwe sessie.'
        return tekst

    def roep(self, naam, args):
        if naam == 'aanmelden':
            return self._tool_aanmelden()
        if naam == 'aanmeldstatus':
            self._probeer_handmatig()
            return _tekst(self.status_tekst())
        if naam == 'afmelden':
            return self._tool_afmelden()
        if self.geladen is None and self.ronde_loopt():
            self._klaar.wait(self.wacht_lijst)
        opnieuw = False
        with self._pakketslot:
            g = self.geladen
            if g is None:
                return _tekst(self._zin(), fout=True)
            schema = {t['name']: t['inputSchema'] for t in g.tools}.get(naam)
            if schema is None:
                return _tekst(f'Onbekende tool: {str(naam)[:80]}', fout=True)
            if args is None:
                args = {}
            if not isinstance(args, dict):
                return _tekst('De argumenten moeten een object zijn.', fout=True)
            onbekend = set(args) - set(schema.get('properties', {}))
            if onbekend:
                return _tekst(f"Onbekende velden: {', '.join(sorted(onbekend))}", fout=True)
            ontbreekt = [v for v in schema.get('required', []) if args.get(v) in (None, '', [])]
            if ontbreekt:
                return _tekst(f"Verplicht: {', '.join(ontbreekt)}", fout=True)
            try:
                uit = g.toolset.roep(naam, dict(args))
                if not isinstance(uit, dict) or not isinstance(uit.get('content'), list) or (not isinstance(uit.get('isError', False), bool)):
                    raise TypeError('antwoord van het pakket')
                return uit
            except NietAangemeld:
                opnieuw = True
            except ToestemmingNodig:
                return _tekst(ZINNEN['toestemming'], fout=True)
            except GeenVerbinding:
                return _tekst(ZINNEN['offline'], fout=True)
            except TransportGeweigerd:
                return _tekst(ZINNEN['grens'], fout=True)
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                return _tekst(f'Onverwachte fout in het koppelstuk: {type(e).__name__}', fout=True)
        if opnieuw:
            self._uitladen('niet_aangemeld')
            return _tekst(ZINNEN['opnieuw'], fout=True)

    def _tool_aanmelden(self):
        status, url = self.aanmelding.start(wacht=self.wacht_aanmelden, na=self._na_aanmelden)
        if status == 'loopt':
            return _tekst(ZINNEN['browser'].format(url=url))
        if status == 'fout':
            soort, code = self.aanmelding.fout or ('mislukt', '')
            if soort in ('toestemming', 'offline'):
                return _tekst(ZINNEN[soort], fout=True)
            return _tekst(ZINNEN['mislukt'].format(code=f', {code}' if code else ''), fout=True)
        if self.geladen is None and self.ronde_loopt():
            self._klaar.wait(self.wacht_lijst)
        return _tekst(self.status_tekst() + ' ' + ZINNEN['nieuwe_sessie'])

    def _tool_afmelden(self):
        with self._staat:
            self._sessie += 1
        self._uitladen('niet_aangemeld')
        self.aanmelding.afmelden()
        with self._staat:
            self.volgende = self._handmatig = self.nieuwste = None
        return _tekst(ZINNEN['afgemeld'])

    def behandel(self, bericht):
        if not isinstance(bericht, dict) or bericht.get('id') is None or 'method' not in bericht:
            return None
        methode, id_ = (bericht.get('method'), bericht.get('id'))
        params = bericht.get('params') if isinstance(bericht.get('params'), dict) else {}
        if methode == 'initialize':
            gevraagd = params.get('protocolVersion')
            resultaat = {'protocolVersion': gevraagd if gevraagd in PROTOCOLLEN else PROTOCOLLEN[0], 'capabilities': {'tools': {'listChanged': True}}, 'serverInfo': {'name': 'koppelstuk', 'title': 'M-IT Koppelstuk', 'version': LADER_VERSIE}, 'instructions': INSTRUCTIES}
        elif methode == 'ping':
            resultaat = {}
        elif methode == 'tools/list':
            resultaat = self._tools_list()
        elif methode == 'tools/call':
            resultaat = self.roep(params.get('name'), params.get('arguments'))
        else:
            return {'jsonrpc': '2.0', 'id': id_, 'error': {'code': -32601, 'message': 'Onbekende methode'}}
        return {'jsonrpc': '2.0', 'id': id_, 'result': resultaat}

    def schrijf(self, antwoord):
        with self._schrijfslot:
            self._uit.write(json.dumps(antwoord, ensure_ascii=False) + '\n')
            self._uit.flush()

    def _werk(self, bericht):
        try:
            antwoord = self.behandel(bericht)
        except Exception:
            traceback.print_exc(file=sys.stderr)
            antwoord = {'jsonrpc': '2.0', 'id': bericht.get('id'), 'error': {'code': -32603, 'message': 'Interne fout'}}
        if antwoord is not None:
            self.schrijf(antwoord)

    def draai(self, invoer=None, nawacht=10):
        invoer = invoer or sys.stdin
        werk = []
        for regel in invoer:
            regel = regel.strip()
            if not regel:
                continue
            try:
                bericht = json.loads(regel)
            except ValueError:
                self.schrijf({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Geen geldige JSON'}})
                continue
            for b in bericht if isinstance(bericht, list) else [bericht]:
                if isinstance(b, dict) and b.get('method') in ('tools/list', 'tools/call') and (b.get('id') is not None):
                    draad = threading.Thread(target=self._werk, args=(b,), daemon=True, name='koppelstuk-werk')
                    draad.start()
                    werk = [w for w in werk if w.is_alive()] + [draad]
                else:
                    self._werk(b)
        eind = time.monotonic() + nawacht
        for w in werk:
            w.join(max(0.0, eind - time.monotonic()))

def main():
    sys.stdout.reconfigure(encoding='utf-8', newline='\n')
    sys.stdin.reconfigure(encoding='utf-8')
    sessie = Sessie()
    sessie.start()
    sessie.draai()
