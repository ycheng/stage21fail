#!/usr/bin/python3

from __future__ import print_function

import gzip
import io
import itertools
import os
import platform
import pwd
import re
import shutil
import stat
import subprocess
import sys
import syslog
import textwrap
import traceback

import apt_pkg
from apt.cache import Cache, FetchFailedException
import debconf

import install_misc

# sys.path.insert(0, '/usr/lib/ubiquity')

class Install():
    def __init__(self):
        self.target = "/target"
        pass

    def install_extras(self):
        """Try to install packages requested by installer components."""
        # We only ever install these packages from the CD.
        sources_list = '/target/etc/apt/sources.list'
        os.rename(sources_list, "%s.apt-setup" % sources_list)
        with open("%s.apt-setup" % sources_list) as old_sources:
            with open(sources_list, 'w') as new_sources:
                found_cdrom = False
                for line in old_sources:
                    if 'cdrom:' in line:
                        print(line, end="", file=new_sources)
                        found_cdrom = True
        if not found_cdrom:
            os.rename("%s.apt-setup" % sources_list, sources_list)

        # this will install free & non-free things, but not things
        # that have multiarch Depends or Recommends. Instead, those
        # will be installed by install_restricted_extras() later
        # because this function runs before i386 foreign arch is
        # enabled
        cache = Cache()
        filtered_extra_packages = install_misc.query_recorded_installed()
        for package in filtered_extra_packages.copy():
            pkg = cache.get(package)
            if not pkg:
                continue
            candidate = pkg.candidate
            dependencies = candidate.dependencies + candidate.recommends
            all_deps = itertools.chain.from_iterable(dependencies)
            for dep in all_deps:
                if ':' in dep.name:
                    filtered_extra_packages.remove(package)
                    break

        self.do_install(filtered_extra_packages)

        if found_cdrom:
            os.rename("%s.apt-setup" % sources_list, sources_list)

        # TODO cjwatson 2007-08-09: python reimplementation of
        # oem-config/finish-install.d/07oem-config-user. This really needs
        # to die in a great big chemical fire and call the same shell script
        # instead.

    def do_install(self, to_install, langpacks=False):
        #self.nested_progress_start()

        with Cache() as cache:

            if cache._depcache.broken_count > 0:
                print(
                    'not installing additional packages, since there are'
                    ' broken packages: %s' % ', '.join(broken_packages(cache)))
                return

            with cache.actiongroup():
                for pkg in to_install:
                    mark_install(cache, pkg)


            chroot_setup(self.target)
            commit_error = None
            try:
                try:
                    if not self.commit_with_verify(
                            cache, fetchprogress, installprogress):
                        fetchprogress.stop()
                        installprogress.finish_update()
                        self.db.progress('STOP')
                        self.nested_progress_end()
                        return
                except IOError:
                    for line in traceback.format_exc().split('\n'):
                        syslog.syslog(syslog.LOG_ERR, line)
                    fetchprogress.stop()
                    installprogress.finish_update()
                    self.db.progress('STOP')
                    self.nested_progress_end()
                    return
                except SystemError as e:
                    for line in traceback.format_exc().split('\n'):
                        syslog.syslog(syslog.LOG_ERR, line)
                    commit_error = str(e)
            finally:
                chroot_cleanup(self.target)
            self.db.progress('SET', 10)

            cache.open(None)
            if commit_error or cache._depcache.broken_count > 0:
                if commit_error is None:
                    commit_error = ''
                brokenpkgs = broken_packages(cache)
                self.warn_broken_packages(brokenpkgs, commit_error)

            self.db.progress('STOP')

            self.nested_progress_end()


if __name__ == '__main__':
    os.environ['DPKG_UNTRANSLATED_MESSAGES'] = '1'
    if not os.path.exists('/tmp/ubiquity'):
        os.makedirs('/tmp/ubiquity')

    install = Install()
    # sys.excepthook = install_misc.excepthook
    # install.run()
    install.install_extras()
    sys.exit(0)

# vim:ai:et:sts=4:tw=80:sw=4:
