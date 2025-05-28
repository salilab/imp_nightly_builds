import glob
import datetime
import pickle
import os
import MySQLdb
import collections
from email.utils import formatdate
from email.mime.text import MIMEText

topdir = '/salilab/diva1/home/imp'
lab_only_topdir = '/salilab/diva1/home/imp-salilab/develop'
OK_STATES = ('OK', 'SKIP', 'EXPFAIL', 'SKIP_EXPFAIL')
lab_only_results_url = 'https://salilab.org/internal/imp/nightly/results/'
results_url = 'https://integrativemodeling.org/nightly/results/'

# Special components are build steps that do not correspond to IMP modules,
# applications, or biological systems. They are only 'built', never tested
# or benchmarked.
SPECIAL_COMPONENTS = {'ALL': 'Entire cmake and make',
                      'ALL_LAB': 'Entire cmake and make of '
                                 'lab-only components',
                      'INSTALL': 'Installation of all of IMP',
                      'INSTALL_LAB': 'Installation of lab-only components',
                      'DOC': 'Build and install of documentation',
                      'RMF-DOC': 'Build and install of RMF documentation',
                      'PACKAGE': 'Build of binary package',
                      'PKGTEST': 'Test of binary package',
                      'OPENMPI': 'Rebuild of IMP.mpi module against '
                                 'different versions of OpenMPI',
                      'PYTHON3': 'Also build Python 3 extensions on platforms '
                                 'that use Python 2 by default',
                      'PYTHON2': 'Also build Python 2 extensions on platforms '
                                 'that use Python 3 by default',
                      'ALLPYTHON': 'Add support for multiple versions '
                                   'of Python 3',
                      'COVERAGE': 'Coverage of C++ and Python code',
                      'COVERAGE_LAB': 'Coverage of C++ and Python code '
                                      'in lab-only components'}


def get_topdir(branch):
    """Get the top-level directory on diva1 for this branch"""
    return os.path.join(topdir, branch)


class Platform:
    def __init__(self, very_short, short, long, very_long, logfile):
        self.very_short = very_short
        self.short = short
        self.long = long
        self.very_long = very_long
        self.logfile = logfile


rpm_vlong_header = """
<p>This platform builds and tests the IMP RPM package on a fully updated
%s system. The actual build is done in a
<a href="https://github.com/rpm-software-management/mock/wiki">mock</a> environment.</p>
"""  # noqa:E501
rpm_vlong_footer = """
<p>To build an RPM package yourself, you can rebuild from the source RPM
(available at the
<a href="https://integrativemodeling.org/download-linux.html">download page</a>)
or use the spec file in the
<a href="https://github.com/salilab/imp/tree/develop/tools/rpm">tools/rpm/</a>
directory. Note that you will
need some extra nonstandard RPM packages to reproduce our builds:
<a href="https://salilab.org/modeller/">modeller</a>,
<a href="https://integrativemodeling.org/libTAU.html">libTAU,
libTAU-devel</a>, and other dependencies available at
<a href="https://integrativemodeling.org/build-extras/">https://integrativemodeling.org/build-extras/</a>.
The build scripts can also be found in the
<a href="https://github.com/salilab/imp_nightly_builds">IMP nightly builds</a>
GitHub repo.
"""  # noqa:E501

rpm_cvlong = rpm_vlong_header + """
<p>The resulting package should install on a RedHat Enterprise machine
(or clones such as CentOS, Rocky, or Alma) with the
<a href="https://fedoraproject.org/wiki/EPEL">EPEL repository</a>.</p>
""" + rpm_vlong_footer + "%s"

rpm_centos5 = """In particular, the versions of cmake, HDF5 and SWIG that ship
with CentOS 5 are too old for IMP. We provide newer versions."""

debug_build_vlong = """
<p>This is a <b>debug</b> build, built with all checks turned on
(<tt>IMP_MAX_CHECKS=INTERNAL</tt> cmake option). This is so that the tests
can be as thorough as possible. The resulting code is much slower, however,
so the IMP tests marked EXPENSIVE are skipped (they are run in fast builds).
</p>
"""
fast_build_vlong = """
<p>This is a <b>fast</b> build, built with all checks and logging turned off
(<tt>IMP_MAX_CHECKS=NONE</tt> and <tt>IMP_MAX_LOG=SILENT</tt> cmake options).
This gives the fastest running code, so even tests marked EXPENSIVE are
run with this build. However, the lack of runtime error checking means that
test failures may be hard to diagnose (IMP may segfault rather than
reporting an error).</p>
"""
fast_build_module_vlong = fast_build_vlong + """
<p>In the Sali lab, fast builds can be used on the Linux workstations
by running <tt>module load imp-fast</tt>.
They can also be used on the Wynton cluster by running
<tt>module load Sali imp-fast</tt>.
Work out all the bugs first though!</p>
"""

release_build_module_vlong = """
<p>This is a <b>release</b> build, built with only usage checks turned on.
This gives code that is almost as fast as a 'fast' build, without sacrificing
logging or error checking (the binary installer packages are similar). Such
builds should be preferred for all but the most compute-intensive tasks.
</p>

<p>In the Sali lab, this build can be used on the Linux workstations
by running <tt>module load imp</tt>.
It can also be used on the Wynton cluster by running
<tt>module load Sali imp</tt>.</p>
"""

windows_vlong = """
<p>This platform builds and tests IMP for %s Windows, and also builds a
<tt>.exe</tt> installer. It does not actually run on a real Windows machine;
it runs on a Linux box and runs the real Windows binaries for the C++ compiler,
Python, and the built IMP itself via <a href="https://winehq.org/">WINE</a>.
(We do this to more easily integrate with our Linux systems.)
</p>

<p>To build the .exe package yourself, see the
<a href="https://github.com/salilab/imp/tree/develop/tools/w32">tools/w32/</a>
directory, in particular the <tt>make-package.sh</tt> script.
The build scripts can also be found in the
<a href="https://github.com/salilab/imp_nightly_builds">IMP nightly builds</a>
GitHub repo.</p>

<p>It should also be possible to build IMP on a real Windows machine;
instructions are in the IMP documentation. If it doesn't work, let us know
and we'll fix it!</p>
"""

mac_header = """
<p>This platform builds and tests IMP on a %s system with %s, using scripts in
the
<a href="https://github.com/salilab/imp_nightly_builds">IMP nightly builds</a>
GitHub repo. This is a
standard Mac with XCode installed plus <a href="https://brew.sh/">Homebrew</a>,
the <tt>salilab/salilab</tt> Homebrew tap, and
the following Homebrew packages: %s<tt>boost</tt>, <tt>cgal</tt>,
<tt>cmake</tt>, <tt>hdf5</tt>, <tt>libtau</tt>, <tt>ninja</tt>,
<tt>pkg-config</tt>, <tt>opencv</tt>, <tt>protobuf</tt>, <tt>eigen</tt>,
<tt>cereal</tt>, <tt>fftw</tt>, <tt>open-mpi</tt>, and <tt>swig</tt>.
</p>
"""
mac_vlong = mac_header + debug_build_vlong

macpkg_vlong = """
<p>This platform also builds the Mac .dmg installer package. This is built from
the same IMP code but with only usage checks turned on (the resulting code
is much faster than that with internal checks).</p>

<p>To build the package yourself, see the
<a href="https://github.com/salilab/imp/tree/develop/tools/mac">tools/mac/</a>
directory, in particular the <tt>make-package.sh</tt> script.</p>
"""

percpp_vlong = """
<p>Most IMP builds do batch compilation, where the compiler handles all the
<tt>.cpp</tt> files for a module at once. However, IMP also supports a
"per-cpp" mode where each <tt>.cpp</tt> file is compiled individually (the
<tt>IMP_PER_CPP_COMPILATION</tt> cmake option). This mode is less tolerant
of missing <tt>#include</tt> statements and other programming errors.
This platform builds IMP in this mode to detect such errors.
</p>
"""

mac109_vlong = """
<p>Note that occasionally the build does not run at all on this platform
(yellow boxes in the build summary). This is because the cronjob on this
machine sometimes doesn't get started. This appears to be a bug in OS X 10.9.
</p>
"""

ubuntu_vlong = """
<p>This platform builds and tests the IMP Debian/Ubuntu (<tt>.deb</tt>) package
on 64-bit Ubuntu %s (running inside a
<a href="https://www.docker.com/">Docker</a> container).</p>

<p>To build the package yourself, see the
<a href="https://github.com/salilab/imp/tree/develop/tools/debian">tools/debian/</a>
directory, in particular the <tt>make-package.sh</tt> script.
The build scripts can also be found in the
<a href="https://github.com/salilab/imp_nightly_builds">IMP nightly builds</a>
GitHub repo.</p>
"""  # noqa:E501

linux_vlong = """
<p>This platform builds and tests IMP on a fully updated %s,
using scripts in the
<a href="https://github.com/salilab/imp_nightly_builds">IMP nightly builds</a>
GitHub repo.%s
The system is customized with additional RPM packages so that all IMP modules
and applications can be built and tested (in contrast to the RPM builds, where
only those modules and applications that use packages in the RedHat
repositories are built).
</p>
%s
"""

cuda_vlong = """
<p>This platform builds and tests IMP on a fully updated %s system with
the CUDA toolkit, using scripts in the
<a href="https://github.com/salilab/imp_nightly_builds">IMP nightly builds</a>
GitHub repo, and activates IMP's <b>experimental</b> GPU code.
</p>
"""

coverage_vlong = """
<p>This platform builds and tests IMP on a fully updated %s system,
and collects coverage information. This information is reported for
both Python and C++ code, for modules and applications, on the far right
side of the build summary page.</p>

<p>
For more information on coverage reporting, see the
<a href="https://github.com/salilab/imp/tree/develop/tools/coverage">tools/coverage/</a>
directory.
The build scripts can also be found in the
<a href="https://github.com/salilab/imp_nightly_builds">IMP nightly builds</a>
GitHub repo.
</p>
%s
"""  # noqa: E501

static_vlong = """
<p>This platform builds IMP on a fully updated %s system, using scripts in the
<a href="https://github.com/salilab/imp_nightly_builds">IMP nightly builds</a>
GitHub repo, but unlike
regular builds, links every binary statically (<tt>IMP_STATIC</tt> cmake
option). Note that many modules do not support static linking and thus are
excluded from this build. Also, since Python requires dynamic linking, no
Python modules are built or tests run.
</p>
"""

openmp_vlong = """
It is built with <a href="http://openmp.org/">OpenMP</a> support
(<tt>-fopenmp</tt> compiler flag) to test IMP parallel code.
"""

openmpi_vlong = """
It is built with <a href="http://www.mpi-forum.org/">MPI</a> support
(<tt>mpicc</tt> and <tt>mpic++</tt>
<a href="https://www.open-mpi.org/">OpenMPI</a> compilers) to test IMP
parallel code.
"""

all_platforms = (('i386-intel8',
                  Platform(
                      'Lin32', 'Linux32',
                      'Debug build (32-bit Linux; CentOS 6.10 on i686; '
                      'Boost 1.41)',
                      linux_vlong % ("32-bit CentOS 6.10 system", '',
                                     debug_build_vlong),
                      'bin.i386-intel8.log')),
                 ('x86_64-intel8',
                  Platform(
                      'Dbg', 'Debug',
                      'Debug build (64-bit Linux; CentOS 7.9 on x86_64; '
                      'Boost 1.53, Python 2)',
                      linux_vlong % ("64-bit CentOS 7.9 system with Python 2",
                                     '', debug_build_vlong),
                      'bin.x86_64-intel8.log')),
                 ('fast64',
                  Platform(
                      'Fast', 'Fast',
                      'Fast build (64-bit Linux, CentOS 7.9, Boost 1.53, '
                      'Python 3)',
                      linux_vlong % ("64-bit CentOS 7.9 system "
                                     "with Python 3", '',
                                     fast_build_module_vlong),
                      'bin-fast.x86_64-intel8.log')),
                 ('debug8',
                  Platform(
                      'Dbg', 'Debug',
                      'Debug build (64-bit Linux, Rocky 8.10)',
                      linux_vlong % ("64-bit Rocky 8.10 system",
                                     '', debug_build_vlong),
                      'bin.x86_64-intel8.log')),
                 ('fast8',
                  Platform(
                      'Fast', 'Fast',
                      'Fast build (64-bit Linux, Rocky 8.10, Boost 1.73)',
                      linux_vlong % ("64-bit Rocky 8.10 system", '',
                                     fast_build_module_vlong),
                      'bin-fast.x86_64-intel8.log')),
                 ('release64',
                  Platform(
                      'Rls', 'Release',
                      'Release build (64-bit Linux, CentOS 7.9, Boost 1.53, '
                      'Python 3)',
                      linux_vlong % ("64-bit CentOS 7.9 system "
                                     "with Python 3", '',
                                     release_build_module_vlong),
                      'bin-release.x86_64-intel8.log')),
                 ('release8',
                  Platform(
                      'Rls', 'Release',
                      'Release build (64-bit Linux, Rocky 8.10, Boost 1.73)',
                      linux_vlong % ("64-bit Rocky 8.10 system", '',
                                     release_build_module_vlong),
                      'bin-release.x86_64-intel8.log')),
                 ('cuda',
                  Platform(
                      'CUDA', 'CUDA',
                      'CUDA build (64-bit Linux, Fedora 42, gcc 15.0, '
                      'Boost 1.83, CUDA toolkit 12.8)',
                      cuda_vlong % "64-bit Fedora 42",
                      'bin-cuda.log')),
                 ('mac10v4-intel',
                  Platform(
                      'Mac', 'Mac 10.4',
                      '32-bit Intel Mac (MacOS X 10.4 (Tiger), '
                      '32 bit; Boost 1.47)', '', 'bin.mac10v4-intel.log')),
                 ('mac10v4-intel64',
                  Platform(
                      'M10.10', 'Mac 10.10',
                      'Debug build (64-bit Intel Mac; MacOS X 10.10 '
                      '(Yosemite); Boost 1.58; Python 2)',
                      mac_vlong % ("64-bit 10.10 (Yosemite) Mac",
                                   "Apple's Python 2", "")
                      + macpkg_vlong,
                      'bin.mac10v4-intel64.log')),
                 ('mac10v8-intel',
                  Platform(
                      'M10.8', 'Mac 10.8',
                      'Debug build (64-bit Intel Mac; MacOS X 10.8 '
                      '(Mountain Lion); clang++; Boost 1.55; '
                      'per-cpp compilation)',
                      mac_vlong % ("64-bit 10.8 (Mountain Lion) Mac",
                                   "Homebrew Python 2", "")
                      + percpp_vlong,
                      'bin.mac10v8-intel.log')),
                 ('mac10v9-intel',
                  Platform(
                      'M10.9', 'Mac 10.9',
                      'Debug build (64-bit Intel Mac; MacOS X 10.9 '
                      '(Mavericks); clang++; Boost 1.58)',
                      mac_vlong % ("64-bit 10.9 (Mavericks) Mac",
                                   "Homebrew Python 2", "")
                      + mac109_vlong,
                      'bin.mac10v9-intel.log')),
                 ('mac10v10-intel',
                  Platform(
                      'M10.10', 'Mac 10.10',
                      'Debug build (64-bit Intel Mac; MacOS X 10.10 '
                      '(Yosemite); clang++; Boost 1.67; Python 3; '
                      'per-cpp compilation)',
                      mac_vlong % ("64-bit 10.10 (Yosemite) Mac",
                                   "Homebrew Python 3", "")
                      + percpp_vlong,
                      'bin.mac10v10-intel.log')),
                 ('mac10v11-intel',
                  Platform(
                      'M10.11', 'Mac 10.11',
                      'Debug build (64-bit Intel Mac; MacOS X 10.11 '
                      '(El Capitan); clang++; Boost 1.67; Python 3)',
                      mac_vlong % ("64-bit 10.11 (El Capitan) Mac",
                                   "Homebrew Python 3", ""),
                      'bin.mac10v11-intel.log')),
                 ('mac10v15-intel',
                  Platform(
                      'M10.15', 'Mac 10.15',
                      'Debug build (64-bit Intel Mac; MacOS 10.15 '
                      '(Catalina); clang++; Boost 1.73; Python 3; '
                      'per-cpp compilation)',
                      mac_vlong % ("64-bit 10.15 (Catalina) Mac",
                                   "Homebrew Python 3", "")
                      + percpp_vlong,
                      'bin.mac10v15-intel.log')),
                 ('mac11v0-intel',
                  Platform(
                      'M11', 'Mac 11',
                      'Debug build (64-bit Intel Mac; MacOS 11 '
                      '(Big Sur); clang++; Boost 1.74; Python 3; '
                      'per-cpp compilation)',
                      mac_vlong % ("64-bit MacOS 11 (Big Sur) Mac",
                                   "Homebrew Python 3", "")
                      + percpp_vlong,
                      'bin.mac11v0-intel.log')),
                 ('mac11-arm64',
                  Platform(
                      'MARM', 'Mac ARM',
                      'Debug build (Apple Silicon Mac; MacOS 11 '
                      '(Big Sur); clang++; Boost 1.74; Python 3; '
                      'per-cpp compilation)',
                      mac_vlong % ("64-bit Apple Silicon "
                                   "MacOS 11 (Big Sur) Mac",
                                   "Homebrew Python 3", "")
                      + percpp_vlong,
                      'bin.mac11-arm64.log')),
                 ('mac11arm64-gnu',
                  Platform(
                      'MARM', 'Mac ARM',
                      'Debug build (Apple Silicon Mac; MacOS 11 '
                      '(Big Sur); clang++; Boost 1.74; Python 3; '
                      'per-cpp compilation)',
                      mac_vlong % ("64-bit Apple Silicon "
                                   "MacOS 12 (Big Sur) Mac",
                                   "Homebrew Python 3", "")
                      + percpp_vlong,
                      'bin.mac11arm64-gnu.log')),
                 ('mac12arm64-gnu',
                  Platform(
                      'MARM', 'Mac ARM',
                      'Debug build (Apple Silicon Mac; MacOS 12 '
                      '(Monterey); clang++; Boost 1.86; Python 3; '
                      'per-cpp compilation)',
                      mac_vlong % ("64-bit Apple Silicon "
                                   "MacOS 12 (Monterey) Mac",
                                   "Homebrew Python 3",
                                   "<tt>doxygen@1.8.6</tt>, "
                                   "<tt>graphviz</tt>, ")
                      + percpp_vlong,
                      'bin.mac12arm64-gnu.log')),
                 ('mac13arm64-gnu',
                  Platform(
                      'MARM', 'Mac ARM',
                      'Debug build (Apple Silicon Mac; MacOS 13 '
                      '(Ventura); clang++; Boost 1.88; per-cpp compilation)',
                      mac_vlong % ("64-bit Apple Silicon "
                                   "MacOS 13 (Ventura) Mac",
                                   "Homebrew Python",
                                   "<tt>doxygen@1.8.6</tt>, "
                                   "<tt>graphviz</tt>, ")
                      + percpp_vlong,
                      'bin.mac13arm64-gnu.log')),
                 ('mac12-intel',
                  Platform(
                      'M12', 'Mac 12',
                      'Debug build (64-bit Intel Mac; MacOS 12 '
                      '(Monterey); clang++; Boost 1.86; Python 3; '
                      'per-cpp compilation)',
                      mac_vlong % ("64-bit MacOS 12 (Monterey) Mac",
                                   "Homebrew Python 3", "")
                      + percpp_vlong,
                      'bin.mac12-intel.log')),
                 ('mac14-intel',
                  Platform(
                      'M14', 'Mac 14',
                      'Debug build (64-bit Intel Mac; MacOS 14 '
                      '(Sonoma); clang++; Boost 1.88; per-cpp compilation)',
                      mac_vlong % ("64-bit MacOS 14 (Sonoma) Mac",
                                   "Homebrew Python", "")
                      + percpp_vlong,
                      'bin.mac14-intel.log')),
                 ('fastmac13',
                  Platform(
                      'McFst', 'Mac Fast',
                      'Fast build (Apple Silicon Mac; MacOS 13 (Ventura); '
                      'clang++; Boost 1.81; Python 3)',
                      mac_header % ("Apple Silicon MacOS 13 (Ventura) Mac",
                                    "Homebrew Python 3", "")
                      + fast_build_vlong, 'bin-fast.mac13-intel.log')),
                 ('fastmac14',
                  Platform(
                      'McFst', 'Mac Fast',
                      'Fast build (Apple Silicon Mac; MacOS 14 (Sonoma); '
                      'clang++; Boost 1.86; Python 3)',
                      mac_header % ("Apple Silicon MacOS 14 (Sonoma) Mac",
                                    "Homebrew Python 3", "")
                      + fast_build_vlong, 'bin-fast.mac14-intel.log')),
                 ('fastmac15',
                  Platform(
                      'McFst', 'Mac Fast',
                      'Fast build (Apple Silicon Mac; MacOS 15 (Sequoia); '
                      'clang++; Boost 1.88)',
                      mac_header % ("Apple Silicon MacOS 15 (Sequoia) Mac",
                                    "Homebrew Python", "")
                      + fast_build_vlong, 'bin-fast.mac15-intel.log')),
                 ('i386-w32',
                  Platform(
                      'Win32', 'Win32',
                      '32-bit Windows build (WINE 6.0.2, MSVC++ 2017, '
                      'Boost 1.83)', windows_vlong % "32-bit",
                      'bin.i386-w32.log')),
                 ('x86_64-w64',
                  Platform(
                      'Win64', 'Win64',
                      '64-bit Windows build (WINE 6.0.2, MSVC++ 2017, '
                      'Boost 1.83)', windows_vlong % "64-bit",
                      'bin.x86_64-w64.log')),
                 ('fast',
                  Platform(
                      'Fst32', 'Fast32',
                      'Fast build (32-bit Linux, CentOS 6.10, Boost 1.41)',
                      linux_vlong % ("32-bit CentOS 6.10 system", '',
                                     fast_build_module_vlong),
                      'bin-fast.i386-intel8.log')),
                 ('openmp',
                  Platform(
                      'OMP', 'OpenMP',
                      'OpenMP build (64-bit Linux, CentOS 6.10, Boost 1.41)',
                      linux_vlong % ("64-bit CentOS 6.10 system", openmp_vlong,
                                     debug_build_vlong),
                      'openmp.x86_64-intel8.log')),
                 ('fastmac',
                  Platform(
                      'FstMc', 'FastMac',
                      'Fast build (MacOS X 10.8 (Mountain Lion), '
                      '64 bit; clang++; Boost 1.55)',
                      mac_header % ("64-bit 10.8 (Mountain Lion) Mac",
                                    "Homebrew Python 2", "")
                      + fast_build_vlong, 'bin-fast.mac10v8-intel.log')),
                 ('fastmac10v10',
                  Platform(
                      'FstMc', 'FastMac',
                      'Fast build (MacOS X 10.10 (Yosemite), '
                      '64 bit; clang++; Boost 1.66)',
                      mac_header % ("64-bit 10.10 (Yosemite) Mac",
                                    "Homebrew Python 3", "")
                      + fast_build_vlong, 'bin-fast.mac10v10-intel.log')),
                 ('fastmac10v15',
                  Platform(
                      'FstMc', 'FastMac',
                      'Fast build (MacOS X 10.15 (Catalina), '
                      '64 bit; clang++; Boost 1.80; Python 3)',
                      mac_header % ("64-bit 10.15 (Catalina) Mac",
                                    "Homebrew Python 3", "")
                      + fast_build_vlong, 'bin-fast.mac10v10-intel.log')),
                 ('fastmac11',
                  Platform(
                      'FstMc', 'FastMac',
                      'Fast build (64-bit Intel Mac; MacOS 11 (Big Sur); '
                      'clang++; Boost 1.80; Python 3)',
                      mac_header % ("64-bit MacOS 11 (Big Sur) Mac",
                                    "Homebrew Python 3", "")
                      + fast_build_vlong, 'bin-fast.mac11-intel.log')),
                 ('fastmpi',
                  Platform(
                      'MPI', 'FastMPI',
                      'Fast build (64-bit Linux, OpenMPI 1.5.4, CentOS 6.10, '
                      'Boost 1.41)',
                      linux_vlong % ("64-bit CentOS 6.10 system",
                                     openmpi_vlong, fast_build_vlong),
                      'bin-fast.x86_64-intel8.mpi.log')),
                 ('static',
                  Platform(
                      'Stat', 'Static',
                      'Static build (x86_64 Linux, CentOS 7.9, Boost 1.53)',
                      static_vlong % "64-bit CentOS 7.9",
                      'bin-static.x86_64-intel8.log')),
                 ('static9',
                  Platform(
                      'Stat', 'Static',
                      'Static build (x86_64 Linux, Rocky 9.5, Boost 1.75)',
                      static_vlong % "64-bit Rocky 9.5",
                      'bin-static.x86_64-intel8.log')),
                 ('coverage',
                  Platform(
                      'Cov', 'Coverage',
                      'Coverage build (debug build on Fedora 42, 64-bit; '
                      'Boost 1.83, gcc 15.0)',
                      coverage_vlong % ("64-bit Fedora 42",
                                        debug_build_vlong),
                      'coverage.log')),
                 ('pkg.el5-i386',
                  Platform(
                      'RH5_3', 'RH5_32',
                      'RedHat Enterprise/CentOS 5.11 32-bit RPM build; '
                      'Boost 1.41',
                      rpm_cvlong % ("32-bit CentOS 5.11", rpm_centos5),
                      'package.el5-i386.log')),
                 ('pkg.el5-x86_64',
                  Platform(
                      'RH5_6', 'RH5_64',
                      'RedHat Enterprise/CentOS 5.11 64-bit RPM build; '
                      'Boost 1.41',
                      rpm_cvlong % ("64-bit CentOS 5.11", rpm_centos5),
                      'package.el5-x86_64.log')),
                 ('pkg.el6-i386',
                  Platform(
                      'RH6_3', 'RH6_32',
                      'RedHat Enterprise/CentOS 6.10 32-bit RPM build; '
                      'Boost 1.41',
                      rpm_cvlong % ("32-bit CentOS 6.10", ""),
                      'package.el6-i386.log')),
                 ('pkg.el6-x86_64',
                  Platform(
                      'RH6_6', 'RH6_64',
                      'RedHat Enterprise/CentOS 6.10 64-bit RPM build; '
                      'Boost 1.41',
                      rpm_cvlong % ("64-bit CentOS 6.10", ""),
                      'package.el6-x86_64.log')),
                 ('pkg.el7-x86_64',
                  Platform(
                      'RH7', 'RH7 RPM',
                      'RedHat Enterprise/CentOS 7.9 RPM build; '
                      'Boost 1.53, Python 2',
                      rpm_cvlong % ("CentOS 7.9", ""),
                      'package.el7-x86_64.log')),
                 ('pkg.el8-x86_64',
                  Platform(
                      'RH8', 'RH8 RPM',
                      'RedHat Enterprise 8.10 RPM build; Boost 1.66',
                      rpm_cvlong % ("Rocky Linux 8.10", ""),
                      'package.el8-x86_64.log')),
                 ('pkg.el9-x86_64',
                  Platform(
                      'RH9', 'RH9 RPM',
                      'RedHat Enterprise 9.5 RPM build; Boost 1.75',
                      rpm_cvlong % ("Rocky Linux 9.5", ""),
                      'package.el9-x86_64.log')),
                 ('pkg.el10-x86_64',
                  Platform(
                      'RH10', 'RH10 RPM',
                      'RedHat Enterprise 10.0 RPM build; Boost 1.83',
                      rpm_cvlong % ("Alma Linux 10.0", ""),
                      'package.el10-x86_64.log')),
                 ('pkg.f16-x86_64',
                  Platform(
                      'F16', 'F16 RPM',
                      'Fedora 16 64-bit RPM; Boost 1.47, gcc 4.6',
                      '', 'package.fc16-x86_64.log')),
                 ('pkg.f17-x86_64',
                  Platform(
                      'F17', 'F17 RPM',
                      'Fedora 17 64-bit RPM; Boost 1.48, gcc 4.7',
                      '', 'package.fc17-x86_64.log')),
                 ('pkg.f18-x86_64',
                  Platform(
                      'F18', 'F18 RPM',
                      'Fedora 18 64-bit RPM; Boost 1.50, gcc 4.7',
                      '', 'package.fc18-x86_64.log')),
                 ('pkg.f19-x86_64',
                  Platform(
                      'F19', 'F19 RPM',
                      'Fedora 19 64-bit RPM; Boost 1.53, gcc 4.8',
                      '', 'package.fc19-x86_64.log')),
                 ('pkg.f20-x86_64',
                  Platform(
                      'F20', 'F20 RPM',
                      'Fedora 20 64-bit RPM build; Boost 1.54, gcc 4.8',
                      rpm_vlong_header % "64-bit Fedora 20"
                      + rpm_vlong_footer + "</p>",
                      'package.fc20-x86_64.log')),
                 ('pkg.f21-x86_64',
                  Platform(
                      'F21', 'F21 RPM',
                      'Fedora 21 64-bit RPM build; Boost 1.55, gcc 4.9',
                      rpm_vlong_header % "64-bit Fedora 21"
                      + rpm_vlong_footer + "</p>",
                      'package.fc21-x86_64.log')),
                 ('pkg.f22-x86_64',
                  Platform(
                      'F22', 'F22 RPM',
                      'Fedora 22 64-bit RPM build; Boost 1.57, gcc 5.1',
                      rpm_vlong_header % "64-bit Fedora 22"
                      + rpm_vlong_footer + "</p>",
                      'package.fc22-x86_64.log')),
                 ('pkg.f23-x86_64',
                  Platform(
                      'F23', 'F23 RPM',
                      'Fedora 23 64-bit RPM build; Boost 1.58, gcc 5.1',
                      rpm_vlong_header % "64-bit Fedora 23"
                      + rpm_vlong_footer + "</p>",
                      'package.fc23-x86_64.log')),
                 ('pkg.f24-x86_64',
                  Platform(
                      'F24', 'F24 RPM',
                      'Fedora 24 64-bit RPM build; Boost 1.60, gcc 6.2',
                      rpm_vlong_header % "64-bit Fedora 24"
                      + rpm_vlong_footer + "</p>",
                      'package.fc24-x86_64.log')),
                 ('pkg.f25-x86_64',
                  Platform(
                      'F25', 'F25 RPM',
                      'Fedora 25 64-bit RPM build; Boost 1.60, gcc 6.2',
                      rpm_vlong_header % "64-bit Fedora 25"
                      + rpm_vlong_footer + "</p>",
                      'package.fc25-x86_64.log')),
                 ('pkg.f26-x86_64',
                  Platform(
                      'F26', 'F26 RPM',
                      'Fedora 26 64-bit RPM build; Boost 1.63, gcc 7.1',
                      rpm_vlong_header % "64-bit Fedora 26"
                      + rpm_vlong_footer + "</p>",
                      'package.fc26-x86_64.log')),
                 ('pkg.f27-x86_64',
                  Platform(
                      'F27', 'F27 RPM',
                      'Fedora 27 64-bit RPM build; Boost 1.64, gcc 7.2',
                      rpm_vlong_header % "64-bit Fedora 27"
                      + rpm_vlong_footer + "</p>",
                      'package.fc27-x86_64.log')),
                 ('pkg.f28-x86_64',
                  Platform(
                      'F28', 'F28 RPM',
                      'Fedora 28 64-bit RPM build; Boost 1.66, gcc 8.0',
                      rpm_vlong_header % "64-bit Fedora 28"
                      + rpm_vlong_footer + "</p>",
                      'package.fc28-x86_64.log')),
                 ('pkg.f29-x86_64',
                  Platform(
                      'F29', 'F29 RPM',
                      'Fedora 29 64-bit RPM build; Boost 1.66, gcc 8.2',
                      rpm_vlong_header % "64-bit Fedora 29"
                      + rpm_vlong_footer + "</p>",
                      'package.fc29-x86_64.log')),
                 ('pkg.f30-x86_64',
                  Platform(
                      'F30', 'F30 RPM',
                      'Fedora 30 64-bit RPM build; Boost 1.69, gcc 9.0, '
                      'Python 3',
                      rpm_vlong_header % "64-bit Fedora 30"
                      + rpm_vlong_footer + "</p>",
                      'package.fc30-x86_64.log')),
                 ('pkg.f31-x86_64',
                  Platform(
                      'F31', 'F31 RPM',
                      'Fedora 31 64-bit RPM build; Boost 1.69, gcc 9.2, '
                      'Python 3',
                      rpm_vlong_header % "64-bit Fedora 31"
                      + rpm_vlong_footer + "</p>",
                      'package.fc31-x86_64.log')),
                 ('pkg.f32-x86_64',
                  Platform(
                      'F32', 'F32 RPM',
                      'Fedora 32 64-bit RPM build; Boost 1.69, gcc 10.0, '
                      'Python 3',
                      rpm_vlong_header % "64-bit Fedora 32"
                      + rpm_vlong_footer + "</p>",
                      'package.fc32-x86_64.log')),
                 ('pkg.f33-x86_64',
                  Platform(
                      'F33', 'F33 RPM',
                      'Fedora 33 64-bit RPM build; Boost 1.73, gcc 10.2, '
                      'Python 3',
                      rpm_vlong_header % "64-bit Fedora 33"
                      + rpm_vlong_footer + "</p>",
                      'package.fc33-x86_64.log')),
                 ('pkg.f34-x86_64',
                  Platform(
                      'F34', 'F34 RPM',
                      'Fedora 34 64-bit RPM build; Boost 1.75, gcc 11.1, '
                      'Python 3',
                      rpm_vlong_header % "64-bit Fedora 34"
                      + rpm_vlong_footer + "</p>",
                      'package.fc34-x86_64.log')),
                 ('pkg.f35-x86_64',
                  Platform(
                      'F35', 'F35 RPM',
                      'Fedora 35 64-bit RPM build; Boost 1.76, gcc 11.2, '
                      'Python 3',
                      rpm_vlong_header % "64-bit Fedora 35"
                      + rpm_vlong_footer + "</p>",
                      'package.fc35-x86_64.log')),
                 ('pkg.f36-x86_64',
                  Platform(
                      'F36', 'F36 RPM',
                      'Fedora 36 64-bit RPM build; Boost 1.76, gcc 12.2, '
                      'Python 3',
                      rpm_vlong_header % "64-bit Fedora 36"
                      + rpm_vlong_footer + "</p>",
                      'package.fc36-x86_64.log')),
                 ('pkg.f37-x86_64',
                  Platform(
                      'F37', 'F37 RPM',
                      'Fedora 37 64-bit RPM build; Boost 1.78, gcc 12.2, '
                      'Python 3',
                      rpm_vlong_header % "64-bit Fedora 37"
                      + rpm_vlong_footer + "</p>",
                      'package.fc37-x86_64.log')),
                 ('pkg.f38-x86_64',
                  Platform(
                      'F38', 'F38 RPM',
                      'Fedora 38 RPM build; Boost 1.78, gcc 13.0, '
                      'Python 3',
                      rpm_vlong_header % "Fedora 38"
                      + rpm_vlong_footer + "</p>",
                      'package.fc38-x86_64.log')),
                 ('pkg.f39-x86_64',
                  Platform(
                      'F39', 'F39 RPM',
                      'Fedora 39 RPM build; Boost 1.81, gcc 13.2, '
                      'Python 3',
                      rpm_vlong_header % "Fedora 39"
                      + rpm_vlong_footer + "</p>",
                      'package.fc39-x86_64.log')),
                 ('pkg.f40-x86_64',
                  Platform(
                      'F40', 'F40 RPM',
                      'Fedora 40 RPM build; Boost 1.83, gcc 14.1, '
                      'Python 3',
                      rpm_vlong_header % "Fedora 40"
                      + rpm_vlong_footer + "</p>",
                      'package.fc40-x86_64.log')),
                 ('pkg.f41-x86_64',
                  Platform(
                      'F41', 'F41 RPM',
                      'Fedora 41 RPM build; Boost 1.83, gcc 14.2, '
                      'Python 3',
                      rpm_vlong_header % "Fedora 41"
                      + rpm_vlong_footer + "</p>",
                      'package.fc41-x86_64.log')),
                 ('pkg.f42-x86_64',
                  Platform(
                      'F42', 'F42 RPM',
                      'Fedora 42 RPM build; Boost 1.83, gcc 15.0',
                      rpm_vlong_header % "Fedora 42"
                      + rpm_vlong_footer + "</p>",
                      'package.fc42-x86_64.log')),
                 ('pkg.precise-x86_64',
                  Platform(
                      'deb12', 'deb12',
                      'Ubuntu 12.04 (Precise Pangolin) 64-bit package; '
                      'Boost 1.48, gcc 4.6',
                      ubuntu_vlong % "12.04 (Precise Pangolin)",
                      'package.precise-x86_64.log')),
                 ('pkg.trusty-x86_64',
                  Platform(
                      'deb14', 'deb14',
                      'Ubuntu 14.04 (Trusty Tahr) 64-bit package; '
                      'Boost 1.54, gcc 4.8',
                      ubuntu_vlong % "14.04 (Trusty Tahr)",
                      'package.trusty-x86_64.log')),
                 ('pkg.xenial-x86_64',
                  Platform(
                      'deb16', 'deb16',
                      'Ubuntu 16.04 (Xenial Xerus) 64-bit package; '
                      'Boost 1.58, gcc 5.3',
                      ubuntu_vlong % "16.04 (Xenial Xerus)",
                      'package.xenial-x86_64.log')),
                 ('pkg.bionic-x86_64',
                  Platform(
                      'deb18', 'deb18',
                      'Ubuntu 18.04 (Bionic Beaver) 64-bit package; '
                      'Boost 1.65, gcc 7.2',
                      ubuntu_vlong % "18.04 (Bionic Beaver)",
                      'package.bionic-x86_64.log')),
                 ('pkg.focal-x86_64',
                  Platform(
                      'deb20', 'deb20',
                      'Ubuntu 20.04 (Focal Fossa) 64-bit package; '
                      'Boost 1.71, gcc 9.2',
                      ubuntu_vlong % "20.04 (Focal Fossa)",
                      'package.focal-x86_64.log')),
                 ('pkg.jammy-x86_64',
                  Platform(
                      'deb22', 'deb22',
                      'Ubuntu 22.04 (Jammy Jellyfish) 64-bit package; '
                      'Boost 1.74, gcc 11.2',
                      ubuntu_vlong % "22.04 (Jammy Jellyfish)",
                      'package.jammy-x86_64.log')),
                 ('pkg.noble-x86_64',
                  Platform(
                      'deb24', 'deb24',
                      'Ubuntu 24.04 (Noble Numbat) 64-bit package; '
                      'Boost 1.83, gcc 13.2',
                      ubuntu_vlong % "24.04 (Noble Numbat)",
                      'package.noble-x86_64.log')))
platforms_dict = dict(all_platforms)


def date_to_directory(date):
    """Convert a datetime.date object into the convention used to name
       directories on our system (e.g. '20120825')"""
    return date.strftime('%Y%m%d')


class _UnitSummary:
    def __init__(self, cur, test_fails, new_test_fails, build_info):
        self.data = summary = {}
        self.arch_ids = seen_archs = {}
        self.unit_ids = {}
        self.failed_archs = failed_archs = {}
        self.failed_units = failed_units = {}
        self.cmake_archs = {}
        for row in cur:
            self.unit_ids[row['unit_name']] = row['unit_id']
            seen_archs[row['arch_name']] = row['arch_id']
            archs = summary.get(row['unit_name'], None)
            if archs is None:
                summary[row['unit_name']] = archs = {}
            tf = test_fails.get((row['arch_id'], row['unit_id']), 0)
            ntf = new_test_fails.get((row['arch_id'], row['unit_id']), 0)
            archs[row['arch_name']] = {'state': row['state'],
                                       'logline': row['logline'],
                                       'lab_only': row['lab_only'],
                                       'numfails': tf,
                                       'numnewfails': ntf}
            if row['state'].startswith('CMAKE_'):
                self.cmake_archs[row['arch_name']] = None
            if row['state'] not in ('OK', 'SKIP', 'NOTEST', 'NOLOG',
                                    'CMAKE_OK', 'CMAKE_SKIP', 'CMAKE_FAILDEP',
                                    'CMAKE_NOBUILD', 'CMAKE_NOTEST',
                                    'CMAKE_NOEX', 'CMAKE_NOBENCH'):
                failed_archs[row['arch_name']] = None
                failed_units[row['unit_name']] = None
        self.all_units = self._sort_units(dict.fromkeys(summary.keys(), True),
                                          build_info)
        known_archs = [x[0] for x in all_platforms]
        self.all_archs = [x for x in known_archs if x in seen_archs] \
            + [x for x in seen_archs if x not in known_archs]

    def make_only_failed(self):
        self.all_units = [x for x in self.all_units if x in self.failed_units]
        self.all_archs = [x for x in self.all_archs if x in self.failed_archs]

    def _sort_units(self, unsorted_units, build_info):
        always_first = [['ALL'], ['ALL_LAB']]
        known_units = []
        for bi, first in zip(build_info, always_first):
            if bi:
                known_units.extend(first)
                for x in bi['modules']:
                    name = x['name']
                    if name == 'kernel':
                        name = 'IMP'
                    known_units.append(name)
                    known_units.append(name + ' benchmarks')
                    known_units.append(name + ' examples')

        sorted_units = []
        for u in known_units:
            if unsorted_units.pop(u, None):
                sorted_units.append(u)
            elif unsorted_units.pop('IMP.'+u, None):
                sorted_units.append('IMP.'+u)
        return sorted_units + list(unsorted_units.keys())


class BuildDatabase:
    def __init__(self, conn, date, lab_only, branch):
        self.conn = conn
        self.date = date
        self.lab_only = lab_only
        self.branch = branch
        self.__build_info = None

    def get_sql_lab_only(self):
        """Get a suitable SQL WHERE fragment to restrict a query to only
           public units, if necessary"""
        if self.lab_only:
            return ""
        else:
            return " AND imp_test_units.lab_only=false"

    def get_branch_table(self, name):
        if self.branch == 'develop':
            return name
        else:
            return name + '_' + self.branch.replace('/', '_').replace('.', '_')

    def get_previous_build_date(self):
        """Get the date of the previous build, or None."""
        if self.branch == 'develop':
            # Assume develop branch is built every day
            return self.date - datetime.timedelta(days=1)
        else:
            # Query database to find last build date
            c = self.conn.cursor()
            table = self.get_branch_table('imp_test_reporev')
            query = 'SELECT date FROM ' + table \
                    + ' WHERE date<%s ORDER BY date DESC LIMIT 1'
            c.execute(query, (self.date,))
            row = c.fetchone()
            if row:
                return row[0]

    def get_unit_summary(self):
        c = MySQLdb.cursors.DictCursor(self.conn)
        table = self.get_branch_table('imp_test')
        query = 'SELECT arch,imp_test_names.unit,delta FROM ' + table \
                + ' imp_test,imp_test_names WHERE date=%s AND state NOT IN ' \
                + str(OK_STATES) + ' AND imp_test.name=imp_test_names.id'
        c.execute(query, (self.date,))
        test_fails = {}
        new_test_fails = {}
        for row in c:
            key = (row['arch'], row['unit'])
            test_fails[key] = test_fails.get(key, 0) + 1
            if row['delta'] == 'NEWFAIL':
                new_test_fails[key] = new_test_fails.get(key, 0) + 1

        table = self.get_branch_table('imp_test_unit_result')
        query = 'SELECT imp_test_archs.name AS arch_name, ' \
                'imp_test_units.lab_only, ' \
                'imp_test_unit_result.arch AS arch_id, ' \
                'imp_test_units.id AS unit_id, ' \
                'imp_test_units.name AS unit_name, ' \
                'imp_test_unit_result.state, ' \
                'imp_test_unit_result.logline FROM imp_test_archs, ' \
                'imp_test_units, ' + table + ' imp_test_unit_result WHERE ' \
                'imp_test_archs.id=imp_test_unit_result.arch AND ' \
                'imp_test_units.id=imp_test_unit_result.unit AND date=%s' \
                + self.get_sql_lab_only()
        c.execute(query, (self.date,))
        return _UnitSummary(c, test_fails, new_test_fails,
                            self.get_build_info())

    def get_doc_summary(self):
        """Get a summary of the doc build"""
        c = MySQLdb.cursors.DictCursor(self.conn)
        table = self.get_branch_table('imp_doc')
        query = "SELECT * FROM " + table + " WHERE date=%s"
        c.execute(query, (self.date,))
        return c.fetchone()

    def get_build_summary(self):
        """Get a one-word summary of the build"""
        c = self.conn.cursor()
        state_ind = 0
        # States ordered by severity
        states = ('OK', 'TEST', 'INCOMPLETE', 'BADLOG', 'BUILD')
        query = 'SELECT state FROM ' \
                + self.get_branch_table('imp_build_summary') + ' WHERE date=%s'
        if not self.lab_only:
            query += ' AND lab_only=false'
        c.execute(query, (self.date,))
        for row in c:
            # Report worst state
            state_ind = max(state_ind, states.index(row[0]))
        return states[state_ind]

    def get_last_build_with_summary(self, states):
        """Get the date of the last build with summary in the given state(s).
           Typically, states would be ('OK',) or ('OK','TEST').
           If no such build exists, None is returned."""
        sql = "(" + ",".join(repr(x) for x in states) + ")"
        sumtable = self.get_branch_table('imp_build_summary')
        # If including lab-only stuff, *both* public and lab-only builds must
        # be in the given state.
        if self.lab_only:
            query = "SELECT public.date FROM " + sumtable + " AS public, " \
                    + sumtable + " AS lab WHERE public.lab_only=false " \
                    "AND lab.lab_only=true AND public.date=lab.date AND " \
                    "lab.date<%s AND public.state IN " + sql + \
                    " AND lab.state IN " + sql
        else:
            query = "SELECT date FROM " + sumtable + " WHERE date<%s AND " \
                    "lab_only=false AND state IN " + sql
        query += " ORDER BY date DESC LIMIT 1"
        c = self.conn.cursor()
        c.execute(query, (self.date,))
        r = c.fetchone()
        if r:
            return r[0]

    def get_git_log(self):
        """Get the git log, as a list of objects, or None if no log exists."""
        _Log = collections.namedtuple('_Log', ['githash', 'author_name',
                                               'author_email', 'title'])
        g = os.path.join(get_topdir(self.branch),
                         date_to_directory(self.date) + '-*', 'build',
                         'imp-gitlog')
        g = glob.glob(g)
        if len(g) > 0:
            data = []
            for line in open(g[0]):
                fields = line.rstrip('\r\n').split('\0')
                data.append(_Log._make(fields))
            return data

    def get_broken_links(self):
        """Get a filehandle to the broken links file."""
        g = os.path.join(get_topdir(self.branch),
                         date_to_directory(self.date) + '-*', 'build',
                         'broken-links.html')
        g = glob.glob(g)
        if len(g) > 0:
            return open(g[0])

    def get_build_info(self):
        """Read in the build_info pickles for both public and lab-only builds,
           and return both. Either can be None if the pickle does not exist or
           we don't have permission to read it."""
        def get_pickle(t):
            g = os.path.join(t, date_to_directory(self.date) + '-*', 'build',
                             'build_info.pck')
            g = glob.glob(g)
            if len(g) > 0:
                with open(g[0], 'rb') as fh:
                    return pickle.load(fh)
        if self.__build_info is None:
            if self.lab_only:
                self.__build_info = (get_pickle(get_topdir(self.branch)),
                                     get_pickle(lab_only_topdir))
            else:
                self.__build_info = (get_pickle(get_topdir(self.branch)),
                                     None)
        return self.__build_info

    def get_all_component_tests(self, component, platform=None):
        platform_where = ''
        if platform:
            platform_where = 'AND imp_test.arch=%s '
        test = self.get_branch_table('imp_test')
        query = "SELECT imp_test_names.name AS test_name, imp_test.name, " \
                "imp_test.arch, imp_test_units.name AS unit_name, " \
                "imp_test_archs.name AS arch_name, imp_test.runtime, " \
                "imp_test.state, imp_test.delta, imp_test.detail FROM " \
                + test + " imp_test, " \
                "imp_test_names, imp_test_units, imp_test_archs WHERE " \
                "imp_test.date=%s AND imp_test_names.unit=%s " \
                + platform_where + \
                "AND imp_test.name=imp_test_names.id " \
                "AND imp_test_names.unit=imp_test_units.id AND " \
                "imp_test.arch=imp_test_archs.id" + self.get_sql_lab_only() \
                + " ORDER BY imp_test.state DESC,imp_test_units.name," \
                + "imp_test_names.id"
        if platform:
            return self._get_tests(query, (self.date, component, platform))
        else:
            return self._get_tests(query, (self.date, component))

    def get_all_failed_tests(self):
        test = self.get_branch_table('imp_test')
        query = "SELECT imp_test_names.name AS test_name, imp_test.name, " \
                "imp_test.arch, imp_test_units.name AS unit_name, " \
                "imp_test_names.unit AS unit_id, " \
                "imp_test_archs.name AS arch_name, imp_test.runtime, " \
                "imp_test.state, imp_test.delta, imp_test.detail FROM " \
                + test + " imp_test, " \
                "imp_test_names, imp_test_units, imp_test_archs WHERE " \
                "imp_test.date=%s AND imp_test.state NOT IN " \
                + str(OK_STATES) + " AND imp_test.name=imp_test_names.id " \
                "AND imp_test_names.unit=imp_test_units.id AND " \
                "imp_test.arch=imp_test_archs.id" + self.get_sql_lab_only() \
                + " ORDER BY imp_test_units.name,imp_test_names.id"
        return self._get_tests(query, (self.date,))

    def get_new_failed_tests(self):
        test = self.get_branch_table('imp_test')
        query = "SELECT imp_test_names.name AS test_name, imp_test.name, " \
                "imp_test.arch, imp_test_units.name AS unit_name, " \
                "imp_test_names.unit AS unit_id, " \
                "imp_test_archs.name AS arch_name, imp_test.runtime, " \
                "imp_test.state, imp_test.delta, imp_test.detail FROM " \
                + test + " imp_test, " \
                "imp_test_names, imp_test_units, imp_test_archs WHERE " \
                "imp_test.date=%s AND imp_test.delta='NEWFAIL' " \
                " AND imp_test.name=imp_test_names.id " \
                "AND imp_test_names.unit=imp_test_units.id AND " \
                "imp_test.arch=imp_test_archs.id" + self.get_sql_lab_only() \
                + " ORDER BY imp_test_units.name,imp_test_names.id"
        return self._get_tests(query, (self.date,))

    def get_long_tests(self):
        test = self.get_branch_table('imp_test')
        query = "SELECT imp_test_names.name AS test_name, imp_test.name, " \
                "imp_test.arch, imp_test_units.name AS unit_name, " \
                "imp_test_names.unit AS unit_id, " \
                "imp_test_archs.name AS arch_name, imp_test.runtime, " \
                "imp_test.state, imp_test.delta, imp_test.detail FROM " \
                + test + " imp_test, " \
                "imp_test_names, imp_test_units, imp_test_archs WHERE " \
                "imp_test.date=%s AND imp_test.runtime>20.0 AND " \
                "imp_test.name=imp_test_names.id AND " \
                "imp_test_names.unit=imp_test_units.id AND " \
                "imp_test.arch=imp_test_archs.id " + self.get_sql_lab_only() \
                + " ORDER BY imp_test.runtime DESC"
        return self._get_tests(query, (self.date,))

    def get_test_dict(self, date=None):
        """Get the state of every one of the day's tests, as a dict keyed by
           the test name and platform."""
        if date is None:
            date = self.date
        d = {}
        c = MySQLdb.cursors.DictCursor(self.conn)
        table = self.get_branch_table('imp_test')
        query = "SELECT name,arch,state FROM " + table + " WHERE date=%s"
        c.execute(query, (date,))
        for row in c:
            d[(row['name'], row['arch'])] = row['state']
        return d

    def _get_tests(self, query, args):
        c = MySQLdb.cursors.DictCursor(self.conn)
        c.execute(query, args)
        return c


def _text_format_build_summary(summary, unit, arch, arch_id):
    statemap = {'SKIP': 'skip',
                'OK': '-',
                'BUILD': 'BUILD',
                'BENCH': 'BENCH',
                'TEST': 'TEST',
                'NOTEST': '-',
                'NOLOG': '-',
                'UNCON': 'UNCON',
                'DISABLED': 'DISAB',
                'CMAKE_OK': '-',
                'CMAKE_BUILD': 'BUILD',
                'CMAKE_BENCH': 'BENCH',
                'CMAKE_TEST': 'TEST',
                'CMAKE_EXAMPLE': 'EXAMP',
                'CMAKE_NOBUILD': '-',
                'CMAKE_NOTEST': '-',
                'CMAKE_NOBENCH': '-',
                'CMAKE_NOEX': '-',
                'CMAKE_RUNBUILD': 'INCOM',
                'CMAKE_RUNTEST': 'INCOM',
                'CMAKE_RUNBENCH': 'INCOM',
                'CMAKE_RUNEX': 'INCOM',
                'CMAKE_CIRCDEP': 'BUILD',
                'CMAKE_FAILDEP': '-',
                'CMAKE_DISABLED': 'DISAB',
                'CMAKE_SKIP': 'skip'}
    try:
        s = summary[unit][arch]
    except KeyError:
        s = None
    if s is None:
        return 'skip'
    else:
        return statemap[s['state']]


def _short_unit_name(unit):
    if unit.startswith('IMP.'):
        return unit[4:]
    elif unit == 'IMP':
        return 'kernel'
    else:
        return unit


def send_imp_results_email(conn, msg_from, lab_only, branch):
    """Send out an email notification that new results are available."""
    import smtplib

    if lab_only:
        url = lab_only_results_url
        msg_to = 'imp-lab-build@salilab.org'
    else:
        url = results_url
        msg_to = 'imp-build@salilab.org'
    db = BuildDatabase(conn, datetime.date.today(), lab_only, branch)
    buildsum = db.get_build_summary()
    summary = db.get_unit_summary()
    log = db.get_git_log()
    doc = db.get_doc_summary()
    summary.make_only_failed()
    msg = MIMEText(_get_email_body(db, buildsum, summary, url, log, doc))
    msg['Keywords'] = ", ".join(["FAIL:" + _short_unit_name(x)
                                 for x in set(summary.failed_units)])
    msg['Subject'] = 'IMP nightly build results, %s' % db.date
    msg['Date'] = formatdate(localtime=True)
    msg['From'] = msg_from
    msg['To'] = msg_to
    s = smtplib.SMTP()
    s.connect()
    s.sendmail(msg_from, [msg_to], msg.as_string())
    s.close()


def _get_email_build_summary(buildsum):
    if buildsum == 'BUILD':
        return "At least part of IMP failed to build today.\n"
    elif buildsum == 'BADLOG':
        return "Something went wrong with the build system today, " \
               "so at least part\nof IMP was not adequately tested. " \
               "Use at your own risk!\n"
    elif buildsum == 'INCOMPLETE':
        return "The build system ran out of time on at least one " \
               "platform today.\n"
    else:
        return ''


def _get_email_body(db, buildsum, summary, url, logs, doc):
    body = """IMP nightly build results, %s.
%sPlease see %s for
full details.

IMP component build summary (BUILD = failed to build;
BENCH = benchmarks failed to build or run;
INCOM = component did not complete building;
TEST = failed tests; EXAMP = failed examples;
DISAB = disabled due to wrong configuration;
UNCON = was not configured; skip = not built on this platform;
only components that failed on at least one platform are shown)
""" % (db.date, _get_email_build_summary(buildsum), url)
    body += " " * 18 + " ".join("%-5s" % platforms_dict[x].very_short
                                for x in summary.all_archs) + "\n"

    for row in summary.all_units:
        errs = [_text_format_build_summary(summary.data, row, col,
                                           summary.arch_ids[col])
                for col in summary.all_archs]
        body += "%-18s" % row[:18] + " ".join("%-5s" % e[:5] for e in errs) \
                + "\n"

    numfail = 0
    failed_units = {}
    for test in db.get_new_failed_tests():
        numfail += 1
        failed_units[test['unit_name']] = None
    if numfail > 0:
        body += "\nThere were %d new test failures (tests that passed " \
                "yesterday\n" % numfail \
                + "but failed today) in the following components:\n" \
                + "\n".join("   " + unit
                            for unit in sorted(failed_units.keys()))
    if doc:
        def _format_doc(title, nbroken):
            if nbroken > 0:
                if nbroken == 1:
                    suffix = ""
                else:
                    suffix = "s"
                return '\nToday\'s %s contains %d broken link%s.' \
                       % (title, nbroken, suffix)
            else:
                return ''
        body += (_format_doc('manual', doc['nbroken_manual'])
                 + _format_doc('reference guide', doc['nbroken_tutorial'])
                 + _format_doc('RMF manual', doc['nbroken_rmf_manual']))
    if logs:
        def _format_log(log):
            txt = '%s %-10s %s' % (log.githash[:10],
                                   log.author_email.split('@')[0][:10],
                                   log.title)
            return txt[:75]
        body += "\n\nChangelog:\n" + "\n".join(_format_log(log)
                                               for log in logs)
    return body
