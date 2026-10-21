#!/bin/bash

# creo il processo
value=$( curl -s -X POST http://localhost:5000/getwebcamdoc -H "Content-Type: application/json" -d '{"comando":"test"}' )

# ricavo il valore di process_id dal json
process_id=$( echo $value | jq '.process_id' )

# debug
echo $process_id
