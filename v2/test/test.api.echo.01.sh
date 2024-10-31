#!/bin/bash

# chiamo il server
value=$( curl -X POST http://localhost:5000/echo -H "Content-Type: application/json" -d '{"comando":"test"}' )

# gestisco la risposta
status=$( echo $value | jq '.status' | tr -d '"' )
comando=$( echo $value | jq '.comando' | tr -d '"' )

# debug
echo $status
echo $comando
