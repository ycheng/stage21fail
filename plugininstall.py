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


# sys.path.insert(0, '/usr/lib/ubiquity')
def query_recorded_installed():
    apt_installed = set()
    if os.path.exists("/var/lib/ubiquity/apt-installed"):
        with open("/var/lib/ubiquity/apt-installed") as record_file:
            for line in record_file:
                apt_installed.add(line.strip())
    return apt_installed


class InstallStepError(Exception):
    """Raised when an install step fails."""

    def __init__(self, message):
        Exception.__init__(self, message)

# TODO this can probably go away now.
def get_cache_pkg(cache, pkg):
    # work around broken has_key in python-apt 0.6.16
    try:
        return cache[pkg]
    except KeyError:
        return None

def broken_packages(cache):
    expect_count = cache._depcache.broken_count
    count = 0
    brokenpkgs = set()
    for pkg in cache.keys():
        try:
            if cache._depcache.is_inst_broken(cache._cache[pkg]):
                brokenpkgs.add(pkg)
                count += 1
        except KeyError:
            # Apparently sometimes the cache goes a bit bonkers ...
            continue
        if count >= expect_count:
            break
    return brokenpkgs

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
        filtered_extra_packages = query_recorded_installed()
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

            return # it throw exception in mark_install

def mark_install(cache, pkg):
    cachedpkg = get_cache_pkg(cache, pkg)
    if cachedpkg is None:
        return
    if not cachedpkg.is_installed or cachedpkg.is_upgradable:
        apt_error = False
        try:
            cachedpkg.mark_install()
        except SystemError as err:
            print("=== apt_error")
            print(err)
            apt_error = True
        print(pkg)
        # print("os.exit()")
        if cache._depcache.broken_count > 0 or apt_error:
            brokenpkgs = broken_packages(cache)
            while brokenpkgs:
                for brokenpkg in brokenpkgs:
                    get_cache_pkg(cache, brokenpkg).mark_keep()
                new_brokenpkgs = broken_packages(cache)
                if brokenpkgs == new_brokenpkgs:
                    break  # we can do nothing more
                brokenpkgs = new_brokenpkgs

            if cache._depcache.broken_count > 0:
                # We have a conflict we couldn't solve
                cache.clear()
                raise InstallStepError(
                    "Unable to install '%s' due to conflicts." % pkg)
    else:
        cachedpkg.mark_auto(False)


if __name__ == '__main__':
    os.environ['DPKG_UNTRANSLATED_MESSAGES'] = '1'
    if not os.path.exists('/var/lib/ubiquity'):
        os.makedirs('/var/lib/ubiquity')

    install = Install()
    # sys.excepthook = install_misc.excepthook
    # install.run()
    install.install_extras()
    sys.exit(0)

# vim:ai:et:sts=4:tw=80:sw=4:
