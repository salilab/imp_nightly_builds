#!/usr/bin/python3

import re
import sys
import subprocess


def rename_tables(lines, branch):
    create_table = re.compile(r'(CREATE TABLE `)(\w+)(` \(.*$)')
    tables = []
    for line in lines:
        m = create_table.match(line)
        if m:
            table = m.group(2) + '_' + branch
            tables.append(table)
            line = m.group(1) + table + m.group(3) + '\n'
        sys.stdout.write(line)
    for table in tables:
        print("GRANT SELECT ON `impusers`.`%s` TO 'imp_www'@'localhost';"
              % table)
        print("GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP ON "
              "`impusers`.`%s` TO 'impusers'@'localhost';" % table)


if len(sys.argv) != 2:
    print("Usage: %s branch" % sys.argv[0], file=sys.stderr)
    print("""
This script will dump out a set of MySQL commands to create the necessary
tables for a given IMP branch (it will prompt you for the MySQL root password).
It is suggested that you pipe the output to a file or directly to
mysql -u root -p impusers
""", file=sys.stderr)
    sys.exit(1)

branch = sys.argv[1]
p = subprocess.Popen(['mysqldump', '-d', 'impusers', '-u', 'root', '-p',
                      '--skip-add-drop-table', 'imp_test_unit_result',
                      'imp_test_reporev', 'imp_test_other_reporev',
                      'imp_benchmark', 'imp_build_summary', 'imp_test',
                      'imp_doc'],
                     universal_newlines=True,
                     stdout=subprocess.PIPE)
rename_tables(p.stdout, branch.replace('/', '_').replace('.', '_'))
