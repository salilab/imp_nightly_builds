[![build](https://github.com/salilab/imp_nightly_builds/actions/workflows/build.yml/badge.svg)](https://github.com/salilab/imp_nightly_builds/actions/workflows/build.yml)
[![codecov](https://codecov.io/gh/salilab/imp_nightly_builds/branch/main/graph/badge.svg)](https://codecov.io/gh/salilab/imp_nightly_builds)

This repository contains the scripts used internally by the Sali Lab
to build IMP in a variety of operating systems (different versions of macOS,
Windows, Linux) and environments (e.g. debug, release, static builds).

 - `build_config.sh.in` is used to configure the scripts for your environment.
   First copy it to `build_config.sh` and set the variables in the script
   appropriately.
 - `setup_build.sh` gets a nightly snapshot of the IMP source code and puts
   both it and the rest of the build scripts on a network-accessible disk so
   that all build hosts can see it.
 - `build.sh` is designed to be run by build hosts (bare metal, containers,
   or VMs) to build, test and deploy IMP.
 - `build_vagrant.sh` is a utility script to start up a virtual machine using
   [Vagrant](https://www.vagrantup.com/), run the `build.sh` script, and
   then stop the VM.
 - `check_build_dir.py` can be run in the top-level install directory to
   check on the status of a currently running build (for example, to check
   if some `build.sh` runs failed and need to be restarted).
 - `check_build.py` collates the results from all of the `build.sh` runs
   and stores them in a database, and notifies the IMP developers by email.
 - the `www` subdirectory contains a simple Flask app that powers the
   https://integrativemodeling.org/nightly/results/ website, by taking
   data from the database.
