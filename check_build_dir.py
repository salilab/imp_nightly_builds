#!/usr/bin/python3

import pickle
import os

dirs = os.listdir('build/logs/imp')
for d in dirs:
    pck = 'build/logs/imp/%s/summary.pck' % d
    if os.path.exists(pck):
        with open(pck, 'rb') as fh:
            p = pickle.load(fh)
        for unit, results in p.items():
            build_result = results.get('build_result', None)
            if build_result == 'running':
                print("%s: %s still running" % (d, unit))
            elif (build_result != 0 and build_result != 'disabled'
                    and build_result is not None):
                print("%s: %s failed with %s" % (d, unit, build_result))

for winarch in ('i386-w32', 'x86_64-w64'):
    log = 'build/logs/imp/%s/PKGTEST.build.log' % winarch
    if os.path.exists(log):
        with open(log) as fh:
            contents = fh.read()
        if 'Ran 1 test in' not in contents:
            print("%s: did not successfully test .exe installer" % winarch)
    else:
        print("%s: did not run .exe installer test" % winarch)
