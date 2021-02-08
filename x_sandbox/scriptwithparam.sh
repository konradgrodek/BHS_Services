#!/bin/bash

if [ -z $1 ]; then
  echo "The argument is required"
  exit
fi

echo Script name is $0
echo "Param1 is $1"
echo 'Param1 is ' $1
echo 'HOST NAME is '$HOSTNAME
echo 'PATH: '$PATH

