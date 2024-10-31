#!/bin/bash

# elimino il log
rm -f ./*.log

# uccido i processi esistenti
pkill -f glisweb

# avvio il server
/bin/python3 /home/fabio/glisweb-agent/glisweb-agent.py

# creo il processo
value=$( curl -X POST http://localhost:5000/getwebcamdoc -H "Content-Type: application/json" -d '{"comando":"test"}' )

# ricavo il valore di process_id dal json
process_id=$( echo $value | jq '.process_id' )

# faccio un ciclo fimnché nel json di ritorno non trovo lo status completed
while [ "$status" != "completed" ]; do

    # chiedo lo stato del processo
    value=$( curl -X POST http://localhost:5000/getwebcamdocname -H "Content-Type: application/json" -d '{"comando":"status","process_id":'$process_id'}' )

    # ricavo lo status dal json
    status=$( echo $value | jq '.status' )

    # rimuovo le virgolette
    status=$( echo $status | tr -d '"' )

    # debug
    echo $status

    # attendo
    sleep 1

done
