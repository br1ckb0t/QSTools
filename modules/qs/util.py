#!/Library/Frameworks/Python.framework/Versions/2.7/bin/python
"""Utility functions for inclusion in public QS package API"""

import json
import string
import random
import subprocess
import inspect
import sys


def dumps(arbitry_obj):
    return json.dumps(arbitry_obj, indent=4, sort_keys=True)


def pp(arbitry_obj):  # pragma: no cover
    """Like pprint.pprint"""
    print_break('-')
    print dumps(arbitry_obj) if arbitry_obj else str(arbitry_obj)
    print_break('-')


def print_break(break_str='*'):  # pragma: no cover
    """Print a break that's the width of the terminal for grouping output info.

    Args:
        break_str: the string to use in the break on repeat.
    """
    columns = float(subprocess.check_output(['stty', 'size']).split()[1])
    print
    print break_str * int(columns / len(break_str))
    print


def dict_list_to_dict(dict_list, id_key='id'):
    """Takes a list of dicts and flattens them to a single dict using the
    id_key for the keys in the flattened dict.
    """
    return {i[id_key]: i for i in dict_list}


def dict_to_dict_list(large_dict):
    """Takes a single dict and expands it out to a list of dicts."""
    return [v for k, v in large_dict.iteritems()]


def rand_str(size=6, chars=string.letters + string.digits):
    """http://stackoverflow.com/a/2257449/1628796"""
    return ''.join(random.choice(chars) for _ in range(size))


def merge(*args):
    """Returned merged version of indefinite number of dicts. Just like the
    builtin dict() method, args to right get precedent over args to the left.

    Example usage: qs.merge({1: 2}, {3: 4}).
    """
    merged = []
    for unmerged in args:
        for item in unmerged.items():
            merged.append(item)
    return dict(merged)


def running_from_test():
    """Tell whether the current script is being run from a test"""
    return 'nosetests' in sys.argv[0]


def clean_id(some_id, func_name=None):
    """Clean some_id to be used as a QS-generated id somewhere. Either returns
    a cleaned string (not int or unicode, etc), or throws an error.

    Args:
        func_name: the name of the function this is being called from/for,
            to be used in exception messages. Mainly there for clean_args()
    """
    if is_valid_id(some_id, func_name) is True:
        return str(some_id)


def is_valid_id(some_id, check_only=False, func_name=None):
    """Check if some_id is a valid id. If check_only is True, then no errors
    are thrown, just a silent check.
    """
    id_part = 'id {}'.format(some_id)
    try:
        if func_name:
            id_part += " for function '{}'".format(func_name)
        if not some_id and some_id != 0:
            raise ValueError('The {} must not be none'.format(id_part))
        elif type(some_id) is int or str(some_id) == some_id:
            return True
        else:
            raise TypeError('The {} must be a string or int'.format(id_part))
    except:
        if check_only:
            return False
        else:
            raise


def is_builtin(obj):
    """Determine if obj is a builtin, like a string or int"""
    builtins = [int, str, dict, list, set, float]
    return type(obj) in builtins


def make_id(*args):
    """Make an id based on arbitrary number of args. This id is in the format
    of: 'arg1:arg2:...:argn'. This is useful for when multiple values must
    be used to make a key unique.
    """
    if not all(str(i) == i or type(i) is int for i in args):
        raise TypeError(
            'All args in make_id must be string or ints. Actual values: '
            '{}'.format(args))
    return ':'.join(str(i) for i in args)


def sets_to_lists(list_of_dicts):
    """Convert all sets in the values in a list of dicts to lists. This is good
    when list_of_dicts will be JSON-serialized, since JSON doesn't take sets.
    """
    for original_dict in list_of_dicts:
        for key, val in original_dict.iteritems():
            if type(val) is set:
                original_dict[key] = list(val)


def format_phone(raw_phone):
    """Format a phone number, such as '1234567890' --> '(123) 456-7890'"""
    if not valid_us_phone(raw_phone): return raw_phone
    return '(%s%s%s) %s%s%s-%s%s%s%s' % tuple(digits(raw_phone))


def valid_us_phone(raw_phone):
    """Tell whether a phone number is a valid US phone number"""
    return raw_phone and len(digits(raw_phone)) == 10


def digits(string):
    """Return just the digits from string"""
    return ''.join([i for i in string if i.isdigit()])


def finance_to_float(finance):
    """Convert a finance number, such as '$100.07' to a float"""
    return float(''.join([i for i in finance if i in '-.0123456789']))

# ==============
# = Decorators =
# ==============


def clean_arg(func):
    """Clean the first argument of the decorated function. Useful if an ID is
    passed as the first arg.
    """
    def inner(*args, **kwargs):
        args = list(args)
        index = 0 if is_builtin(args[0]) else 1
        args[index] = clean_id(args[index])
        return func(*args, **kwargs)
    return inner

# TODO: implement clean_args for multiple args
