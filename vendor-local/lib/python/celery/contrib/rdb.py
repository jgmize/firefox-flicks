# -*- coding: utf-8 -*-
"""
celery.contrib.rdb
==================

Remote debugger for Celery tasks running in multiprocessing pool workers.
Inspired by http://snippets.dzone.com/posts/show/7248

**Usage**

.. code-block:: python

    from celery.contrib import rdb
    from celery import task

    @task()
    def add(x, y):
        result = x + y
        rdb.set_trace()
        return result


**Environment Variables**

.. envvar:: CELERY_RDB_HOST

    Hostname to bind to.  Default is '127.0.01', which means the socket
    will only be accessible from the local host.

.. envvar:: CELERY_RDB_PORT

    Base port to bind to.  Default is 6899.
    The debugger will try to find an available port starting from the
    base port.  The selected port will be logged by the worker.

"""
from __future__ import absolute_import
from __future__ import with_statement

import errno
import os
import socket
import sys

from pdb import Pdb

from billiard import current_process

from celery.platforms import ignore_errno

default_port = 6899

CELERY_RDB_HOST = os.environ.get('CELERY_RDB_HOST') or '127.0.0.1'
CELERY_RDB_PORT = int(os.environ.get('CELERY_RDB_PORT') or default_port)

#: Holds the currently active debugger.
_current = [None]

_frame = getattr(sys, '_getframe')


class Rdb(Pdb):
    me = 'Remote Debugger'
    _prev_outs = None
    _sock = None

    def __init__(self, host=CELERY_RDB_HOST, port=CELERY_RDB_PORT,
                 port_search_limit=100, port_skew=+0, out=sys.stdout):
        self.active = True
        self.out = out

        self._prev_handles = sys.stdin, sys.stdout

        self._sock, this_port = self.get_avail_port(
            host, port, port_search_limit, port_skew,
        )
        self._sock.listen(1)
        me = '%s:%s' % (self.me, this_port)
        context = self.context = {'me': me, 'host': host, 'port': this_port}
        self.say('%(me)s: Please telnet %(host)s %(port)s.'
                 '  Type `exit` in session to continue.' % context)
        self.say('%(me)s: Waiting for client...' % context)

        self._client, address = self._sock.accept()
        context['remote_addr'] = ':'.join(map(str, address))
        self.say('%(me)s: In session with %(remote_addr)s' % context)
        self._handle = sys.stdin = sys.stdout = self._client.makefile('rw')
        Pdb.__init__(self, completekey='tab',
                     stdin=self._handle, stdout=self._handle)

    def get_avail_port(self, host, port, search_limit=100, skew=+0):
        try:
            _, skew = current_process().name.split('-')
            skew = int(skew)
        except ValueError:
            pass
        this_port = None
        for i in xrange(search_limit):
            _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            this_port = port + skew + i
            try:
                _sock.bind((host, this_port))
            except socket.error, exc:
                if exc.errno in [errno.EADDRINUSE, errno.EINVAL]:
                    continue
                raise
            else:
                return _sock, this_port
        else:
            raise Exception(
                '%s: Could not find available port. Please set using '
                'environment variable CELERY_RDB_PORT' % (self.me, ))

    def say(self, m):
        self.out.write(m + '\n')

    def _close_session(self):
        self.stdin, self.stdout = sys.stdin, sys.stdout = self._prev_handles
        self._handle.close()
        self._client.close()
        self._sock.close()
        self.active = False
        self.say('%(me)s: Session %(remote_addr)s ended.' % self.context)

    def do_continue(self, arg):
        self._close_session()
        self.set_continue()
        return 1
    do_c = do_cont = do_continue

    def do_quit(self, arg):
        self._close_session()
        self.set_quit()
        return 1
    do_q = do_exit = do_quit

    def set_trace(self, frame=None):
        if frame is None:
            frame = _frame().f_back
        with ignore_errno(errno.ECONNRESET):
            Pdb.set_trace(self, frame)

    def set_quit(self):
        # this raises a BdbQuit exception that we are unable to catch.
        sys.settrace(None)


def debugger():
    """Returns the current debugger instance (if any),
    or creates a new one."""
    rdb = _current[0]
    if rdb is None or not rdb.active:
        rdb = _current[0] = Rdb()
    return rdb


def set_trace(frame=None):
    """Set breakpoint at current location, or a specified frame"""
    if frame is None:
        frame = _frame().f_back
    return debugger().set_trace(frame)
