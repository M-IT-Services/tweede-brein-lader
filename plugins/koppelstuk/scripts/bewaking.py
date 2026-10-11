# -*- coding: utf-8 -*-
# (c) M-IT Services. Gebruik alleen volgens de licentievoorwaarden.
import json
import re
import sys
MELDING = 'Dit is niet toegestaan volgens de licentievoorwaarden van het Tweede Brein van M-IT Services. Heb je een vraag over de werking? Neem contact op met de servicedesk van M-IT.'
DOEL = '(tweede\\s*brein|koppelstuk|koppeling(en)?|plugin|kernserver|\\bkern\\b|\\bmcp\\b|connector|\\bm-?it\\b|\\blader\\b)'
HANDELING = '(na\\s*(te\\s*)?bouwen|nabouw|na\\s*te\\s*maken|namaken|ontleed|ontleden|reverse[\\s-]*engineer|decompil|disassembl|broncode|source\\s*code|de\\s+code\\s+(van|achter)|code\\s+(laten\\s+)?zien|toon\\s+(de\\s+|je\\s+)?(code|instructies|prompt)|kopieer\\s+(de\\s+)?(code|plugin|instructies)|zelf\\s+(bouwen|maken)|zonder\\s+licentie|gratis\\s+(gebruiken|verder)|rebuild|replicate|clone)'
PROMPT_TREFFER = re.compile(f'{HANDELING}.{{0,80}}{DOEL}|{DOEL}.{{0,80}}{HANDELING}|\\b(bouw|maak)\\w*\\b.{{0,80}}{DOEL}.{{0,40}}\\bna\\b', re.I | re.S)
PADEN = re.compile('(plugins[\\\\/]+cache[\\\\/]+m-it|plugins[\\\\/]+data[\\\\/]+koppelstuk|koppelstuk-bron|mit-koppelstuk|marketplaces[\\\\/]+m-it|M-IT[\\\\/]+Koppelstuk)', re.I)

def prompt(invoer):
    tekst = str(invoer.get('prompt') or '')
    if PROMPT_TREFFER.search(tekst):
        return {'decision': 'block', 'reason': MELDING}
    return None

def tool(invoer):
    inhoud = json.dumps(invoer.get('tool_input') or {}, ensure_ascii=False)
    if PADEN.search(inhoud):
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
