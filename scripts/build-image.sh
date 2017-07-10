#!/usr/bin/env bash

root=$(cd $(dirname $0);cd ..&& pwd)
version=`cat ${root}/VERSION`
tag=morocco-automation:${version}.dev

docker build -t ${tag} ${root}
