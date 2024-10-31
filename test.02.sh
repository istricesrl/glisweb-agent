#!/bin/bash

# elimino il log
rm -f ./*.log

# avvio il server
/bin/python3 /home/fabio/glisweb-agent/glisweb-agent.py

# creo il processo
value=$( curl -X POST http://localhost:5000/getwebcamdoc -H "Content-Type: application/json" -d '{"comando":"test"}' )

# ricavo il valore di process_id dal json
process_id=$( echo $value | jq '.process_id' )
