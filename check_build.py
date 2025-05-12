#!/usr/bin/python3

import os
import urllib.request
import urllib.parse
import http.client
import socket
import ssl
import html
import math
import pickle
import sys
import glob
import re
import time
import shutil
import subprocess
from argparse import ArgumentParser
import datetime
import hashlib
import imp_build_utils
from imp_build_utils import SPECIAL_COMPONENTS, OK_STATES
import xml.sax
from xml.sax.handler import ContentHandler
import json
import yaml
import base64
import zlib

imp_testhtml = '/guitar3/home/www/html/imp/nightly/'
imp_testurl = 'http://salilab.org/imp/nightly/tests.html'
imp_downloadhtml = '/guitar3/home/www/html/imp/nightly/download/'

imp_lab_testhtml = '/guitar3/home/www/html/internal/imp-salilab/nightly/'
imp_lab_testurl = 'https://salilab.org/internal/imp-salilab/nightly/tests.html'


class ExcludedModule(object):
    pass


class NoLogModule(object):
    pass


class Error(object):
    pass


class CircularDependencyError(Error):
    pass


class FailedDependencyError(Error):
    pass


class ExampleFailedError(Error):
    pass


# Part of the build didn't start yet
class NotRunError(Error):
    pass


class BuildNotRunError(NotRunError):
    pass


class TestNotRunError(NotRunError):
    pass


class ExampleNotRunError(NotRunError):
    pass


class BenchmarkNotRunError(NotRunError):
    pass


# Part of the build is still running
class RunningError(Error):
    pass


class BuildRunningError(RunningError):
    pass


class TestRunningError(RunningError):
    pass


class ExampleRunningError(RunningError):
    pass


class BenchmarkRunningError(RunningError):
    pass


class MissingLogError(Error):
    def __init__(self, logpath, abslogpath, description):
        self._logpath = logpath
        self._abslogpath = abslogpath
        self._description = description


class ExtraLogError(Error):
    def __init__(self, logpath, abslogpath):
        self._logpath = logpath
        self._abslogpath = abslogpath


class ModuleDisabledError(Error):
    pass


class TestFailedError(Error):
    pass


class BuildFailedError(Error):
    pass


class BenchmarkFailedError(Error):
    pass


class MissingOutputError(Error):
    def __init__(self, output, logpath, abslogpath, description):
        self._output = output
        self._logpath = logpath
        self._abslogpath = abslogpath
        self._description = description


def byte_compile_python_dir(dirname):
    """Byte-compile a directory full of Python files.
       Ignore errors from modules that contain invalid syntax."""
    subprocess.call(['python3', '-m', 'compileall', '-f', '-qq', dirname])


def update_symlink(src, dest):
    """Atomically update the symlink from `src` to `dest`.
       Make a symlink dest -> src. If dest already exists, rather than
       deleting it and recreating it, make a new temporary symlink and then
       rename it over the existing link. The latter action is atomic so there
       is no window where the link does not exist (which might cause runs on
       the cluster to fail)."""
    tmplink = dest + '.tmp'
    os.symlink(src, tmplink)
    os.rename(tmplink, dest)


def _get_only_failed_modules(module_map, modules, archs):
    failures = {}
    for m in modules:
        for a in archs:
            err = module_map[m][a]
            if err is not None \
               and not isinstance(err, (ExcludedModule, NoLogModule,
                                        TestNotRunError, NotRunError)):
                failures[m] = failures[a] = None
    return ([m for m in modules if m in failures],
            [a for a in archs if a in failures])


def _get_text_module_map(name, module_map, modules, archs):
    def _format_module_error(error):
        if error is None or isinstance(error, (NoLogModule, TestNotRunError,
                                               FailedDependencyError,
                                               NotRunError)):
            return "-"
        elif isinstance(error, (BuildFailedError,
                                CircularDependencyError)):
            return "BUILD"
        elif isinstance(error, RunningError):
            return "INCOM"
        elif isinstance(error, BenchmarkFailedError):
            return "BENCH"
        elif isinstance(error, (TestFailedError, ExampleFailedError)):
            return "TEST"
        elif isinstance(error, ModuleDisabledError):
            return "DISAB"
        elif isinstance(error, ExcludedModule):
            return "skip"
        raise RuntimeError("Cannot handle error: " + str(error))
    t = "%s module failure summary (BUILD = failed to build;\n" \
        "TEST = failed tests; DISAB = disabled due to wrong configuration;\n" \
        "skip = not built on this platform; only modules that failed on\n" \
        "at least one architecture are shown)\n" \
        % name
    modules, archs = _get_only_failed_modules(module_map, modules, archs)
    t += (" " * 13 +
          " ".join("%-5s" % imp_build_utils.platforms_dict[x].very_short
                   for x in archs) + "\n")
    for m in modules:
        errs = [_format_module_error(module_map[m][arch])
                for arch in archs]
        t += "%-13s" % m[:13] + " ".join("%-5s" % e[:5] for e in errs) + "\n"
    return t


class CoverageLink(object):
    def __init__(self, desc, loc):
        self.desc = desc
        self.loc = loc

    def parse_logdir(self, logdir):
        return self.parse_file(os.path.join(logdir, self.loc, 'index.html'))

    def parse_file(self, fname):
        pass

    def _extract_percentage(self, fname, regex):
        # Get total percent coverage from index.html and add to desc
        r = re.compile(regex)
        try:
            for line in open(fname):
                m = r.search(line)
                if m:
                    self.desc += " (%s%%)" % m.group(1)
                    return m.group(1)
        except IOError:
            pass


class PythonCoverageLink(CoverageLink):
    def parse_file(self, fname):
        return self._extract_percentage(fname,
                                        r"<span class=.pc_cov.>(\d+)%</span>")


class CCoverageLink(CoverageLink):
    def parse_file(self, fname):
        return self._extract_percentage(
            fname,
            r'<td class="headerCovTableEntry\w+">(\d+\.\d+)(\s|&nbsp;)*%</td>')


class GitHubStatusUpdater(object):
    """Update the status of a repository in GitHub"""

    def __init__(self, dryrun, owner, repo):
        self.dryrun = dryrun
        self.api_root = 'https://api.github.com/repos/%s/%s' % (owner, repo)
        self.get_auth()

    def get_auth(self):
        """Read the GitHub username and password to use.
           The auth file has a simple YAML format:
           username: foo
           password: bar
        """
        authfile = os.path.join(os.path.dirname(sys.argv[0]),
                                'githubauth.yaml')
        with open(authfile) as fh:
            self.auth = yaml.safe_load(fh)

    def get_default_headers(self):
        """Get headers needed for every API request"""
        authstr = self.auth['username'] + ":" + self.auth['password']
        authstr = base64.b64encode(authstr.encode('ascii')).decode('ascii')
        headers = {'Authorization': 'Basic %s' % authstr}
        return headers

    def get_statuses(self, sha):
        headers = self.get_default_headers()
        req = urllib.request.Request(
            self.api_root + '/commits/%s/statuses' % sha, None, headers)
        return json.load(urllib.request.urlopen(req))

    def set_status(self, sha, state, target_url, description,
                   context="continuous-integration/salilab-nightly-builds",
                   duplicate=True):
        if not duplicate:
            for s in self.get_statuses(sha):
                if s['context'] == context:
                    return
        headers = self.get_default_headers()
        headers['Content-Type'] = 'application/json'
        data = json.dumps({'state': state, 'target_url': target_url,
                           'description': description, 'context': context})
        data = data.encode('utf-8')
        url = self.api_root + '/statuses/%s' % sha
        if self.dryrun:
            print(data)
            return
        else:
            req = urllib.request.Request(url, data, headers)
            try:
                return urllib.request.urlopen(req).read()
            except (urllib.request.HTTPError,
                    urllib.request.URLError) as error:
                if hasattr(error, 'read'):
                    print(error.read())
                print(str(error))


class LinkChecker(object):
    def __init__(self, url_root, title, html, verbose):
        self.nbroken = 0
        self.url_root = url_root
        self.title = title
        self.html = html
        self.verbose = verbose
        self._broken_links = {}
        self._checked_externals = {}

    def check_link(self, fname, nline, link):
        if link in self._broken_links:
            self.add_broken_link(link, fname, nline)
        elif (link.startswith('http:') or link.startswith('https:')
              or link.startswith('//') or link.startswith('ftp:')):
            if link not in self._checked_externals:
                self._checked_externals[link] = None
                self._check_http_link(fname, nline, link)
            elif link in self._broken_links:
                self.add_broken_link(link, fname, nline)
        else:
            if not os.path.exists(urllib.parse.urlsplit(link).path):
                self.add_broken_link(link, fname, nline)

    def log(self, msg):
        if self.verbose:
            print("    " + msg, file=sys.stderr)

    def _check_http_link(self, fname, nline, link):
        # Several websites forbid queries by bots; ninja-build.org has
        # SSL issues; doxygen often times out
        if ('wikipedia' in link or 'amazon.com' in link
                or 'stackoverflow.com' in link
                or 'anaconda.com' in link
                or 'creativecommons.org' in link
                or 'nih.gov/pmc/' in link
                or 'atlassian.com' in link
                or 'git-scm.com' in link
                or 'graphviz.org' in link
                or 'pubs.acs.org' in link
                or 'msdn.microsoft' in link
                or 'ninja-build.org' in link
                or 'docs.github.com' in link
                or 'cmake.org' in link
                or '/salilab/imp/blob/develop/doc/manual/' in link
                or link == 'http://www.doxygen.org/'):
            self.log("Skipping check of link " + link)
        else:
            self.log("Checking external link " + link)
            checklink = link
            # If no scheme provided, assume http:
            if checklink.startswith('//'):
                checklink = 'http:' + checklink
            try:
                r = urllib.request.Request(checklink,
                                           headers={'User-Agent': 'urllib'})
                _ = urllib.request.urlopen(r, timeout=10)
            except socket.timeout:
                self.add_broken_link(link, fname, nline, 'timeout')
            except (urllib.request.URLError, http.client.HTTPException,
                    ssl.SSLError, ssl.CertificateError,
                    socket.error) as detail:
                self.add_broken_link(link, fname, nline, str(detail))

    def add_broken_link(self, link, fname, nline, detail=None):
        self.nbroken += 1
        if link in self._broken_links:
            self._broken_links[link][2] += 1
        else:
            self._broken_links[link] = [fname, nline, 0, detail]

    def print_summary(self, outfh):
        if self.html:
            if self.nbroken == 0:
                suffix = "s."
            elif self.nbroken == 1:
                suffix = ":"
            else:
                suffix = "s:"
            print('<p>The %s has %d broken link%s</p>'
                  % (self.make_link(None, self.title), self.nbroken, suffix),
                  file=outfh)
            if self.nbroken > 0:
                print('<ul>', file=outfh)
        for link, info in self._broken_links.items():
            fname, nline, nothers, detail = info
            if nothers > 1:
                others = " (and %d other locations)" % nothers
            elif nothers == 1:
                others = " (and 1 other location)"
            else:
                others = ""
            if detail:
                detail = " (" + detail + ")"
            else:
                detail = ""
            if self.html:
                if link.startswith('http'):
                    link = '<a href="%s">%s</a>' % (link, link)
                print('<li>%s%s from %s, line %d%s</li>'
                      % (link, html.escape(detail),
                         self.make_link(fname, fname), nline + 1, others),
                      file=outfh)
            else:
                print("Broken link %s%s from %s, line %d%s"
                      % (link, detail, fname, nline + 1, others), file=outfh)
        if self.html and self.nbroken > 0:
            print("</ul>", file=outfh)

    def make_link(self, subdir, text):
        if self.url_root is None:
            return text
        elif subdir:
            return '<a href="%s">%s</a>' \
                   % (os.path.join(self.url_root, subdir), text)
        else:
            return '<a href="%s">%s</a>' % (self.url_root, text)

    def check_file(self, fname):
        r = re.compile('(?:href|src)="([^#"]+)[#"]')
        # Some files aren't UTF-8, so accept any bytes
        for nline, line in enumerate(open(fname, encoding='latin1')):
            links = r.findall(line)
            if len(links) > 0:
                for link in links:
                    self.check_link(fname, nline, link)


def check_broken_links(html_dir, url_root, html, verbose, title,
                       outfh=sys.stdout):
    if not os.path.exists(html_dir):
        return 0
    cwd = os.getcwd()
    os.chdir(html_dir)

    lc = LinkChecker(url_root, title, html, verbose)

    nfiles = 0
    for x in os.listdir('.'):
        if x.endswith('.html'):
            nfiles += 1
            if nfiles % 100 == 0 and verbose:
                print("Checking file #%d" % nfiles, file=sys.stderr)
            lc.check_file(x)
    lc.print_summary(outfh)
    os.chdir(cwd)
    return lc.nbroken


class Formatter(object):
    pass


class TextFormatter(Formatter):
    def print_product(self, comp, errors, module_map=None, modules=None,
                      archs=None, logdir=None):
        if len(errors) == 0:
            print("%s OK" % comp.name)
        else:
            print("%s FAILED" % comp.name)
            for err in errors:
                self._print_error(err)
        if module_map:
            print(_get_text_module_map(comp.name, module_map, modules, archs))
            print()

    def print_header(self, title=None):
        pass

    def print_footer(self):
        pass

    def print_start_products(self):
        pass

    def print_end_products(self):
        pass

    def print_new_repos(self, repos):
        pass

    def print_old_repos(self, repos):
        pass

    def _print_error(self, error):
        if isinstance(error, MissingLogError):
            print("  %s: log %s not generated" % (error._description,
                                                  error._logpath))
        elif isinstance(error, ExtraLogError):
            print("  Unexpected log %s generated" % error._logpath)
        elif isinstance(error, MissingOutputError):
            if error._logpath is None:
                print("  %s: output %s not generated"
                      % (error._description, error._output))
            else:
                print("  %s: output %s not generated; see log %s"
                      % (error._description, error._output, error._logpath))


def get_imp_build_email_from():
    """Get the From: address for emails to the IMP-build mailing list"""
    d = os.path.dirname(sys.argv[0])
    fh = open(os.path.join(d, 'email-from.txt'))
    for line in fh:
        line = line.rstrip('\r\n')
        if len(line) > 0 and not line.startswith('#'):
            return line
    raise ValueError("Could not read email address")


class Repository(object):
    def __init__(self, name):
        self.name = name

    def set_verfile(self, newpath):
        (self.newlongver, self.newversion, self.newrevision) = \
            self._parse_verfile(newpath)

    def _parse_verfile(self, path):
        verfile = os.path.join(path, "build/%s-version" % self.name)
        revfile = os.path.join(path, "build/%s-gitrev" % self.name)
        with open(verfile, "r") as fh:
            longver = fh.readline().rstrip('\r\n')
        spl = longver.split(".")
        if os.path.exists(revfile):
            version = 'git'
            with open(revfile, "r") as fh:
                revision = fh.readline().rstrip('\r\n')
        elif len(spl) > 1 and spl[-1].startswith('r'):
            version = ".".join(spl[:-1])
            revision = spl[-1]
        elif longver.startswith('r'):
            version = 'SVN'
            revision = longver
        else:
            version = longver
            revision = 'unknown'
        return (longver, version, revision)


class Product(object):
    def __init__(self, name, dir, module_coverage=False):
        self.modules = []
        self.units = {}
        self.module_coverage = module_coverage
        self.name = name
        self.dir = dir
        self.__logs = {}
        self.__log_desc = {}

    def update_status(self, dryrun):
        pass

    def set_component_file(self, path):
        modfile = os.path.join(path, "build/%s-components" % self.dir)
        if os.path.exists(modfile):
            lines = [m.rstrip('\r\n')
                     for m in open(modfile).readlines()]
            lines = [m for m in lines if len(m) > 0]
            for line in lines:
                typ, unit = line.split('\t')
                self.units[unit] = typ
                self.modules.append(unit)

    def add_log(self, log, description, generated_files):
        if log not in self.__logs:
            self.__logs[log] = []
        self.__log_desc[log] = description
        lst = self.__logs[log]
        if isinstance(generated_files, (list, tuple)):
            lst.extend(generated_files)
        else:
            lst.append(generated_files)

    def make_module_map(self, archs):
        self.module_map = {}
        self.archs = archs
        for m in self.modules:
            self.module_map[m] = dict.fromkeys(archs)
            if self.units[m] == 'module':
                self.module_map[m + ' examples'] = dict.fromkeys(archs)
                self.module_map[m + ' benchmarks'] = dict.fromkeys(archs)

    def exclude_component(self, module, archs):
        if module not in self.module_map:
            print("WARNING: ignoring attempt to exclude missing component %s"
                  % module)
            return
        if self.units[module] == 'module':
            for a in archs:
                self.module_map[module + ' examples'][a] = ExcludedModule()
                self.module_map[module + ' benchmarks'][a] = ExcludedModule()
        for a in archs:
            self.module_map[module][a] = ExcludedModule()

    def exclude_component_all(self, module):
        self.exclude_component(module, self.archs)

    def include_component(self, module, archs):
        a = [x for x in self.archs if x not in archs]
        self.exclude_component(module, a)

    def check_logs(self, checker, formatters, dryrun):
        self._errors = []
        for (log, generated_files) in self.__logs.items():
            self.__check_log(log, self.__log_desc[log], generated_files,
                             checker, self._errors)
        for cmake_log in self.cmake_logs:
            self.__check_cmake_log(cmake_log, checker, self._errors)
        self.__check_extra_logs(checker, self._errors)
        self._check_module_errors(checker)
        logdir = os.path.join(checker.logdir, self.dir)
        self.print_product(formatters, logdir)
        self.write_build_info(logdir, dryrun)
        lenerr = len(self._errors)
        if self.get_module_state() != 'OK':
            lenerr += 1
        return lenerr

    def _check_module_errors(self, checker):
        pass

    def get_module_state(self):
        return 'OK'

    def print_product(self, formatters, logdir):
        self.state = self.get_module_state()
        failure = (self.state != 'OK')
        if failure:
            if self.state in ('OK', 'TEST'):
                for e in self._errors:
                    if isinstance(e, MissingOutputError):
                        self.state = 'BUILD'
                        break
                    elif isinstance(e, (MissingLogError, ExtraLogError)):
                        self.state = 'BADLOG'
            if self.state == 'OK':
                self.state == 'BUILD'
            for f in formatters:
                f.print_product(self, self._errors, self.module_map,
                                self.modules, self.archs, logdir)
        elif len(self.modules) > 0:
            for f in formatters:
                f.print_product(self, self._errors, self.module_map,
                                self.modules, self.archs, logdir)
        else:
            for f in formatters:
                f.print_product(self, self._errors)

    def write_build_info(self, logdir, dryrun):
        build_info = self._get_build_info(self.modules, self.module_coverage,
                                          logdir)
        if dryrun:
            print(build_info)
        else:
            pth = os.path.join(logdir, '..', '..', 'build_info.pck')
            with open(pth, 'wb') as fh:
                pickle.dump(build_info, fh, 2)

    def _get_build_info(self, modules, module_coverage, logdir):
        build_info = {}
        build_info['modules'] = bimods = []
        for m in modules:
            modinfo = {'name': m}
            if module_coverage:
                pycov = PythonCoverageLink('', 'coverage/python/%s/' % m)
                ccov = CCoverageLink('', 'coverage/cpp/%s/' % m)
                for key, cov in (('pycov', pycov), ('cppcov', ccov)):
                    pct = cov.parse_logdir(logdir)
                    modinfo[key] = pct
            bimods.append(modinfo)
        return build_info

    def __check_extra_logs(self, checker, errors):
        logmatch = os.path.join(checker.logdir, self.dir, "*.log")
        all_logs = [os.path.basename(x) for x in glob.glob(logmatch)]
        for log in all_logs:
            if log not in self.__logs:
                logpath = os.path.join(self.dir, log)
                abslogpath = os.path.join(checker.logdir, logpath)
                errors.append(ExtraLogError(logpath, abslogpath))

    def __check_cmake_log(self, cmake_log, checker, errors):
        for gen in cmake_log.generated_files:
            filepath = os.path.join(checker.newbuilddir, gen)
            if not os.path.exists(filepath):
                desc = imp_build_utils.platforms_dict[cmake_log.arch].long
                errors.append(MissingOutputError(gen, None, None, desc))

    def __check_log(self, log, description, generated_files, checker, errors):
        logpath = os.path.join(self.dir, log)
        abslogpath = os.path.join(checker.logdir, logpath)
        if not os.path.exists(abslogpath):
            errors.append(MissingLogError(logpath, abslogpath,
                                          description))
        else:
            for gen in generated_files:
                filepath = os.path.join(checker.newbuilddir, gen)
                if not os.path.exists(filepath):
                    errors.append(MissingOutputError(gen, logpath, abslogpath,
                                                     description))


class CMakeLog(object):
    all_build_types = ['build', 'test', 'example', 'benchmark']

    not_run_error = {'build': BuildNotRunError, 'test': TestNotRunError,
                     'example': ExampleNotRunError,
                     'benchmark': BenchmarkNotRunError}
    running_error = {'build': BuildRunningError, 'test': TestRunningError,
                     'example': ExampleRunningError,
                     'benchmark': BenchmarkRunningError}

    def __init__(self, arch, build_types, generated_files):
        # Make sure build_types is correctly ordered
        self.build_types = [x for x in self.all_build_types
                            if x in build_types]
        self.arch = arch
        if not isinstance(generated_files, (list, tuple)):
            self.generated_files = [generated_files]
        else:
            self.generated_files = generated_files

    def update_module_error(self, modmap, err, compname):
        olderr = modmap[self.arch]
        if isinstance(olderr, ExcludedModule):
            if not isinstance(err, (NotRunError, ModuleDisabledError)):
                print("WARNING: build of %s reported %s for %s, but component "
                      "is supposed to be excluded" % (compname, err,
                                                      self.arch))
            return False
        if err is None:
            return False
        modmap[self.arch] = err
        return True

    def check_extra_build_types(self, name, comp):
        for build_type in self.all_build_types:
            if build_type not in self.build_types:
                if hasattr(comp, '%s_result' % build_type):
                    print("WARNING: %s in %s has extra build type %s"
                          % (name, self.arch, build_type))

    def check_module_errors(self, comp, logdir):
        logdir = os.path.join(logdir, self.arch)
        summary = os.path.join(logdir, 'summary.pck')
        if os.path.exists(summary):
            with open(summary, 'rb') as fh:
                summary = pickle.load(fh)
        else:
            summary = {}
        for m in comp.units:
            if m in summary:
                self.check_extra_build_types(m, summary[m])
            self.check_build_types(m, comp, summary)

    def check_build_types(self, m, comp, summary):
        if m in SPECIAL_COMPONENTS:
            build_types = ['build']
        else:
            build_types = self.build_types[:]
        example = 'example' in build_types
        benchmark = 'benchmark' in build_types
        if example:
            build_types.remove('example')
        if benchmark:
            build_types.remove('benchmark')
        self.get_build_result(m, comp, summary, build_types)
        if comp.units[m] == 'module':
            if example:
                self.get_build_result(m + ' examples', comp, summary,
                                      ['example'])
            else:
                comp.module_map[m + ' examples'][self.arch] = ExcludedModule()
            if benchmark:
                self.get_build_result(m + ' benchmarks', comp, summary,
                                      ['benchmark'])
            else:
                comp.module_map[m + ' benchmarks'][self.arch] \
                    = ExcludedModule()

    def get_build_result(self, m, comp, summary, build_types):
        sm = m
        if sm.endswith(' examples'):
            sm = sm[:-9]
        elif sm.endswith(' benchmarks'):
            sm = sm[:-11]
        for typ in build_types:
            res = '%s_result' % typ
            if sm in summary and summary[sm].get(res, 'notrun') != 'notrun':
                res = summary[sm][res]
                if res == 0:
                    err = None
                elif res == 'circdep':
                    err = CircularDependencyError()
                elif res == 'depfail':
                    err = FailedDependencyError()
                elif res == 'disabled':
                    err = ModuleDisabledError()
                elif res == 'running':
                    err = self.running_error[typ]()
                else:
                    if typ == 'build':
                        err = BuildFailedError()
                    elif typ == 'test':
                        err = TestFailedError()
                    elif typ == 'example':
                        err = ExampleFailedError()
                    elif typ == 'benchmark':
                        err = BenchmarkFailedError()
            else:
                err = self.not_run_error[typ]()
            if self.update_module_error(comp.module_map[m], err, m):
                # Stop at first error
                return


class IMPProduct(Product):
    def __init__(self, name, dir, repo, *args, **kwargs):
        super().__init__(name, dir, *args, **kwargs)
        self.cmake_logs = []
        self.repo = repo

    def update_status(self, dryrun):
        s = GitHubStatusUpdater(dryrun, "salilab", "imp")
        s.set_status(sha=self.repo.newrevision,
                     state={'OK': 'success', 'TEST': 'success',
                            'BUILD': 'failure', 'BADLOG': 'error',
                            'INCOMPLETE': 'error'}[self.state],
                     description={
                         'OK': 'The build succeeded and all tests passed',
                         'TEST': 'The build succeeded although some tests '
                                 'failed',
                         'BUILD': 'The build failed',
                         'BADLOG': 'A bad log file was produced',
                         'INCOMPLETE': 'The build system '
                                       'ran out of time'}[self.state],
                     target_url="http://integrativemodeling.org/nightly/"
                                "results/?date=%s"
                                % datetime.date.today().strftime('%Y%m%d'))

    def add_cmake_log(self, arch, build_types, generated_files):
        self.cmake_logs.append(CMakeLog(arch, build_types, generated_files))

    def _check_module_errors(self, checker):
        for log in self.cmake_logs:
            log.check_module_errors(
                self, os.path.join(checker.logdir, self.dir))

    def get_module_state(self):
        states = ['BUILD', 'INCOMPLETE', 'TEST', 'OK']
        state = 'OK'
        for m in self.modules:
            for a in self.archs:
                err = self.module_map[m][a]
                if isinstance(err, RunningError):
                    newstate = 'INCOMPLETE'
                elif isinstance(err, (TestFailedError, ExampleFailedError,
                                      BenchmarkFailedError)):
                    newstate = 'TEST'
                elif isinstance(err, (BuildFailedError,
                                      CircularDependencyError,
                                      ModuleDisabledError)):
                    newstate = 'BUILD'
                else:
                    newstate = 'OK'
                if states.index(newstate) < states.index(state):
                    state = newstate
        return state


class PruneDirectories(object):
    def __init__(self, topdir):
        self._topdir = topdir

    def prune(self):
        dirs_to_prune = self._get_dirs_to_prune()
        for d in dirs_to_prune:
            shutil.rmtree(os.path.join(self._topdir, d))

    def _exclude_linked_dirs(self, dirs_to_prune, links):
        for link in links:
            full_link = os.path.join(self._topdir, link)
            if os.path.exists(full_link):
                dest = os.path.basename(os.readlink(full_link))
                try:
                    dirs_to_prune.remove(dest)
                except ValueError:
                    pass

    def _get_dirs_to_prune(self):
        today = datetime.datetime.today()
        dirre = re.compile(r'(\d{4})(\d{2})(\d{2})')
        alldirs = os.listdir(self._topdir)
        alldirs.sort()

        months = {}
        dirs_to_prune = []
        for d in alldirs:
            m = dirre.match(d)
            if m:
                dirdate = datetime.datetime(int(m.group(1)), int(m.group(2)),
                                            int(m.group(3)))
                age = today - dirdate
                # Prune directories older than 30 days, but leave one per month
                if age.days > 30:
                    month = (dirdate.year, dirdate.month)
                    if month not in months:
                        months[month] = None
                    else:
                        dirs_to_prune.append(d)
        self._exclude_linked_dirs(dirs_to_prune,
                                  ('nightly', 'stable',
                                   '.last', 'last_ok_build'))
        return dirs_to_prune


class Checker(object):
    def __init__(self, dirroot):
        self._products = []
        self._repos = []
        self.dirroot = dirroot
        self.newbuilddir = os.path.join(dirroot, ".new")
        self.logdir = os.path.join(self.newbuilddir, "build/logs")
        self.builddir = os.path.join(dirroot, "stable")
        self.timenow = time.time()

    def add_product(self, prod):
        self._products.append(prod)
        prod.set_component_file(self.newbuilddir)

    def add_repository(self, repo):
        self._repos.append(repo)
        repo.set_verfile(self.newbuilddir)

    def print_header(self, formatter):
        formatter.print_header()

    def check_logs(self, formatters, dryrun):
        numerr = 0
        for f in formatters:
            self.print_header(f)
            f.print_start_products()
        for comp in self._products:
            numerr += comp.check_logs(self, formatters, dryrun)
        for f in formatters:
            f.print_end_products()
            f.print_new_repos(self._repos)
            if numerr > 0:
                f.print_old_repos(self._repos)
            f.print_footer()
        return numerr

    def copy_log_files(self, testhtml):
        pass

    def update_done_build(self, dryrun):
        pass

    def activate_new_build(self):
        pass


def update_arch(arch_table, arch, cur):
    cur.execute("SELECT id FROM " + arch_table + " WHERE NAME=%s", (arch,))
    r = cur.fetchone()
    if r is not None:
        return r[0]
    else:
        cur.execute("INSERT INTO " + arch_table + " (name) values(%s)",
                    (arch,))
        cur.execute("SELECT LAST_INSERT_ID()")
        return cur.fetchone()[0]


def update_unit(unit_table, unit, cur, lab_only):
    cur.execute("SELECT id FROM " + unit_table + " WHERE NAME=%s", (unit,))
    r = cur.fetchone()
    if r is not None:
        return r[0]
    else:
        cur.execute("INSERT INTO " + unit_table +
                    " (name, lab_only) values(%s, %s)", (unit, lab_only))
        cur.execute("SELECT LAST_INSERT_ID()")
        return cur.fetchone()[0]


def update_name(name_table, name, unit_id, cur):
    cur.execute("SELECT id FROM " + name_table + " WHERE name=%s AND unit=%s",
                (name, unit_id))
    r = cur.fetchone()
    if r is not None:
        return r[0]
    else:
        cur.execute("INSERT INTO " + name_table
                    + " (name,unit) values(%s,%s)", (name, unit_id))
        cur.execute("SELECT LAST_INSERT_ID()")
        return cur.fetchone()[0]


update_benchmark_file = update_name


def update_benchmark_name(name_table, name, algorithm, file_id, cur):
    cur.execute("SELECT id FROM " + name_table
                + " WHERE name=%s AND algorithm=%s AND file=%s",
                (name, algorithm, file_id))
    r = cur.fetchone()
    if r is not None:
        return r[0]
    else:
        cur.execute("INSERT INTO " + name_table
                    + " (name,algorithm,file) values(%s,%s,%s)",
                    (name, algorithm, file_id))
        cur.execute("SELECT LAST_INSERT_ID()")
        return cur.fetchone()[0]


def connect_mysql():
    import MySQLdb
    d = os.path.dirname(sys.argv[0])
    with open(os.path.join(d, 'imp-sql-args.pck'), 'rb') as fh:
        args = pickle.load(fh)
    return MySQLdb.connect(**args)


def get_unit_name_from_modules(unit, comp_units):
    example = unit.endswith(' examples')
    benchmark = unit.endswith(' benchmarks')
    if example:
        unit = unit[:-9]
    elif benchmark:
        unit = unit[:-11]
    if comp_units[unit] == 'module' and unit != 'RMF':
        if unit == 'kernel':
            unit = 'IMP'
        elif not unit.startswith('IMP.'):
            unit = 'IMP.' + unit
    if example:
        unit += ' examples'
    elif benchmark:
        unit += ' benchmarks'
    return unit


def get_benchmark_name(table, name_table, file_id, unit_id, arch_id, cur,
                       name, algorithm, runtime, check, seen_name_ids, date):
    name_id = update_benchmark_name(name_table, name, algorithm, file_id, cur)
    if name_id in seen_name_ids:
        print("WARNING: ignoring duplicate benchmark %s, %s"
              % (name, algorithm))
        return
    seen_name_ids[name_id] = None
    # MySQL doesn't seem to like nan or inf values
    if math.isinf(check) or math.isnan(check):
        check = None
    # runtime can be inf/nan if an exception occurred
    if math.isinf(runtime) or math.isnan(runtime):
        runtime = None
    cur.execute('INSERT INTO ' + table + ' (name, runtime, checkval, date, '
                'platform) VALUES(%s, %s, %s, %s, %s)',
                (name_id, runtime, check, date, arch_id))


class BenchmarkSQLInserter(object):
    def __init__(self, file_table, unit, unit_table, lab_only, table,
                 name_table, arch_id, cur, date):
        (self.file_table, self.unit, self.unit_table, self.lab_only,
         self.table, self.name_table, self.arch_id, self.cur, self.date) \
            = (file_table, unit, unit_table, lab_only, table, name_table,
               arch_id, cur, date)
        self.unit_id = None

    def __call__(self, test):
        if self.unit_id is None:
            self.unit_id = update_unit(self.unit_table, self.unit, self.cur,
                                       self.lab_only)
        if test['status'] != 'OK':
            return
        if 'test output was removed' in test['output']:
            print("WARNING: output of benchmark %s in %s was truncated"
                  % (test['name'], self.unit))
        file_id = update_benchmark_file(self.file_table, test['name'],
                                        self.unit_id, self.cur)
        seen_name_ids = {}
        for line in test['output'].split('\n'):
            spl = line.split(',')
            if len(spl) == 5:
                line_ok = True
                try:
                    runtime = float(spl[2])
                    check = float(spl[3])
                except ValueError:
                    line_ok = False
                if line_ok:
                    get_benchmark_name(self.table, self.name_table, file_id,
                                       self.unit_id, self.arch_id, self.cur,
                                       spl[0].strip(), spl[1].strip(),
                                       runtime, check, seen_name_ids,
                                       self.date)


class TestXMLHandler(ContentHandler):
    def __init__(self, func, module):
        super().__init__()
        self._test = None
        self._in_name = False
        self._in_measure = None
        self._in_output = False
        self._in_value = False
        self.func = func
        self.module = module
        self.ntests = 0

    def get_string(self, s):
        return s

    def start_test(self, status):
        status_map = {'passed': 'OK', 'failed': 'FAIL', 'notrun': 'FAIL'}
        self._test = {'status': status_map[self.get_string(status)],
                      'output': '', 'cases': []}
        self.ntests += 1

    def end_test(self):
        if self._test:
            if self._check_test_fields():
                self.func(self._test)
            self._test = None

    def _check_test_fields(self):
        if 'name' not in self._test:
            print("WARNING: test without a name encountered; ignored")
            return
        name = self.get_string(self._test['name'])
        if name.startswith('IMP.'):
            name = name[4:]
        if name.startswith(self.module + '.') \
           or name.startswith(self.module + '-'):
            name = name[len(self.module) + 1:]
        else:
            print("WARNING: test name %s does not start with module "
                  "%s; ignoring" % (name, self.module))
            return
        self._test['name'] = name
        expfail = skip = False
        for case in self._test['cases']:
            if case['state'] == 'EXPFAIL':
                expfail = True
            elif case['state'] == 'SKIP':
                skip = True
        if 'time' in self._test:
            self._test['time'] = float(self._test['time'])
        else:
            # In some cases, a test is not run; the time is not reported
            self._test['time'] = 0.
        if 'docstring' in self._test:
            self._test['docstring'] = self.get_string(self._test['docstring'])
        if 'exit_code' in self._test:
            if self._test['exit_code'] == u'Timeout':
                self._test['status'] = 'TIMEOUT'
            elif self._test['exit_code'] == u'SEGFAULT':
                self._test['status'] = 'SEGFAULT'
        if self._test['status'] == 'OK':
            if skip and expfail:
                self._test['status'] = 'SKIP_EXPFAIL'
            elif skip:
                self._test['status'] = 'SKIP'
            elif expfail:
                self._test['status'] = 'EXPFAIL'
        if 'output' in self._test:
            self._test['output'] = self.get_string(self._test['output'])
        if 'detail' in self._test:
            self._test['detail'] = self.get_string(self._test['detail'])
        return True

    def startElement(self, name, attrs):
        if name == 'Test' and 'Status' in attrs:
            self.start_test(attrs['Status'])
        elif self._test:
            if name == 'Name':
                self._in_name = True
            elif name == 'NamedMeasurement' and 'name' in attrs:
                self._in_measure = attrs['name']
            elif name == 'Measurement':
                self._in_output = True
            elif name == 'Value':
                self._in_value = (attrs.get('encoding', None),
                                  attrs.get('compression', None))
                self._chs = ''
            elif name == 'TestCase':
                self._test['cases'].append({'name': attrs['name'],
                                            'state': attrs['state']})

    def endElement(self, name):
        if name == 'Test':
            self.end_test()
        elif self._test:
            if name == 'Name':
                self._in_name = False
            elif name == 'NamedMeasurement':
                self._in_measure = None
            elif name == 'Measurement':
                self._in_output = False
            elif name == 'Value':
                self.end_value(self._chs, *self._in_value)
                self._in_value = False

    def _append_test_text(self, field, ch):
        self._test[field] = self._test.get(field, '') + ch

    def characters(self, ch):
        if self._in_name:
            self._append_test_text('name', ch)
        elif self._in_value:
            self._chs += ch

    def end_value(self, ch, encoding, compression):
        if encoding == 'base64':
            ch = base64.b64decode(ch)
        elif encoding is not None:
            raise ValueError("Unknown encoding %s" % encoding)
        if compression == 'gzip':
            ch = zlib.decompress(ch)
        elif compression is not None:
            raise ValueError("Unknown compression %s" % compression)
        if isinstance(ch, bytes):
            ch = ch.decode('latin1')  # todo: could it be another encoding?
        if self._in_measure == 'Execution Time':
            self._append_test_text('time', ch)
        elif self._in_measure == 'Exit Code':
            self._append_test_text('exit_code', ch)
        elif self._in_measure == 'docstring':
            self._append_test_text('docstring', ch)
        elif self._in_measure == 'Python unittest detail':
            self._append_test_text('detail', ch)
        elif self._in_output:
            self._append_test_text('output', ch)


class TestXMLParser(object):
    def __init__(self, product, test_xml, ignore_unknown, use_base_unit=False):
        self.test_xml = test_xml
        fname = os.path.basename(test_xml)
        spl = fname.split('.')
        self.module = spl[0]
        try:
            self.unit = get_unit_name_from_modules(self.module, product.units)
        except KeyError:
            if ignore_unknown:
                self.unit = None
            else:
                raise
        if not use_base_unit:
            if self.unit and fname.endswith('.example.xml'):
                self.unit += " examples"
            if self.unit and fname.endswith('.benchmark.xml'):
                self.unit += " benchmarks"

    def parse(self, func):
        parser = xml.sax.make_parser()
        handler = TestXMLHandler(func, self.module)
        parser.setContentHandler(handler)
        try:
            parser.parse(open(self.test_xml))
        except xml.sax.SAXParseException as exc:
            print("WARNING: invalid test XML file: " + str(exc))
        return handler.ntests


class TestSQLInserter(object):
    def __init__(self, table, name_table, unit, unit_table, lab_only,
                 arch_id, date, cur, prev_tests):
        self.table = table
        self.name_table = name_table
        self.unit = unit
        self.unit_table = unit_table
        self.lab_only = lab_only
        self.arch_id = arch_id
        self.date = date
        self.cur = cur
        self.prev_tests = prev_tests
        self.seen_names = {}
        self.unit_id = None

    def __call__(self, test):
        if 'docstring' in test:
            test['name'] = test['docstring']
        if test['name'] in self.seen_names:
            print("WARNING: duplicate test %s in %s; ignoring"
                  % (test['name'], self.unit))
            return
        self.seen_names[test['name']] = None
        if self.unit_id is None:
            self.unit_id = update_unit(self.unit_table, self.unit, self.cur,
                                       self.lab_only)
        name_id = update_name(self.name_table, test['name'], self.unit_id,
                              self.cur)
        if test['status'] == 'OK':
            test['output'] = None
        else:
            # If a test produced a large amount of amount, take the tail
            if len(test['output']) > 2048:
                test['output'] = '[...] ' + test['output'][-2048:]
            # If we have unittest output, prefer that
            if 'detail' in test and test['detail']:
                test['output'] = test['detail'][:20480]
            # Don't store empty strings in the db
            if test['output'] == '':
                test['output'] = None
        prev_status = self.prev_tests.get((name_id, self.arch_id), None)
        delta = None
        if prev_status is not None:
            if prev_status in OK_STATES and test['status'] not in OK_STATES:
                delta = 'NEWFAIL'
            elif prev_status not in OK_STATES and test['status'] in OK_STATES:
                delta = 'NEWOK'
        self.cur.execute("INSERT INTO " + self.table + " (name, arch, "
                         "state, detail, runtime, date, delta) VALUES "
                         "(%s, %s, %s, %s, %s, %s, %s)",
                         (name_id, self.arch_id, test['status'],
                          test['output'], test['time'], self.date, delta))


class DatabaseUpdater(object):
    """Handle updating the database with build results"""
    setup_tables = {}

    def __init__(self, dryrun, test_table_prefix, bench_table_prefix, lab_only,
                 imp_branch, clean=False):
        self.clean = clean
        self.dryrun = dryrun
        self.test_table_prefix = test_table_prefix
        self.bench_table_prefix = bench_table_prefix
        self.lab_only = lab_only
        self.imp_branch = imp_branch
        self.imp_branch_sql = imp_branch.replace('/', '_').replace('.', '_')
        self.conn = connect_mysql()

    def get_test_table(self, suffix, per_branch):
        return self.get_table(self.test_table_prefix + '_' + suffix,
                              per_branch)

    def get_benchmark_table(self, suffix):
        return self.get_table(self.bench_table_prefix + '_' + suffix, False)

    def get_table(self, name, per_branch):
        """Get the name of a table to use."""
        if self.dryrun:
            # Don't alter the original table; use a temporary
            table = name + '_temp'
            if table not in self.setup_tables:
                cur = self.conn.cursor()
                cur.execute('DROP TABLE IF EXISTS %s' % table)
                cur.execute('CREATE TABLE %s LIKE %s' % (table, name))
                self.setup_tables[table] = None
            return table
        elif per_branch and self.imp_branch != 'develop':
            return name + "_" + self.imp_branch_sql
        else:
            return name

    def get_unit_summary(self, comp):
        cur = self.conn.cursor()
        date = datetime.date.today()

        arch_table = self.get_test_table("archs", False)
        unit_table = self.get_test_table("units", False)
        result_table = self.get_test_table("unit_result", True)
        if self.clean:
            cur.execute("DELETE FROM " + result_table + " WHERE date=%s",
                        (date,))

        state_to_sql = {type(None): 'OK',
                        ModuleDisabledError: 'DISABLED',
                        TestFailedError: 'TEST',
                        TestNotRunError: 'NOTEST',
                        BuildFailedError: 'BUILD',
                        BenchmarkFailedError: 'BENCH',
                        NoLogModule: 'NOLOG',
                        ExcludedModule: 'SKIP',
                        BuildNotRunError: 'NOBUILD',
                        ExampleNotRunError: 'NOEX',
                        BenchmarkNotRunError: 'NOBENCH',
                        BuildRunningError: 'RUNBUILD',
                        TestRunningError: 'RUNTEST',
                        ExampleRunningError: 'RUNEX',
                        BenchmarkRunningError: 'RUNBENCH',
                        CircularDependencyError: 'CIRCDEP',
                        FailedDependencyError: 'FAILDEP',
                        ExampleFailedError: 'EXAMPLE'}
        cmake_archs = [x.arch for x in comp.cmake_logs]
        arch_ids = {}
        for unit, results in comp.module_map.items():
            unit = get_unit_name_from_modules(unit, comp.units)
            unit_id = update_unit(unit_table, unit, cur, self.lab_only)
            for arch, state in results.items():
                arch_id = arch_ids.get(arch, None)
                if arch_id is None:
                    arch_ids[arch] = arch_id = update_arch(arch_table,
                                                           arch, cur)
                sql = state_to_sql[type(state)]
                if arch in cmake_archs:
                    sql = 'CMAKE_' + sql
                cur.execute("INSERT INTO " + result_table +
                            " (arch, unit, "
                            "state, logline, date) VALUES (%s, %s, %s, %s, "
                            "%s)",
                            (arch_id, unit_id, sql,
                             getattr(state, '_line_number', None), date))
        self.conn.commit()

    def get_benchmarks(self, xmldir, comp, ignore_unknown=False):
        cur = self.conn.cursor()
        date = datetime.date.today()

        file_table = self.get_benchmark_table("files")
        name_table = self.get_benchmark_table("names")
        arch_table = self.get_test_table("archs", False)
        unit_table = self.get_test_table("units", False)
        table = self.get_table(self.bench_table_prefix, per_branch=True)
        if self.clean:
            cur.execute("DELETE FROM " + table + " WHERE date=%s", (date,))

        try:
            archs = os.listdir(xmldir)
        except OSError:
            return
        # Only include benchmark results for fast or release builds
        archs = [x for x in archs if 'fast' in x or 'release' in x]
        for arch in archs:
            test_xmls = glob.glob(os.path.join(xmldir, arch,
                                               '*.benchmark.xml'))
            if len(test_xmls) > 0:
                arch_id = update_arch(arch_table, arch, cur)
                for test_xml in test_xmls:
                    t = TestXMLParser(comp, test_xml, ignore_unknown,
                                      use_base_unit=True)
                    if t.unit:
                        t.parse(BenchmarkSQLInserter(
                            file_table, t.unit, unit_table, self.lab_only,
                            table, name_table, arch_id, cur, date))
        self.conn.commit()

    def get_repo_revision(self, rev, version=None):
        """Record the revision number of today's build in the database."""
        cur = self.conn.cursor()
        date = datetime.date.today()
        rev_table = self.get_test_table("reporev", True)
        if self.clean:
            cur.execute("DELETE FROM " + rev_table + " WHERE date=%s", (date,))

        if version:
            cur.execute("INSERT INTO " + rev_table
                        + " (rev, date, version) VALUES (%s, %s, %s)",
                        (rev, date, version))
        else:
            cur.execute("INSERT INTO " + rev_table
                        + " (rev, date) VALUES (%s, %s)", (rev, date))
        self.conn.commit()

    def get_other_repo_revisions(self, verdir):
        """Record the revision of other repos in the database."""
        cur = self.conn.cursor()
        date = datetime.date.today()
        rev_table = self.get_test_table("other_reporev", True)
        if self.clean:
            cur.execute("DELETE FROM " + rev_table + " WHERE date=%s", (date,))
        repovers = (glob.glob(os.path.join(verdir, "*-version"))
                    + glob.glob(os.path.join(verdir, "*-gitrev")))
        for repover in repovers:
            repo = os.path.split(repover)[-1].split('-')[0]
            if repo == 'multifit':
                # multifit2 lives in the multifit repo
                repo = 'multifit2'
            elif repo == 'imp':
                # Currently we don't have any lab-only stuff built from
                # the IMP repo
                continue
            rev = open(repover).readline().rstrip('\r\n')
            cur.execute("INSERT INTO " + rev_table
                        + " (rev, repo, date) VALUES (%s, %s, %s)",
                        (rev, repo, date))
        self.conn.commit()

    def get_docs(self, broken_links):
        """Record numbers of broken links in the docs in the database."""
        cur = self.conn.cursor()
        date = datetime.date.today()
        table = self.get_table("imp_doc", per_branch=True)
        if self.clean:
            cur.execute("DELETE FROM " + table + " WHERE date=%s", (date,))
        cur.execute("INSERT INTO " + table +
                    " (date, nbroken_manual, nbroken_tutorial, "
                    "nbroken_rmf_manual) VALUES (%s, %s, %s, %s)",
                    (date, broken_links[0], broken_links[1], broken_links[2]))
        self.conn.commit()

    def get_build_summary(self, comp):
        """Record the summary of today's build in the database."""
        cur = self.conn.cursor()
        date = datetime.date.today()
        table = self.get_table("imp_build_summary", per_branch=True)
        if self.clean:
            cur.execute("DELETE FROM " + table + " WHERE date=%s", (date,))
        cur.execute("INSERT INTO " + table +
                    " (state, date, lab_only) VALUES (%s, %s, %s)",
                    (comp.state, date, self.lab_only))
        self.conn.commit()

    def get_test_results(self, comp, xmldir, ignore_unknown=False):
        """Extract all IMP test results from ctest XML in the named directory,
           and store in the named table in the MySQL database.
           See test_db.readme for MySQL setup info."""
        date = datetime.date.today()
        # Get previous build's results, so we can mark deltas
        db = imp_build_utils.BuildDatabase(self.conn, date, False,
                                           self.imp_branch)
        prev = db.get_previous_build_date()
        if prev is None:
            prev_tests = {}
        else:
            prev_tests = db.get_test_dict(prev)

        cur = self.conn.cursor()
        table = self.get_table(self.test_table_prefix, per_branch=True)
        arch_table = self.get_test_table("archs", False)
        unit_table = self.get_test_table("units", False)
        name_table = self.get_test_table("names", False)
        if self.clean:
            cur.execute("DELETE FROM " + table + " WHERE date=%s", (date,))

        try:
            archs = os.listdir(xmldir)
        except OSError:
            return
        for arch in archs:
            test_xmls = (glob.glob(os.path.join(xmldir, arch, '*.test.xml'))
                         + glob.glob(os.path.join(xmldir, arch,
                                                  '*.benchmark.xml'))
                         + glob.glob(os.path.join(xmldir, arch,
                                                  '*.example.xml')))
            if len(test_xmls) > 0:
                arch_id = update_arch(arch_table, arch, cur)
                for test_xml in test_xmls:
                    t = TestXMLParser(comp, test_xml, ignore_unknown)
                    if t.unit:
                        ntests = t.parse(TestSQLInserter(
                            table, name_table, t.unit, unit_table,
                            self.lab_only, arch_id, date, cur, prev_tests))
                        if test_xml.endswith('.test.xml') and ntests == 0:
                            print("WARNING: no tests for", t.unit, arch)
        self.conn.commit()


def link_to_logs(dirroot, subdir, destdir, branch):
    """Make symlinks so current and old logs are accessible over the web"""
    if branch:
        log_dir = os.path.join(destdir, 'logs', branch)
    else:
        log_dir = os.path.join(destdir, 'logs')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Remove existing links
    for log_link in glob.glob(os.path.join(log_dir, '*')):
        if os.path.islink(log_link):
            os.unlink(log_link)

    # Make new links
    for d in glob.glob(os.path.join(dirroot, '*-*')):
        src = os.path.join(d, 'build', 'logs', subdir)
        if os.path.exists(src):
            target = os.path.join(log_dir, os.path.split(d)[1].split('-')[0])
            # If multiple builds ran on the same day, take only the first one
            if not os.path.exists(target):
                os.symlink(src, target)


class IMPChecker(Checker):
    # Note: differs from Modeller behavior in that directories are not deleted
    # or renamed; instead symlinks are simply updated if necessary to point
    # to new dated directories

    def __init__(self, dirroot, branch):
        super().__init__(dirroot)
        self.branch = branch
        self._dirroot = dirroot
        self.donebuildlink = os.path.join(dirroot, '.last')
        self.okbuildlink = os.path.join(dirroot, 'last_ok_build')
        self.nightlybuildlink = os.path.join(dirroot, 'nightly')

    def build_has_changed(self):
        """Return True only if the build changed since the last run"""
        return (not os.path.exists(self.donebuildlink)
                or not os.path.exists(self.newbuilddir)
                or os.readlink(self.donebuildlink)
                != os.readlink(self.newbuilddir))

    def print_header(self, formatter):
        title = 'IMP nightly build results, %s, %s' \
                % (self._repos[0].newrevision, time.strftime("%m/%d/%Y"))
        formatter.print_header(title)

    def update_downloads(self, pattern, subdir=''):
        """If a downloadable file was produced, make it available for
           download, overwriting any previous versions"""
        download = imp_downloadhtml
        if subdir:
            download = os.path.join(download, subdir)
            if not os.path.exists(download):
                os.mkdir(download)
        basepat = os.path.basename(pattern)
        produced = glob.glob(os.path.join(self.newbuilddir, pattern))
        if len(produced) > 0:
            old = glob.glob(os.path.join(download, basepat))
            for f in old:
                os.unlink(f)
            for f in produced:
                shutil.copy(f, download)
            # Also copy Debian repo files
            if pattern.endswith('.deb'):
                for f in ('Release', 'Packages', 'Packages.gz'):
                    path = os.path.join(self.newbuilddir,
                                        'packages', subdir, f)
                    if os.path.exists(path):
                        shutil.copy(path, download)
                    else:
                        print("WARNING: %s not found" % path)

    def calculate_download_digests(self, patterns):
        digest1 = open(os.path.join(imp_downloadhtml, 'SHA1SUM'), 'w')
        digest256 = open(os.path.join(imp_downloadhtml, 'SHA256SUM'), 'w')
        for pat in patterns:
            basepat = os.path.basename(pat)
            for f in glob.glob(os.path.join(imp_downloadhtml, basepat)):
                m1 = hashlib.sha1()
                m256 = hashlib.sha256()
                with open(f, 'rb') as fh:
                    while True:
                        d = fh.read(65536)
                        if len(d) == 0:
                            break
                        m1.update(d)
                        m256.update(d)
                print("%s  %s" % (m1.hexdigest(), os.path.basename(f)),
                      file=digest1)
                print("%s  %s" % (m256.hexdigest(), os.path.basename(f)),
                      file=digest256)

    def check_docs(self):
        if self.branch == 'develop':
            ref_url = 'https://integrativemodeling.org/nightly/doc/ref/'
            manual_url = 'https://integrativemodeling.org/nightly/doc/manual/'
            rmf_manual_url = 'https://integrativemodeling.org/rmf/nightly/doc/'
        else:
            ref_url = manual_url = rmf_manual_url = None
        outfh = open(os.path.join(self.nightlybuildlink, 'build',
                                  'broken-links.html'), 'w')
        nbroken_manual = check_broken_links(
            os.path.join(self.nightlybuildlink, 'doc', 'manual'), manual_url,
            html=True, verbose=False, title='IMP manual', outfh=outfh)
        nbroken_ref = check_broken_links(
            os.path.join(self.nightlybuildlink, 'doc', 'ref'), ref_url,
            html=True, verbose=False, title='Reference guide', outfh=outfh)
        nbroken_rmf_manual = check_broken_links(
            os.path.join(self.nightlybuildlink, 'RMF-doc'), rmf_manual_url,
            html=True, verbose=False, title='RMF manual', outfh=outfh)
        return (nbroken_manual, nbroken_ref, nbroken_rmf_manual)

    def update_done_build(self, dryrun):
        if not dryrun:
            # Update last-build symlink to point to the new build
            src = os.readlink(self.newbuilddir)
            update_symlink(src, self.donebuildlink)
        db = DatabaseUpdater(dryrun, 'imp_test', 'imp_benchmark', False,
                             self.branch, clean=True)
        db.get_test_results(self._products[0],
                            os.path.join(self.newbuilddir, 'build',
                                         'logs', 'imp'))
        db.get_other_repo_revisions(os.path.join(self.newbuilddir, 'build'))
        db.get_unit_summary(self._products[0])
        db.get_benchmarks(os.path.join(self.newbuilddir, 'build',
                                       'logs', 'imp'),
                          self._products[0])
        db.get_build_summary(self._products[0])
        for p in self._products:
            p.update_status(dryrun)

        version = None
        if not dryrun and self.branch == 'main':
            # Add version symlink if main branch
            verlink = os.path.join(self._dirroot, self._repos[0].newlongver)
            version = self._repos[0].newlongver
            if os.path.exists(verlink):
                print("WARNING: link %s already exists - not updating"
                      % verlink)
            else:
                src = os.readlink(self.newbuilddir)
                os.symlink(src, verlink)
        db.get_repo_revision(self._repos[0].newrevision, version)

        if dryrun:
            return

        # Abort if the build didn't build any docs
        if not os.path.exists(self.newbuilddir + '/doc/manual/index.html'):
            link_to_logs(self.dirroot, 'imp', imp_testhtml, self.branch)
            return
        download_patterns = ['packages/*-10.10.dmg',
                             'packages/*.exe',
                             'packages/*.src.rpm', 'build/sources/*.tar.gz',
                             'packages/*.fc*.x86_64.rpm',
                             'packages/IMP*.el*.x86_64.rpm']
        subdirs = [os.path.basename(d)
                   for d in glob.glob(os.path.join(self.newbuilddir,
                                                   'packages', '*'))
                   if os.path.isdir(d)]
        if self.branch == 'develop':
            for pattern in download_patterns:
                self.update_downloads(pattern)
            for subdir in subdirs:
                self.update_downloads('packages/%s/*.deb' % subdir,
                                      subdir=subdir)
        self.calculate_download_digests(download_patterns)
        # Check static and fast builds
        pydir = os.path.join(self.newbuilddir, 'lib')
        for d in glob.glob("%s/*/IMP" % pydir):
            # Byte-compile all Python files:
            byte_compile_python_dir(d)
        # Update nightly symlink to point to the new build
        src = os.readlink(self.newbuilddir)
        update_symlink(src, self.nightlybuildlink)

        # Check for broken links in docs
        db.get_docs(self.check_docs())

        # If everything built OK, update ok_build symlink
        if self._products[0].state in ('OK', 'TEST'):
            update_symlink(src, self.okbuildlink)

        if self.branch == 'develop':
            # Remove old builds
            p = PruneDirectories(self.dirroot)
            p.prune()

        link_to_logs(self.dirroot, 'imp', imp_testhtml, self.branch)

    def activate_new_build(self):
        # Update 'stable' symlink to point to the new build
        src = os.readlink(self.newbuilddir)
        update_symlink(src, self.builddir)


class IMPLabChecker(Checker):

    def __init__(self, dirroot):
        super().__init__(dirroot)
        self.donebuildlink = os.path.join(dirroot, 'nightly')

    def update_done_build(self, dryrun):
        db = DatabaseUpdater(dryrun, 'imp_test', 'imp_benchmark', True,
                             'develop')

        db.get_other_repo_revisions(os.path.join(self.newbuilddir, 'build'))

        p = self._products[0]
        db.get_test_results(self._products[0],
                            os.path.join(self.newbuilddir, 'build', 'logs',
                                         'imp-salilab'),
                            ignore_unknown=True)
        db.get_unit_summary(self._products[0])
        db.get_benchmarks(os.path.join(self.newbuilddir, 'build',
                                       'logs', 'imp-salilab'),
                          self._products[0], ignore_unknown=True)
        db.get_build_summary(self._products[0])

        if dryrun:
            return

        # Update done-build symlink to point to the new build
        src = os.readlink(self.newbuilddir)
        if os.path.exists(self.donebuildlink):
            os.remove(self.donebuildlink)
        os.symlink(src, self.donebuildlink)

        # Remove old builds
        p = PruneDirectories(self.dirroot)
        p.prune()
        link_to_logs(self.dirroot, 'imp-salilab', imp_lab_testhtml, None)

    def activate_new_build(self):
        # Update symlink to point to the new build
        src = os.readlink(self.newbuilddir)
        if os.path.exists(self.builddir):
            os.remove(self.builddir)
        os.symlink(src, self.builddir)


def get_options():
    """Parse command line options"""
    parser = ArgumentParser()
    parser.add_argument("-n", "--no-email", dest="email", default=True,
                        action="store_false",
                        help="Don't send email on failure; just print a "
                             "message instead")
    parser.add_argument("--branch", dest="imp_branch", default='develop',
                        help="IMP branch to use (default 'develop')")
    parser.add_argument("--dry-run", dest="dryrun", default=False,
                        action="store_true",
                        help="Run checks only; don't update databases "
                             "or send out email")
    return parser.parse_args()


def _deb_packages(version, codename):
    """Get a list of all generated .deb binary and source packages"""
    srcprefix = 'packages/%s/source/imp_%s-1~%s' % (codename, version,
                                                    codename)
    return ['packages/%s/imp_%s-1_amd64.deb' % (codename, version),
            'packages/%s/source/imp_%s.orig.tar.gz' % (codename, version),
            srcprefix + '.debian.tar.xz',
            srcprefix + '_source.buildinfo',
            srcprefix + '_source.changes',
            srcprefix + '.dsc']


def main():
    opts = get_options()
    impcheck = IMPChecker("/salilab/diva1/home/imp/" + opts.imp_branch,
                          opts.imp_branch)
    # Lab-only components are currently only built against the develop branch
    if opts.imp_branch == 'develop':
        imp_lab_check = IMPLabChecker(
            "/salilab/diva1/home/imp-salilab/develop")
    else:
        # Do nothing for non-develop builds if the build didn't run today
        # (unless a dry run was explicitly requested)
        if not opts.dryrun and not impcheck.build_has_changed():
            return
        imp_lab_check = None

    if imp_lab_check:
        repo = Repository("multifit")
        imp_lab_check.add_repository(repo)

    repo = Repository("imp")
    impcheck.add_repository(repo)

    c = IMPProduct("IMP", "imp", module_coverage=True, repo=repo)
    impcheck.add_product(c)

    # Check RMF as part of IMP
    c.modules.insert(0, 'RMF')
    c.units['RMF'] = 'module'

    for m in ('COVERAGE', 'PACKAGE', 'PKGTEST', 'DOC', 'RMF-DOC',
              'INSTALL', 'ALLPYTHON', 'ALL'):
        c.modules.insert(0, m)
        c.units[m] = 'build'

    # Main platforms to build on: macOS (Intel, ARM64); old Mac;
    # Windows (32-bit, 64-bit)
    mac14 = 'mac14-intel'
    mac13arm = 'mac13arm64-gnu'
    win32 = 'i386-w32'
    win64 = 'x86_64-w64'
    all_archs = [mac14, mac13arm, win32, win64]

    for arch in all_archs:
        c.add_cmake_log(arch, ['build', 'benchmark', 'test', 'example'], [])

    # Check static, debug and release Linux builds
    static = 'static9'
    c.add_cmake_log(static, ['build'], [])
    debug8 = 'debug8'
    release8 = 'release8'
    # Check fast Linux and Mac builds
    fast8 = 'fast8'
    fastmac = 'fastmac15'
    for f in (fastmac, fast8, release8, debug8):
        c.add_cmake_log(f, ['build', 'benchmark', 'test', 'example'], [])

    f42_64 = 'pkg.f42-x86_64'  # Fedora 42 RPM
    rh8_64 = 'pkg.el8-x86_64'  # RHEL 8 RPM
    rh9_64 = 'pkg.el9-x86_64'  # RHEL 9 RPM
    focal = 'pkg.focal-x86_64'  # Ubuntu 20.04 (Focal Fossa) .deb package
    jammy = 'pkg.jammy-x86_64'  # Ubuntu 22.04 (Jammy Jellyfish) .deb package
    noble = 'pkg.noble-x86_64'  # Ubuntu 24.04 (Noble Numbat) .deb package

    # Check CUDA builds
    cuda = 'cuda'
    c.add_cmake_log(cuda, ['build', 'test', 'example'], [])

    # Check coverage (on Fedora)
    coverage = 'coverage'
    c.add_cmake_log(coverage, ['build', 'test', 'example'], [])

    new_archs_map = [rh8_64, rh9_64, focal, jammy, noble, win64]
    rh_rpms = [rh8_64, rh9_64]
    all_archs_map = [debug8, mac14, mac13arm, win32, fast8, fastmac, static,
                     release8, f42_64] + new_archs_map + [coverage, cuda]
    c.make_module_map(all_archs_map)
    # Only cmake builds have an ALL component
    incs = [f42_64, fastmac, coverage, cuda, fast8, static, debug8,
            release8, focal, jammy, noble] + rh_rpms + all_archs
    c.include_component('ALL', incs)
    c.include_component('INSTALL', [fastmac, fast8, debug8,
                                    release8, cuda] + all_archs)
    incs = [win32, win64]
    c.include_component('PACKAGE', incs)
    # Only the Windows installer has a separate package test step
    c.include_component('PKGTEST', [win32, win64])
    c.include_component('COVERAGE', [coverage])
    c.include_component('ALLPYTHON', [fast8, release8])
    for m in ('mpi', 'spb', 'nestor'):
        mods = [release8, debug8, rh8_64, rh9_64, f42_64, fast8,
                coverage, win32, win64, mac14, mac13arm, fastmac, focal,
                jammy, noble]
        c.include_component(m, mods)
    # Documentation only built on one platform
    c.include_component('DOC', mac13arm)
    c.include_component('RMF-DOC', mac13arm)

    # scratch module is excluded from all RPM and deb builds
    for m in ('scratch',):
        c.exclude_component(m, [f42_64, focal, jammy, noble] + rh_rpms)
    for m in ('RMF', 'rmf', 'gsl', 'multifit', 'em2d', 'EMageFit',
              'domino', 'example', 'pepdock', 'cgal',
              'cnmultifit', 'saxs_merge', 'integrative_docking',
              'npctransport', 'sampcon'):
        c.exclude_component(m, (static,))

    # Check RPMs
    c.add_log('rpm.source.log', 'RPM specfile',
              ['packages/IMP.spec', 'packages/IMP-copr.spec'])
    c.add_cmake_log(f42_64, ['build', 'test'],
                    'packages/IMP-%s-1.fc42.x86_64.rpm' % repo.newlongver)
    c.add_cmake_log(rh8_64, ['build', 'test'],
                    'packages/IMP-%s-1.el8.x86_64.rpm' % repo.newlongver)
    c.add_cmake_log(rh9_64, ['build', 'test'],
                    'packages/IMP-%s-1.el9.x86_64.rpm' % repo.newlongver)

    # Check debs
    c.add_cmake_log(focal, ['build', 'test'],
                    _deb_packages(repo.newlongver, 'focal'))
    c.add_cmake_log(jammy, ['build', 'test'],
                    _deb_packages(repo.newlongver, 'jammy'))
    c.add_cmake_log(noble, ['build', 'test'],
                    _deb_packages(repo.newlongver, 'noble'))
    repo = Repository("imp")
    if imp_lab_check:
        imp_lab_check.add_repository(repo)
        c = IMPProduct("IMP-salilab", "imp-salilab",
                       module_coverage=True, repo=repo)

        imp_lab_check.add_product(c)
        for arch in all_archs:
            c.add_cmake_log(arch, ['build', 'benchmark', 'test',
                                   'example'], [])

        for m in ('COVERAGE_LAB', 'INSTALL_LAB', 'ALL_LAB'):
            c.modules.insert(0, m)
            c.units[m] = 'build'

        # Add debug, fast, static and release builds
        for f in (debug8, fastmac, fast8, release8):
            c.add_cmake_log(f, ['build', 'benchmark', 'test', 'example'],
                            [])
        c.add_cmake_log(static, ['build'], [])
        # Add CUDA build
        c.add_cmake_log(cuda, ['build', 'test', 'example'], [])
        # Add coverage build
        c.add_cmake_log(coverage, ['build', 'test', 'example'], [])
        all_archs_map = [debug8, mac14, mac13arm, fast8, fastmac, static,
                         release8, win32, win64, cuda, coverage]
        c.make_module_map(all_archs_map)

        # Only cmake builds have an ALL_LAB component
        incs = [f42_64, fastmac, cuda, coverage, fast8, debug8,
                static, release8, focal, jammy, noble] + rh_rpms + all_archs
        c.include_component('ALL_LAB', incs)
        c.include_component('COVERAGE_LAB', [coverage])
        c.include_component('INSTALL_LAB',
                            [fastmac, fast8, debug8, release8, cuda]
                            + all_archs)

        for m in ('multifit2', 'domino3', 'bayesem2d'):
            c.exclude_component(m, (static,))
        for m in ('multifit2',):
            c.exclude_component(m, (cuda,))
        for m in ('domino3',):
            c.exclude_component(m, (win32, win64, mac13arm, fastmac))
        # Seth's code only works on very recent machines with cppad-devel
        # installed (just our Fedora boxes)
        for m in ('liegroup', 'autodiff'):
            c.include_component(m, [cuda, coverage])
        for m in ('isd_emxl',):
            incs = [release8, debug8, f42_64, fast8, coverage, win32,
                    win64, mac14, mac13arm, fastmac] + rh_rpms
            c.include_component(m, incs)

    checks = []
    checks.append((impcheck, imp_testhtml, imp_testurl))
    if imp_lab_check:
        checks.append((imp_lab_check, imp_lab_testhtml, imp_lab_testurl))

    for check, testhtml, testurl in checks:
        if opts.dryrun:
            formatters = [TextFormatter()]
        else:
            formatters = []
            check.copy_log_files(testhtml)

        nerr = check.check_logs(formatters, opts.dryrun)
        del formatters  # Ensure that output file gets closed
        if not opts.dryrun:
            if nerr == 0:
                check.activate_new_build()
        check.update_done_build(opts.dryrun)
    if not opts.dryrun and opts.email \
       and opts.imp_branch == 'develop':
        email_from = get_imp_build_email_from()
        conn = connect_mysql()
        for lab_only in (False, True):
            imp_build_utils.send_imp_results_email(conn, email_from, lab_only,
                                                   opts.imp_branch)


if __name__ == '__main__':
    main()
