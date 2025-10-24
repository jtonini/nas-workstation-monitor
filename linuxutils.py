# -*- coding: utf-8 -*-
import typing
from   typing import *

###
# Standard imports, starting with os and sys
###
min_py = (3, 9)
import os
import sys
if sys.version_info < min_py:
    print(f"This program requires Python {min_py[0]}.{min_py[1]}, or higher.")
    sys.exit(os.EX_SOFTWARE)

###
# Other standard distro imports
###
import argparse
from   collections.abc import *
import contextlib
import getpass
import logging

###
# Installed libraries like numpy, pandas, paramiko
###

###
# From hpclib
###
import linuxutils
from   urdecorators import trap
from   urlogger import URLogger

###
# imports and objects that were written for this project.
###
import atexit
import collections
import copy
from   ctypes import cdll, byref, create_string_buffer
import datetime
import dateutil
from   dateutil import parser
import enum
import fcntl
import glob
import grp
import inspect
import platform
import pwd
import re
import signal
import socket
import string
import subprocess
import threading
import time
import traceback
###
# Global objects
###
mynetid = getpass.getuser()
logger = None

###
# Credits
###
__author__ = 'George Flanagin'
__copyright__ = 'Copyright 2024, University of Richmond'
__credits__ = None
__version__ = 0.1
__maintainer__ = 'George Flanagin, Skyler He'
__email__ = 'gflanagin@richmond.edu, skyler.he@richmond.edu'
__status__ = 'in progress'
__license__ = 'MIT'

def bookmark() -> list:
    """
    Return a list of function calls that arrived at this
    one. If no information is available, return an empty
    list.

    bookmark()'s list does not include itself, therefore the
    range() statement starts at 1 rather than zero. Note that
    if you are printing the list, you probably don't care
    about the print() function, so you should

    print(bookmark()[1:])
    """

    stak = inspect.stack()
    return [ stak[i].function
        for i in range(1, len(stak))
        if stak[i].function not in ('wrapper', '<module>', '__call__') ]


byte_remap = {
    'PB':'P',
    'TB':'T',
    'GB':'G',
    'MB':'M',
    'KB':'K'
    }


byte_scaling = {
    'P':1024**5,
    'T':1024**4,
    'G':1024**3,
    'M':1024**2,
    'K':1024**1,
    'B':1024**0,
    'X':None
    }


def byte_scale(i:int, key:str='X') -> str:
    """
    i -- an integer to scale.
    key -- a character to use for scaling.
    """
    try:
        divisor = byte_scaling[key]
    except:
        return ""

    try:
        return f"{round(i/divisor, 3)}{key}"
    except:
        for k, v in byte_scaling.items():
            if i > v: return f"{round(i/v, 3)}{k}"
        else:
            # How did this happen?
            return f"Error: byte_scale({i}, {k})"

def bytes2human(n:int) -> str:
    """
    Convert a byte count to a human-readable format (e.g., KB, MB, GB).     Returns the formatted string.

    Examples:
        http://code.activestate.com/recipes/578019
        bytes2human(10000)
        '9.8K'
        bytes2human(100001221)
        '95.4M'
    """

    symbols = ('K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y')
    prefix = {}
    for i, s in enumerate(symbols):
        prefix[s] = 1 << (i + 1) * 10
    for s in reversed(symbols):
        if n >= prefix[s]:
            value = float(n) / prefix[s]
            return '%.1f%s' % (value, s)
    return "%sB" % n

def byte_size(s:str) -> int:
    """
    Takes a string like '20K' and changes it to 20*1024.
    Note that it accepts '20k' or '20K'
    """
    if not s: return 0

    # Take care of the case where it is KB rather than K, etc.
    if s[-2:] in byte_remap:
        s = s[:-2] + byte_remap[s[-2:]]

    try:
        multiplier = byte_scaling[s[-1].upper()]
        the_rest = int(s[:-1])
        return the_rest*multiplier
    except:
        return 0


###
# C
###

def coerce(s:str) -> Union[int, float, datetime.datetime, tuple, str]:
    """
    Examine a shred of str data, and see if we can make something
    more structured from it.
    """
    try:
        return int(s)
    except:
        pass

    try:
        return float(s)
    except:
        pass

    try:
        return parser.parse(s)
    except:
        pass

    if ',' in s:
        try:
            return tuple(coerce(part) for part in s.split(','))
        except:
            pass

    return s


def columns() -> int:
    """
    If we are in a console window, return the number of columns.
    Return zero if we cannot figure it out, or the request fails.
    """
    try:
        return int(subprocess.check_output(['tput','cols']).decode('utf-8').strip())
    except:
        return 0

###
# There is no standard way to do this, particularly with virtualization.
###
def cpucounter() -> int:
    """
    Return the number of CPU cores available on the current system,
    based on the operating system.
    """
    names = {
        'macOS': lambda : os.cpu_count(),
        'Linux': lambda : len(os.sched_getaffinity(0)),
        'Windows' : lambda : os.cpu_count()
        }
    return names[platform.platform().split('-')[0]]()


###
# D
###
def daemonize_me() -> bool:
    """
    Turn this program into a daemon, if it is not already one.
    """
    if os.getppid() == 1: return

    try:
        pid = os.fork()
        if pid: sys.exit(os.EX_OK)

    except OSError as e:
        print(f"Fork failed. {e.error} = {e.strerror}")
        sys.exit(os.EX_OSERR)

    os.chdir("/")
    os.setsid()
    os.umask(0)

    try:
        pid = os.fork()
        if pid:
            print(f"Daemon's PID is {pid}")
            sys.exit(os.EX_OK)

    except OSError as e:
        print(f"Second fork failed. {e.error} = {e.strerror}")
        sys.exit(os.EX_OSERR)

    else:
        return True


def dump_cmdline(args:argparse.ArgumentParser, return_it:bool=False, split_it:bool=False) -> str:
    """
    Print the command line arguments as they would have been if the user
    had specified every possible one (including optionals and defaults).
    """
    if not return_it: print("")
    opt_string = ""
    sep='\n' if split_it else ' '
    for _ in sorted(vars(args).items()):
        opt_string += f"{sep}--"+ _[0].replace("_","-") + " " + str(_[1])
    if not return_it: print(opt_string + "\n")

    return opt_string if return_it else ""


####
# E
####

def explain(code:int) -> str:
    """
    Lookup the os.EX_* codes.
    """
    codes = { _:getattr(os, _) for _ in dir(os) if _.startswith('EX_') }
    names = {v:k for k, v in codes.items()}
    return names.get(code, 'No explanation for {}'.format(code))


####
# F
####

####
# G
####

def getallgroups():
    """
    Yield the names of all groups available on the system
    """
    yield from ( _.gr_name for _ in grp.getgrall())


def getgroups(u:str) -> tuple:
    """
    Return a tuple of all the groups that "u" belongs to.
    """
    groups = [g.gr_name for g in grp.getgrall() if u in g.gr_mem]
    try:
        primary_group = pwd.getpwnam(u).pw_gid
    except KeyError as e:
        return tuple()

    groups.append(grp.getgrgid(primary_group).gr_name)
    return tuple(groups)


def getproctitle() -> str:
    """
    Retrieve the current process title.

    This function uses the libc `prctl` system call to fetch the title of the current process.
    The title is stored in a buffer, which is then decoded and returned as a UTF-8 string.

    If an error occurs during retrieval, an empty string is returned.
    """
    global libc
    try:
        buff = create_string_buffer(128)
        libc.prctl(16, byref(buff), 0, 0, 0)
        return buff.value.decode('utf-8')

    except Exception as e:
        return ""

default_group = 'people'
def getusers_in_group(g:str) -> tuple:
    """
    Linux's group registry does not know about the default group
    that is kept in LDAP.
    TODO: This function requires some cleanup before release.
    """

    global default_group
    try:
        return ( tuple(",".join(glob.glob('/home/*')).replace('/home/','').split(','))
            if g == default_group else
            tuple(grp.getgrnam(g).gr_mem) )
    except KeyError as e:
        return tuple()

def group_dicts() -> dict:
    """
    The dict will have both the names and the integer values as keys,
    so the lookup can proceed in either direction. IOW, the dict will
    contain both of these pairs:

        groups['gflanagi'] = 2032
        groups[2032] = 'gflanagi'

    """
    groups = {}
    for line in open('/etc/group').read().split():
        if line.startswith('#') or not line.strip():
            continue

        # Split the line into components: group_name:x:group_id:members
        parts = line.strip().split(':')
        if len(parts) >= 3:
            groups[parts[0]] = int(parts[2])
            groups[int(parts[2])] = parts[0]

    return groups


def group_exists(g:str) -> bool:
    """
    Check if a group with the given name exists on the system. Returns True if it exists, False otherwise.
    """
    try:
        grp.getgrnam(g)
        return True
    except KeyError as e:
        return False

####
# H
####

####
# I
####

def iso_time(seconds:int) -> str:
    """
    Convert a time in seconds since the epoch to an ISO-formatted string (e.g., 'YYYY-MM-DD HH:MM').
    """

    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(seconds))


def iso_seconds(timestring:str) -> int:
    """
    Convert an ISO-formatted time string to seconds since the epoch
    """

    dt = datetime.datetime.strptime(timestring, '%Y-%m-%dT%H:%M')
    return dt.strftime("%s")

###
# L
###
class LockFile:
    """
    Simple class using a context manager to provide a semaphore
    locking strategy.

    Usage:

    try:
        with LockFile(lockfile_name) as lock:
            blah blah blah
    except:
        print(f"Already locked by {int(lock)}")

    """

    def __init__(self, lockfile_name:str):
        self.lockfile_name = lockfile_name
        self.lockfile = None


    def __enter__(self):
        self.lockfile = open(self.lockfile_name, 'w')
        try:
            fcntl.flock(self.lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.lockfile.write(str(os.getpid()))
            self.lockfile.flush()

        except (BlockingIOError, IOError):
            self.lockfile.close()
            raise RuntimeError("Another instance is already running.")

        return self

    def __exit__(self, exception_type:type, exception_value:object, traceback:object) -> bool:
        try:
            fcntl.flock(self.lockfile, fcntl.LOCK_UN)
            self.lockfile.close()

        finally:
            os.unlink(self.lockfile_name)


    def __int__(self) -> int:
        try:
            self.lockfile = open(self.lockfile_name)
            the_pid = int(self.lockfile.read().strip())
            self.lockfile.close()
            return the_pid

        except:
            # This really should not happen ...
            return -1



####
# M
####

def memavail() -> float:
    """
    Return a fraction representing the available memory to run
    new processes.
    """
    with open('/proc/meminfo') as m:
        info = [ _.split() for _ in m.read().split('\n') ]
    return float(info[2][1])/float(info[0][1])


def mygroups() -> Tuple[str]:
    """
    Collect the group information for the current user, including
    the self associated group, if any.
    """
    return getgroups(getpass.getuser())


####
# N
####
def next_uid() -> int:
    existing_uids = {entry.pw_uid for entry in pwd.getpwall()}

    min_uid = None
    with open('/etc/login.defs', 'r') as f:
        for line in f:
            if line.startswith('UID_MIN'):
                min_uid = int(line.split()[1])
                break

    if min_uid is None:
        # Default minimum UID for regular users if not found in login.defs
        min_uid = 1000

    # Find the next available UID starting from min_uid
    next_uid = min_uid
    while next_uid in existing_uids:
        next_uid += 1

    return next_uid


def now_as_seconds() -> int:
    """
    Return the current time as seconds since the epoch using a high-resolution clock.
    """

    return time.clock_gettime(0)


def now_as_string(replacement:str=' ') -> str:
    """ Return full timestamp for printing. """
    return datetime.datetime.now().isoformat()[:21].replace('T',replacement)


####
# P
####

def parse_proc(pid:int) -> dict:
    """
    Parse the proc file for a given PID and return the values
    as a dict with keys set to lower without the "vm" in front,
    and the values converted to ints.
    """
    try:
        with open(f'/proc/{pid}/status', 'r') as f:
            rows = f.read().splitlines()
    except (FileNotFoundError, PermissionError):
        return None

    if not rows: return None

    interesting_keys = ['VmSize', 'VmLck', 'VmHWM', 'VmRSS',
                        'VmData', 'VmStk', 'VmExe', 'VmSwap' ]

    kv = {k.lower()[2:]: int(v.split()[0])
          for row in rows
          if ":" in row
          for k, v in [row.split(":", 1)]
          if k in interesting_keys}
    return kv


def pids_of(process_name:str, anywhere:Any=None) -> list:
    """
    Canøe is likely to have more than one background process running,
    and we will only know the first bit of the name, i.e., "canoed".
    This function gets a list of matching process IDs.

    process_name -- a text shred containing the bit you want
        to find.

    anywhere -- unused argument, maintained for backward compatibility.

    returns -- a possibly empty list of ints containing the pids
        whose names match the text shred.
    """
    if anywhere:
        # Match process name anywhere in the command line
        cmd = f'pgrep -f {process_name}'
    else:
        # Match exact process name
        cmd = f'pgrep {process_name}'

    # Execute the command
    results = subprocess.run(cmd, stdout=subprocess.PIPE)

    return [int(_) for _ in results.stdout.decode('utf-8').split('\n') if _ ]


####
# S
####

def script_driven() -> bool:
    """
    returns True if the input is piped or coming from an IO redirect.
    """

    mode = os.fstat(0).st_mode
    return True if stat.S_ISFIFO(mode) or stat.S_ISREG(mode) else False

def setproctitle(s:str) -> str:
    """
    Change the name of the current process, and return the previous
    name for the convenience of setting it back the way it was.
    """
    global libc
    old_name = getproctitle()
    if libc is not None:
        try:
            buff = create_string_buffer(len(s)+1)
            buff.value = s.encode('utf-8')
            libc.prctl(15, byref(buff), 0, 0, 0)

        except Exception as e:
            print(f"Process name not changed: {str(e)}")

    return old_name.encode('utf-8')


def signal_name(i:int) -> str:
    """
    Improve readability of signal processing.
    """
    try:
        return f"{signal.Signals(i).name} ({signal.strsignal(i)})"
    except:
        return f"unnamed signal {i}"

def snooze(n: int, num_retries: int = 10, delay: float = 10, scaling: float = 1.2) -> float:
    """
    Calculate the delay. The formula is arbitrary, and can
    be changed.

    n -- how many times we have tried so far.

    returns -- a number of seconds to delay
    """
    for attempt in range(n, num_retries):
        nap = delay * (scaling ** attempt)
        print(f'Waiting {nap:.2f} seconds to try again.')
        time.sleep(nap)
        yield nap


def splitter(group:Iterable, num_chunks:int) -> Iterator:
    """
    Generator to divide a collection into num_chunks pieces.
    It works with str, tuple, list, and dict, and the return
    value is of the same type as the first argument.

    group      -- str, tuple, list, or dict.
    num_chunks -- how many pieces you want to have.

    Use:
        for chunk in splitter(group, num_chunks):
            ... do something with chunk ...
    """

    quotient, remainder = divmod(min(len(group), num_chunks), num_chunks)
    is_dict = isinstance(group, dict)
    if is_dict:
        group = tuple(group.items())

    for i in range(num_chunks):
        lower = i*quotient + min(i, remainder)
        upper = (i+1)*quotient + min(i+1, remainder)
        slice_ = group[lower:upper]

        yield dict(slice_) if is_dict else type(group)(slice_)


def squeal(s: str=None, rectus: bool=True, source=None) -> str:
    """ The safety goat will appear when there is trouble. """
    tombstone(str)
    return

    for raster in goat:
        if not rectus:
            print(raster.replace(RED, "").replace(LIGHT_BLUE, "").replace(REVERT, ""))
        else:
            print(raster)

    if s:
        postfix = " from " + source if source else ''
        s = (now_as_string() +
             " Eeeek! It is my job to give you the following urgent message" + postfix + ": \n\n<<< " +
            str(s) + " >>>\n")
    tombstone(s)
    return s


class Stopwatch:
    """
    Note that the laps are an OrderedDict, so you can name them
    as you like, and they will still be regurgitated in order
    later on.
    """
    conversions = {
        "minutes":(1/60),
        "seconds":1,
        "tenths":10,
        "deci":10,
        "centi":100,
        "hundredths":100,
        "milli":1000,
        "micro":1000000
        }

    def __init__(self, *, units:Any='milli'):
        """
        Build the Stopwatch object, and click the start button. For ease of
        use, you can use the text literals 'seconds', 'tenths', 'hundredths',
        'milli', 'micro', 'deci', 'centi' or any integer as the units.

        'minutes' is also provided if you think this is going to take a while.

        The default is milliseconds, which makes a certain utilitarian sense.
        """
        try:
            self.units = units if isinstance(units, int) else Stopwatch.conversions[units]
        except:
            self.units = 1000
        self.laps = collections.OrderedDict()
        self.laps['start'] = time.time()


    def start(self) -> float:
        """
        For convenience, in case you want to print the time when
        you started.

        returns -- the time you began.
        """

        return self.laps['start']


    def lap(self, event:object=None) -> float:
        """
        Click the lap button. If you do not supply a name, then we
        call this event 'start+n", where n is the number of events
        already recorded including start.

        returns -- the time you clicked the lap counter.
        """
        if event:
            self.laps[event] = time.time()
        else:
            event = 'start+{}'.format(len(self.laps))
            self.laps[event] = time.time()

        return self.laps[event]


    def stop(self) -> float:
        """
        This function is a little different than the others, because
        it is here that we apply the scaling factor, and calc the
        differences between our laps and the start.

        returns -- the time you declared stop.
        """
        return_value = self.laps['stop'] = time.time()
        diff = self.laps['start']
        for k in self.laps:
            self.laps[k] -= diff
            self.laps[k] *= self.units

        return return_value


    def __str__(self) -> str:
        """
        Facilitate printing nicely.

        returns -- a nicely formatted list of events and time
            offsets from the beginning:

        Units are in sec/1000
        ------------------
        start     :  0.000000
        lap one   :  10191.912651
        start+2   :  15940.931320
        last lap  :  27337.829828
        stop      :  31454.867363

        """
        # w is the length of the longest event name.
        w = max(len(k) for k in self.laps)

        # A clever print statement is required.
        s = "{:" + "<{}".format(w) + "}  : {: f}"
        header = "Units are in sec/{}".format(self.units) + "\n" + "-"*(w+20) + "\n"

        return header + "\n".join([ s.format(k, self.laps[k]) for k in self.laps ])


####
# T
####

####
# U
####
def unwhite(s: str) -> str:
    """ Remove all non-print chars from string. """
    t = []
    for c in s.strip():
        if c in string.printable:
            t.append(c)
    return ''.join(t)


def user_from_uid(uid:int) -> str:
    return dorunrun("id -nu {uid}", return_datatype=str)


####
# V
####
def version(full:bool = True) -> str:
    """
    Do our best to determine the git commit ID ....
    """
    try:
        v = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            universal_newlines=True
            ).strip()
        if not full: return v
    except:
        v = 'unknown'
    else:
        mods = subprocess.check_output(
            ["git", "status", "--short"],
            universal_newlines=True
            )
        if mods.strip() != mods:
            v += (", with these files modified: \n" + str(mods))
    finally:
        return v


####
# W X Y Z
####


if __name__ == '__main__':

    here       = os.getcwd()
    progname   = os.path.basename(__file__)[:-3]
    configfile = f"{here}/{progname}.toml"
    logfile    = f"{here}/{progname}.log"
    lockfile   = f"{here}/{progname}.lock"

    parser = argparse.ArgumentParser(prog="linuxutils",
        description="What linuxutils does, linuxutils does best.")

    parser.add_argument('--loglevel', type=int,
        choices=range(logging.FATAL, logging.NOTSET, -10),
        default=logging.DEBUG,
        help=f"Logging level, defaults to {logging.DEBUG}")

    parser.add_argument('-o', '--output', type=str, default="",
        help="Output file name")

    parser.add_argument('-z', '--zap', action='store_true',
        help="Remove old log file and create a new one.")

    myargs = parser.parse_args()
    logger = URLogger(logfile=logfile, level=myargs.loglevel)

    try:
        outfile = sys.stdout if not myargs.output else open(myargs.output, 'w')
        with contextlib.redirect_stdout(outfile):
            sys.exit(globals()[f"{progname}_main"](myargs))

    except Exception as e:
        print(f"Escaped or re-raised exception: {e}")

