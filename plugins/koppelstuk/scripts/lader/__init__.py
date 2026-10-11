# -*- coding: utf-8 -*-
# (c) M-IT Services. Gebruik alleen volgens de licentievoorwaarden.
LADER_VERSIE = '1.0.0'
API = 1
MIN_PAKKET = '0.4.0'
CLIENT_ID = '8bccc79f-c515-4c69-8f1c-c71754125a07'
LOGIN = 'https://login.microsoftonline.com'
KERN_SCOPE = 'https://core.mitservices.nl/mcp/brein.gebruik'
PAKKET_URL = 'https://core.mitservices.nl/koppelstuk/v1/pakket'
GRAPH_BASIS = 'https://graph.microsoft.com/v1.0/'
SLEUTELS = (bytes.fromhex('fe63cc3dbe135c2fcef05b596c4adc06a3386f36697bc21ac983f516b6a73e2d'),)
DREMPEL = 1
DOMEIN = b'M-IT koppelstuk-pakket v1\n'
HERCONTROLE_S = 15 * 60
STORINGSMARGE_S = 60 * 60
RETRY_AFTER_S = 30
HANDMATIG_PER_S = 60
WACHT_LIJST_S = 8
WACHT_AANMELDEN_S = 45
MAX_ANTWOORD = 2 * 1024 * 1024
MAX_BESTANDEN = 64
MAX_BUNDEL = 2 * 1024 * 1024
TIJD_KERN_S = 20
TIJD_GRAPH_S = 60
LADER_TOOLS = ('aanmelden', 'aanmeldstatus', 'afmelden')
KLIK_VERPLICHT = ('afspraak_inplannen', 'afspraak_verplaatsen', 'afspraak_afzeggen')
ZINNEN = {'aanmelden': 'Je bent nog niet aangemeld voor Koppelingen. Gebruik eerst de tool aanmelden. (KS-AANMELDEN)', 'opnieuw': 'Opnieuw aanmelden nodig. Gebruik de tool aanmelden. (KS-AANMELDEN)', 'mislukt': 'Aanmelden is niet gelukt. Probeer het opnieuw met de tool aanmelden. (KS-AANMELDEN{code})', 'offline': 'Je laptop heeft nu geen verbinding. Outlook via het brein werkt weer zodra die er is. (KS-OFFLINE)', 'storing': 'De kern van M-IT is nu niet bereikbaar, dus Outlook via het brein werkt even niet. Probeer het over een kwartier opnieuw; blijft het zo, meld het dan bij M-IT. (KS-STORING)', 'licentie': 'Koppelingen staan niet aan voor jullie organisatie. Neem contact op met M-IT. (KS-LICENTIE)', 'toegang': 'Je toegang tot het Tweede Brein staat uit. Vraag je kernbeheerder of dat klopt. (KS-TOEGANG)', 'te_oud': 'Je koppelstuk moet worden bijgewerkt. Vraag de servicedesk van M-IT om dat te doen. (KS-TE-OUD)', 'toestemming': 'De toestemming van een beheerder van jullie organisatie ontbreekt nog. De servicedesk van M-IT helpt daarbij. (KS-TOESTEMMING)', 'controle': 'Het koppelstuk is niet gestart, omdat de controle op echtheid niet klopte. Je mail en agenda zijn niet aangeraakt. Meld dit bij M-IT met code KS-CONTROLE-{reden}.', 'start': 'Het koppelstuk start nog. Probeer het over een paar seconden opnieuw. (KS-START)', 'grens': 'Geweigerd door het koppelstuk: deze aanroep naar Microsoft doet het koppelstuk nooit. (KS-GRENS)', 'afgemeld': 'Je bent afgemeld op deze laptop. Er is niets veranderd in je postbus.', 'nieuwe_sessie': 'Zie je de Outlook-tools niet, open dan een nieuwe sessie.', 'browser': 'Er staat een aanmeldvenster van Microsoft open in de browser. Rond het daar af; het koppelstuk wacht nog vijf minuten. Opent er niets, gebruik dan deze link: {url}'}
REDEN_403 = {'geen_koppelingen': 'licentie'}
