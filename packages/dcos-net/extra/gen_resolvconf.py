#!/opt/mesosphere/bin/python

import errno
import os
import random
import socket
import sys

import dns.query


# Constants
MAX_SERVER_COUNT = 3
NAME_SERVERS = ['198.51.100.1', '198.51.100.2', '198.51.100.3']


if len(sys.argv) != 2:
    print('Usage: gen_resolvconf.py RESOLV_CONF_PATH', file=sys.stderr)
    print('Received: {}'.format(sys.argv), file=sys.stderr)
    sys.exit(-1)
resolvconf_path = sys.argv[1]
dns_test_query = 'ready.spartan'
dns_timeout = 5


def check_server(addr):
    try:
        query = dns.message.make_query(dns_test_query, dns.rdatatype.ANY)
        result = dns.query.udp(query, addr, dns_timeout)
        if len(result.answer) == 0:
            print('Skipping DNS server {}: no records for {}'.format(
                addr, dns_test_query), file=sys.stderr)
        else:
            return True
    except socket.gaierror as ex:
        print(ex, file=sys.stderr)
    except dns.exception.Timeout:
        print('Skipping DNS server {}: no response'.format(
            addr), file=sys.stderr)
    except:
        print("Unexpected error querying DNS for server \"{}\" exception: {}".format(
            addr, sys.exc_info()[1]))

    return False


contents = """# Generated by gen_resolvconf.py. Do not edit.
# Change configuration options by changing DC/OS cluster configuration.
# This file must be overwritten regularly for proper cluster operation around
# master failure.

options timeout:1
options attempts:3

"""

if 'SEARCH' in os.environ:
    contents += "search {}\n".format(os.environ['SEARCH'])

# Check if dcos-net is up
dcos_nets_up = []
for ns in NAME_SERVERS:
    if check_server(ns):
        dcos_nets_up.append(ns)

if len(dcos_nets_up) > 0:
    for ns in dcos_nets_up:
        contents += "nameserver {}\n".format(ns)

# If dcos-net is not up, fall back, and insert the upstreams
else:
    fallback_servers = []

    # Resolvconf does not support custom ports, skip if not default
    for ns in os.environ['RESOLVERS'].split(','):
        if len(ns.strip()) == 0:
            continue
        ip, separator, port = ns.rpartition(':')
        if not separator:
            fallback_servers.append(ns)
            continue
        if port == "53":
            fallback_servers.append(ip)
            continue
        print('Skipping DNS server {}: non-default ports are not supported in /etc/resolv.conf'.format(
            ns), file=sys.stderr)

    random.shuffle(fallback_servers)
    for ns in fallback_servers[:MAX_SERVER_COUNT]:
        contents += "nameserver {}\n".format(ns)

# Don't change resolv.conf if it has the correct contents already. This is
# especially important in Docker enviroments where an atomic overwrite using
# `os.rename` is not possible (see below) and causes race conditions.
with open(resolvconf_path, 'r') as f:
    existing_contents = f.read()
    if existing_contents == contents:
        print("Not touching {} because it has proper contents.".format(resolvconf_path))
        sys.exit(0)

# Generate the resolv.conf config
print('Updating {}'.format(resolvconf_path))
with open(resolvconf_path + ".tmp", 'w') as f:
    print(contents, file=sys.stderr)
    f.write(contents)

# Move the temp file into place. This also takes care of
# making the file at resolvconf_path not a symlink if it
# was one (writing directly we would just update the
# target of the symlink). systemd-resolved updates the
# target of the symlink itself though, which results in fun
# conflicting things like https://dcosjira.atlassian.net/browse/DCOS-305

try:
    os.rename(resolvconf_path + ".tmp", resolvconf_path)
except OSError as e:
    # fall back to old behavior because resolv.conf in dcos-docker
    # is a mount point that doesn't like getting renamed
    if e.errno == errno.EBUSY:
        print('Falling back to writing directly due to EBUSY on rename')
        with open(resolvconf_path, 'w') as f:
            f.write(contents)
    else:
        raise

sys.exit(0)
