#!/usr/bin/env python3
"""Patch Ryu 4.34 for modern eventlet.

Ryu's ryu/app/wsgi.py does:

    class _AlreadyHandledResponse(Response):
        from eventlet.wsgi import ALREADY_HANDLED

eventlet removed ALREADY_HANDLED in 0.31, and eventlet <= 0.30.2 no longer
imports on Python 3.10.12+. Wrapping the import in try/except lets Ryu start
with a current eventlet. The constant is only used by Ryu's optional REST/WSGI
server, which this project does not use.

Safe to run more than once.
"""

import os
import sys

try:
    import ryu
except ImportError:
    sys.exit("Ryu is not installed - run this after installing it.")


def main():
    path = os.path.join(os.path.dirname(ryu.__file__), 'app', 'wsgi.py')
    with open(path, encoding='utf-8') as handle:
        source = handle.read()

    marker = 'except ImportError:  # removed in eventlet'
    if marker in source:
        print('ryu/app/wsgi.py already patched')
        return 0

    old = (
        '    # XXX: Eventlet API should not be used directly.\n'
        '    from eventlet.wsgi import ALREADY_HANDLED\n'
    )
    new = (
        '    # XXX: Eventlet API should not be used directly.\n'
        '    try:\n'
        '        from eventlet.wsgi import ALREADY_HANDLED\n'
        '    except ImportError:  # removed in eventlet >= 0.31\n'
        '        ALREADY_HANDLED = None\n'
    )

    if old not in source:
        sys.exit('Unexpected ryu/app/wsgi.py layout, cannot patch: %s' % path)

    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(source.replace(old, new))

    print('patched %s' % path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
