#!/bin/bash

# Build some part of IMP from source code.

# First argument is the platform to build (can be multiple space-separated
# platforms, if desired).
# Remaining arguments are the branches to build (e.g. main, develop)

# Get common functions
. `dirname $0`/build_functions.sh

TAR=tar
TMPDIR=/tmp/nightly-build-$$
# /tmp can be rather small in Docker containers, so use /var/tmp instead
if [ -e /.dockerenv ]; then
  TMPDIR=/var/tmp/nightly-build-$$
  # make dpkg-deb use /var/tmp too
  export TMPDIR
fi

# crontab doesn't usually set up compilers, etc. for us
. /etc/profile

# Workaround failure to set up modules in Fedora 34 containers
# (/etc/profile does not source modules.sh because
# [ -r /etc/profile.d/modules.sh ] returns false)
if [ -f /etc/profile.d/sali-modules.sh ] && ! module avail >& /dev/null; then
  . /etc/profile.d/modules.sh
  . /etc/profile.d/sali-modules.sh
fi

# Use GNU make and tar (in /usr/local/bin on Sun, /usr/freeware/bin on IRIX,
# and /usr/linux/bin on AIX);
# add MacPorts path (/opt/local/bin) for 7za on our Macs;
# and make sure we can find xlc on AIX
PATH="/opt/homebrew/bin:/usr/local/bin:/usr/freeware/bin:/usr/linux/bin:/opt/local/bin:${PATH}:/usr/vac/bin"

# Make sure that log files are world-readable
umask 0022

host=`hostname`
case $host in
# Use scratch disks on cluster nodes
  o64*|node*)
    TMPDIR=/scratch/nightly-build-$$
    ;;
# Use larger /var partition on clarinet
  clarinet*)
    TMPDIR=/var/tmp/nightly-build-$$
    ;;
esac

if [ $# -lt 2 ]; then
  echo "Usage: $0 platform branch [branch...]"
  exit 1
fi

do_build() {
  PLATFORM=$1
  BRANCH=$2
  if [ -d $HOME/diva1/home/imp ]; then
    IMPINSTALL=`readlink $HOME/diva1/home/imp/${BRANCH}/.SVN-new | sed -e "s,/salilab,$HOME,"`
  else
    IMPINSTALL=`readlink /salilab/diva1/home/imp/${BRANCH}/.SVN-new`
  fi

  # Skip non-develop build if nothing has changed
  if [ ${BRANCH} != "develop" ]; then
    if [ -d $HOME/diva1/home/imp ]; then
      OLD_IMPINSTALL=`readlink $HOME/diva1/home/imp/${BRANCH}/lastbuild | sed -e "s,/salilab,$HOME,"`
    else
      OLD_IMPINSTALL=`readlink /salilab/diva1/home/imp/${BRANCH}/lastbuild`
    fi
    if [ "${OLD_IMPINSTALL}" = "${IMPINSTALL}" ]; then
      return
    fi
    # Otherwise, wait until the develop build is all done (at 7am)
    # or, for test runs, the entire build is done (at 11am)
    # Use UTC for calculations as many containers aren't set to local time
    if [ ${PLATFORM} = "pkgtest-x86_64-w64" -o ${PLATFORM} = "pkgtest-i386-w32" ]; then
      sleep $(( $(date -u -d 1900 +%s) - $(date -u +%s) ))
    else
      sleep $(( $(date -u -d 1500 +%s) - $(date -u +%s) ))
    fi
  fi
  unset PYTHONPATH

  # For now, only build lab-only components against the develop branch
  # (not main)
  if [ ${BRANCH} = "develop" ]; then
    if [ -d $HOME/diva1/home/imp ]; then
      IMP_LAB_INSTALL=`readlink $HOME/diva1/home/imp-salilab/${BRANCH}/.SVN-new | sed -e "s,/salilab,$HOME,"`
    else
      IMP_LAB_INSTALL=`readlink /salilab/diva1/home/imp-salilab/${BRANCH}/.SVN-new`
    fi
    IMPLABSRCTGZ=${IMP_LAB_INSTALL}/build/sources/imp-salilab.tar.gz
    IMP_LAB_LOGS=${IMP_LAB_INSTALL}/build/logs
  else
    IMPLABSRCTGZ=""
  fi
  IMPPKG=${IMPINSTALL}/packages
  IMPBUILD=${IMPINSTALL}/build
  IMPSOURCES=${IMPBUILD}/sources
  IMPLOGS=${IMPBUILD}/logs
  IMPDOCDIR=${IMPINSTALL}/doc/
  IMPVERSION=`cat ${IMPBUILD}/imp-version`
  IMPSRCTGZ=${IMPSOURCES}/imp-${IMPVERSION}.tar.gz

  mkdir -p ${IMPLOGS}/imp

  rm -rf ${TMPDIR}
  mkdir ${TMPDIR}
  cd ${TMPDIR}

  # If using ccache, use TMPDIR for its own cache
  CCACHE_DIR="${TMPDIR}/.ccache"
  export CCACHE_DIR

  ${TAR} -xzf ${IMPSRCTGZ}

  cd ${TMPDIR}/imp-${IMPVERSION}

  # If running as root (e.g. inside a podman container), allow running mpiexec
  if [ `id -u` -eq 0 ]; then
    perl -pi -e 's#\{MPIEXEC_PREFLAGS\}#\{MPIEXEC_PREFLAGS\};--allow-run-as-root#' modules/mpi/dependency/MPI.cmake
  fi

  # Copy Linux support libraries so that we can run on the cluster or Fedora
  if test ${PLATFORM} = "x86_64-intel8"; then
    libdir=/usr/lib64
    instdir=x86_64
    (cd $libdir \
     && cp libboost_filesystem-mt.so.1.53.0 \
           libboost_system-mt.so.1.53.0 \
           libboost_graph-mt.so.1.53.0 \
           libboost_random-mt.so.1.53.0 \
           libboost_regex-mt.so.1.53.0 \
           libboost_program_options.so.1.53.0 \
           libboost_iostreams-mt.so.1.53.0 \
           libboost_program_options-mt.so.1.53.0 \
           libboost_serialization-mt.so.1.53.0 \
           libboost_thread-mt.so.1.53.0 libCGAL.so.10 \
           libcv.so.2.1 libcxcore.so.2.1 libgslcblas.so.0 libgsl.so.0 \
           libhighgui.so.2.1 libjpeg.so.62 \
           libtiff.so.3 libfftw3.so.3 libhdf5.so.103 libhdf5_hl.so.100 \
           libgmpxx.so.4 libprotobuf.so.8 \
           libunwind.so.8 libprofiler.so.0 \
           libesmtp.so.6 libmpfr.so.4 /salilab/diva1/home/libs/${instdir} \
     && cp libgcrypt.so.11 libX11-xcb.so.1 libcrypt.so.1 \
           /salilab/diva1/home/libs/${instdir}/centos8/ \
     && cp libTAU.so.1 libgmp.so.10 \
           /salilab/diva1/home/libs/${instdir}/centos/)
  elif test ${PLATFORM} = "fast8"; then
    libdir=/usr/lib64
    instdir=x86_64
    (cd $libdir \
     && cp libgsl.so.23 \
           /salilab/diva1/home/libs/${instdir}/)
  fi

  # Test IMP static build
  if test $PLATFORM = "static9"; then
    get_cmake $PLATFORM
    CMAKE_ARGS+=("-DCMAKE_BUILD_TYPE=Release" \
                 "-DIMP_MAX_CHECKS=INTERNAL" \
                 "-DIMP_STATIC=on" \
                 "-DIMP_DISABLED_MODULES=cgal:domino")
    # autodiff only currently tested on Fedora
    CMAKE_LAB_ONLY_ARGS+=("-DIMP_DISABLED_MODULES=cgal:domino:liegroup:autodiff")
    mkdir ../build && cd ../build && run_cmake_build ../imp-${IMPVERSION} $PLATFORM python3 "$CMAKE" "$CTEST" "make -k" ""

  # Test IMP fast build (with benchmarks)
  elif test $PLATFORM = "fast8" -o $PLATFORM = "fastmac14" ; then
    get_cmake $PLATFORM
    PYTHON="python3"
    if test $PLATFORM != "fastmac14"; then
      use_modeller_svn
    fi
    if test $PLATFORM = "fast8"; then
      # autodiff only currently tested on Fedora
      CMAKE_LAB_ONLY_ARGS+=("-DIMP_DISABLED_MODULES=liegroup:autodiff")
      module purge
      module load mpi/openmpi-x86_64
      # Load modules for build tools and dependencies not present on a
      # Wynton dev node
      module load swig ninja boost eigen cereal cgal libtau hdf5 opencv python3/protobuf python3/numpy
      module list -t >& ${IMPBUILD}/modules.${PLATFORM}
      # Load extra modules for tests
      module load python3/scipy python3/scikit python3/matplotlib python3/pandas python3/pyrmsd gnuplot python3/biopython python3/networkx
    fi
    if test $PLATFORM = "fastmac14"; then
      # domino3 uses SSE3, so won't work on ARM; autodiff only currently
      # tested on Fedora
      CMAKE_LAB_ONLY_ARGS+=("-DIMP_DISABLED_MODULES=domino3:liegroup:autodiff")
      export LANG="en_US.UTF-8"
      # Work around boost/clang incompatibility
      CMAKE_ARGS+=("-DCMAKE_CXX_FLAGS='-std=c++17 -D_LIBCPP_ENABLE_CXX17_REMOVED_UNARY_BINARY_FUNCTION'" \
                   "-DIMP_TIMEOUT_FACTOR=4" \
                   "-DPython3_EXECUTABLE=/opt/homebrew/bin/python3")
    fi
    if test $PLATFORM = "fast8"; then
      CMAKE_ARGS+=("-DIMP_TIMEOUT_FACTOR=20" "-DUSE_PYTHON2=off" \
                   "-DCMAKE_CXX_FLAGS='-std=c++14 -DOMPI_SKIP_MPICXX=1'")
    elif test $PLATFORM = "fastmpi"; then
      CMAKE_ARGS+=("-DIMP_TIMEOUT_FACTOR=4")
    fi
    CMAKE_ARGS+=("-DCMAKE_BUILD_TYPE=Release" \
                 "-GNinja" \
                 "-DIMP_MAX_CHECKS=NONE" "-DIMP_MAX_LOG=SILENT")
    EXTRA="allinstall"
    if test $PLATFORM = "fast8"; then
      # Build interfaces for all Python versions
      EXTRA="${EXTRA}:allpython"
    fi
    # Set blank PYTHONPATH so we use system numpy, not that from modules
    mkdir ../build && cd ../build && CMAKE_PYTHONPATH="NONE" run_cmake_build ../imp-${IMPVERSION} $PLATFORM $PYTHON "$CMAKE" "$CTEST" "ninja -k9999 -j1" "--run-tests=all --run-examples --run-benchmarks" ${EXTRA}
    if test $PLATFORM = "fast8"; then
      # CMake links against mpi_cxx which isn't needed (due to OMPI_SKIP_MPICXX
      # above) and isn't available on Fedora 40 or later, so remove it
      patchelf --remove-needed libmpi_cxx.so.40 ${IMPINSTALL}/lib/${PLATFORM}/*.so.* ${IMPINSTALL}/lib/${PLATFORM}/_IMP_*.so ${IMPINSTALL}/bin/${PLATFORM}/spb*
    fi
  # Build IMP .deb packages in Ubuntu Docker container
  elif test $PLATFORM = "debs"; then
    codename=`lsb_release -c -s`
    DEBPKG=${IMPPKG}/${codename}
    mkdir -p ${DEBPKG}
    # Also make source packages for non-develop builds
    if [ ${BRANCH} != "develop" ]; then
      mkdir ${DEBPKG}/source
    fi
    deb_build() {
      local LOG_DIR=$1
      # Build source package
      if [ ${BRANCH} != "develop" ]; then
        cp ${IMPSRCTGZ} ../imp_${IMPVERSION}.orig.tar.gz
        tools/debian-ppa/make-package.sh  # will fail due to unmet deps
        dpkg-buildpackage -S -d
        rm -f ../imp_${IMPVERSION}.orig.tar.gz
        rm -rf debian
        mv ../*.debian.tar.gz ../*.dsc ../*.buildinfo ../*.changes ${DEBPKG}/source/
      fi

      tools/debian/make-package.sh ${IMPVERSION} && cp ../imp*.deb ${DEBPKG}
      RET=$?
      release=`lsb_release -r -s`
      cpppath='/usr/include/eigen3'
      if [ "${codename}" = "focal" -o "${codename}" = "jammy" ]; then
        cxxflags="-std=c++11 -I/usr/include/hdf5/serial/"
      else
        cxxflags="-std=c++20 -I/usr/include/hdf5/serial/"
      fi
      # Build files for Ubuntu apt-get repository (/etc/apt/sources.list)
      # For stable releases, should also make Release.gpg by running
      # gpg -bas -o Release.gpg Release
      rm -f /tmp/Release
      cat <<EOF > /tmp/Release
Architectures: amd64
Codename: ${codename}
Suite: ${codename}
Version: ${release}
EOF
      (cd .. && mkdir ${codename} && mv imp*.deb ${codename} \
       && apt-ftparchive packages ${codename} > ${codename}/Packages \
       && gzip -9c ${codename}/Packages > ${codename}/Packages.gz \
       && apt-ftparchive release ${codename} >> /tmp/Release \
       && cp /tmp/Release ${codename}/Packages* ${DEBPKG})
      rm -f /tmp/Release
      cp build/logs/* ${LOG_DIR}
      if [ ${RET} -eq 0 ]; then
	# Also test imp-python2 subpackage with stable branch on older Ubuntu
	if [ "${codename}" = "noble" -o "${BRANCH}" = "develop" ]; then
          dpkg -i ../${codename}/*.deb \
            && cd tools/nightly-tests/test-install \
            && scons python=python3 mock_config=ubuntu-${codename} \
                     cxxflags="${cxxflags}" cpppath="${cpppath}" \
            && dpkg -r imp imp-dev imp-openmpi
          RET=$?
	else
          dpkg -i ../${codename}/*.deb \
            && cd tools/nightly-tests/test-install \
            && scons python=python2 mock_config=ubuntu-${codename} \
                     cxxflags="${cxxflags}" cpppath="${cpppath}" \
            && scons python=python3 mock_config=ubuntu-${codename} \
                     cxxflags="${cxxflags}" cpppath="${cpppath}" \
            && dpkg -r imp imp-dev imp-python2 imp-openmpi
          RET=$?
	fi
      fi
      return $RET
    }

    LOG_DIR="${IMPLOGS}/imp/pkg.${codename}-x86_64"
    run_imp_build ALL ${LOG_DIR} deb_build ${LOG_DIR}

  # Build IMP RPMs from spec file using mock on clarinet (Fedora box)
  elif test $PLATFORM = "rhelrpms" -o $PLATFORM = "fedorarpms"; then
    echo "Building RPMs for branch $BRANCH"

    # Make spec file
    SPEC=${IMPPKG}/IMP.spec
    SPEC_COPR=${IMPPKG}/IMP-copr.spec
    (mkdir -p ${IMPPKG} \
     && sed -e "s/@IMP_VERSION@/${IMPVERSION}/" < tools/rpm/IMP.spec.in \
                                                > ${SPEC} \
     && sed -e "s/@IMP_VERSION@/${IMPVERSION}/" < tools/rpm/IMP-copr.spec.in \
                                                > ${SPEC_COPR}) \
                            > ${IMPLOGS}/imp/rpm.source.log 2>&1

    make_modeller_config() {
      local MODELLER_VERSION="$1"
      local CONFIG="$2"
      cat > "${CONFIG}" <<END
install_dir = r'/usr/lib/modeller${MODELLER_VERSION}'
license = 'XXXXX'
END
    }

    fix_mock_environment() {
      local CFG="$1"
      if echo ${CFG} | grep -q fedora-34; then 
        # test -r always fails on F34 when run in mock on EPEL8 for some
	# reason, causing 'module' to not work. Work around by disabling
	# the -r check in /etc/profile
        mock -r ${CFG} --copyout /etc/profile mockprof \
        && sed -ie 's/\[ -r "$i" \]/true/' mockprof \
	&& mock -r ${CFG} --copyin mockprof /etc/profile \
	&& rm -f mockprof
      fi
    }

    mock_build() {
      local CFG="$1"
      local LOG_DIR="$2"
      local CXXFLAGS="$3"
      local CPPPATH="$4"
      local LIBPATH="$5"
      local EXTRAREPO="$6"
      local MPI_MODULE="$7"
      local RESDIR=/var/lib/mock/${CFG}/result
      local SCONS="scons"
      local SCONS_PKG="scons"
      # Pull in BioPython for PMI tests
      # Pull in Python protobuf support for npctransport tests
      if echo ${CFG} | grep -q epel; then
        if echo ${CFG} | grep -q epel-8; then
	  # no biopython or protobuf in RHEL8, but we have our own protobuf
          local extra_pkgs="python3-protobuf"
        elif echo ${CFG} | grep -q epel-9; then
	  # Pull in RHEL9's Python protobuf
          local extra_pkgs="python3-protobuf"
	else
          local extra_pkgs="python-biopython protobuf-python"
        fi
      else
        # Python 2 is deprecated as of Fedora 30; use Python 3 packages instead
        local extra_pkgs="python3-biopython python3-protobuf"
      fi

      # scons package and binary are named differently on RHEL8
      # Note also that for the install test we need to pull in our own
      # python3-protobuf package (it is not in the IMP RPM's own Requires:
      # because it is not in RHEL8 for some reason)
      if echo ${CFG} | grep -q epel-8; then
        SCONS_PKG="python3-scons python3-protobuf"
        SCONS="scons-3"
      fi
      if echo ${CFG} | grep -q epel-9; then
        SCONS_PKG="python3-scons"
        SCONS="scons-3"
      fi

      SCONS="${SCONS} mock_config=$CFG cxxflags=${CXXFLAGS}"

      if [ -n "${CPPPATH}" ]; then
        SCONS="${SCONS} cpppath='/usr/include/eigen3:${CPPPATH}'"
      else
        SCONS="${SCONS} cpppath='/usr/include/eigen3'"
      fi
      if [ -n "${LIBPATH}" ]; then
        SCONS="${SCONS} libpath='${LIBPATH}'"
      fi
      if [ -n "${MPI_MODULE}" ]; then
        SCONS="${SCONS} mpi_module=${MPI_MODULE}"
      fi
      # On RHEL7, tests need Python 2 rather than 3
      if echo $CFG | grep -q 'epel-7' ; then
        SCONS="${SCONS} python=python2"
      else
        SCONS="${SCONS} python=python3"
      fi
      mock -r $CFG --init \
      && mkdir packages-${CFG} \
      && mock -r $CFG --buildsrpm --no-clean --spec $SPEC --sources $IMPSOURCES \
      && mock -r $CFG --installdeps $RESDIR/IMP-*.src.rpm \
      && mock -r $CFG --install modeller $extra_pkgs \
      && MODELLER_VERSION=$(mock -r $CFG --shell "ls -d /usr/lib/modeller*" | cut -b18- | tr -d '\n\r') \
      && make_modeller_config ${MODELLER_VERSION} config.py.$$ \
      && mock -r $CFG --copyin config.py.$$ \
             /usr/lib/modeller${MODELLER_VERSION}/modlib/modeller/config.py \
      && fix_mock_environment $CFG \
      && mock -r $CFG --no-clean -D "keep_going 1" \
              --enable-network \
              -D "RHEL_SALI_LAB 1" --rebuild $RESDIR/IMP-*.src.rpm \
      && cp ${RESDIR}/IMP{,-devel}-*[64].rpm ${IMPPKG} \
      && cp ${RESDIR}/IMP{,-devel}-*[64].rpm packages-${CFG} \
      && cp ${RESDIR}/IMP-*.src.rpm ${IMPPKG}
      RET=$?
      # We should be able to use IMP without the debuginfo packages
      rm -f packages-${CFG}/IMP-*debuginfo*.rpm
      cp /var/lib/mock/${CFG}/root/builddir/build/BUILD/imp-*/build/logs/* \
         ${LOG_DIR}
      cat /var/lib/mock/${CFG}/result/*.log
      if [ ${RET} -eq 0 ]; then
        mock -r $CFG --clean \
        && mock -r $CFG --install ${SCONS_PKG} gcc-c++ \
        && mock -r $CFG --disablerepo=mock-extras ${EXTRAREPO} \
                        --install packages-${CFG}/*.rpm \
        && mock -r $CFG --copyin tools/nightly-tests/test-install \
                                 /builddir/test-install \
        && mock -r $CFG --shell "cd /builddir/test-install && ${SCONS}"
        RET=$?
      fi
      mock -r $CFG --scrub=all
      return $RET
    }

    run_mock_build() {
      local PLATFORM="$1"
      local MOCK_CFG="$2"
      local CXXFLAGS="$3"
      local CPPPATH="$4"
      local LIBPATH="$5"
      local EXTRAREPO="$6"
      local MPI_MODULE="$7"
      local LOG_DIR=${IMPLOGS}/imp/${PLATFORM}
      run_imp_build ALL $LOG_DIR mock_build $MOCK_CFG $LOG_DIR "$CXXFLAGS" \
                    "$CPPPATH" "$LIBPATH" "$EXTRAREPO" "$MPI_MODULE"
    }

    if [ $PLATFORM = "fedorarpms" ]; then
      run_mock_build pkg.f40-x86_64 fedora-40-x86_64 "-std=c++20" "" "" "" "mpi/mpich-x86_64"
    else
      if [ ${BRANCH} != "develop" ]; then
        run_mock_build pkg.el7-x86_64 epel-7-x86_64 "-std=c++11" "" "" "" "mpi/mpich-x86_64"
      fi
      run_mock_build pkg.el8-x86_64 epel-8-x86_64 "-std=c++11" "" "" "" "mpi/mpich-x86_64"
      run_mock_build pkg.el9-x86_64 epel-9-x86_64 "" "" "" "" "mpi/mpich-x86_64"
    fi
    rm -f config.py.$$

  # Build with CUDA
  elif test $PLATFORM = "cuda"; then
    # CUDA doesn't currently support latest Fedora gcc
    module purge
    module load gcc/10.2.1 cuda/12.4.0 gnuplot
    get_cmake $PLATFORM
    use_modeller_svn

    CMAKE_ARGS=("${CMAKE_ARGS[@]}" \
                "-DCMAKE_LIBRARY_PATH=$CUDA_LIB_PATH" \
                "-DCMAKE_INCLUDE_PATH=$CUDA_LIB_PATH/../include" \
                "-DIMP_CUDA=ALL" \
                "-DCMAKE_BUILD_TYPE=Release" \
                "-DIMP_TIMEOUT_FACTOR=2" \
                "-DIMP_DISABLED_MODULES=multifit2" \
                "-GNinja")
    mkdir ../build && cd ../build && run_cmake_build ../imp-${IMPVERSION} $PLATFORM python3 "$CMAKE" "$CTEST" "ninja -k9999 -j4" "--run-tests=fast --run-examples" allinstall

  # Get coverage information on clarinet (Fedora box)
  elif test $PLATFORM = "coverage"; then
    # lcov doesn't yet understand gcc 9's output
    module purge
    module load gcc/7.3.1
    get_cmake $PLATFORM
    use_modeller_svn
    module load mpi/openmpi-x86_64

    CMAKE_ARGS=("${CMAKE_ARGS[@]}" "-DCMAKE_BUILD_TYPE=Debug" \
                "-DIMP_TIMEOUT_FACTOR=20" \
                "-DCGAL_DO_NOT_WARN_ABOUT_CMAKE_BUILD_TYPE=TRUE" \
                "-GNinja" \
                "-DCMAKE_CXX_FLAGS='-std=c++11 -fprofile-arcs -ftest-coverage'")
    mkdir ../build && cd ../build && CMAKE_PYTHONPATH="`pwd`/coverage" run_cmake_build ../imp-${IMPVERSION} $PLATFORM python3 "$CMAKE" "$CTEST -j4" "ninja -k9999 -j4" "--run-tests=fast --run-examples --coverage" coverage

  # Normal full build
  else

    if test $PLATFORM = "mac10v10-intel" -o $PLATFORM = "mac10v15-intel" -o $PLATFORM = "mac11v0-intel" -o $PLATFORM = "mac12arm64-gnu" -o $PLATFORM = "mac12-intel"; then
      export LANG="en_US.UTF-8"
      get_cmake $PLATFORM
      CMAKE_ARGS+=("-DCMAKE_BUILD_TYPE=Release" \
                   "-DIMP_TIMEOUT_FACTOR=2" \
		   "-DCMAKE_CXX_FLAGS='-std=c++17'" \
                   "-DIMP_PER_CPP_COMPILATION=ALL" \
                   "-GNinja" \
                   "-DIMP_MAX_CHECKS=INTERNAL")
      if test $PLATFORM = "mac12arm64-gnu"; then
        # Find Homebrew Python 3 on Apple Silicon
	CMAKE_ARGS+=("-DCMAKE_FRAMEWORK_PATH=/opt/homebrew/Frameworks" \
                     "-DPython3_EXECUTABLE=/opt/homebrew/bin/python3")
        # domino3 uses SSE3, so won't work on ARM; autodiff only currently
        # tested on Fedora
        CMAKE_LAB_ONLY_ARGS+=("-DIMP_DISABLED_MODULES=domino3:liegroup:autodiff")
        # Otherwise linkage of _IMP_em2d.so fails because it can't find
        # @rpath/libgcc_s.1.1.dylib
        CMAKE_ARGS+=("-DCMAKE_MODULE_LINKER_FLAGS=-L/opt/homebrew/Cellar/gcc/12.1.0/lib/gcc/12")
        # Sometimes Python takes a long time to start up under virtualization,
        # particularly for MPI tests
        CMAKE_ARGS+=("-DIMP_TIMEOUT_FACTOR=8")
        mkdir ../build && cd ../build && run_cmake_build ../imp-${IMPVERSION} $PLATFORM python3 "$CMAKE" "$CTEST" "ninja -k9999 -j2" "--run-tests=fast --run-examples --run-benchmarks" allinstall:docinstall
      else
        CMAKE_ARGS+=("-DPython3_EXECUTABLE=/usr/local/bin/python3")
        # autodiff only currently tested on Fedora
        CMAKE_LAB_ONLY_ARGS+=("-DIMP_DISABLED_MODULES=liegroup:autodiff")
        mkdir ../build && cd ../build && run_cmake_build ../imp-${IMPVERSION} $PLATFORM python3 "$CMAKE" "$CTEST" "ninja -k9999 -j2" "--run-tests=fast --run-examples --run-benchmarks" allinstall
      fi
    elif test $PLATFORM = "mac10v11-intel"; then
      export LANG="en_US.UTF-8"
      get_cmake $PLATFORM
      CMAKE_ARGS+=("-DCMAKE_BUILD_TYPE=Release" \
		   "-DCMAKE_CXX_FLAGS='-std=c++11'" \
                   "-GNinja" \
                   "-DIMP_MAX_CHECKS=INTERNAL")
      mkdir ../build && cd ../build && run_cmake_build ../imp-${IMPVERSION} $PLATFORM python3 "$CMAKE" "$CTEST" "ninja -k9999 -j1" "--run-tests=fast --run-examples --run-benchmarks" allinstall
    elif test ${PLATFORM} = "debug8"; then
      # Debug build
      module purge
      module load mpi/openmpi-x86_64
      # Load modules for build tools and dependencies not present on a
      # Wynton dev node
      module load swig ninja boost eigen cereal cgal libtau hdf5 opencv python3/protobuf python3/numpy
      module list -t >& ${IMPBUILD}/modules.${PLATFORM}
      # Load extra modules for tests
      module load python3/scipy python3/scikit python3/matplotlib python3/pandas python3/pyrmsd gnuplot python3/biopython python3/networkx
      get_cmake $PLATFORM
      CMAKE_ARGS=("${CMAKE_ARGS[@]}" "-DCMAKE_BUILD_TYPE=Release" \
                  "-DIMP_TIMEOUT_FACTOR=2" \
                  "-DUSE_PYTHON2=off" \
                  "-DCMAKE_CXX_FLAGS='-std=c++14'" \
                  "-DIMP_MAX_CHECKS=INTERNAL" \
                   "-GNinja")
      # autodiff only currently tested on Fedora
      CMAKE_LAB_ONLY_ARGS+=("-DIMP_DISABLED_MODULES=liegroup:autodiff")
      use_modeller_svn
      # Set blank PYTHONPATH so we use system numpy, not that from modules
      mkdir ../build && cd ../build && CMAKE_PYTHONPATH="NONE" run_cmake_build ../imp-${IMPVERSION} $PLATFORM python3 "$CMAKE" "$CTEST" "ninja -k9999 -j1" "--run-tests=fast --run-examples --run-benchmarks" allinstall
    elif test ${PLATFORM} = "release8"; then
      # Release build (no internal checks)
      module purge
      module load mpi/openmpi-x86_64
      # Load modules for build tools and dependencies not present on a
      # Wynton dev node
      module load swig ninja boost eigen cereal cgal libtau hdf5 opencv python3/protobuf python3/numpy
      module list -t >& ${IMPBUILD}/modules.${PLATFORM}
      # Load extra modules for tests
      module load python3/scipy python3/scikit python3/matplotlib python3/pandas python3/pyrmsd gnuplot python3/biopython python3/networkx
      get_cmake $PLATFORM
      CMAKE_ARGS=("${CMAKE_ARGS[@]}" "-DCMAKE_BUILD_TYPE=Release" \
                  "-DIMP_TIMEOUT_FACTOR=2" \
                  "-DUSE_PYTHON2=off" \
                  "-DCMAKE_CXX_FLAGS='-std=c++14 -DOMPI_SKIP_MPICXX=1'" \
                  "-GNinja")
      # autodiff only currently tested on Fedora
      CMAKE_LAB_ONLY_ARGS+=("-DIMP_DISABLED_MODULES=liegroup:autodiff")
      use_modeller_svn
      # Add interfaces for all Python versions
      # Set blank PYTHONPATH so we use system numpy, not that from modules
      mkdir ../build && cd ../build && CMAKE_PYTHONPATH="NONE" run_cmake_build ../imp-${IMPVERSION} $PLATFORM python3 "$CMAKE" "$CTEST" "ninja -k9999 -j1" "--run-tests=fast --run-examples --run-benchmarks" allinstall:allpython
      # CMake links against mpi_cxx which isn't needed (due to OMPI_SKIP_MPICXX
      # above) and isn't available on Fedora 40 or later, so remove it
      patchelf --remove-needed libmpi_cxx.so.40 ${IMPINSTALL}/lib/${PLATFORM}/*.so.* ${IMPINSTALL}/lib/${PLATFORM}/_IMP_*.so ${IMPINSTALL}/bin/${PLATFORM}/spb*
    elif test ${PLATFORM} = "mac10v4-intel64"; then
      get_cmake $PLATFORM
      CMAKE_ARGS=("${CMAKE_ARGS[@]}" "-DCMAKE_BUILD_TYPE=Release" \
                  "-DIMP_TIMEOUT_FACTOR=2" \
                  "-DIMP_MAX_CHECKS=INTERNAL")
      # pynet and nestor don't work with Python 2; autodiff only currently
      # tested on Fedora
      CMAKE_ARGS+=("-DIMP_DISABLED_MODULES=nestor")
      CMAKE_LAB_ONLY_ARGS+=("-DIMP_DISABLED_MODULES=nestor:pynet:liegroup:autodiff")
      mkdir ../build && cd ../build && run_cmake_build ../imp-${IMPVERSION} $PLATFORM python "$CMAKE" "$CTEST" "make -k -j2" "--run-tests=fast --run-examples --run-benchmarks" allinstall:macpackage
    elif test ${PLATFORM} = "i386-w32" -o ${PLATFORM} = "x86_64-w64"; then
      # Build IMP for Windows
      if test ${PLATFORM} = "i386-w32"; then
        local BITS=32
        local EXTRA_CXX_FLAGS=""
        local HOSTPYTHON="python3"
      else
        local BITS=64
        local EXTRA_CXX_FLAGS=" /bigobj"
        local HOSTPYTHON="python3"
      fi

      # Prevent wine from trying to open an X connection
      unset DISPLAY

      get_cmake $PLATFORM
      CMAKE_ARGS+=("-DCMAKE_BUILD_TYPE=Release" \
                   "-DCMAKE_CXX_FLAGS='/DBOOST_ALL_DYN_LINK /EHsc /DH5_BUILT_AS_DYNAMIC_LIB /DWIN32 /DGSL_DLL${EXTRA_CXX_FLAGS}'" \
                   "-DIMP_TIMEOUT_FACTOR=20")
      if test ${BITS} = "32"; then
        CMAKE_ARGS+=("-Dfftw3_LIBRARY='/usr/lib/w32comp/Program Files/Microsoft Visual Studio/2017/Community/VC/Tools/MSVC/14.16.27023/lib/x86/libfftw3-3.lib'")
	CMAKE_ARGS+=("-DCGAL_DIR=/usr/lib/w32comp/CGAL-5.1/")
	CMAKE_ARGS+=("-DPYTHON_NUMPY_INCLUDE_DIR=/usr/lib/w32comp/w32python/3.9/lib/site-packages/numpy/core/include")
	CMAKE_ARGS+=("-DPYTHON_TEST_EXECUTABLE=w32python3")
	CMAKE_ARGS+=("-DPYTHON_INCLUDE_DIRS=/usr/lib/w32comp/w32python/3.9/include/")
	CMAKE_ARGS+=("-DPYTHON_EXECUTABLE=python3")
      else
        CMAKE_ARGS+=("-DCMAKE_C_FLAGS='/Dinline=__inline'")
        CMAKE_ARGS+=("-Dfftw3_LIBRARY='/usr/lib/w64comp/Program Files/Microsoft Visual Studio/2017/Community/VC/Tools/MSVC/14.16.27023/lib/x64/libfftw3-3.lib'")
	CMAKE_ARGS+=("-DCGAL_DIR=/usr/lib/w64comp/CGAL-5.1/")
	CMAKE_ARGS+=("-DPYTHON_NUMPY_INCLUDE_DIR=/usr/lib/w64comp/w64python/3.9/lib/site-packages/numpy/core/include")
	CMAKE_ARGS+=("-DPYTHON_TEST_EXECUTABLE=w64python3")
      fi
      CMAKE_NON_CACHE_ARGS+=("-DPATH_SEP=:" "-DSETUP_EXT=sh" \
                             "-DPYTHON_PATH_SEP=w32")
      # domino3 currently doesn't work on Windows;
      # autodiff only currently tested on Fedora
      CMAKE_LAB_ONLY_ARGS+=("-DIMP_DISABLED_MODULES=domino3:liegroup:autodiff")
      use_modeller_svn $PLATFORM
      add_imp_to_wine_path ${TMPDIR}/build
      # Ensure that we find the Windows protoc in the path before the Linux one
      mkdir bins
      ln -s /usr/lib/w${BITS}comp/bin/protoc bins/
      export PATH=`pwd`/bins:$PATH
      mkdir ../build && cd ../build && run_cmake_build ../imp-${IMPVERSION} $PLATFORM ${HOSTPYTHON} "$CMAKE" "$CTEST -j2" "make -k -j4" "--run-tests=fast --run-examples --run-benchmarks" allinstall:w${BITS}package
    elif test ${PLATFORM} = "pkgtest-i386-w32" -o ${PLATFORM} = "pkgtest-x86_64-w64"; then
      # Test IMP Windows installer
      if test ${PLATFORM} = "pkgtest-i386-w32"; then
        local BITS=32
        local LOG_DIR="${IMPLOGS}/imp/i386-w32"
      else
        local BITS=64
        local LOG_DIR="${IMPLOGS}/imp/x86_64-w64"
      fi

      # Prevent wine from trying to open an X connection
      unset DISPLAY

      run_imp_build PKGTEST "${LOG_DIR}" test_w32_package `pwd` ${BITS}
    fi
  fi

  cd
  rm -rf ${TMPDIR}
}

PLATFORMS=$1
shift
ALL_BRANCHES="$@"
echo "Building branches $ALL_BRANCHES on $PLATFORMS"
for BRANCH in $ALL_BRANCHES; do
  for PLATFORM in $PLATFORMS; do
    echo "Building $BRANCH on $PLATFORM"
    do_build $PLATFORM $BRANCH
  done
done
