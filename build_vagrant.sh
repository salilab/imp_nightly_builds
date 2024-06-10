#!/bin/bash

# Build IMP using the build.sh script within a Vagrant VM.
# Run from crontab.

BUILD=$(dirname $0)

# Vagrant VMs should have been built using Vagrantfiles in INT/vagrant/
# and be set up so that "vagrant ssh" uses the "autobuild" user
VAGRANT=$1
shift

LOGFILE=$1
shift

# Find directory containing Vagrantfile
VAGRANT_DIR=$(vagrant global-status |grep $VAGRANT|awk '{print $NF}')
cd $VAGRANT_DIR && \
  vagrant up > /dev/null && \
  vagrant ssh -c "ls /salilab/diva1/ > /dev/null 2>&1; sleep 30" && \
  vagrant ssh -c "${BUILD}/build.sh $* > ${LOGFILE} 2>&1" || : && \
  vagrant halt > /dev/null
