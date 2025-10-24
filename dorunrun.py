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
import enum
import math
import shlex
import subprocess
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


def dorunrun(command:Union[str, list],
    timeout:int=None,
    return_datatype:type=dict,
    OK_values:Iterable = (0,)) -> Union[str, bool, int, dict]:
    """
    A wrapper around (almost) all the complexities of running child
        processes.

    Parameters:
    -----------
    command: A string, or a list of strings,
             that constitute the commonsense definition of the command to be attemped.
    timeout: Generally, we don't
    return_datatype: This argument corresponds to the item the caller wants returned.
                     It can be one of these values:

        - bool : True if the subprocess exited with code 0.
        - int  : the exit code itself.
        - str  : the stdout of the child process.
        - dict : everything as a dict of key-value pairs.

        The default data type is dict
    OK_values: By default, OK means zero. However, the caller can supply a group
        of codes that are interpreted as being acceptable.

    ----------
    Returns: A value corresponding to the requested info.
    """

    # If return_datatype is not in the list, use dict. Note
    # that the next statement covers None, as well.
    return_datatype = dict if return_datatype not in (int, str, bool) else return_datatype

    # Let's convert all the arguments to str and relieve the caller
    # of that responsibility.
    if isinstance(command, (list, tuple)):
        command = [str(_) for _ in command]
        shell = False
    elif isinstance(command, str):
        command = shlex.split(command)
        shell = False
    else:
        raise Exception(f"Bad argument type to dorunrun: {command=}")

    try:
        result = subprocess.run(command,
            timeout=timeout,
            input="",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False)
        i_code = code = result.returncode
        b_code = code in OK_values
        s = result.stdout[:-1] if result.stdout.endswith('\n') else result.stdout
        e = result.stderr[:-1] if result.stderr.endswith('\n') else result.stderr

        if return_datatype is int:
            return i_code
        elif return_datatype is str:
            return s
        elif return_datatype is bool:
            return b_code
        else:
            return {"OK":b_code,
                    "code":i_code,
                    "name":ExitCode(i_code).name if i_code in ExitCode else f"EXIT_{i_code}",
                    "stdout":s,
                    "stderr":e}

    except subprocess.TimeoutExpired as e:
        return {"OK":False,
                "code":255,
                "name":ExitCode(255).name if 255 in ExitCode else "EXIT_255",
                "stdout":"",
                "stderr":""}

    except Exception as e:
        raise Exception(f"Unexpected error: {str(e)}")


class FakingIt(enum.EnumMeta):

    def __contains__(self, something:object) -> bool:
        """
        Normally ... the "in" operator checks if something is in
        an instance of the container. We want to check if a value
        is one of the IntEnum class's members.
        """
        try:
            self(something)
        except ValueError:
            return False

        return True


class ExitCode(enum.IntEnum, metaclass=FakingIt):
    """
    This is a comprehensive list of exit codes in Linux, and it
    includes four utility functions. Suppose x is an integer:

        x in ExitCode     # is x a valid value?
        x.OK              # Workaround: enums all evaluate to True, even if they are zero.
        x.is_signal       # True if the value is a "killed by Linux signal"
        x.signal          # Which signal, or zero.
    """
    @property
    def OK(self) -> bool:
        return self is ExitCode.SUCCESS

    @property
    def is_signal(self) -> bool:
        return ExitCode.KILLEDBYMAX > self > ExitCode.KILLEDBYSIGNAL

    @property
    def signal(self) -> int:
        return self % ExitCode.KILLEDBYSIGNAL if self.is_signal else 0


    # All was well.
    SUCCESS = os.EX_OK

    # It just did not work. No info provided.
    GENERAL = 1

    # BASH builtin error (e.g. basename)
    BUILTIN = 2

    # No device or address by that name was found.
    NODEVICE = 6

    # Trying to create a user or group that already exists.
    USERORGROUPEXISTS = 9

    # The execution requires sudo
    NOSUDO = 10

    ######
    # Code 64 is also the usage error, and the least number
    # that has reserved meanings, and nothing above here
    # should be used by a user program.
    ######
    BASEVALUE = 64
    # command line usage error
    USAGE = os.EX_USAGE
    # data format error
    DATAERR = os.EX_DATAERR
    # cannot open input
    NOINPUT = os.EX_NOINPUT
    # user name unknown
    NOUSER = os.EX_NOUSER
    # host name unknown
    NOHOST = os.EX_NOHOST
    # unavailable service or device
    UNAVAILABLE = os.EX_UNAVAILABLE
    # internal software error
    SOFTWARE = os.EX_SOFTWARE
    # system error
    OSERR = os.EX_OSERR
    # Cannot create an ordinary user file
    OSFILE = os.EX_OSFILE
    # Cannot create a critical file, or it is missing.
    CANTCREAT = os.EX_CANTCREAT
    # input/output error
    IOERR = os.EX_IOERR
    # retry-able error
    TEMPFAIL = os.EX_TEMPFAIL
    # remotely reported error in protocol
    PROTOCOL = os.EX_PROTOCOL
    # permission denied
    NOPERM = os.EX_NOPERM
    # configuration file error
    CONFIG = os.EX_CONFIG

    # The operation was run with a timeout, and it timed out.
    TIMEOUT = 124

    # The request to run with a timeout failed.
    TIMEOUTFAILED = 125

    # Tried to execute a non-executable file.
    NOTEXECUTABLE = 126

    # Command not found (in $PATH)
    NOSUCHCOMMAND = 127

    ###########
    # If $? > 128, then the process was killed by a signal.
    ###########
    KILLEDBYSIGNAL = 128

    # These are common enough to include in the list.
    KILLEDBYCTRLC = 130
    KILLEDBYKILL = 137
    KILLEDBYPIPE = 141
    KILLEDBYTERM = 143

    KILLEDBYMAX = 161

    # Nonsense argument to exit()
    OUTOFRANGE = 255

if __name__ == '__main__':

    here       = os.getcwd()
    progname   = os.path.basename(__file__)[:-3]
    configfile = f"{here}/{progname}.toml"
    logfile    = f"{here}/{progname}.log"
    lockfile   = f"{here}/{progname}.lock"

    parser = argparse.ArgumentParser(prog="dorunrun",
        description="What dorunrun does, dorunrun does best.")

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

