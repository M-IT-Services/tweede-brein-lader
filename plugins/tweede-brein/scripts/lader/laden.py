# -*- coding: utf-8 -*-
# (c) M-IT Services. Gebruik alleen volgens de licentievoorwaarden.
import importlib
import importlib.abc
import importlib.util
import sys
import threading
NAAM = 'koppelstuk'
_SLOT = threading.Lock()

class GeheugenLader(importlib.abc.MetaPathFinder, importlib.abc.InspectLoader):

    def __init__(self, bestanden, naam=NAAM):
        self.naam = naam
        self._code = {}
        for pad, bron in sorted(bestanden.items()):
            delen = pad[:-3].split('/') if pad.endswith('.py') else []
            if len(delen) != 2 or delen[0] != naam or (not delen[1].isidentifier()):
                raise ValueError(f'ongeldige bestandsnaam in het pakket: {pad!r}')
            is_pakket = delen[1] == '__init__'
            modnaam = naam if is_pakket else f'{naam}.{delen[1]}'
            self._code[modnaam] = (compile(bron, f'<{modnaam}>', 'exec', dont_inherit=True), is_pakket)
        if naam not in self._code:
            raise ValueError('het pakket heeft geen __init__.py')

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self.naam and (not fullname.startswith(self.naam + '.')):
            return None
        if fullname not in self._code:
            raise ModuleNotFoundError(f'No module named {fullname!r}', name=fullname)
        return importlib.util.spec_from_loader(fullname, self, origin=f'<{fullname}>', is_package=self._code[fullname][1])

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        exec(self._code[module.__spec__.name][0], module.__dict__)

    def get_code(self, fullname):
        return self._code[fullname][0]

    def get_source(self, fullname):
        return None

    def is_package(self, fullname):
        return self._code[fullname][1]

    def modules(self):
        return sorted(self._code)

def _weg(naam):
    sys.meta_path[:] = [f for f in sys.meta_path if not (isinstance(f, GeheugenLader) and f.naam == naam)]
    for m in [m for m in sys.modules if m == naam or m.startswith(naam + '.')]:
        del sys.modules[m]

def laad(bestanden, naam=NAAM):
    lader = GeheugenLader(bestanden, naam)
    with _SLOT:
        _weg(naam)
        sys.meta_path.insert(0, lader)
        try:
            module = importlib.import_module(naam)
            if getattr(module, '__spec__', None) is None or module.__spec__.loader is not lader:
                raise ImportError('het pakket kwam niet uit het geheugen')
        except BaseException:
            _weg(naam)
            raise
    return (lader, module)

def uitladen(lader):
    if lader is None:
        return
    with _SLOT:
        if lader in sys.meta_path:
            sys.meta_path.remove(lader)
        for m in [m for m in sys.modules if m == lader.naam or m.startswith(lader.naam + '.')]:
            if getattr(getattr(sys.modules[m], '__spec__', None), 'loader', None) is lader:
                del sys.modules[m]
