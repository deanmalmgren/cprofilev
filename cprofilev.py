#!/usr/bin/env python

import argparse
import bottle
import cProfile
import os
import pstats
import re
import sys
import threading

try:
    from cStringIO import StringIO
except ImportError:
    try:
        from StringIO import StringIO
    except ImportError:
        # Python 3 compatibility.
        from io import StringIO


VERSION = '1.0.7'

__doc__ = """\
An easier way to use cProfile.

Outputs a simpler html view of profiled stats.
Able to show stats while the code is still running!

"""


STATS_TEMPLATE = """\
<html>
    <head>
        <title>{{ title }} | cProfile Results</title>
        <link rel="stylesheet" type="text/css" href="https://cdnjs.cloudflare.com/ajax/libs/twitter-bootstrap/3.3.6/css/bootstrap.min.css">
        <link rel="stylesheet" type="text/css" href="https://cdnjs.cloudflare.com/ajax/libs/datatables/1.10.10/css/dataTables.bootstrap.min.css">
    </head>
    <body>
        <div class="container">
            <pre>{{ !stats_header }}</pre>
            <table class="table table-striped">{{ !stats_table }}</table>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/jquery/2.1.4/jquery.min.js"></script>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/twitter-bootstrap/3.3.6/js/bootstrap.min.js"></script>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/datatables/1.10.10/js/jquery.dataTables.min.js"></script>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/datatables/1.10.10/js/dataTables.bootstrap.min.js"></script>
            <script>
                $(document).ready(function(){
                    $('table').DataTable({
                        "order": [[3, "desc"]]
                    });
                });
            </script>

            % if callers:
                <h2>Called By:</h2>
                <pre>{{ !callers }}</pre>

            % if callees:
                <h2>Called:</h2>
                <pre>{{ !callees }}</pre>
        </div> <!-- .container -->
    </body>
</html>"""


SORT_KEY = 'sort'
FUNC_NAME_KEY = 'func_name'


class Stats(object):
    """Wrapper around pstats.Stats class."""

    IGNORE_FUNC_NAMES = ['function', '']

    STATS_LINE_REGEX = r'(.*)\((.*)\)$'
    HEADER_LINE_REGEX = r'ncalls|tottime|cumtime'

    def __init__(self, profile_output=None, profile_obj=None):
        self.profile = profile_output or profile_obj
        self.stream = StringIO()
        self.stats = pstats.Stats(self.profile, stream=self.stream)

    def read_stream(self):
        value = self.stream.getvalue()
        self.stream.seek(0)
        self.stream.truncate()
        return value

    def read(self):
        output = self.read_stream()
        lines = output.splitlines(True)
        return "".join(map(self.process_line, lines))

    @classmethod
    def process_line(cls, line):
        # Format stat lines (such that clicking on the function name drills into
        # the function call).
        match = re.search(cls.STATS_LINE_REGEX, line)
        if match:
            prefix = match.group(1)
            func_name = match.group(2)
            if func_name not in cls.IGNORE_FUNC_NAMES:
                url_link = bottle.template(
                    "<a href='{{ url }}'>{{ func_name }}</a>",
                    url=cls.get_updated_href(FUNC_NAME_KEY, func_name),
                    func_name=func_name)
                line = bottle.template(
                    "{{ prefix }}({{ !url_link }})\n",
                    prefix=prefix, url_link=url_link)
        return line

    @classmethod
    def get_updated_href(cls, key, val):
        href = '?'
        query = dict(bottle.request.query)
        query[key] = val
        for key in query.keys():
            href += '%s=%s&' % (key, query[key])
        return href[:-1]

    def show(self, restriction=''):
        self.stats.print_stats(restriction)
        return self

    def show_callers(self, func_name):
        self.stats.print_callers(func_name)
        return self

    def show_callees(self, func_name):
        self.stats.print_callees(func_name)
        return self

    def get_stats_header(self, stats_str):
        header = ''
        for line in stats_str.splitlines():
            if re.search(self.HEADER_LINE_REGEX, line):
                break
            header += line + '\n'
        return header

    def iter_stats_table_row(self, stats_str):
        # rows in the stats table are formatted in a really simple way. the
        # first 5 columns are separated by whitespace. the fifth column extends
        # to the end of the line
        in_table = False
        for line in stats_str.splitlines():
            if re.search(self.HEADER_LINE_REGEX, line):
                in_table = True
            cols = line.split()
            if in_table and cols:
                row = cols[:5] + [' '.join(cols[5:])]
                yield row

    def format_stats_table(self, stats_str):
        table_dom = []
        col_el = 'th'
        for row in self.iter_stats_table_row(stats_str):
            row_dom = '<tr>'
            for col in row:
                row_dom += '<%s>%s</%s>' % (col_el, col, col_el)
            row += '</tr>'
            col_el = 'td'
            table_dom.append(row_dom)
        table_dom[0] = '<thead>' + table_dom[0] + '</thead>'
        table_dom[1] = '<tbody>' + table_dom[1]
        table_dom[-1] = table_dom[-1] + '</tbody>'
        return '\n'.join(table_dom)

class CProfileV(object):
    def __init__(self, profile, title, address='127.0.0.1', port=4000):
        self.profile = profile
        self.title = title
        self.port = port
        self.address = address

        # Bottle webserver.
        self.app = bottle.Bottle()
        self.app.route('/')(self.route_handler)

    def route_handler(self):
        self.stats = Stats(self.profile)

        func_name = bottle.request.query.get(FUNC_NAME_KEY) or ''

        callers = self.stats.show_callers(func_name).read() if func_name else ''
        callees = self.stats.show_callees(func_name).read() if func_name else ''
        stats_str =  self.stats.show(func_name).read()
        data = {
            'title': self.title,
            'stats_header': self.stats.get_stats_header(stats_str),
            'stats_table': self.stats.format_stats_table(stats_str),
            'callers': callers,
            'callees': callees,
        }
        return bottle.template(STATS_TEMPLATE, **data)

    def start(self):
        self.app.run(host=self.address, port=self.port, quiet=True)


def main():
    parser = argparse.ArgumentParser(
        description='An easier way to use cProfile.',
        usage='%(prog)s [--version] [-a ADDRESS] [-p PORT] scriptfile [arg] ...',
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('-a', '--address', type=str, default='127.0.0.1',
        help='The address to listen on. (defaults to 127.0.0.1).')
    parser.add_argument('-p', '--port', type=int, default=4000,
        help='The port to listen on. (defaults to 4000).')
    # Preserve v0 functionality using a flag.
    parser.add_argument('-f', '--file', type=str,
        help='cProfile output to view.\nIf specified, the scriptfile provided will be ignored.')
    parser.add_argument('remainder', nargs=argparse.REMAINDER,
        help='The python script file to run and profile.',
        metavar="scriptfile")

    args = parser.parse_args()
    if not sys.argv[1:]:
        parser.print_help()
        sys.exit(2)

    info = '[cProfileV]: cProfile output available at http://%s:%s' % \
        (args.address, args.port)

    # v0 mode: Render profile output.
    if args.file:
        # Note: The info message is sent to stderr to keep stdout clean in case
        # the profiled script writes some output to stdout
        sys.stderr.write(info + "\n")
        cprofilev = CProfileV(args.file, title=args.file, address=args.address, port=args.port)
        cprofilev.start()
        return

    # v1 mode: Start script and render profile output.
    sys.argv[:] = args.remainder
    if len(args.remainder) < 0:
        parser.print_help()
        sys.exit(2)

    # Note: The info message is sent to stderr to keep stdout clean in case
    # the profiled script writes some output to stdout
    sys.stderr.write(info + "\n")
    profile = cProfile.Profile()
    progname = args.remainder[0]
    sys.path.insert(0, os.path.dirname(progname))
    with open(progname, 'rb') as fp:
        code = compile(fp.read(), progname, 'exec')
    globs = {
        '__file__': progname,
        '__name__': '__main__',
        '__package__': None,
    }

    # Start the given program in a separate thread.
    progthread = threading.Thread(target=profile.runctx, args=(code, globs, None))
    progthread.setDaemon(True)
    progthread.start()

    cprofilev = CProfileV(profile, title=progname, address=args.address, port=args.port)
    cprofilev.start()


if __name__ == '__main__':
    main()
