#!/bin/bash

# creo il processo
value=$( curl -s -X POST http://localhost:5000/testopenwindow -H "Content-Type: application/json" -d '{"comando":"test"}' )

# ricavo lo status dal json
status=$( echo $value | jq '.status' | tr -d '"' )

# debug
echo $status
