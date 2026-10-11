# -*- coding: utf-8 -*-
# Gebaseerd op RFC 8032, sectie 6 (c) IETF Trust, Simplified BSD License; zie NOTICE.
# Aanpassingen (c) M-IT Services. Gebruik alleen volgens de licentievoorwaarden.
import hashlib
P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493

def _inv(x):
    return pow(x, P - 2, P)
D = -121665 * _inv(121666) % P
_WORTEL_MIN1 = pow(2, (P - 1) // 4, P)

def _x(y, teken):
    if y >= P:
        return None
    x2 = (y * y - 1) * _inv(D * y * y + 1) % P
    if x2 == 0:
        return None if teken else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * _WORTEL_MIN1 % P
    if (x * x - x2) % P:
        return None
    if x & 1 != teken:
        x = P - x
    return x

def _punt(b):
    y = int.from_bytes(b, 'little')
    teken = y >> 255
    y &= (1 << 255) - 1
    x = _x(y, teken)
    if x is None:
        return None
    return (x, y, 1, x * y % P)

def _plus(a, b):
    e1 = (a[1] - a[0]) * (b[1] - b[0]) % P
    e2 = (a[1] + a[0]) * (b[1] + b[0]) % P
    c = 2 * a[3] * b[3] * D % P
    d = 2 * a[2] * b[2] % P
    e, f, g, h = (e2 - e1, d - c, d + c, e2 + e1)
    return (e * f % P, g * h % P, f * g % P, e * h % P)

def _maal(s, q):
    r = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            r = _plus(r, q)
        q = _plus(q, q)
        s >>= 1
    return r

def _gelijk(a, b):
    return (a[0] * b[2] - b[0] * a[2]) % P == 0 and (a[1] * b[2] - b[1] * a[2]) % P == 0
_BY = 4 * _inv(5) % P
B = (_x(_BY, 0), _BY, 1, _x(_BY, 0) * _BY % P)

def verify(sleutel, handtekening, bericht):
    if not all((isinstance(w, bytes) for w in (sleutel, handtekening, bericht))):
        raise TypeError('sleutel, handtekening en bericht moeten bytes zijn')
    if len(sleutel) != 32:
        raise ValueError('een Ed25519-sleutel is 32 bytes')
    if len(handtekening) != 64:
        raise ValueError('een Ed25519-handtekening is 64 bytes')
    a = _punt(sleutel)
    if a is None:
        return False
    r = _punt(handtekening[:32])
    if r is None:
        return False
    s = int.from_bytes(handtekening[32:], 'little')
    if s >= L:
        return False
    k = int.from_bytes(hashlib.sha512(handtekening[:32] + sleutel + bericht).digest(), 'little') % L
    return _gelijk(_maal(s, B), _plus(r, _maal(k, a)))
