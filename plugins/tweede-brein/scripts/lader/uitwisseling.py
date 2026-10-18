# -*- coding: utf-8 -*-
# (c) M-IT Services. Gebruik alleen volgens de licentievoorwaarden.
import os
import stat
import unicodedata
from pathlib import Path
from . import MAX_BESTAND, UITWISSELMAP
from .transport import TeGroot
VERBODEN_TEKENS = frozenset('\\/:*?"<>|')
APPARATEN = frozenset({'con', 'prn', 'aux', 'nul', 'conin$', 'conout$'} | {f'{p}{c}' for p in ('com', 'lpt') for c in '0123456789¹²³'})
VERBODEN_NAMEN = frozenset({'claude.md', 'claude.local.md', 'agents.md'})
UITVOERBAAR = frozenset({'exe', 'dll', 'com', 'bat', 'cmd', 'ps1', 'psm1', 'psd1', 'vbs', 'vbe', 'js', 'jse', 'wsf', 'wsh', 'msi', 'msp', 'lnk', 'scr', 'cpl', 'hta', 'reg', 'pif', 'url', 'jar', 'py', 'pyw', 'sys', 'inf'})
MAX_NAAM = 200
_REPARSE = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024)

class UitwisselFout(ValueError):
    pass

def toets_naam(naam):
    if not isinstance(naam, str) or not naam or len(naam) > MAX_NAAM:
        raise UitwisselFout('Geef een bestandsnaam van hooguit 200 tekens.')
    if any((c in VERBODEN_TEKENS or ord(c) < 32 or ord(c) == 127 or (unicodedata.category(c) == 'Cf') for c in naam)):
        raise UitwisselFout('Een bestandsnaam mag geen \\ / : * ? " < > | of onzichtbare tekens bevatten.')
    if naam in ('.', '..') or naam.startswith('.') or naam.endswith(('.', ' ')):
        raise UitwisselFout('Een bestandsnaam begint niet met een punt en eindigt niet op een punt of spatie.')
    klein = naam.lower()
    if klein.split('.', 1)[0].rstrip(' ') in APPARATEN:
        raise UitwisselFout('Deze bestandsnaam is in Windows gereserveerd. Kies een andere naam.')
    if klein in VERBODEN_NAMEN:
        raise UitwisselFout('Deze bestandsnaam kan niet in de uitwisselmap. Kies een andere naam.')
    if '.' in klein and klein.rsplit('.', 1)[-1] in UITVOERBAAR:
        raise UitwisselFout('Een programma of script kan niet door de uitwisselmap.')
    return naam

def _gelijk(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))

def _onder(pad, ouder):
    pad, ouder = (os.path.normcase(pad), os.path.normcase(ouder))
    try:
        return os.path.commonpath([pad, ouder]) == ouder
    except ValueError:
        return False

def _is_link(st):
    return stat.S_ISLNK(st.st_mode) or bool((getattr(st, 'st_file_attributes', 0) or 0) & _REPARSE)

class Uitwisseling:

    def __init__(self, thuis=None, datamap=None, claude=None):
        self._thuis = thuis
        self._datamap = datamap
        self._claude = claude

    def map_(self):
        thuis = Path(self._thuis) if self._thuis else Path.home()
        m = thuis / UITWISSELMAP
        try:
            os.mkdir(m)
        except FileExistsError:
            pass
        except OSError:
            raise UitwisselFout('De uitwisselmap kan niet worden aangemaakt.') from None
        st = os.lstat(m)
        if _is_link(st) or not stat.S_ISDIR(st.st_mode):
            raise UitwisselFout('De uitwisselmap is een koppeling of geen gewone map. Meld dit bij M-IT.')
        echt = os.path.realpath(m)
        if not _gelijk(echt, os.path.join(os.path.realpath(thuis), UITWISSELMAP)):
            raise UitwisselFout('De uitwisselmap is een koppeling of geen gewone map. Meld dit bij M-IT.')
        verboden = [self._claude or thuis / '.claude', os.environ.get('CLAUDE_CONFIG_DIR'), self._datamap]
        for v in verboden:
            if v and _onder(echt, os.path.realpath(v)):
                raise UitwisselFout('De uitwisselmap ligt op een plek waar hij niet mag liggen. Meld dit bij M-IT.')
        return m

    def lees(self, naam):
        toets_naam(naam)
        m = self.map_()
        pad = m / naam
        try:
            st = os.lstat(pad)
        except FileNotFoundError:
            raise UitwisselFout(f'Er staat geen bestand {naam} in de uitwisselmap.') from None
        if _is_link(st) or not stat.S_ISREG(st.st_mode):
            raise UitwisselFout('Dit is geen gewoon bestand in de uitwisselmap.')
        if not _gelijk(os.path.dirname(os.path.realpath(pad)), os.path.realpath(m)):
            raise UitwisselFout('Dit bestand staat niet direct in de uitwisselmap.')
        if st.st_nlink != 1:
            raise UitwisselFout('Dit bestand heeft een tweede naam elders (hardlink). Kopieer het eerst.')
        if st.st_size > MAX_BESTAND:
            raise TeGroot('uitwisselmap')
        with open(pad, 'rb') as f:
            nu = os.fstat(f.fileno())
            if (nu.st_ino, nu.st_dev) != (st.st_ino, st.st_dev) or nu.st_nlink != 1:
                raise UitwisselFout('Het bestand veranderde tijdens het lezen. Probeer het opnieuw.')
            data = f.read(MAX_BESTAND + 1)
        if len(data) > MAX_BESTAND:
            raise TeGroot('uitwisselmap')
        return data

    def schrijf(self, naam, data):
        toets_naam(naam)
        if not isinstance(data, (bytes, bytearray)):
            raise UitwisselFout('Alleen bytes kunnen in de uitwisselmap.')
        if len(data) > MAX_BESTAND:
            raise TeGroot('uitwisselmap')
        m = self.map_()
        stam, punt, ext = naam.rpartition('.')
        if not punt:
            stam, ext = (naam, '')
        for n in range(1, 100):
            kandidaat = naam if n == 1 else f'{stam} ({n}){punt}{ext}'
            if len(kandidaat) > MAX_NAAM:
                break
            pad = m / kandidaat
            try:
                with open(pad, 'xb') as f:
                    f.write(data)
            except FileExistsError:
                continue
            return str(pad)
        raise UitwisselFout('Er staan al te veel bestanden met deze naam in de uitwisselmap. Ruim hem eerst op.')
