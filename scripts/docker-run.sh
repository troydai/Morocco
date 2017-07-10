#!/usr/bin/env bash

root=$(cd $(dirname $0);cd ..&& pwd)
version=`cat ${root}/VERSION`
image=morocco-automation:${version}.dev
container=morocco-local-${version}.dev

docker rm -f ${container} 2>&1
docker run -d --name ${container} -p 80:80 ${image}

