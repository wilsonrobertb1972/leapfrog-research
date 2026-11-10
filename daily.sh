#!/bin/bash
cd ~/Desktop/leapfrog-research && source venv/bin/activate
python3 paper_trader.py
python3 paper_trader_4slot.py
D=backups/$(date +%F); mkdir -p "$D"
cp -f paper_state*.json paper_log*.csv "$D"/ 2>/dev/null
python3 report.py
