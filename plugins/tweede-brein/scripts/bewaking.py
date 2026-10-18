# -*- coding: utf-8 -*-
# (c) M-IT Services. Gebruik alleen volgens de licentievoorwaarden.
import json
import re
import sys
from lader import CLIENT_ID, DATA_PATROON, MARKTPLAATS, UITPAKMAP
MELDING = 'Dit is niet toegestaan volgens de licentievoorwaarden van het Tweede Brein van M-IT Services. Heb je een vraag over de werking? Neem contact op met de servicedesk van M-IT.'
DOEL = '(tweede\\s*brein|koppelstuk|koppeling(en)?|plugin|kernserver|\\bkern\\b|\\bmcp\\b|connector|\\bm-?it\\b|\\blader\\b)'
HANDELING = '(na\\s*(te\\s*)?bouwen|nabouw|na\\s*te\\s*maken|namaken|ontleed|ontleden|reverse[\\s-]*engineer|decompil|disassembl|broncode|source\\s*code|de\\s+code\\s+(van|achter)|code\\s+(laten\\s+)?zien|toon\\s+(de\\s+|je\\s+)?(code|instructies|prompt)|kopieer\\s+(de\\s+)?(code|plugin|instructies)|zelf\\s+(bouwen|maken)|zonder\\s+licentie|gratis\\s+(gebruiken|verder)|rebuild|replicate|clone)'
PROMPT_TREFFER = re.compile(f'{HANDELING}.{{0,80}}{DOEL}|{DOEL}.{{0,80}}{HANDELING}|\\b(bouw|maak)\\w*\\b.{{0,80}}{DOEL}.{{0,40}}\\bna\\b', re.I | re.S)
MIDDEL = re.compile('\\b(via|met|vanuit|gebruik)\\s+(de\\s+|het\\s+)?koppelingen\\b', re.I)
CODEWOORD = re.compile('(broncode(?![-\\w])|source\\s*code|de\\s+code\\s+(van|achter)|code\\s+(laten\\s+)?zien|toon\\s+(de\\s+|je\\s+)?code|decompil|disassembl|reverse[\\s-]*engineer|ontle(ed|den)\\s+hoe)', re.I)
PADEN = re.compile('|'.join((f'plugins[\\\\/]+cache[\\\\/]+{re.escape(MARKTPLAATS)}', 'plugins[\\\\/]+data[\\\\/]+koppelstuk', DATA_PATROON, re.escape(UITPAKMAP), 'mit-koppelstuk', f'marketplaces[\\\\/]+{re.escape(MARKTPLAATS)}', 'M-IT[\\\\/]+Koppelstuk')), re.I)
CLIENT = re.compile(re.escape(CLIENT_ID.split('-')[0]), re.I)
TOEGANG_VELDEN = ('command', 'url', 'file_path', 'path', 'notebook_path')

def prompt(invoer):
    tekst = str(invoer.get('prompt') or '')
    if not CODEWOORD.search(tekst):
        tekst = MIDDEL.sub(' hulpmiddel ', tekst)
    if PROMPT_TREFFER.search(tekst):
        return {'decision': 'block', 'reason': MELDING}
    return None

def _toegang(ti):
    if not isinstance(ti, dict):
        return json.dumps(ti, ensure_ascii=False)
    return json.dumps([ti.get(v) for v in TOEGANG_VELDEN], ensure_ascii=False)

def tool(invoer):
    ti = invoer.get('tool_input') or {}
    inhoud = json.dumps(ti, ensure_ascii=False)
    if PADEN.search(inhoud) or CLIENT.search(_toegang(ti)):
        return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': MELDING}}
    return None

def main():
    soort = sys.argv[1] if len(sys.argv) > 1 else ''
    try:
        invoer = json.loads(sys.stdin.read() or '{}')
    except ValueError:
        return 0
    uit = {'prompt': prompt, 'tool': tool}.get(soort, lambda i: None)(invoer)
    if uit:
        sys.stdout.write(json.dumps(uit, ensure_ascii=False))
    return 0
if __name__ == '__main__':
    sys.exit(main())
