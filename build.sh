#!/bin/bash

# Build some part of IMP from source code.

# First argument is the platform to build (can be multiple space-separated
# platforms, if desired).
# Remaining arguments are the branches to build (e.g. main, develop)

# Get config
. $(dirname $0)/build_config.sh

# Get common functions
. $(dirname $0)/build_functions.sh

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

# Use GNU make and tar (potentially in Homebrew locations on Macs)
PATH="/opt/homebrew/bin:/usr/local/bin:/opt/local/bin:${PATH}"

# Make sure that log files are world-readable
umask 0022

host=$(hostname)
case $host in
# Use larger /var partition on clarinet
  clarinet*)
    TMPDIR=/var/tmp/nightly-build-$$
    ;;
esac

# Run all IMP tests, even unstable ones
export IMP_UNSTABLE_TESTS=1

if [ $# -lt 2 ]; then
  echo "Usage: $0 platform branch [branch...]"
  exit 1
fi

do_build() {
  PLATFORM=$1
  BRANCH=$2
  # Get directory to install this branch of IMP in (populated by setup_build.sh)
  IMPINSTALL=$(cd ${IMP_INSTALL_TOP}/${BRANCH}/.new && pwd -P)

  # Skip non-develop build if nothing has changed
  if [ ${BRANCH} != "develop" ]; then
    LAST_IMPINSTALL=$(cd ${IMP_INSTALL_TOP}/${BRANCH}/.last && pwd -P)
    if [ "${LAST_IMPINSTALL}" = "${IMPINSTALL}" ]; then
      return
    fi
    # Otherwise, wait until the develop build is all done (at 7am)
    # or, for test runs, the entire build is done (at 11am)
    # Use UTC for calculations as many containers aren't set to local time
    if [ ${PLATFORM} = "pkgtest-x86_64-w64" ] || [ ${PLATFORM} = "pkgtest-i386-w32" ]; then
      sleep $(( $(date -u -d 1900 +%s) - $(date -u +%s) ))
    else
      sleep $(( $(date -u -d 1500 +%s) - $(date -u +%s) ))
    fi
  fi
  unset PYTHONPATH

  # For now, only build lab-only components against the develop branch
  # (not main)
  if [ ${BRANCH} = "develop" ]; then
    IMP_LAB_INSTALL=$(cd ${IMP_LAB_INSTALL_TOP}/${BRANCH}/.new && pwd -P)
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
  IMPVERSION=$(cat ${IMPBUILD}/imp-version)
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
  if [ $(id -u) -eq 0 ]; then
    perl -pi -e 's#\{MPIEXEC_PREFLAGS\}#\{MPIEXEC_PREFLAGS\};--allow-run-as-root#' modules/mpi/dependency/MPI.cmake
  fi

  # Copy Linux support libraries so that we can run on the cluster or Fedora
  if [ ${PLATFORM} = "fast8" ]; then
    libdir=/usr/lib64
    instdir=x86_64
    (cd $libdir \
     && cp libgsl.so.23 \
           /salilab/diva1/home/libs/${instdir}/)
  fi

  # Test IMP static build
  if [ $PLATFORM = "static9" ]; then
    get_cmake $PLATFORM
    CMAKE_ARGS+=("-DCMAKE_BUILD_TYPE=Release" \
                 "-DIMP_MAX_CHECKS=INTERNAL" \
                 "-DIMP_STATIC=on" \
                 "-DIMP_DISABLED_MODULES=cgal:domino")
    # autodiff only currently tested on Fedora
    CMAKE_LAB_ONLY_ARGS+=("-DIMP_DISABLED_MODULES=cgal:domino:liegroup:autodiff")
    mkdir ../build && cd ../build && run_cmake_build ../imp-${IMPVERSION} $PLATFORM python3 "$CMAKE" "$CTEST" "make -k" ""

  # Test IMP fast build (with benchmarks)
  elif [ $PLATFORM = "fast8" ] || [ $PLATFORM = "fastmac15" ]; then
    get_cmake $PLATFORM
    PYTHON="python3"
    if [ $PLATFORM != "fastmac15" ]; then
      use_modeller_svn
    fi
    if [ $PLATFORM = "fast8" ]; then
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
      # Build with numpy 2 headers so that IMP binaries work with both
      # numpy 1 (RHEL 8, 9) and numpy 2 (Fedora)
      patch -p1 < tools/debian-ppa/patches/imp-numpy2_vendor.patch
      # Add support for the ancient numpy 1.14 in RHEL 8
      patch -p1 < tools/build/numpy-rhel8.patch
    fi
    if [ $PLATFORM = "fastmac15" ]; then
      # domino3 uses SSE3, so won't work on ARM; autodiff only currently
      # tested on Fedora
      CMAKE_LAB_ONLY_ARGS+=("-DIMP_DISABLED_MODULES=domino3:liegroup:autodiff")
      export LANG="en_US.UTF-8"
      # Work around boost/clang incompatibility
      CMAKE_ARGS+=("-DCMAKE_CXX_FLAGS='-std=c++17 -D_LIBCPP_ENABLE_CXX17_REMOVED_UNARY_BINARY_FUNCTION'" \
                   "-DIMP_TIMEOUT_FACTOR=4" \
                   "-DPython3_EXECUTABLE=/opt/homebrew/bin/python3")
    fi
    if [ $PLATFORM = "fast8" ]; then
      CMAKE_ARGS+=("-DIMP_TIMEOUT_FACTOR=20" \
                   "-DCMAKE_CXX_FLAGS='-std=c++14 -DOMPI_SKIP_MPICXX=1'")
    fi
    CMAKE_ARGS+=("-DCMAKE_BUILD_TYPE=Release" \
                 "-GNinja" \
                 "-DIMP_MAX_CHECKS=NONE" "-DIMP_MAX_LOG=SILENT")
    EXTRA="allinstall"
    if [ $PLATFORM = "fast8" ]; then
      # Build interfaces for all Python versions
      EXTRA="${EXTRA}:allpython"
    fi
    # Set blank PYTHONPATH so we use system numpy, not that from modules
    mkdir ../build && cd ../build && CMAKE_PYTHONPATH="NONE" run_cmake_build ../imp-${IMPVERSION} $PLATFORM $PYTHON "$CMAKE" "$CTEST" "ninja -k9999 -j1" "--run-tests=all --run-examples --run-benchmarks" ${EXTRA}
    if [ $PLATFORM = "fast8" ]; then
      # CMake links against mpi_cxx which isn't needed (due to OMPI_SKIP_MPICXX
      # above) and isn't available on Fedora 40 or later, so remove it
      patchelf --remove-needed libmpi_cxx.so.40 ${IMPINSTALL}/lib/${PLATFORM}/*.so.* ${IMPINSTALL}/lib/${PLATFORM}/_IMP_*.so ${IMPINSTALL}/bin/${PLATFORM}/spb*
      # Remove bundled copy of python-ihm; lab users will get it instead
      # with "module load python3/ihm"
      rm -rf ${IMPINSTALL}/lib/${PLATFORM}/ihm
    fi
  # Build IMP .deb packages in Ubuntu Docker container
  elif [ $PLATFORM = "debs" ]; then
    codename=$(lsb_release -c -s)
    DEBPKG=${IMPPKG}/${codename}
    mkdir -p ${DEBPKG}/source
    deb_build() {
      local LOG_DIR=$1
      # Build source package
      cp ${IMPSRCTGZ} ../imp_${IMPVERSION}.orig.tar.gz
      tools/debian-ppa/make-package.sh  # will fail due to unmet deps
      if [ ${BRANCH} = "develop" ]; then
        # Add nightly build "version" to changelog
	DATE_R=$(date -R)
	mv debian/changelog debian/changelog.orig
        cat <<END > debian/changelog
imp (${IMPVERSION}-1~${codename}) ${codename}; urgency=low

  * Synthesized changelog entry for nightly build

 -- IMP Developers <imp@salilab.org>  ${DATE_R}

END
        cat debian/changelog.orig >> debian/changelog
	rm -f debian/changelog.orig
      fi
      # Temporarily back out changes to MPI.cmake; dpkg wants pristine sources
      if [ $(id -u) -eq 0 ]; then
        perl -pi -e 's#;--allow-run-as-root##' modules/mpi/dependency/MPI.cmake
      fi
      dpkg-buildpackage -S -d
      if [ $(id -u) -eq 0 ]; then
        perl -pi -e 's#\{MPIEXEC_PREFLAGS\}#\{MPIEXEC_PREFLAGS\};--allow-run-as-root#' modules/mpi/dependency/MPI.cmake
      fi
      rm -f ../imp_${IMPVERSION}.orig.tar.gz
      rm -rf debian
      mv ../*.debian.tar.* ../*.dsc ../*.buildinfo ../*.changes \
         ${DEBPKG}/source/
      ln -sf ../../../build/sources/imp-${IMPVERSION}.tar.gz \
             ${DEBPKG}/source/imp_${IMPVERSION}.orig.tar.gz

      tools/debian/make-package.sh ${IMPVERSION} && cp ../imp*.deb ${DEBPKG}
      RET=$?
      release=$(lsb_release -r -s)
      cpppath='/usr/include/eigen3'
      if [ "${codename}" = "jammy" ]; then
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
        dpkg -i ../${codename}/*.deb \
          && cd tools/nightly-tests/test-install \
          && scons python=python3 mock_config=ubuntu-${codename} \
                   cxxflags="${cxxflags}" cpppath="${cpppath}" \
          && dpkg -r imp imp-dev imp-openmpi
        RET=$?
      fi
      return $RET
    }

    LOG_DIR="${IMPLOGS}/imp/pkg.${codename}-x86_64"
    run_imp_build ALL ${LOG_DIR} deb_build ${LOG_DIR}

  # Build IMP RPMs from spec file using mock
  elif [ $PLATFORM = "rhelrpms" ] || [ $PLATFORM = "fedorarpms" ]; then
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
license = '${MODELLER_LICENSE_KEY}'
END
    }

    # Do any necessary fixes to make the Modeller package work with Python
    fix_modeller_python() {
      local CFG="$1"
      local MODELLER_VERSION="$2"
      # Modeller 10.7 does not include Python 3.14 (for Fedora 43) symlinks,
      # so add them
      if [ "${CFG}" = "fedora-43-x86_64" ] && [ "${MODELLER_VERSION}" = "10.7" ]; then
        mock -r $CFG --shell "ln -sf /usr/lib/modeller10.7/modlib/modeller /usr/lib64/python3.14/site-packages/modeller" \
            && mock -r $CFG --shell "ln -sf /usr/lib/modeller10.7/lib/x86_64-intel8/python3.3/_modeller.so /usr/lib64/python3.14/site-packages/"
      else
        return 0
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
        elif echo ${CFG} | grep -q epel-10; then
	  # Pull in RHEL10's Python protobuf
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
      if echo ${CFG} | grep -q epel-10; then
        SCONS_PKG="python3-scons"
        SCONS="scons"
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
      SCONS="${SCONS} python=python3"
      mock -r $CFG --init \
      && mkdir packages-${CFG} \
      && mock -r $CFG --buildsrpm --no-clean --spec $SPEC --sources $IMPSOURCES \
      && mock -r $CFG --installdeps $RESDIR/IMP-*.src.rpm \
      && mock -r $CFG --install modeller $extra_pkgs \
      && MODELLER_VERSION=$(mock -r $CFG --shell "ls -d /usr/lib/modeller*" | cut -b18- | tr -d '\n\r') \
      && make_modeller_config ${MODELLER_VERSION} config.py.$$ \
      && mock -r $CFG --copyin config.py.$$ \
             /usr/lib/modeller${MODELLER_VERSION}/modlib/modeller/config.py \
      && fix_modeller_python $CFG ${MODELLER_VERSION} \
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
       /var/lib/mock/${CFG}/root/builddir/build/BUILD/IMP-*/imp-*/build/logs/* \
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
      run_mock_build pkg.f43-x86_64 fedora-43-x86_64 "-std=c++20" "" "" "" "mpi/mpich-x86_64"
    else
      run_mock_build pkg.el8-x86_64 epel-8-x86_64 "-std=c++11" "" "" "" "mpi/mpich-x86_64"
      run_mock_build pkg.el9-x86_64 epel-9-x86_64 "" "" "" "" "mpi/mpich-x86_64"
      run_mock_build pkg.el10-x86_64 epel-10-x86_64 "" "" "" "" "mpi/mpich-x86_64"
    fi
    rm -f config.py.$$

  # Build with CUDA
  elif [ $PLATFORM = "cuda" ]; then
    # Latest CUDA doesn't support latest Fedora gcc, so use previous version
    module purge
    module load cuda/12.8.1 gnuplot
    get_cmake $PLATFORM
    use_modeller_svn

    CMAKE_ARGS=("${CMAKE_ARGS[@]}" \
                "-DCMAKE_LIBRARY_PATH=$CUDA_LIB_PATH" \
                "-DCMAKE_INCLUDE_PATH=$CUDA_LIB_PATH/../include" \
                "-DIMP_CUDA=ALL" \
                "-DCUDA_HOST_COMPILER=/usr/bin/gcc-14" \
                "-DCMAKE_BUILD_TYPE=Release" \
                "-DIMP_TIMEOUT_FACTOR=2" \
                "-DIMP_DISABLED_MODULES=multifit2" \
                "-GNinja")
    mkdir ../build && cd ../build && run_cmake_build ../imp-${IMPVERSION} $PLATFORM python3 "$CMAKE" "$CTEST" "ninja -k9999 -j4" "--run-tests=fast --run-examples" allinstall

  # Get coverage information on Fedora
  elif [ $PLATFORM = "coverage" ]; then
    get_cmake $PLATFORM
    use_modeller_svn
    module load mpi/openmpi-x86_64

    CMAKE_ARGS=("${CMAKE_ARGS[@]}" "-DCMAKE_BUILD_TYPE=Debug" \
                "-DIMP_TIMEOUT_FACTOR=30" \
                "-DCGAL_DO_NOT_WARN_ABOUT_CMAKE_BUILD_TYPE=TRUE" \
                "-GNinja" \
                "-DCMAKE_CXX_FLAGS='-std=c++11 -fprofile-arcs -ftest-coverage'")
    mkdir ../build && cd ../build && CMAKE_PYTHONPATH="$(pwd)/coverage" run_cmake_build ../imp-${IMPVERSION} $PLATFORM python3 "$CMAKE" "$CTEST -j4" "ninja -k9999 -j4" "--run-tests=fast --run-examples --coverage" coverage

  # Normal full build
  else

    if [ $PLATFORM = "mac10v10-intel" ] || [ $PLATFORM = "mac10v15-intel" ] || [ $PLATFORM = "mac11v0-intel" ] || [ $PLATFORM = "mac26arm64-gnu" ] || [ $PLATFORM = "mac14-intel" ]; then
      export LANG="en_US.UTF-8"
      get_cmake $PLATFORM
      CMAKE_ARGS+=("-DCMAKE_BUILD_TYPE=Release" \
                   "-DIMP_TIMEOUT_FACTOR=2" \
		   "-DCMAKE_CXX_FLAGS='-std=c++17'" \
                   "-DIMP_PER_CPP_COMPILATION=ALL" \
                   "-GNinja" \
                   "-DIMP_MAX_CHECKS=INTERNAL")
      if [ $PLATFORM = "mac26arm64-gnu" ]; then
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
    elif [ $PLATFORM = "mac10v11-intel" ]; then
      export LANG="en_US.UTF-8"
      get_cmake $PLATFORM
      CMAKE_ARGS+=("-DCMAKE_BUILD_TYPE=Release" \
		   "-DCMAKE_CXX_FLAGS='-std=c++11'" \
                   "-GNinja" \
                   "-DIMP_MAX_CHECKS=INTERNAL")
      mkdir ../build && cd ../build && run_cmake_build ../imp-${IMPVERSION} $PLATFORM python3 "$CMAKE" "$CTEST" "ninja -k9999 -j1" "--run-tests=fast --run-examples --run-benchmarks" allinstall
    elif [ ${PLATFORM} = "debug8" ]; then
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
                  "-DCMAKE_CXX_FLAGS='-std=c++14'" \
                  "-DIMP_MAX_CHECKS=INTERNAL" \
                   "-GNinja")
      # autodiff only currently tested on Fedora
      CMAKE_LAB_ONLY_ARGS+=("-DIMP_DISABLED_MODULES=liegroup:autodiff")
      use_modeller_svn
      # Set blank PYTHONPATH so we use system numpy, not that from modules
      mkdir ../build && cd ../build && CMAKE_PYTHONPATH="NONE" run_cmake_build ../imp-${IMPVERSION} $PLATFORM python3 "$CMAKE" "$CTEST" "ninja -k9999 -j1" "--run-tests=fast --run-examples --run-benchmarks" allinstall
    elif [ ${PLATFORM} = "release8" ]; then
      # Release build (no internal checks)
      module purge
      module load mpi/openmpi-x86_64
      # Load modules for build tools and dependencies not present on a
      # Wynton dev node
      module load swig ninja boost eigen cereal cgal libtau hdf5 opencv python3/protobuf python3/numpy
      module list -t >& ${IMPBUILD}/modules.${PLATFORM}
      # Load extra modules for tests
      module load python3/scipy python3/scikit python3/matplotlib python3/pandas python3/pyrmsd gnuplot python3/biopython python3/networkx
      # Build with numpy 2 headers so that IMP binaries work with both
      # numpy 1 (RHEL 8, 9) and numpy 2 (Fedora)
      patch -p1 < tools/debian-ppa/patches/imp-numpy2_vendor.patch
      # Add support for the ancient numpy 1.14 in RHEL 8
      patch -p1 < tools/build/numpy-rhel8.patch
      get_cmake $PLATFORM
      CMAKE_ARGS=("${CMAKE_ARGS[@]}" "-DCMAKE_BUILD_TYPE=Release" \
                  "-DIMP_TIMEOUT_FACTOR=2" \
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
      # Remove bundled copy of python-ihm; lab users will get it instead
      # with "module load python3/ihm"
      rm -rf ${IMPINSTALL}/lib/${PLATFORM}/ihm
    elif [ ${PLATFORM} = "mac10v4-intel64" ]; then
      get_cmake $PLATFORM
      CMAKE_ARGS=("${CMAKE_ARGS[@]}" "-DCMAKE_BUILD_TYPE=Release" \
                  "-DIMP_TIMEOUT_FACTOR=2" \
                  "-DIMP_MAX_CHECKS=INTERNAL")
      # pynet and nestor don't work with Python 2; autodiff only currently
      # tested on Fedora
      CMAKE_ARGS+=("-DIMP_DISABLED_MODULES=nestor")
      CMAKE_LAB_ONLY_ARGS+=("-DIMP_DISABLED_MODULES=nestor:pynet:liegroup:autodiff")
      mkdir ../build && cd ../build && run_cmake_build ../imp-${IMPVERSION} $PLATFORM python "$CMAKE" "$CTEST" "make -k -j2" "--run-tests=fast --run-examples --run-benchmarks" allinstall:macpackage
    elif [ ${PLATFORM} = "i386-w32" ] || [ ${PLATFORM} = "x86_64-w64" ]; then
      # Build IMP for Windows
      if [ ${PLATFORM} = "i386-w32" ]; then
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

      # Prevent matplotlib from trying to use the non-functional TkAgg backend
      export MPLBACKEND=Agg

      get_cmake $PLATFORM
      CMAKE_ARGS+=("-DCMAKE_BUILD_TYPE=Release" \
                   "-DCMAKE_CXX_FLAGS='/DBOOST_ALL_DYN_LINK /EHsc /DH5_BUILT_AS_DYNAMIC_LIB /DWIN32 /DGSL_DLL${EXTRA_CXX_FLAGS}'" \
                   "-DIMP_TIMEOUT_FACTOR=20" \
                   "-DCMAKE_DEPENDS_USE_COMPILER=FALSE")
      if [ ${BITS} = "32" ]; then
        CMAKE_ARGS+=("-Dfftw3_LIBRARY='/usr/lib/w32comp/Program Files/Microsoft Visual Studio/2017/Community/VC/Tools/MSVC/14.16.27023/lib/x86/libfftw3-3.lib'")
	CMAKE_ARGS+=("-DCGAL_DIR=/usr/lib/w32comp/CGAL-5.1/")
	CMAKE_ARGS+=("-DPYTHON_TEST_EXECUTABLE=w32python3")
	CMAKE_ARGS+=("-DPYTHON_INCLUDE_DIRS=/usr/lib/w32comp/w32python/3.9/include/")
	CMAKE_ARGS+=("-DPYTHON_EXECUTABLE=python3")
      else
        CMAKE_ARGS+=("-DCMAKE_C_FLAGS='/Dinline=__inline'")
        CMAKE_ARGS+=("-Dfftw3_LIBRARY='/usr/lib/w64comp/Program Files/Microsoft Visual Studio/2017/Community/VC/Tools/MSVC/14.16.27023/lib/x64/libfftw3-3.lib'")
	CMAKE_ARGS+=("-DCGAL_DIR=/usr/lib/w64comp/CGAL-5.1/")
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
      export PATH=$(pwd)/bins:$PATH
      mkdir ../build && cd ../build && run_cmake_build ../imp-${IMPVERSION} $PLATFORM ${HOSTPYTHON} "$CMAKE" "$CTEST -j2" "make -k -j4" "--run-tests=fast --run-examples --run-benchmarks" allinstall:w${BITS}package
    elif [ ${PLATFORM} = "pkgtest-i386-w32" ] || [ ${PLATFORM} = "pkgtest-x86_64-w64" ]; then
      # Test IMP Windows installer
      if [ ${PLATFORM} = "pkgtest-i386-w32" ]; then
        local BITS=32
        local LOG_DIR="${IMPLOGS}/imp/i386-w32"
      else
        local BITS=64
        local LOG_DIR="${IMPLOGS}/imp/x86_64-w64"
      fi

      # Prevent wine from trying to open an X connection
      unset DISPLAY

      run_imp_build PKGTEST "${LOG_DIR}" test_w32_package $(pwd) ${BITS}
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
