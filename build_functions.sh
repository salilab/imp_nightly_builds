# Not all systems (e.g. Mac 10.6) have a 'python2' binary; some systems
# (e.g. Fedora) don't have Python 2 installed at all:
OLDPYTHON=python2; which $OLDPYTHON >& /dev/null || OLDPYTHON=python; which $OLDPYTHON >& /dev/null || OLDPYTHON=python3

# Show a command and also execute it
show_and_execute() {
  echo "$@"
  "$@"
}

# Show a command and also execute it in a different directory
cd_show_and_execute() {
  local dir="$1"
  shift
  echo "cd ${dir} && $@"
  (cd "${dir}" && "$@")
}

# Add a return value to the IMP build summary pickle
add_to_summary_pck() {
  local BUILD_TYPE=$1
  local LOG_DIR=$2
  local RET=$3
  local PCKFILE=${LOG_DIR}/summary.pck
  ${OLDPYTHON} <<END
import pickle
import os
pckfile = "${PCKFILE}"
if os.path.exists(pckfile):
  p = pickle.load(open(pckfile, 'rb'))
else:
  p = {}
p['${BUILD_TYPE}'] = {'build_result': ${RET}}
pickle.dump(p, open(pckfile, 'wb'), 2)
END
}

# Run an IMP build command, and add results to the log directory
run_imp_build() {
  local BUILD_TYPE=$1
  shift
  local LOG_DIR=$1
  shift

  mkdir -p ${LOG_DIR}

  add_to_summary_pck $BUILD_TYPE $LOG_DIR '"running"'
  "$@" > ${LOG_DIR}/${BUILD_TYPE}.build.log 2>&1
  local RET=$?
  add_to_summary_pck $BUILD_TYPE $LOG_DIR $RET
  return $RET
}

cmake_build() {
  local SRCDIR="$1"
  local PYTHON="$2"
  local CMAKE="$3"
  local CTEST="$4"
  local MAKE="$5"
  local OPTS="$6"
  local BUILD_CMD="$PYTHON $SRCDIR/tools/nightly-tests/build_all.py"
  if [ -n "${CMAKE_PYTHONPATH}" ]; then
    echo "PYTHONPATH=${CMAKE_PYTHONPATH} $CMAKE $SRCDIR ${CMAKE_ARGS[@]} && $BUILD_CMD $OPTS --ctest=\"$CTEST --output-on-failure\" \"$MAKE\""
    PYTHONPATH=${CMAKE_PYTHONPATH} $CMAKE $SRCDIR "${CMAKE_ARGS[@]}" && $BUILD_CMD $OPTS --ctest="$CTEST --output-on-failure" "$MAKE"
  elif [ "${CMAKE_PYTHONPATH}" = "NONE" ]; then
    echo "env -u PYTHONPATH $CMAKE $SRCDIR ${CMAKE_ARGS[@]} && $BUILD_CMD $OPTS --ctest=\"$CTEST --output-on-failure\" \"$MAKE\""
    env -u PYTHONPATH $CMAKE $SRCDIR "${CMAKE_ARGS[@]}" && $BUILD_CMD $OPTS --ctest="$CTEST --output-on-failure" "$MAKE"
  else
    echo "$CMAKE $SRCDIR ${CMAKE_ARGS[@]} && $BUILD_CMD $OPTS --ctest=\"$CTEST --output-on-failure\" \"$MAKE\""
    $CMAKE $SRCDIR "${CMAKE_ARGS[@]}" && $BUILD_CMD $OPTS --ctest="$CTEST --output-on-failure" "$MAKE"
  fi
}

# Build a Windows IMP package
build_w32_package() {
  local CMAKE="$1"
  local SRCDIR="$2"
  local MAKE="$3"
  local BITS="$4"
  local w32py="/usr/lib/w${BITS}comp/w${BITS}python"
  mkdir -p ${IMPPKG}
  # Note that 3.9 is first since IMP should already be built against 3.9;
  # this should avoid an unnecessary rebuild
  local PYVERS="3.9 3.8 3.10 3.11 3.12 3.13"
  for PYVER in ${PYVERS}; do
    PYLIB=`echo "python${PYVER}.lib" | sed -e 's/\.//'`
    ${CMAKE} ${SRCDIR} -DCMAKE_INSTALL_PYTHONDIR=/pylib/$PYVER \
                -DSWIG_PYTHON_LIBRARIES=$w32py/$PYVER/lib/$PYLIB \
                -DPYTHON_INCLUDE_DIRS=$w32py/$PYVER/include/ \
                -DPYTHON_INCLUDE_PATH=$w32py/$PYVER/include/ \
                -DPYTHON_LIBRARIES=$w32py/$PYVER/lib/$PYLIB \
                -DCMAKE_INSTALL_PREFIX=/usr/local \
                -DCMAKE_INSTALL_DATADIR=share \
                -DCMAKE_INSTALL_INCLUDEDIR=include \
                -DCMAKE_INSTALL_LIBDIR=lib \
                -DCMAKE_INSTALL_BINDIR=bin \
                -DCMAKE_INSTALL_DOCDIR=share/doc/IMP \
        && ${MAKE} DESTDIR=`pwd`/w32-inst install || return 1
  done
  $SRCDIR/tools/w32/make-package.sh ${IMPVERSION} ${BITS} \
          && cp IMP-${IMPVERSION}-${BITS}bit.exe ${IMPPKG} || return 1
}

# Test a Windows IMP package
test_w32_package() {
  local SRCDIR="$1"
  local BITS="$2"

  # Test silent install, run tests, then uninstall
  local TESTDIR=$SRCDIR/tools/nightly-tests/test-install
  if [ "${BITS}" = "64" ]; then
    local WINPYTHONA="w64python3.9"
    local WINPYTHONB="w64python3.12"
  else
    local WINPYTHONA="w32python3.9"
    local WINPYTHONB="w32python3.12"
  fi
  # Need to set pipefail otherwise test failures get ignored (only the return
  # value from cat is checked by default)
  set -o pipefail
  # w*python3 doesn't like having its stderr redirected to a file
  # "Fatal Python error: Py_Initialize: can't initialize sys standard streams"
  # so use a workaround (2>&1|cat)
  wine ${IMPPKG}/IMP-${IMPVERSION}-${BITS}bit.exe /S /D=C:\\IMP-test \
      && add_installed_imp_to_wine_path \
      && echo "Testing with ${WINPYTHONA}" \
      && ${WINPYTHONA} $TESTDIR/test.py -v 2>&1 | cat \
      && ${WINPYTHONA} $TESTDIR/test_ihm.py -v 2>&1 | cat \
      && MOCK_CONFIG=w${BITS} ${WINPYTHONA} $TESTDIR/test_mock.py -v 2>&1 | cat \
      && ${WINPYTHONA} $TESTDIR/test_rmf.py -v 2>&1 | cat \
      && echo "Testing with ${WINPYTHONB}" \
      && ${WINPYTHONB} $TESTDIR/test.py -v 2>&1 | cat \
      && ${WINPYTHONB} $TESTDIR/test_ihm.py -v 2>&1 | cat \
      && MOCK_CONFIG=w${BITS} ${WINPYTHONB} $TESTDIR/test_mock.py -v 2>&1 | cat \
      && ${WINPYTHONB} $TESTDIR/test_rmf.py -v 2>&1 | cat \
      && wine "C:\\IMP-test\\Uninstall.exe" /S
  local RET=$?
  set +o pipefail

  return $RET
}

# Build a Mac IMP package
build_mac_package() {
  local CMAKE="$1"
  local SRCDIR="$2"
  local MAKE="$3"
  rm -rf /tmp/IMP-${IMPVERSION}-*.dmg
  mkdir -p ${IMPPKG}
  ${CMAKE} $SRCDIR -DCMAKE_INSTALL_PYTHONDIR=lib/IMP-python \
              -DCMAKE_INSTALL_PREFIX=/usr/local \
              -DCMAKE_INSTALL_DATADIR=share \
              -DCMAKE_INSTALL_INCLUDEDIR=include \
              -DCMAKE_INSTALL_LIBDIR=lib \
              -DCMAKE_INSTALL_BINDIR=bin \
              -DCMAKE_INSTALL_DOCDIR=share/doc/IMP \
              -DIMP_MAX_CHECKS=USAGE \
        && ${MAKE} DESTDIR=/tmp/impinstall.$$ install \
        && $SRCDIR/tools/mac/make-package.sh /tmp/impinstall.$$ ${IMPVERSION} \
        && cp /tmp/IMP-${IMPVERSION}-*.dmg ${IMPPKG} \
        && rm -rf /tmp/impinstall.$$ /tmp/IMP-${IMPVERSION}-*.dmg
}

report_coverage() {
  local SRCDIR=$1
  shift
  python3 ${SRCDIR}/tools/coverage/gather.py && python3 ${SRCDIR}/tools/coverage/report.py "$@"
}

# Install lab-only modules
do_lab_install() {
  local PLATFORM="$1"
  local LAB_ONLY_MODULES="$2"
  for module in $LAB_ONLY_MODULES; do
    cp -LR include/IMP/${module}.h include/IMP/${module} \
           ${IMPINSTALL}/src/${PLATFORM}/include/IMP/
    cp -LR lib/_IMP_${module}.* lib/libimp_${module}.* \
           ${IMPINSTALL}/lib/${PLATFORM}/
    cp -LR lib/IMP/${module} ${IMPINSTALL}/lib/${PLATFORM}/IMP/
    cp -LR data/${module} ${IMPINSTALL}/data/IMP/
    cp -LR swig/IMP_${module}.i* ${IMPINSTALL}/share/IMP/swig/
  done
}

# Do a 'make install', and check the install for usability
do_make_install() {
  local MAKE="$1"
  local SRCDIR="$2"
  local PLATFORM="$3"
  local PYTHON="$4"
  show_and_execute ${MAKE} install || return 1
  for fullbin in ${IMPINSTALL}/bin/${PLATFORM}/*; do
    bin=`basename ${fullbin}`
    for binpath in /usr/bin /usr/local/bin /usr/sbin /usr/local/sbin; do
      if [ -e ${binpath}/${bin} ]; then
        echo "IMP binary $bin clashes with system binary ${binpath}/${bin}"
        return 1
      fi
    done
  done

  if [ ${PLATFORM} = "debug8" ] || [ ${PLATFORM} = "fast8" ] || [ ${PLATFORM} = "release8" ]; then
    # Make sure command line tools use system Python 3
    sed -i -e 's,^#!.*python.*,#!/usr/bin/python3,' ${IMPINSTALL}/bin/${PLATFORM}/*
  fi

  if [ -f /usr/bin/scons-3 ]; then
    SCONS=scons-3
  else
    SCONS=scons
  fi
  if [ ${PLATFORM} = "debug8" ] || [ ${PLATFORM} = "fast8" ] || [ ${PLATFORM} = "release8" ]; then
    # Get install-time paths from IMP CMake config
    local CMAKECFG="${IMPINSTALL}/lib/${PLATFORM}/cmake/IMP/IMPConfig.cmake"
    local EIGEN_INCLUDE=$(grep EIGEN3_INCLUDE_DIR ${CMAKECFG} | cut -d\" -f2)
    local CEREAL_INCLUDE=$(grep cereal_INCLUDE_DIRS ${CMAKECFG} | cut -d\" -f2)
    local BOOST_INCLUDE=$(grep Boost_INCLUDE_DIR ${CMAKECFG} | cut -d\" -f2)
    local IMP_INCLUDE=$(grep IMP_INCLUDE_DIR ${CMAKECFG} | cut -d\" -f2)
    local IMP_LIB=$(grep "set(IMP_LIB_DIR" ${CMAKECFG} | cut -d\" -f2)
    local IMP_PYTHON=$(grep IMP_PYTHON_DIR ${CMAKECFG} | cut -d\" -f2)
    local IMP_BIN=$(grep IMP_BIN_DIR ${CMAKECFG} | cut -d\" -f2)
    local BOOST_LIB=$(dirname $(grep BOOST.SYSTEM_LIBRARIES ${CMAKECFG} | cut -d\" -f2) )
    local TAU_LIB=$(dirname $(grep LIBTAU_LIBRARIES ${CMAKECFG} | cut -d\" -f2 | cut -d\; -f1) )
    local ARGS=("libpath=${IMP_LIB}:${BOOST_LIB}:${TAU_LIB}" \
                "cpppath=${EIGEN_INCLUDE}:${CEREAL_INCLUDE}:${BOOST_INCLUDE}:${IMP_INCLUDE}" \
                "pypath=${IMP_PYTHON}" \
                "path=${IMP_BIN}")
    local DIR=$SRCDIR/tools/nightly-tests/test-install
    local CXXFLAGS="-std=c++14"
    cd_show_and_execute $DIR ${SCONS} \
              "${ARGS[@]}" \
              "python=${PYTHON}" \
              "cxxflags=${CXXFLAGS}" || return 1
  fi
}

# Add Python interfaces for multiple versions of Python 3
add_extra_python() {
  local PLATFORM=$1

  local PY3ABITAG="cpython-36m-x86_64-linux-gnu"
  # Rename already-installed Python 3 extensions to use PEP3149 naming
  # so only Python 3 will load them
  echo "Adding Python 3.6 ABI tag ${PY3ABITAG} to all IMP extensions..."
  (cd ${IMPINSTALL}/lib/${PLATFORM} && for ext in _*.so; do mv $ext ${ext%.so}.${PY3ABITAG}.so; done)

  # Add symlinks for newer compatible Python versions (Wynton and Fedora)
  for pyver in 37m 38 39 310 311 312 313; do
    echo "Adding symlinks for Python ${pyver}..."
    (cd lib && for ext in _*.so; do ln -sf ${ext%.so}.${PY3ABITAG}.so ${IMPINSTALL}/lib/${PLATFORM}/${ext%.so}.cpython-${pyver}-x86_64-linux-gnu.so; done)
  done
}

# Configure, build and test IMP using cmake
run_cmake_build() {
  local SRCDIR=$1
  local PLATFORM=$2
  local PYTHON="$3"
  local CMAKE="$4"
  local CTEST="$5"
  local MAKE="$6"
  local OPTS="$7"
  local EXTRA="$8"
  local LOG_DIR=${IMPLOGS}/imp/${PLATFORM}
  local LAB_LOG_DIR=${IMP_LAB_LOGS}/imp-salilab/${PLATFORM}

  local CMAKE_INSTALL="${CMAKE}"
  CMAKE_ARGS=("${CMAKE_ARGS[@]}" "${CMAKE_NON_CACHE_ARGS[@]}")
  if echo "${EXTRA}" | grep -q install; then
    # Set install directories if we're doing any installs
    CMAKE_INSTALL="${CMAKE_INSTALL} -DCMAKE_INSTALL_PREFIX=${IMPINSTALL} -DCMAKE_INSTALL_DATADIR=data -DCMAKE_INSTALL_BUILDINFODIR=build_info/${PLATFORM} -DCMAKE_INSTALL_PYTHONDIR=lib/${PLATFORM} -DCMAKE_INSTALL_INCLUDEDIR=src/${PLATFORM}/include -DCMAKE_INSTALL_LIBDIR=lib/${PLATFORM} -DCMAKE_INSTALL_BINDIR=bin/${PLATFORM} -DCMAKE_INSTALL_DOCDIR=doc"
  fi

  run_imp_build ALL ${LOG_DIR} cmake_build "$SRCDIR" "$PYTHON" "$CMAKE_INSTALL" "$CTEST" "$MAKE" "$OPTS --outdir=${LOG_DIR} --summary=${LOG_DIR}/summary.pck --all=ALL"
  local BUILDRET=$?
  cp CMakeCache.txt ${LOG_DIR}

  # Run doc build before install, since install triggers a doc build
  # (and we want the doc output in the doc log file, not the install log file)
  if echo "${EXTRA}" | grep -q docinstall; then
    run_imp_build DOC ${LOG_DIR} ${MAKE} IMP-doc-install
    run_imp_build RMF-DOC ${LOG_DIR} ${MAKE} RMF-doc && cp -r src/dependency/RMF/doc/html ${IMPINSTALL}/RMF-doc
  fi

  # Skip if build failed
  if [ ${BUILDRET} -eq 0 ]; then
    if echo "${EXTRA}" | grep -q allinstall; then
      run_imp_build INSTALL ${LOG_DIR} do_make_install "${MAKE}" "${SRCDIR}" "${PLATFORM}" "${PYTHON}"
    fi
  fi
  if echo "${EXTRA}" | grep -q coverage; then
    run_imp_build COVERAGE ${LOG_DIR} report_coverage "${SRCDIR}" ${LOG_DIR}
  fi
  if echo "${EXTRA}" | grep -q allpython; then
    run_imp_build ALLPYTHON ${LOG_DIR} add_extra_python "${PLATFORM}"
  fi
  if [ ${BUILDRET} -eq 0 ]; then
    if echo "${EXTRA}" | grep -q w..package; then
      # Make installer in a temporary copy of the build dir, so as not to
      # affect further builds
      local cwd=`pwd`
      local BITS=32
      if echo "${EXTRA}" | grep -q w64package; then
        BITS=64
      fi
      cd .. && mv build build.bak && cp -a build.bak build && cd build && \
          run_imp_build PACKAGE ${LOG_DIR} build_w32_package "$CMAKE" "$SRCDIR" "$MAKE" "${BITS}"
      cd $cwd/.. && rm -rf build && mv build.bak build
      cd $cwd
    fi
    if echo "${EXTRA}" | grep -q macpackage; then
      local cwd=`pwd`
      cd .. && mv build build.bak && cp -a build.bak build && cd build && \
          run_imp_build PACKAGE ${LOG_DIR} build_mac_package "$CMAKE" "$SRCDIR" "$MAKE"
      cd $cwd/.. && rm -rf build && mv build.bak build
      cd $cwd
    fi
  fi

  if [ -n "${IMPLABSRCTGZ}" ]; then
    (cd ${SRCDIR}/modules && ${TAR} -xzf ${IMPLABSRCTGZ})
    # Don't pass -D cache options to cmake again, since it gets confused
    # if we try to set (e.g.) CMAKE_CXX_COMPILER this way; use only
    # non-cache args
    CMAKE_ARGS=("${CMAKE_NON_CACHE_ARGS[@]}" "${CMAKE_LAB_ONLY_ARGS[@]}")
    run_imp_build ALL_LAB ${LAB_LOG_DIR} cmake_build "$SRCDIR" "$PYTHON" "$CMAKE" "$CTEST" "$MAKE" "$OPTS --exclude=${LOG_DIR}/summary.pck --outdir=${LAB_LOG_DIR} --summary=${LAB_LOG_DIR}/summary.pck --all=ALL_LAB"
    cp CMakeCache.txt ${LAB_LOG_DIR}
    local LAB_ONLY_MODULES=`${OLDPYTHON} -c "import pickle; mods = [k for k in pickle.load(open(\"${LAB_LOG_DIR}/summary.pck\", \"rb\")).keys() if k != 'ALL_LAB']; print(' '.join(mods))"`

    if echo "${EXTRA}" | grep -q coverage; then
      run_imp_build COVERAGE_LAB ${LAB_LOG_DIR} report_coverage "${SRCDIR}" --exclude=${LOG_DIR}/summary.pck ${LAB_LOG_DIR}
    fi
    if echo "${EXTRA}" | grep -q allinstall; then
      # Install lab-only modules with main IMP in diva1 (must do this manually
      # rather than with "make install" since we don't want to pollute the
      # docs, etc. with lab-only stuff)
      run_imp_build INSTALL_LAB ${LAB_LOG_DIR} do_lab_install "${PLATFORM}" "${LAB_ONLY_MODULES}"
    fi
  fi
}

# Determine which cmake/ctest binary to use for this platform, and get
# a default set of cmake arguments.
get_cmake() {
  local PLATFORM=$1
  CMAKE="cmake"
  CMAKE_NON_CACHE_ARGS=()
  CMAKE_LAB_ONLY_ARGS=()
  CMAKE_ARGS=()
  CTEST="ctest"
  # Cross compile for Windows
  if [ ${PLATFORM} == "i386-w32" ]; then
    CMAKE="cmake3-w32"
    CTEST="ctest3-w32"
  elif [ ${PLATFORM} == "x86_64-w64" ]; then
    CMAKE="cmake3-w64"
    CTEST="ctest3-w64"
  fi
}

# Set paths so that the latest successful build of Modeller SVN can be used.
# The single argument is the Modeller exetype to use; if not given, the most
# appropriate exetype for the current machine is used.
use_modeller_svn() {
  local PLATFORM=$1
  local ROOT=/salilab/diva1/home/modeller/SVN
  if [ "${PLATFORM}" = "i386-w32" ] || [ "${PLATFORM}" = "x86_64-w64" ]; then
    local PP=${ROOT}/modlib
    if [ -z "${PYTHONPATH}" ]; then
      export PYTHONPATH=${PP}
    else
      export PYTHONPATH="${PYTHONPATH};${PP}"
    fi
  else
    if [ -z "${PLATFORM}" ]; then
      if [ `uname -m` = "x86_64" ]; then
        PLATFORM="x86_64-intel8"
      else
        PLATFORM="i386-intel8"
      fi
    fi
    local LLP=${ROOT}/lib/${PLATFORM}
    local PP=${LLP}:${ROOT}/modlib
    if [ -z "${PYTHONPATH}" ]; then
      export PYTHONPATH=${PP}
    else
      export PYTHONPATH="${PYTHONPATH}:${PP}"
    fi
    if [ -z "${LD_LIBRARY_PATH}" ]; then
      export LD_LIBRARY_PATH=${LLP}
    else
      export LD_LIBRARY_PATH="${LD_LIBRARY_PATH}:${LLP}"
    fi
  fi
}

# Modify wine's default path so that IMP binaries will run from the build dir
add_imp_to_wine_path() {
  python2 - "$1" <<END
import os, sys
dbl_bksl = '\\\\\\\\'
imp = 'Z:' + sys.argv[1].replace('/', dbl_bksl)
sysreg = os.path.join(os.environ['HOME'], '.wine', 'system.reg')
outfh = open(sysreg + '.new', 'w')
for line in open(sysreg):
    if line.startswith('"PATH"='):
        print >> outfh, \\
              r'"PATH"=str(2):"C:\\\\windows\\\\system32;C:\\\\windows;' \\
              + dbl_bksl.join((imp, 'lib')) + ';' \\
              + dbl_bksl.join((imp, 'bin')) + ';' \\
              + dbl_bksl.join((imp, 'src', 'dependency', 'RMF')) + '"'
    else:
        outfh.write(line)
os.rename(sysreg + '.new', sysreg)
END
}

# Modify wine's default path so that installed IMP binaries will run
add_installed_imp_to_wine_path() {
  # Make sure that wine is finished editing system.reg (otherwise it will
  # overwrite our changes)
  sleep 30
  python3 - << END
import os
sysreg = os.path.join(os.environ['HOME'], '.wine', 'system.reg')
outfh = open(sysreg + '.new', 'w')
for line in open(sysreg):
    if line.startswith('"PATH"='):
        print(r'"PATH"=str(2):"C:\\\\windows\\\\system32;C:\\\\windows;'
	      r'C:\\\\IMP-test\\\\bin"', file=outfh)
    else:
        outfh.write(line)
os.rename(sysreg + '.new', sysreg)
END
}
