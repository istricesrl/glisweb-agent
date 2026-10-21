#!/bin/bash

# creo il processo
value=$( curl -s -X POST http://localhost:5000/testjobstart -H "Content-Type: application/json" -d '{"comando":"test"}' )

# ricavo il valore di process_id dal json
process_id=$( echo $value | jq '.process_id' )

# debug
echo $process_id

# faccio un ciclo fimnché nel json di ritorno non trovo lo status completed
while [ "$status" != "completed" ]; do

    # chiedo lo stato del processo
    value=$( curl -s -X POST http://localhost:5000/testjobstatus -H "Content-Type: application/json" -d '{"comando":"status","process_id":'$process_id'}' )

    # ricavo lo status dal json
    status=$( echo $value | jq '.status' )
    elapsed=$( echo $value | jq '.elapsed' )

    # rimuovo le virgolette
    status=$( echo $status | tr -d '"' )
    elapsed=$( echo $elapsed | tr -d '"' )

    # debug
    echo $status
    echo $elapsed

    # attendo
    sleep 1

done
