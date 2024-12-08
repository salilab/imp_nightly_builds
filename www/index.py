#!/usr/bin/python3

import cgi
import html
import cgitb
import traceback
import sys
import re
import os
import glob
import pickle
import MySQLdb
import time
import datetime
sys.path.append('/home/ben/imp_nightly_builds')
from imp_build_utils import BuildDatabase, get_topdir  # noqa: E402
from imp_build_utils import lab_only_topdir  # noqa: E402
from imp_build_utils import platforms_dict, OK_STATES  # noqa: E402
from imp_build_utils import results_url, lab_only_results_url  # noqa: E402
from imp_build_utils import SPECIAL_COMPONENTS  # noqa: E402

imp_github = 'https://github.com/salilab/imp'
rmf_github = 'https://github.com/salilab/rmf'
pmi_github = 'https://github.com/salilab/pmi'


def get_cache_headers():
    """Cache results for 1 hour"""
    def get_time(t):
        mtime = time.gmtime(t)
        return time.strftime('%a, %d %b %Y %H:%M:%S GMT', mtime)
    t = time.time()
    return """Cache-Control: public, max-age=3600
Last-Modified: %s
Expires: %s""" % (get_time(t), get_time(t + 3600))


def get_platform_td(platform, fmt="%s"):
    val = platforms_dict.get(platform, None)
    if val:
        return "<td title=\"%s\">%s</td>" % (val.long, fmt % val.short)
    else:
        return "<td>" + (fmt % platform) + "</td>"


def handle_plural(num, text):
    if num == 1:
        return num, text
    else:
        return num, text + "s"


def get_state_td(state):
    if state in OK_STATES:
        cls = "testok"
    else:
        cls = "testfail"
    return "<td class=\"%s\">%s</td>" % (cls, state)


def get_delta_td(delta):
    if delta is None:
        return '<td></td>'
    else:
        if delta == 'NEWOK':
            cls = "testok"
        else:
            cls = "testfail"
        return "<td class=\"%s\">%s</td>" % (cls, delta)


def html_escape(text):
    from xml.sax.saxutils import escape
    if text is None:
        return ""
    else:
        return escape(text, {'"': "&quot;"})


def get_date_link(date):
    return date.strftime('%Y%m%d')


def connect_mysql():
    d = os.path.dirname(sys.argv[0])
    with open(os.path.join(d, 'imp-sql-args.pck'), 'rb') as fh:
        args = pickle.load(fh)
    conn = MySQLdb.connect(**args)
    return conn


def print_footer():
    print("</body></html>")


def get_coverage_link(date, covtyp, component, pct, lab_only, branch,
                      nightly_url):
    fpct = float(pct)
    if fpct >= 90:
        cls = "high_coverage"
    elif fpct >= 75:
        cls = "med_coverage"
    else:
        cls = "low_coverage"
    if lab_only:
        prefix = '/internal/imp/nightly'
        branch = ''
    else:
        prefix = nightly_url
        branch = branch + '/'
    return '<a class="%s" href="%s/logs/%s%s/coverage/%s/%s/">%s%%</a>' \
           % (cls, prefix, branch, get_date_link(date), covtyp, component, pct)


class TestPage(object):
    all_branches = ['develop', 'main', 'release/2.10.1',
                    'release/2.11.0', 'release/2.11.1', 'release/2.12.0',
                    'release/2.13.0', 'release/2.14.0', 'release/2.15.0',
                    'release/2.16.0', 'release/2.17.0', 'release/2.18.0',
                    'release/2.19.0', 'release/2.20.0', 'release/2.20.1',
                    'release/2.20.2', 'release/2.21.0', 'release/2.22.0']

    def __init__(self):
        self.lab_only = (os.environ.get('HTTPS', 'off') == 'on'
                         and os.environ.get('REMOTE_USER', None) is not None)
        self.script_name = os.environ.get('SCRIPT_NAME', '')
        if '/imp' in self.script_name:
            self.nightly_url = '/imp/nightly'
        else:
            self.nightly_url = '/nightly'
        form = cgi.FieldStorage()
        self.branch = form.getfirst('branch', 'develop')
        if self.branch not in self.all_branches:
            self.branch = 'develop'
        if self.branch != 'develop':
            self.lab_only = False
        (self.date, self.last_build_date, self.version,
         self.last_build_version) = self.get_date_and_version(form)
        self.revision = self.get_revision()
        self.test = self.get_form_integer(form, 'test')
        self.platform = self.get_form_integer(form, 'plat')
        self.component = self.get_form_integer(form, 'comp')
        self.bench = self.get_form_integer(form, 'bench')
        self.default_page = 'build'
        self.pages = {'results': self.display_test,
                      'runtime': self.display_test_runtime,
                      'log': self.display_log,
                      'build': self.display_build_summary,
                      'comp': self.display_component,
                      'compplattest': self.display_comp_plat_tests,
                      'new': self.display_new_failures,
                      'long': self.display_long_tests,
                      'doc': self.display_doc_build_summary,
                      'bench': self.display_benchmarks,
                      'platform': self.display_platform,
                      'benchfile': self.display_benchmark_file,
                      'stat': self.display_build_status_badge,
                      'all': self.display_all_failures}
        askpage = form.getfirst('p', self.default_page)
        if self.test and self.platform:
            self.page = 'results'
        elif self.bench:
            self.page = 'benchfile'
        elif self.platform and self.component:
            self.page = 'compplattest'
        elif (self.platform and not askpage.startswith('bench')
              and askpage != 'platform'):
            self.page = 'log'
        elif self.component:
            self.page = 'comp'
        else:
            self.page = askpage
            if self.page in ('results', 'log', 'comp', 'compplattest',
                             'benchfile') \
               or self.page not in self.pages:
                self.page = self.default_page
        if self.page != 'stat':
            print('Content-type: text/html')
            print('X-Robots-Tag: noindex, nofollow\n\n')

    def get_branch_table(self, name):
        if self.branch == 'develop':
            return name
        else:
            return name + '_' + self.branch.replace('/', '_').replace('.', '_')

    def get_build_id(self):
        id = str(self.date)
        if self.revision:
            id += ', ' + self.branch + ' ' + self.revision[:10]
        if self.version:
            id += ' (%s)' % self.version
        return id

    def print_header(self, include_charts=False):
        print("""
<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN"
     "http://www.w3.org/TR/html4/strict.dtd">
<html>
<head>
<meta http-equiv="Content-Type" content="text/html;charset=utf-8">
<script type="text/javaScript" src="testfunc.js"></script>
<script type="text/javaScript" src="sorttable.js"></script>""")
        if include_charts:
            print("""
<!--[if lt IE 9]><script language="javascript" type="text/javascript" src="excanvas.min.js"></script><![endif]-->
<script type="text/javaScript" src="jquery-1.8.1.min.js"></script>
<script type="text/javaScript" src="jquery.jqplot.min.js"></script>
<script type="text/javaScript" src="jqplot.canvasAxisLabelRenderer.min.js"></script>
<script type="text/javaScript" src="jqplot.canvasTextRenderer.min.js"></script>
<script type="text/javaScript" src="jqplot.cursor.min.js"></script>
<script type="text/javaScript" src="jqplot.highlighter.min.js"></script>
<script type="text/javaScript" src="jqplot.dateAxisRenderer.min.js"></script>
<link href="jquery.jqplot.css" rel="stylesheet" type="text/css">""")  # noqa: E501
        print("""
<link href="tests.css" rel="stylesheet" type="text/css">
<link href="/fontawesome6/css/fontawesome.min.css" rel="stylesheet" type="text/css">
<link href="/fontawesome6/css/brands.min.css" rel="stylesheet" type="text/css">

<script type="text/javascript"><!--
window.onload = linkEmail;
-->
</script>

<title>IMP nightly build results, %s</title>
</head>

<body>
<div id="header">
<div id="impnav">
   <table class="imptnav">
      <tr>
         <td><a href="//integrativemodeling.org/">
             <img src="//integrativemodeling.org/images/the_imp.png" height="60" alt="IMP logo"></a></td>
         <td>
            <div class="implinks">
             <ul>
               <li><a href="//integrativemodeling.org/">home</a></li>
               <li><a href="//integrativemodeling.org/about.html">about</a></li>
               <li><a href="//integrativemodeling.org/news.html">news</a></li>
               <li><a href="//integrativemodeling.org/download.html">download</a></li>
               <li><a href="//integrativemodeling.org/doc.html" title="Manual, tutorials, and reference guide">doc</a></li>
               <li><a href="https://github.com/salilab/imp" title="Source code, maintained at GitHub">source</a></li>
               <li><a href="//integrativemodeling.org/systems/" title="Applications of IMP to real biological systems">systems</a></li>
               <li><a href="//integrativemodeling.org/nightly/results/" title="Results of IMP's internal test suite">tests</a></li>
               <li><a href="https://github.com/salilab/imp/issues" title="Report a bug in IMP">bugs</a></li>
               <li><a href="//integrativemodeling.org/contact.html" title="Mailing lists and email">contact</a></li>
           </ul>
            </div>
         </td>
      </tr>
   </table>
</div>

<div id="impheaderline">
</div>
""" % self.get_build_id())  # noqa: E501

    def get_form_integer(self, form, name):
        if name not in form:
            return None
        try:
            return int(form.getfirst(name))
        except ValueError:
            return 0

    def get_revision(self):
        conn = connect_mysql()
        query = ('SELECT rev from ' + self.get_branch_table('imp_test_reporev')
                 + ' where date=%s')
        c = conn.cursor()
        c.execute(query, (self.date,))
        res = c.fetchone()
        if res:
            return res[0]

    def get_other_repo_revs(self):
        conn = connect_mysql()
        query = 'SELECT repo,rev from ' \
                + self.get_branch_table('imp_test_other_reporev') \
                + ' where date=%s'
        c = conn.cursor()
        c.execute(query, (self.date,))
        revs = {}
        for res in c:
            revs[res[0]] = res[1]
        return revs

    def get_last_build_date(self):
        """Get date of most recent nightly build"""
        s = os.readlink(os.path.join(get_topdir(self.branch), '.last'))
        return datetime.date(year=int(s[:4]), month=int(s[4:6]),
                             day=int(s[6:8]))

    def get_version(self, date):
        """Map date to version"""
        if self.branch == 'main':
            conn = connect_mysql()
            c = conn.cursor()
            table = self.get_branch_table('imp_test_reporev')
            query = 'SELECT version FROM ' + table + ' WHERE date=%s'
            c.execute(query, (date,))
            res = c.fetchone()
            if res:
                return res[0]

    def get_date_and_version(self, form):
        # Map version to date, if given
        version = form.getfirst('version', None)
        if version:
            self.branch = 'main'
            last_build_date = self.get_last_build_date()
            conn = connect_mysql()
            c = conn.cursor()
            table = self.get_branch_table('imp_test_reporev')
            query = 'SELECT date FROM ' + table + ' WHERE version=%s'
            c.execute(query, (version,))
            res = c.fetchone()
            if res:
                return (res[0], last_build_date, version,
                        self.get_version(last_build_date))

        last_build_date = self.get_last_build_date()
        date = form.getfirst('date', None)
        if date:
            m = re.match(r'(\d{4})(\d{2})(\d{2})$', date)
            if m:
                date = datetime.date(year=int(m.group(1)),
                                     month=int(m.group(2)),
                                     day=int(m.group(3)))
                return (date, last_build_date, self.get_version(date),
                        self.get_version(last_build_date))
        last_build_version = self.get_version(last_build_date)
        return (last_build_date, last_build_date,
                last_build_version, last_build_version)

    def display(self):
        if self.page == 'stat':
            self.pages[self.page]()
        else:
            self.print_header(self.bench is not None or self.page == 'runtime')
            self.display_page()
            print_footer()

    def get_sql_lab_only(self):
        """Get a suitable SQL WHERE fragment to restrict a query to only
           public components, if necessary"""
        if self.lab_only:
            return ""
        else:
            return " AND imp_test_units.lab_only=false"

    def get_component_from_id(self, conn, component):
        query = 'SELECT name, lab_only from imp_test_units WHERE id=%s' \
                + self.get_sql_lab_only()
        c = conn.cursor()
        c.execute(query, (component,))
        res = c.fetchone()
        if res:
            name = res[0]
            # Hack to map 'IMP' to kernel
            if name.startswith('IMP ') or name == 'IMP':
                name = ('IMP.kernel ' + name[4:]).rstrip()
            return name, res[1]
        return None, False

    def get_platform_name_from_id(self, conn, platform):
        c = conn.cursor()
        c.execute('SELECT name from imp_test_archs WHERE id=%s',
                  (platform,))
        res = c.fetchone()
        if res:
            return res[0]

    def display_comp_plat_tests(self):
        def loglinks(plat, comp, lab_only):
            build_type = 'test'
            if comp.startswith('IMP.'):
                comp = comp[4:]
            elif comp == 'IMP':
                comp = 'kernel'
            if comp.endswith(' examples'):
                build_type = 'example'
                comp = comp[:-9]
            elif comp.endswith(' benchmarks'):
                build_type = 'benchmark'
                comp = comp[:-11]
            link = "<li>%s</li>" % self.get_raw_log_link(
                '%s/%s.%s.log' % (plat, comp, build_type), lab_only,
                "The raw log file", remove_prefix=False)
            if build_type == 'test':
                link += "\n<li>%s</li>" % self.get_raw_log_link(
                    '%s/%s.build.log' % (plat, comp),
                    lab_only, "The build log file", remove_prefix=False)
            return link
        conn = connect_mysql()
        component_name, lab_only = self.get_component_from_id(conn,
                                                              self.component)
        if not component_name:
            print("<p><b>Unknown component.</b></p>")
            return
        platform_name = self.get_platform_name_from_id(conn, self.platform)
        if not platform_name:
            print("<p><b>Unknown platform.</b></p>")
            return
        if len(component_name.split(" ")) == 2:
            results = "results"
        else:
            results = "test results"
        print("<h1>%s %s for build on %s</h1>"
              % (component_name, results, self.get_build_id()))
        print('<p>These were generated by the '
              '<a href="%s">%s</a>.</p>'
              % (self.get_link(page='platform'),
                 platforms_dict[platform_name].long))
        print('<p>See also:</p>')
        print('<ul><li><a href="%s">Test results for this component on '
              '<b>all</b> platforms</a></li>' % self.get_link(page='comp'))
        print('%s</ul>' % loglinks(platform_name, component_name, lab_only))
        db = BuildDatabase(conn, self.date, self.lab_only, self.branch)
        self.display_tests(db.get_all_component_tests(self.component,
                                                      self.platform),
                           include_component=False, include_platform=False)

    def display_component(self):
        conn = connect_mysql()
        component_name, lab_only = self.get_component_from_id(conn,
                                                              self.component)
        if not component_name:
            print("<p><b>Unknown component.</b></p>")
            return

        print("<h1>All %s test results for build on %s</h1>"
              % (component_name, self.get_build_id()))
        db = BuildDatabase(conn, self.date, self.lab_only, self.branch)
        self.display_tests(db.get_all_component_tests(self.component),
                           include_component=False)

    def display_build_status_badge(self):
        imgroot = "https://img.shields.io/badge/"
        db = BuildDatabase(connect_mysql(), self.date, self.lab_only,
                           self.branch)
        s = db.get_build_summary()
        if s in ("OK", "TEST"):
            imgurl = imgroot + "nightly build-passing-brightgreen.svg"
        else:
            imgurl = imgroot + "nightly build-failing-red.svg"
        print("Status: 302 Found")
        print(get_cache_headers())
        print("Location: %s" % imgurl)
        print()

    def display_all_failures(self):
        print("<h1>All test failures for build on %s</h1>"
              % self.get_build_id())
        db = BuildDatabase(connect_mysql(), self.date, self.lab_only,
                           self.branch)
        self.display_tests(db.get_all_failed_tests())

    def display_new_failures(self):
        print("<h1>New test failures for build on %s</h1>"
              % self.get_build_id())
        db = BuildDatabase(connect_mysql(), self.date, self.lab_only,
                           self.branch)
        prev_build = db.get_previous_build_date()
        if prev_build is None:
            print("<p><i>No previous builds exist, so no new test "
                  "failures.</i></p>")
        else:
            print("<p>All tests that failed on %s but passed on %s "
                  "are shown below.</p>" % (self.date, prev_build))
            self.display_tests(db.get_new_failed_tests())

    def display_long_tests(self):
        print("<h1>Long-running tests for build on %s</h1>"
              % self.get_build_id())
        print("<p>All tests that ran for more than 20 seconds are shown.</p>")
        db = BuildDatabase(connect_mysql(), self.date, self.lab_only,
                           self.branch)
        self.display_tests(db.get_long_tests())

    def display_benchmark_file(self):
        conn = connect_mysql()
        c = MySQLdb.cursors.DictCursor(conn)
        plats = self.get_benchmark_platforms(c)
        thisplat = self.show_benchmark_platform_links(plats)
        c.execute('SELECT imp_benchmark_files.name AS file_name, '
                  'imp_test_units.name AS unit_name '
                  'FROM imp_benchmark_files,imp_test_units WHERE '
                  'imp_benchmark_files.unit=imp_test_units.id '
                  'AND imp_benchmark_files.id=%s '
                  + self.get_sql_lab_only(), (self.bench,))
        fc_r = c.fetchone()
        if fc_r is None:
            print("<p>Invalid benchmark file</p>")
            return
        if thisplat is None:
            print("<p>Invalid platform</p>")
            return
        print("<h1>File benchmarks for build on %s</h1>" % self.get_build_id())
        print("<p>All benchmarks from file <b>%s</b> in <b>%s</b> are shown. "
              "Each plot shows how long the benchmark ran for, and the "
              "check value, "
              "the meaning of which varies from test to test (for example, "
              "many benchmarks use it to track how much memory is "
              "being used).</p>" % (fc_r['file_name'], fc_r['unit_name']))

        print("<p><i>Click and drag on a plot to zoom in; double click "
              "to reset the zoom.</i></p>")

        table = self.get_branch_table('imp_benchmark')
        query = 'SELECT imp_benchmark_names.name, ' \
                'imp_benchmark_names.id, ' \
                'imp_benchmark_names.algorithm, imp_benchmark.date, ' \
                'imp_benchmark.runtime, imp_benchmark.checkval ' \
                'FROM ' + table + ' imp_benchmark, imp_benchmark_names ' \
                'WHERE imp_benchmark_names.file=%s AND ' \
                'imp_benchmark.name=imp_benchmark_names.id AND ' \
                'imp_benchmark.platform=%s ' \
                'AND date<=%s ORDER BY imp_benchmark_names.id,date'
        c.execute(query, (self.bench, self.platform, self.date))
        print('<script type="text/javascript">')
        print("""function plot_bench(chartid, values) {
  return $.jqplot(chartid, values, {
    series:[
      {label: 'Runtime'},
      {yaxis:'y2axis', label: 'Check'}
    ],
    legend: {show:true, location: 'sw'},
    axesDefaults:{useSeriesColor: true},
    axes: {
      xaxis: {
        renderer: $.jqplot.DateAxisRenderer,
        tickOptions: {formatString: '%F', showGridline: false}
      },
      yaxis: {
        label: 'Runtime (s)',
        labelRenderer: $.jqplot.CanvasAxisLabelRenderer,
        tickOptions: { showGridline: false }
      },
      y2axis: {
        label: 'Check',
        labelRenderer: $.jqplot.CanvasAxisLabelRenderer,
        tickOptions: { showGridline: false }
      },
    },
    highlighter: {
      show: true,
      sizeAdjust: 10
    },
    cursor: {
       show: true,
       zoom:true,
       showTooltip:true
    }
  });
}""")
        print('</script>')
        print("<ul>")
        bench = {'id': None}
        for row in c:
            if row['id'] != bench['id']:
                if bench['id'] is not None:
                    self.display_benchmark(bench)
                bench = {'id': row['id'],
                         'name': row['name'],
                         'algorithm': row['algorithm'],
                         'dates': [],
                         'runtimes': [],
                         'checkvals': []}
            bench['dates'].append(row['date'])
            bench['runtimes'].append(row['runtime'] or 0)
            bench['checkvals'].append(row['checkval'] or 0)
        if bench['id'] is not None:
            self.display_benchmark(bench)
        print("</ul>")

    def display_benchmark(self, bench):
        def get_check(val):
            if val[1] is None:
                return (val[0], 0.0)
            else:
                return val
        # Exclude benchmarks that didn't run today
        if len(bench['dates']) > 0 and bench['dates'][-1] != self.date:
            return
        print('<li><a name="%d">%s %s</a> '
              '<a class="permalink" href="#%d">[link]</a>'
              % (bench['id'], bench['name'], bench['algorithm'], bench['id']))
        print('<div id="bench_%d" class="benchmark">' % bench['id'])
        print('</div>')
        print('<script type="text/javascript">')
        print("""$(document).ready(function() {
  var plot%d = plot_bench('bench_%d', [[%s], [%s]]);
});""" % (bench['id'], bench['id'],
          ",".join("['%s', %f]" % x
                   for x in zip(bench['dates'], bench['runtimes'])),
          ",".join("['%s', %f]" % get_check(x)
                   for x in zip(bench['dates'], bench['checkvals']))))
        print('</script>')
        print('</li>')

    def get_benchmark_platforms(self, c):
        table = self.get_branch_table('imp_benchmark')
        query = 'SELECT DISTINCT imp_test_archs.id, imp_test_archs.name ' \
                'FROM ' + table + ' imp_benchmark,imp_test_archs ' \
                'WHERE date=%s AND imp_test_archs.id=imp_benchmark.platform ' \
                'ORDER BY imp_test_archs.id DESC'
        c.execute(query, (self.date,))
        return c.fetchall()

    def show_benchmark_platform_links(self, plats):
        thisplat = None
        print("<div class=\"linkspacer\"></div>")
        print("<div class=\"implinks\">\n<ul>")
        for p in plats:
            plat = platforms_dict[p['name']]
            if p['id'] == self.platform:
                thisplat = plat
                cls = ' class="thispage"'
            else:
                cls = ''
            print('<li%s><a title="%s" href="%s">%s</a>'
                  % (cls, plat.long, self.get_link(platform=p['id']),
                     plat.short))
        print("</ul></div>")
        return thisplat

    def display_doc_build_summary(self):
        conn = connect_mysql()
        db = BuildDatabase(conn, self.date, self.lab_only, self.branch)
        print("<h1>Doc summary for build on %s</h1>" % self.get_build_id())
        fh = db.get_broken_links()
        if fh:
            for line in fh:
                sys.stdout.write(line)
        else:
            print("<p>No information available for this build.</p>")

    def display_platform(self):
        conn = connect_mysql()
        plat_name = self.get_platform_name_from_id(conn, self.platform)
        if not plat_name:
            print("<p><b>Invalid platform requested</b></p>")
            return
        p = platforms_dict[plat_name]
        print("<h1>Platform: %s</h1>" % p.short)
        print("<p>%s</p>" % p.long)
        print("<p>%s</p>" % p.very_long)
        print("<ul>")
        if self.lab_only:
            print("<li>%s</li>"
                  % self.get_raw_log_link(
                      '%s/' % plat_name, False,
                      "All public log files for this platform",
                      remove_prefix=False))
            print("<li>%s</li>"
                  % self.get_raw_log_link(
                      '%s/' % plat_name, True,
                      "All lab-only log files for this platform",
                      remove_prefix=False))
        else:
            print("<li>%s</li>"
                  % self.get_raw_log_link('%s/' % plat_name, False,
                                          "All log files for this platform",
                                          remove_prefix=False))
        print("</ul>")

    def display_benchmarks(self):
        conn = connect_mysql()
        c = MySQLdb.cursors.DictCursor(conn)
        plats = self.get_benchmark_platforms(c)
        if self.platform is None and len(plats) > 0:
            self.platform = plats[0]['id']
        thisplat = self.show_benchmark_platform_links(plats)
        print("<h1>Benchmarks for build on %s</h1>" % self.get_build_id())
        if thisplat is None:
            print("<p><b>No benchmarks for this platform</b></p>")
            return
        print('<p>These benchmarks are run as part of the '
              '<a href="%s">%s</a>.</p>'
              % (self.get_link(page='platform'), thisplat.long))
        table = self.get_branch_table('imp_benchmark')
        query = 'SELECT imp_test_units.name AS unit_name, ' \
                'imp_test_units.id AS unit_id, ' \
                'imp_benchmark_files.name AS file_name, ' \
                'imp_benchmark_files.id AS file_id, ' \
                'COUNT(*) as n_benchmarks ' \
                'FROM ' + table + ' imp_benchmark, imp_benchmark_names, ' \
                'imp_benchmark_files, imp_test_units WHERE date=%s ' \
                + self.get_sql_lab_only() \
                + ' AND imp_benchmark.name=imp_benchmark_names.id AND ' \
                'imp_benchmark_names.file=imp_benchmark_files.id AND ' \
                'imp_benchmark_files.unit=imp_test_units.id AND ' \
                'imp_benchmark.platform=%s ' \
                'GROUP BY imp_test_units.name,imp_benchmark_files.name'
        print("<table class=\"sortable\">\n<thead>")
        print("<tr><th>Component</th>")
        print("<th>File name</th>")
        print("<th>Number of benchmarks</th></tr></thead><tbody>")
        c.execute(query, (self.date, self.platform))
        for row in c:
            link = self.get_link(page='benchfile', bench=row['file_id'])
            print("<tr><td>%s</td> <td><a href=\"%s\">%s</a></td> "
                  "<td>%d</td></tr>"
                  % (row['unit_name'], link, row['file_name'],
                     row['n_benchmarks']))
        print("</tbody></table>")

    def get_link(self, page=None, test=None, platform=None, date=None,
                 component=None, bench=None, branch=None):
        if page is None:
            page = self.page
        if test is None:
            test = self.test
        if platform is None:
            platform = self.platform
        if date is None:
            date = self.date
        if component is None:
            component = self.component
        if bench is None:
            bench = self.bench
        if branch is None:
            branch = self.branch
        if page == 'results' and test is not None and platform is not None:
            ret = "?test=%d&amp;plat=%d" % (test, platform)
        elif page == 'runtime' and test is not None:
            ret = "?p=runtime&amp;test=%d" % test
        elif page == 'log' and platform is not None:
            ret = "?plat=%d" % platform
        elif page == 'comp' and component is not None:
            ret = "?comp=%d" % component
        elif (page == 'compplattest' and component is not None
              and platform is not None):
            ret = "?comp=%d&amp;plat=%d" % (component, platform)
        elif (page == 'benchfile' and bench is not None
              and platform is not None):
            ret = "?bench=%d&amp;plat=%d" % (bench, platform)
        else:
            ret = "?p=%s" % page
        if page in ('bench', 'platform') and platform is not None:
            ret += "&amp;plat=%d" % platform
        if date != self.last_build_date:
            ret += '&amp;date=%s' % get_date_link(date)
        if branch != 'develop':
            ret += '&amp;branch=%s' % branch
        return ret

    def format_build_summary(self, summary, unit, arch, arch_id, unit_id):
        def make_cmake_loglink(cls, title, build_type, data, numfails=0,
                               numnewfails=0):
            if numfails > 0:
                caption = '%d' % numfails
                if numnewfails > 0:
                    caption += ', +%d' % numnewfails
            else:
                caption = '&nbsp;'
            tags = 'class="summbox %s" title="%s" ' % (cls, title)
            if build_type == 'test' \
               or (build_type == 'benchmark'
                   and unit.endswith(' benchmarks')) \
               or (build_type == 'example' and unit.endswith(' examples')):
                link = '<a %shref="%s">%s</a>' \
                       % (tags,
                          self.get_link(page='compplattest',
                                        component=unit_id,
                                        platform=arch_id),
                          caption)
            else:
                lnkunit = unit
                if unit.startswith('IMP.'):
                    lnkunit = unit[4:]
                elif unit == 'IMP':
                    lnkunit = 'kernel'
                if lnkunit.endswith(' examples'):
                    lnkunit = lnkunit[:-9]
                    build_type = 'example'
                elif lnkunit.endswith(' benchmarks'):
                    lnkunit = lnkunit[:-11]
                    build_type = 'benchmark'
                link = self.get_raw_log_link('%s/%s.%s.log'
                                             % (arch, lnkunit, build_type),
                                             data['lab_only'], caption,
                                             remove_prefix=False, tags=tags)
            return '<td>%s</td>' % link

        def make_cmake(cls, title):
            return '<td><div class="summbox %s" title="%s">&nbsp;</div></td>' \
                   % (cls, title)

        def make_loglink(img, alt, title, data):
            prefixes = {True: 'l', False: 'n'}
            return '<td><a href="%s#%s_%d">' \
                   '<img src="%s/images/%s" ' \
                   'alt="%s" title="%s"></a></td>' \
                   % (self.get_link(page='log', platform=arch_id),
                      prefixes[data['lab_only']], data['logline'],
                      self.nightly_url, img, alt, title)

        def print_newfail(s):
            if s['numnewfails'] == 0:
                return ''
            else:
                return ' (%d %s since previous build)' \
                       % handle_plural(s['numnewfails'], "new failure")
        try:
            s = summary[unit][arch]
        except KeyError:
            s = None
        if s is None or s['state'] in ('SKIP', 'CMAKE_SKIP'):
            return make_cmake('moduleskip',
                              "Component is not built on this platform")
        elif s['state'] == 'OK':
            return '<td><img src="%s/images/moduleok.png" alt="ok" ' \
                   'title="Component built successfully"></td>' \
                   % self.nightly_url
        elif s['state'] == 'BUILD':
            return make_loglink(img='modulebuild.png', alt='BUILD',
                                title="Component failed to build", data=s)
        elif s['state'] == 'TEST':
            return make_loglink(img='moduletest.png', alt='TEST',
                                title="Component failed test cases", data=s)
        elif s['state'] == 'NOTEST':
            return ('<td><img src="%s/images/moduletestnotrun.png" '
                    'alt="TEST" title="Component test cases did not run"></td>'
                    % self.nightly_url)
        elif s['state'] == 'NOLOG':
            return '<td><img src="%s/images/moduletestnotrun.png" ' \
                   'alt="NOLOG" title="No log file for build on this ' \
                   'platform"></td>' % self.nightly_url
        elif s['state'] == 'DISABLED':
            return make_loglink(img='modulebuild.png', alt='DISAB',
                                title="Component disabled due to "
                                      "configuration error", data=s)
        elif s['state'] == 'UNCON':
            return '<td><img src="%s/images/modulebuild.png" ' \
                   'alt="UNCON" title="Component was not configured"></td>' \
                   % self.nightly_url
        elif s['state'] == 'BENCH':
            return make_loglink(img='modulebuild.png', alt='BENCH',
                                title="Component benchmark failed", data=s)
        elif s['state'] == 'CMAKE_OK':
            if unit.endswith(' examples'):
                return make_cmake_loglink(
                    cls='moduleok', title="Examples ran successfully",
                    build_type='example', data=s)
            elif unit.endswith(' benchmarks'):
                return make_cmake_loglink(
                    cls='moduleok', title="Benchmarks ran successfully",
                    build_type='benchmark', data=s)
            else:
                return make_cmake_loglink(
                    cls='moduleok', title="Component built successfully",
                    build_type='build', data=s)
        elif s['state'] == 'CMAKE_BUILD':
            return make_cmake_loglink(
                cls='modulebuild', title="Component failed to build",
                build_type='build', data=s)
        elif s['state'] == 'CMAKE_CIRCDEP':
            return make_cmake('modulecircdep',
                              "Component did not build (circular dependency)")
        elif s['state'] == 'CMAKE_FAILDEP':
            return make_cmake('modulefaildep',
                              'Component was not built due to the '
                              'failure to build a dependency')
        elif s['state'] == 'CMAKE_DISABLED':
            return make_cmake('moduledisab',
                              "Component disabled due to configuration error")
        elif s['state'] == 'CMAKE_NOBUILD':
            return make_cmake('moduletestnotrun',
                              "Component build did not run")
        elif s['state'] == 'CMAKE_RUNBUILD':
            return make_cmake_loglink(
                cls='modulebuild', title="Component build did not complete",
                build_type='build', data=s)
        elif s['state'] == 'CMAKE_BENCH':
            return make_cmake_loglink(
                cls='modulebench',
                title="%d component %s failed" % handle_plural(s['numfails'],
                                                               "benchmark")
                + print_newfail(s),
                build_type='benchmark', data=s, numfails=s['numfails'],
                numnewfails=s['numnewfails'])
        elif s['state'] == 'CMAKE_NOBENCH':
            return make_cmake('moduletestnotrun',
                              "Component benchmark did not run")
        elif s['state'] == 'CMAKE_RUNBENCH':
            return make_cmake_loglink(
                cls='modulebuild',
                title="Component benchmark did not complete",
                build_type='benchmark', data=s)
        elif s['state'] == 'CMAKE_TEST':
            return make_cmake_loglink(
                cls='moduletest',
                title="Component failed %d %s" % handle_plural(s['numfails'],
                                                               "test case")
                + print_newfail(s),
                build_type='test', data=s,
                numfails=s['numfails'], numnewfails=s['numnewfails'])
        elif s['state'] == 'CMAKE_NOTEST':
            return make_cmake('moduletestnotrun',
                              "Component test did not run")
        elif s['state'] == 'CMAKE_RUNTEST':
            return make_cmake_loglink(
                cls='modulebuild', title="Component test did not complete",
                build_type='test', data=s)
        elif s['state'] == 'CMAKE_EXAMPLE':
            return make_cmake_loglink(
                cls='moduleexample',
                title="%d %s failed" % handle_plural(s['numfails'],
                                                     "component example")
                + print_newfail(s),
                build_type='example', data=s,
                numfails=s['numfails'], numnewfails=s['numnewfails'])
        elif s['state'] == 'CMAKE_NOEX':
            return make_cmake('moduletestnotrun',
                              "Component examples did not run")
        elif s['state'] == 'CMAKE_RUNEX':
            return make_cmake_loglink(
                cls='modulebuild', title="Component examples did not complete",
                build_type='example', data=s)
        else:
            raise ValueError("Unknown state %s" % s['state'])

    def print_last_ok_build(self, db):
        last_ok = db.get_last_build_with_summary(('OK', 'TEST'))
        if last_ok is not None:
            print('<p>IMP last built successfully on <a href="%s">%s</a>.</p>'
                  % (self.get_link(date=last_ok), last_ok))

    def print_doc_summary(self, db):
        def fmt_msg(title, nbroken):
            if nbroken:
                if nbroken == 1:
                    suffix = ""
                else:
                    suffix = "s"
                return 'Today\'s %s contains <a href="%s">%d broken ' \
                       'link%s</a>. ' % (title, self.get_link(page='doc'),
                                         nbroken, suffix)
            else:
                return ''
        s = db.get_doc_summary()
        if s:
            msg = (fmt_msg('manual', s['nbroken_manual'])
                   + fmt_msg('reference guide', s['nbroken_tutorial'])
                   + fmt_msg('RMF manual', s['nbroken_rmf_manual']))
            if msg:
                print("<p>%s</p>" % msg)

    def print_build_summary(self, db):
        s = db.get_build_summary()
        not_recommend = 'It is therefore not recommended to check out and ' \
                        'build this version of IMP, unless you know what ' \
                        'you\'re doing.'
        if s == 'BUILD':
            print('<p><span class="warning">At least part of IMP failed to '
                  'build today</span> '
                  '(red boxes in the grid below). %s</p>' % not_recommend)
            self.print_last_ok_build(db)
        elif s == 'INCOMPLETE':
            print('<p>The build system <span class="warning">ran out of '
                  'time</span> on at least '
                  'one platform today. This <i>might</i> indicate a problem '
                  'with IMP. %s</p>' % not_recommend)
            self.print_last_ok_build(db)
        elif s == 'BADLOG':
            print('<p><span class="warning">Something went wrong with the '
                  'build system infrastructure today</span> '
                  '(see the "Miscellaneous log errors" below), '
                  'so at least part of IMP was not adequately '
                  'tested. %s</p>' % not_recommend)
            self.print_last_ok_build(db)
        elif s == 'TEST':
            print('<p>Some of the IMP testcases '
                  '<span class="warning">failed</span> today '
                  '(orange or blue boxes '
                  'in the grid below). These suggest that the indicated '
                  'parts of IMP might not work '
                  'properly. Use a nightly build at your own risk!</p>')

    def toggle_failmap(self, show_failures, caption):
        if show_failures:
            return ("<a title=\"Show only components or platforms that have "
                    "at least one failure\" "
                    "onclick=\"toggle_visibility('failmap', "
                    "'fullmap', 'faillink', 'fulllink'); "
                    "return false;\" href=\"#\">%s</a>" % caption)
        else:
            return ("<a title=\"Show all components and platforms\" "
                    "onclick=\"toggle_visibility('fullmap', 'failmap', "
                    "'fulllink', 'faillink'); "
                    "return false;\" href=\"#\">%s</a>" % caption)

    def display_build_summary(self):
        db = BuildDatabase(connect_mysql(), self.date, self.lab_only,
                           self.branch)
        summary = db.get_unit_summary()
        build_info = db.get_build_info()

        print("<div class=\"linkspacer\"></div>")
        print("<div class=\"implinks\">\n<ul>")
        print("<li class=\"thispage\" id=\"faillink\">")
        print(self.toggle_failmap(show_failures=True, caption="Failures"))
        print("<li id=\"fulllink\">")
        print(self.toggle_failmap(show_failures=False, caption="All"))
        print("</ul></div>")

        print("<h1>Summary for build on %s</h1>" % self.get_build_id())
        if self.lab_only:
            listname = 'IMP-lab-build'
        else:
            listname = 'IMP-build'
        if self.branch == 'develop':
            print('<p class="maillist">To get an email when new results '
                  'become available, subscribe to the '
                  '<a href="https://salilab.org/mailman/listinfo/%s">%s</a> '
                  'mailing list.</p>' % (listname.lower(), listname))

        self.print_build_summary(db)
        self.print_doc_summary(db)

        if self.revision:
            git = len(self.revision) > 20
            if git:
                print('<p>You can get IMP source code '
                      '<a href="%s/tree/%s">'
                      'from github</a>. (To look at this '
                      '<a href="%s/tree/%s">specific revision</a>, '
                      'run "<tt>git checkout %s</tt>".)'
                      % (imp_github, self.branch, imp_github, self.revision,
                         self.revision[:10]))
            else:
                print('<p>To get this version of IMP, run the following '
                      'command: "<tt>svn co -%s '
                      'http://svn.salilab.org/imp/trunk imp</tt>" (or, if '
                      'you have an existing SVN checkout, use "<tt>svn up '
                      '-%s</tt>").' % (self.revision, self.revision))
            revs = self.get_other_repo_revs()
            rmf_rev = revs.get('rmf', '')
            if rmf_rev:
                print('This includes <a href="%s">RMF</a> revision '
                      '<a href="%s/tree/%s">%s</a>.'
                      % (rmf_github, rmf_github, rmf_rev, rmf_rev[:7]))
            if self.date == self.last_build_date:
                if self.lab_only:
                    lab_only_note = " (note these only include the " \
                                    "public components)"
                else:
                    lab_only_note = ""
                if self.branch == 'develop':
                    print('Pre-built binaries <a href="https://'
                          'integrativemodeling.org/nightly/download/">'
                          'are also available</a>%s.' % lab_only_note)
            if git:
                print('</p>')
            else:
                print(' You can also '
                      '<a href="http://svn.salilab.org/viewvc/imp/trunk/'
                      '?pathrev=%s">browse the source code</a>.</p>'
                      % self.revision[1:])
            if self.lab_only:
                print('<p>Lab-only components can be obtained by git '
                      'or SVN from the following locations:</p>')
                print('<ul>')
                for comp, url in [
                        ('multifit2',
                         'https://svn.salilab.org/multifit/multifit2/'),
                        ('isd2', 'https://github.com/salilab/isd2'),
                        ('isd_emxl', 'https://github.com/salilab/isd_emxl'),
                        ('hdx', 'https://github.com/salilab/hdx'),
                        ('shg', 'https://github.com/salilab/shg'),
                        ('hmc', 'https://github.com/salilab/hmc'),
                        ('bayesem2d', 'https://github.com/salilab/bayesem2d'),
                        ('autodiff', 'https://github.com/salilab/autodiff'),
                        ('liegroup', 'https://github.com/salilab/liegroup'),
                        ('pynet', 'https://github.com/salilab/pynet'),
                        ('bbm', 'https://github.com/salilab/bbm'),
                        ('domino3', 'https://github.com/salilab/domino3')]:
                    rev = revs.get(comp, "")
                    if rev:
                        if 'github' in url:
                            branch, hash = rev.split(' ')
                            rev = ', <a href="%s/commit/%s">%s</a>' \
                                  % (url, hash, rev)
                        else:
                            rev = ", " + rev
                    print('<li><a href="%s">%s</a>%s</li>' % (url, comp, rev))
                print('</ul>')

        print('<div id="fullmap" style="display:none">')
        self.print_summary_table(summary, build_info,
                                 'All components and platforms are shown',
                                 show_failures=True)
        print("</div>")

        print('<div id="failmap" style="display:block">')
        summary.make_only_failed()
        self.print_summary_table(summary, build_info,
                                 'Only components or platforms that have at '
                                 'least one failure are shown',
                                 show_failures=False)
        print("</div>")
        self.print_misc_errors(build_info[0], False)
        if self.lab_only:
            self.print_misc_errors(build_info[1], True)
        self.print_git_log(db)

    def print_git_log(self, db):
        log = db.get_git_log()
        if log:
            print('<div class="gitlog">')
            print('<h2>Log</h2>')
            print('<table>')
            for lg in log:
                title = lg.title
                if len(title) > 100:
                    title = title[:100] + '...'
                # Link to RMF or PMI commits
                title = re.sub("salilab/rmf@([a-z0-f]{7})([a-z0-f]+)",
                               r'<a href="' + rmf_github +
                               r'/commit/\1\2">salilab/rmf@\1</a>', title)
                title = re.sub("salilab/pmi@([a-z0-f]{7})([a-z0-f]+)",
                               r'<a href="' + pmi_github +
                               r'/commit/\1\2">salilab/pmi@\1</a>', title)
                # Link to issues
                title = re.sub(r" #(\d+)",
                               r' <a href="' + imp_github +
                               r'/issues/\1">#\1</a>', title)
                print('<tr><td><a href="%s/commit/%s">%s</a></td> '
                      '<td>%s</td> <td>%s</td></tr>'
                      % (imp_github, lg.githash, lg.githash[:10],
                         lg.author_email.split('@')[0], title))
            print('</table>')
            print('</div>')

    def print_misc_errors(self, build_info, lab_only):
        if build_info is None:
            return
        errs = build_info.get('misc_errors', [])
        if len(errs) == 0:
            return
        print('<div class="comperrors">')
        if lab_only:
            print('<h2>Miscellaneous log errors for lab-only components</h2>')
        else:
            print('<h2>Miscellaneous log errors</h2>')
        print('<ul class="comperrors">')
        for e in errs:
            self.print_misc_error(e, lab_only)
        print('</ul>')
        print('</div>')

    def get_raw_log_link(self, logfile, lab_only, caption=None,
                         remove_prefix=True, tags=''):
        """Get a link to a raw log file"""
        if remove_prefix:
            # Remove path prefix if any
            dest = logfile.split('/')[-1]
        else:
            dest = logfile
        if caption is None:
            caption = dest
        if lab_only:
            prefix = '/internal/imp/nightly/logs/'
        else:
            prefix = '%s/logs/%s/' % (self.nightly_url, self.branch)
        dest = prefix + get_date_link(self.date) + '/' + dest
        return '<a %shref="%s">%s</a>' % (tags, dest, caption)

    def get_raw_build_files_link(self, platname, lab_only, caption):
        """Get a link to the directory containing raw build files"""
        if lab_only:
            prefix = '/internal/imp/nightly/logs/'
        else:
            prefix = '%s/logs/%s/' % (self.nightly_url, self.branch)
        dest = prefix + get_date_link(self.date) + '/' + platname + '/'
        return '<a href="%s">%s</a>' % (dest, caption)

    def print_misc_error(self, err, lab_only):
        if err['type'] == 'unexplog':
            txt = ('Unexpected log file generated: '
                   + self.get_raw_log_link(err['log'], lab_only))
        elif err['type'] == 'misslog':
            txt = 'Expected log file not generated: ' + err['log']
        else:
            txt = (self.get_raw_log_link(err['log'], lab_only, err['type'])
                   + ': ' + err['text'])
        print('<li>%s</li>' % txt)

    def print_summary_table(self, summary, build_info, caption, show_failures):
        def get_row_header(component, component_id):
            special = SPECIAL_COMPONENTS.get(component, None)
            if special:
                return '<td class="comptype" title="%s"><b>%s</b></td>' \
                       % (special, component)
            else:
                return '<td class="comptype">%s</td>' \
                       % self.get_component_link(row, summary.unit_ids[row])
        print("<table class=\"modules\">")
        print('<caption>%s; '
              'mouseover or click for more details. %s</caption>'
              % (caption,
                 self.toggle_failmap(
                     show_failures,
                     "[show only failures]"
                     if show_failures else "[show all]")))
        print("<thead><tr><th></th>")
        for x in summary.all_archs:
            p = platforms_dict[x]
            if x in summary.cmake_archs:
                print('<th title="%s"><a href="%s">%s</a></th>'
                      % (p.long,
                         self.get_link(page='platform',
                                       platform=summary.arch_ids[x]),
                         p.short))
            else:
                print('<th title="%s"><a href="%s">%s</a></th>'
                      % (p.long,
                         self.get_link(page='log',
                                       platform=summary.arch_ids[x]),
                         p.short))
        if build_info[0]:
            print('<th title="Percentage of all executable lines of Python '
                  'code in this component that were executed by its '
                  'own regular (non-expensive) tests">Python coverage</th>')
            print('<th title="Percentage of all executable lines of C++ '
                  'code in this component that were executed by its own '
                  'regular (non-expensive) tests">C++ coverage</th>')
        print("</tr></thead><tbody>")
        if build_info[0]:
            coverage = {}
            for m in build_info[0]['modules']:
                coverage[m['name']] = (m['pycov'], m['cppcov'], False)
            if build_info[1]:
                for m in build_info[1]['modules']:
                    if 'pycov' in m:
                        coverage[m['name']] = (m['pycov'], m['cppcov'], True)
        for row in summary.all_units:
            unit_id = summary.unit_ids[row]
            print("<tr>" + get_row_header(row, unit_id))
            for col in summary.all_archs:
                print(self.format_build_summary(summary.data, row, col,
                                                summary.arch_ids[col],
                                                unit_id))
            if build_info[0]:
                if row.startswith('IMP.'):
                    subdir = row[4:]
                elif row == 'IMP':
                    subdir = 'kernel'
                else:
                    subdir = row
                cov = coverage.get(subdir, None)
                if cov:
                    for dir, key in (('python', 0), ('cpp', 1)):
                        if cov[key] is None:
                            print("<td></td>")
                        else:
                            print("<td>%s</td>"
                                  % get_coverage_link(self.date, dir, subdir,
                                                      cov[key], cov[2],
                                                      self.branch,
                                                      self.nightly_url))
            print("</tr>")
        print("</tbody></table>")

    def get_logfile(self, arch_name, lab_only):
        if lab_only and not self.lab_only:
            return None
        fname = platforms_dict[arch_name].logfile
        if lab_only:
            g = os.path.join(lab_only_topdir, get_date_link(self.date) + '-*',
                             'build', 'logs', 'imp-salilab', fname)
        else:
            g = os.path.join(get_topdir(self.branch),
                             get_date_link(self.date) + '-*', 'build',
                             'logs', 'imp', fname)
        g = glob.glob(g)
        if len(g) > 0:
            return g[0]

    def display_log(self):
        conn = connect_mysql()
        c = MySQLdb.cursors.DictCursor(conn)
        arch_name = self.get_platform_name_from_id(conn, self.platform)
        if not arch_name:
            print("<p><b>Invalid platform requested</b></p>")
            return
        logfile = self.get_logfile(arch_name, False)
        lab_only_logfile = self.get_logfile(arch_name, True)
        if logfile is None:
            print("<p><b>Sorry, logs for this date are no longer "
                  "available.</b></p>")
            return
        table = self.get_branch_table('imp_test_unit_result')
        query = ('SELECT imp_test_units.name as unit_name, '
                 'imp_test_units.lab_only, imp_test_unit_result.state, '
                 'imp_test_unit_result.logline from imp_test_units, '
                 + table + ' imp_test_unit_result '
                 'where imp_test_units.id=imp_test_unit_result.unit and '
                 'date=%s and imp_test_unit_result.arch=%s and '
                 'imp_test_unit_result.logline is not null '
                 + self.get_sql_lab_only()
                 + ' order by imp_test_unit_result.logline')
        print('<div class="loglinks">')
        print('<p>The build on %s gave the following errors on %s:</p>'
              % (self.date, platforms_dict[arch_name].long))
        print('<ul>')
        c.execute(query, (self.date, self.platform))
        rows = c.fetchall()
        loglines = []
        lab_only_loglines = []
        for r in rows:
            if not r['lab_only']:
                loglines.append(r['logline'])
                self.print_log_link(r, 'n')
        for r in rows:
            if r['lab_only']:
                lab_only_loglines.append(r['logline'])
                self.print_log_link(r, 'l')
        print('</ul>')
        print("<p>%s</p>" % self.get_raw_log_link(logfile, False,
                                                  "Download log file"))
        print("<p>%s</p>"
              % self.get_raw_build_files_link(arch_name, False,
                                              "View other build files"))

        if self.lab_only and lab_only_logfile:
            print("<p>%s</p>"
                  % self.get_raw_log_link(logfile, True,
                                          "Download log file (lab-only)"))
            print("<p>%s</p>"
                  % self.get_raw_build_files_link(
                      arch_name, True, "View other build files (lab-only)"))
        print('</div>')

        print('<div class="log">')
        self.print_log(logfile, loglines, 'n')
        if self.lab_only and lab_only_logfile:
            self.print_log(lab_only_logfile, lab_only_loglines, 'l')
        print('</div>')

    def print_log(self, logfile, loglines, prefix):
        build_complete = False

        def get_next_link():
            if len(loglines) > 0:
                return loglines.pop(0)
            else:
                return 0
        next_link = get_next_link()
        print("<pre>")
        for n, line in enumerate(open(logfile)):
            if 'BUILD COMPLETED' in line:
                build_complete = True
            if n + 1 == next_link:
                print('</pre>')
                print('<a name="%s_%d"></a><pre class="errorline">'
                      % (prefix, next_link))
                sys.stdout.write(html.escape(line))
                print("</pre><pre>")
                next_link = get_next_link()
            else:
                sys.stdout.write(html.escape(line))
        print("</pre>")
        if not build_complete:
            b = os.path.basename(logfile)
            if b.startswith('bin') or b.startswith('package') \
               or b.startswith('coverage'):
                print('<pre class="incomplete">...\n[ Build appears to '
                      'be incomplete ]</pre>')

    def print_log_link(self, sql, prefix):
        state_msg = {'TEST': 'test failure',
                     'BUILD': 'failed to build',
                     'BENCH': 'benchmark failure',
                     'DISABLED': 'disabled'}
        print('<li><a href="#%s_%d">%s %s</a></li>'
              % (prefix, sql['logline'], sql['unit_name'],
                 state_msg[sql['state']]))

    def display_tests(self, cur, include_component=True,
                      include_platform=True):
        print("<table class=\"sortable\">\n<thead>")
        print("<tr>")
        if include_component:
            print("<th>Component</th>")
        if include_platform:
            print("<th>Platform</th>")
        print('<th class="sorttable_nosort"><a title="Show/hide all output" '
              'onclick="toggle_all_detail(); return false;" '
              'id="dettog" class="dettog" href="#">[+]</a></th>')
        print('<th title="Name of the Python or C++ file containing test '
              'cases">Name</th>')
        print('<th title="Time (in seconds) that all tests in this file '
              'took to run">Runtime (s)</th>')
        print('<th title="OK: all tests ran successfully; FAIL: at least '
              'one test failed; SEGFAULT: the test program crashed with a '
              'segmentation fault; TIMEOUT: the test program ran out of '
              'time; SKIP: at least one test was deliberately skipped; '
              'EXPFAIL: at least one test failed, but the failure was '
              'expected; SKIP_EXPFAIL: this file contains both skipped '
              'tests and expected failures">State</th>')
        print('<th title="Difference between this test and the same test '
              'run in the previous build">Delta</th></tr>')
        print("<tbody>")
        for n, row in enumerate(cur):
            print("<tr>")
            if include_component:
                print("<td>%s</td>"
                      % self.get_component_link(row['unit_name'],
                                                row['unit_id']))
            if include_platform:
                print(get_platform_td(row['arch_name']))
            detail = row['detail']
            if detail is None or detail == '':
                detail = ''
                print("<td></td>")
            else:
                print('<td><a title="Show/hide output" '
                      'onclick="toggle_detail(%d); return false;" '
                      'id="dettog%d" class="dettog" '
                      'href="#">[+]</a></td>' % (n, n))
                detail = ' <div id="detail%d" class="detail">' \
                         '<pre>%s</pre></div>' % (n, html_escape(detail))
            testlink = self.get_link(page='results', test=row['name'],
                                     platform=row['arch'])
            test_name = row['test_name']
            if len(test_name) > 80:
                test_name = test_name[:80] + '[...]'

            print("<td><a href=\"%s\">%s</a>%s</td>"
                  % (testlink, test_name, detail))
            print("<td>%.2f</td> %s %s</tr>"
                  % (row['runtime'], get_state_td(row['state']),
                     get_delta_td(row['delta'])))
        print("</tbody>\n</table>")

    def get_contiguous_dates(self):
        """Get a contiguous set of dates either side of the current date.
           This assumes that builds run every day (develop branch)."""
        return [self.date - datetime.timedelta(days=1), self.date,
                self.date + datetime.timedelta(days=1)]

    def get_dates_from_db(self):
        """Get a set of dates either side of the current date.
           This queries the database, so days with no builds are skipped."""
        dates = []
        versions = []
        conn = connect_mysql()
        c = conn.cursor()
        table = self.get_branch_table('imp_test_reporev')
        if self.branch == 'main':
            to_select = 'date,version'
        else:
            to_select = 'date'
        prev = 'SELECT ' + to_select + ' FROM ' + table \
               + ' WHERE date<%s ORDER BY date DESC LIMIT 1'
        next = 'SELECT ' + to_select + ' FROM ' + table \
               + ' WHERE date>=%s ORDER BY date LIMIT 2'
        for q in (prev, next):
            c.execute(q, (self.date,))
            if self.branch == 'main':
                for row in c:
                    dates.append(row[0])
                    versions.append(row[1])
            else:
                for row in c:
                    dates.append(row[0])
                versions = [None] * len(dates)
        return dates, versions

    def display_date_navigation(self):
        print("<ul>")
        if self.branch == 'develop':
            dates = self.get_contiguous_dates()
            versions = [None] * len(dates)
        else:
            dates, versions = self.get_dates_from_db()
        if self.last_build_date not in dates:
            dates.append(self.last_build_date)
            versions.append(self.last_build_version)
        for date, version in zip(dates, versions):
            if date <= self.last_build_date:
                cls = ''
                if date == self.date:
                    cls = ' class="thispage"'
                if date == self.last_build_date:
                    txt = 'last build'
                else:
                    txt = str(date)
                if version:
                    txt += ' (%s)' % version
                print("<li%s><a href=\"%s\">%s</a></li> "
                      % (cls, self.get_link(date=date), txt))
        print("</ul>")

    def get_component_link(self, component, component_id):
        # Hack to map 'IMP' to kernel
        if component.startswith('IMP ') or component == 'IMP':
            component = ('IMP.kernel ' + component[4:]).rstrip()
        return '<a href="%s">%s</a>' \
               % (self.get_link(page='comp', component=component_id),
                  component)

    def get_arch_id_map(self, c):
        map = {}
        c.execute("SELECT * FROM imp_test_archs")
        for row in c:
            map[row['id']] = platforms_dict[row['name']]
        return map

    def display_test_runtime(self):
        print("<h1>Test runtime, %s</h1>" % self.get_build_id())
        conn = connect_mysql()
        table = self.get_branch_table('imp_test')
        query = ("SELECT imp_test_names.name AS test_name, imp_test.name, "
                 "imp_test_names.unit, imp_test_units.name AS unit_name "
                 "FROM " + table + " imp_test, imp_test_names, imp_test_units "
                 "WHERE imp_test.date=%s AND imp_test.name=%s AND "
                 "imp_test.name=imp_test_names.id AND "
                 "imp_test_names.unit=imp_test_units.id"
                 + self.get_sql_lab_only())
        c = MySQLdb.cursors.DictCursor(conn)
        c.execute(query, (self.date, self.test))
        row = c.fetchone()
        if row is None:
            print("<b>No results for this test on this date</b>")
            return
        print("<table><tbody>")
        print("<tr><td>Name</td> <td>%s</td></tr>" % row['test_name'])
        print("<tr><td>Component</td> <td>%s</td></tr>"
              % self.get_component_link(row['unit_name'], row['unit']))
        print("</tbody></table>")
        print("<p>Runtimes on each platform are shown for this test, "
              "for each instance where the test completed successfully.</p>")
        print("<p><i>Click and drag on the plot to zoom in; double click "
              "to reset the zoom.</i></p>")

        print("<p>Note that test runtimes are <b>not</b> reliable "
              "measurements of "
              "IMP's performance. For that, please see the "
              "<a href=\"%s\">benchmarks</a>.</p>"
              % self.get_link(page='bench'))
        print('<div id="runtime" class="benchmark"></div>')

        arch_id_map = self.get_arch_id_map(c)

        query = "SELECT runtime, date, arch FROM " + table \
                + " WHERE date<=%s AND name=%s AND state='OK' " \
                "ORDER BY arch, date"
        c.execute(query, (self.date, self.test))
        arch = None
        data = []
        arch_ids = []
        print("""<script type="text/javascript">
$(document).ready(function() {
  var plot = $.jqplot('runtime', [""")

        def print_series(d, suffix=''):
            print("[" + ",".join("['%s', %f]" % x for x in d) + "]" + suffix)
        for row in c:
            if arch != row['arch']:
                if arch is not None and data:
                    print_series(data, suffix=',')
                    arch_ids.append(arch)
                arch = row['arch']
                data = []
            data.append((row['date'], row['runtime']))
        if arch and data:
            print_series(data)
            arch_ids.append(arch)
        print("""],
 {
    series:[
%s
    ],
    legend: {show:true, location: 'sw'},
    axes: {
      xaxis: {
        renderer: $.jqplot.DateAxisRenderer,
        tickOptions: {formatString: '%%F', showGridline: false}
      },
      yaxis: {
        label: 'Runtime (s)',
        labelRenderer: $.jqplot.CanvasAxisLabelRenderer,
        tickOptions: { showGridline: false }
      }
    },
    highlighter: {
      show: true,
      sizeAdjust: 10
    },
    cursor: {
       show: true,
       zoom:true,
       showTooltip:true
    }
  });
});""" % ",\n".join("      {label: '%s'}" % arch_id_map[x].short
                    for x in arch_ids))

        print('</script>')

    def display_test(self):
        print("<h1>Test results, %s</h1>" % self.get_build_id())
        conn = connect_mysql()
        table = self.get_branch_table('imp_test')
        query = ("SELECT imp_test_names.name as test_name, imp_test.name, "
                 "imp_test_names.unit, imp_test.arch, imp_test_units.name "
                 "as unit_name, imp_test_archs.name as arch_name, "
                 "imp_test.runtime, imp_test.date, imp_test.state, "
                 "imp_test.detail from " + table
                 + " imp_test, imp_test_names, imp_test_units, imp_test_archs "
                 "where imp_test.date=%s and imp_test.name=%s and "
                 "imp_test.arch=%s and imp_test.name=imp_test_names.id and "
                 "imp_test_names.unit=imp_test_units.id and "
                 "imp_test.arch=imp_test_archs.id" + self.get_sql_lab_only())
        c = MySQLdb.cursors.DictCursor(conn)
        c.execute(query, (self.date, self.test, self.platform))
        row = c.fetchone()
        if row is None:
            print("<b>No results for this test on this date</b>")
            return
        print('<table class="testres"><tbody>')
        print("<tr><td>Name</td> <td>%s</td></tr>" % row['test_name'])
        print("<tr><td>State</td> %s</tr>" % get_state_td(row['state']))
        print("<tr><td>Detail</td> <td><pre>%s</pre></td></tr>"
              % html_escape(row['detail']))
        print("<tr><td>Component</td> <td>%s</td></tr>"
              % self.get_component_link(row['unit_name'], row['unit']))
        print("<tr><td>Platform</td> %s</tr>"
              % get_platform_td(row['arch_name']))
        print("<tr><td>Runtime (s)</td> <td>%.2f (<a title=\"Show a plot of "
              "runtimes for this test for every platform against date\" "
              "href=\"%s\">plot</a>)</td></tr>"
              % (row['runtime'], self.get_link(page='runtime')))
        print("<tr><td>Date</td> <td>%s</td></tr>" % row['date'])
        if row['state'] in OK_STATES:
            print("<tr><td>Previously failed on</td> <td>%s</td></tr>"
                  % self.get_previous_test_link(conn, self.test, self.platform,
                                                False))
        else:
            print("<tr><td>Previously passed on</td> <td>%s</td></tr>"
                  % self.get_previous_test_link(conn, self.test, self.platform,
                                                True))
        print("</tbody></table>")
        self.display_test_other_platforms(conn, self.test, self.platform)

    def display_test_other_platforms(self, conn, test, arch):
        print("<h2>Summary of results on all platforms</h2>")
        table = self.get_branch_table('imp_test')
        query = ("SELECT imp_test_archs.name as arch_name, imp_test.arch, "
                 "imp_test.runtime, imp_test.state from " + table
                 + " imp_test, imp_test_names, imp_test_units, imp_test_archs "
                 "where imp_test.date=%s and imp_test.name=%s and "
                 "imp_test.name=imp_test_names.id and "
                 "imp_test_names.unit=imp_test_units.id and "
                 "imp_test.arch=imp_test_archs.id" + self.get_sql_lab_only())
        c = MySQLdb.cursors.DictCursor(conn)
        c.execute(query, (self.date, test))
        print("<table class=\"sortable\"><thead><tr><th>Platform</th>")
        print("<th>State</th><th>Runtime (s)</th></tr></thead><tbody>")
        for row in c:
            link = self.get_link(page='results', test=test,
                                 platform=row['arch'])
            print("<tr>%s"
                  % get_platform_td(row['arch_name'],
                                    fmt="<a href=\"" + link + "\">%s</a>"))
            print("%s <td>%.2f</td></tr>"
                  % (get_state_td(row['state']), row['runtime']))
        print("</tbody></table>")

    def get_previous_test_link(self, conn, test, arch, previous_success):
        if previous_success:
            state_op = 'in'
        else:
            state_op = 'not in'
        table = self.get_branch_table('imp_test')
        query = "SELECT date from " + table + " where name=%s and arch=%s " \
                "and state " + state_op + " " + str(OK_STATES) \
                + " and date<%s order by date desc limit 1"
        c = MySQLdb.cursors.DictCursor(conn)
        c.execute(query, (test, arch, self.date))
        row = c.fetchone()
        if row:
            return "<a href=\"%s\">%s</a>" \
                   % (self.get_link(page='results', test=test, platform=arch,
                                    date=row['date']),
                      row['date'])
        else:
            return "never"

    def display_page(self):
        self.display_navigation()
        self.pages[self.page]()

    def display_branch_link(self):
        branch_links = [self.get_link(branch=x).replace('&amp;', '&')
                        for x in self.all_branches]
        print('<script type="text/javascript">')
        print('function change_branch()')
        print('{')
        print('var sel=document.getElementById("branchlist");')
        print('var branches=' + repr(branch_links) + ';')
        print('window.location.assign(branches[sel.selectedIndex]);')
        print('}')
        print('</script>')
        print('<div class="branchlink">')
        print('<select id="branchlist" onchange="change_branch()">')
        for branch in self.all_branches:
            if branch == self.branch:
                sel = ' selected="selected"'
            else:
                sel = ''
            print('<option%s>Branch: %s</option>' % (sel, branch))
        print('</select></div>')

    def display_lab_only_link(self):
        if self.branch != 'develop':
            return
        data = {False: (lab_only_results_url,
                        'Lab-only (auth required)',
                        'Also include results from building extra IMP '
                        'components that are developed within the Sali lab, '
                        'and not yet part of the public release. Requires '
                        'authentication with a Sali lab username '
                        'and password.'),
                True: (results_url,
                       'Public', 'Only show results for components that are '
                                 'included in the IMP public release.')}
        d = data[self.lab_only]
        print('<a class="labonly" title="%s" href="%s%s">%s</a>'
              % (d[2], d[0], self.get_link(), d[1]))
        if self.lab_only:
            print('<a class="nonimp" title="Show results for other lab '
                  'software, such as MODELLER (lab username and password '
                  'required)." href="https://salilab.org/internal/nightly/'
                  'tests.html">Non-IMP</a>')

    def display_navigation(self):
        print('<div class="implinks">')
        self.display_lab_only_link()
        print('  <ul>')
        links = []
        if self.page in ('results', 'runtime', 'log', 'comp', 'compplattest',
                         'benchfile', 'doc'):
            links.append(self.page)
        links.extend(('build', 'new', 'all', 'long', 'bench'))
        linktext = {'results': 'Test results',
                    'runtime': 'Test runtime',
                    'log': 'Log file',
                    'build': 'Build summary',
                    'compplattest': 'Component tests',
                    'comp': 'Component summary',
                    'new': 'New test failures',
                    'all': 'All test failures',
                    'long': 'Long-running tests',
                    'doc': 'Doc summary',
                    'benchfile': 'File benchmarks',
                    'platform': 'Platform',
                    'bench': 'Benchmarks'}
        for link in links:
            if link == self.page:
                cls = ' class="thispage"'
            else:
                cls = ''
            print('    <li%s><a href="%s">%s</a></li>'
                  % (cls, self.get_link(page=link), linktext[link]))
        print('    <li><a href="https://github.com/salilab/'
              'imp_nightly_builds/blob/main/www/index.py">'
              '<i class="fab fa-github"></i> Edit on GitHub</a></li>')
        print('  </ul>\n</div>')
        print("<div class=\"linkspacer\"></div>")
        print("<div class=\"implinks\">")
        self.display_branch_link()
        self.display_date_navigation()
        print("</div></div>")


def email_error(email_to, email_from, exc_info):
    import smtplib
    import email.utils
    from email.mime.text import MIMEText
    text = "".join(traceback.format_exception(*exc_info))
    msg = MIMEText(text)
    msg['Subject'] = 'Error in IMP nightly build results CGI script'
    msg['Date'] = email.utils.formatdate(localtime=True)
    msg['From'] = email_from
    msg['To'] = email_to
    s = smtplib.SMTP()
    s.connect()
    s.sendmail(email_from, [email_to], msg.as_string())
    s.close()


def main():
    t = TestPage()
    t.display()


if __name__ == '__main__':
    try:
        main()
    except:  # noqa: E722
        # Don't email if we're running from the command line (testing)
        if sys.argv[0].startswith('./'):
            raise
        else:
            email_error('ben@salilab.org', 'root@salilab.org', sys.exc_info())
            print(cgitb.reset())
            print("<p>Sorry, but an error was detected. We have been "
                  "notified of the problem and will fix it shortly.</p>")
