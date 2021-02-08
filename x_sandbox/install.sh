#!/bin/bash

if [ -z $1 ]; then
  echo "Missing required parameter service-name"
  echo "Usage: ./install.ch servicename"
  exit 1
fi

echo "Installing service "$1

echo "1. Stopping and disabling service - it may throw an error if this is initial installation"
sudo systemctl stop $1.service
sudo systemctl disable $1.service

echo "2. Copying python scripts to target dir"
sudo cp -u -v BHSCore.py /usr/local/bin
sudo cp -u -v $1.py /usr/local/bin

echo "3. Copying configuration file and creating target dir if necessary"
sudo mkdir -p -v /etc/bhs
sudo cp -u -v $1.config /etc/bhs

echo "4. Ensuring log folder exists"
sudo mkdir -p -v /var/log/bhs

echo "5. Making the script executable"
sudo chmod -v u+x /usr/local/bin/$1.py

echo "6. Copying service definition"
sudo cp -u $1.service /etc/systemd/system

echo "7. Updating list of daemons"
sudo systemctl daemon-reload
sudo systemctl enable $1.service

#echo "8. Immediately start the service"
#sudo systemctl start $1.service

echo "All done!"
exit 0


