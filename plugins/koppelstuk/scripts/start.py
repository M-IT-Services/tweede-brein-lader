# -*- coding: utf-8 -*-
# (c) M-IT Services. Gebruik alleen volgens de licentievoorwaarden.
import os
import sys
if sys.version_info < (3, 11):
    sys.stderr.write('Het koppelstuk vraagt Python 3.11 of nieuwer.\n')
    sys.exit(1)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lader.mcp import main
main()
