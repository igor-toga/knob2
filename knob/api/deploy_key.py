#!/usr/bin/python

######################################################################
# ssh-deploy-key is a tool to rapidly push out ssh key files
# to one or more remote hosts.
#######################################################################

# Copyright (C) 2014, Travis Bear
# All rights reserved.
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
import os
import socket
import sys
from threading import Thread

# conditional imports
try:
    from queue import Queue
except ImportError:
    from Queue import Queue
try:
    import paramiko
except ImportError:
    print ("FATAL: paramiko libraries not present.")
    print ("run 'pip install paramiko' to fix")
    sys.exit(1)


EXIT_COMMAND = "exit"
SMART_REMOVE_SCRIPT = "ssh-deploy-key.smart-remove.sh"
SMART_APPEND_SCRIPT = "ssh-delpoy-key.smart-append.sh"
MAX_HOST_WIDTH = 75

# status constants
AUTH_FAILURE = "AUTHENTICATION FAILURE"
APPENDED = "APPENDED"
REMOVED = "REMOVED"
CONNECTION_FAILURE = "CONNECTION FAILURE"
GENERAL_FAILURE = "GENERAL FAILURE"
IO_FAILURE = "LOCAL IO FAILURE"
NO_ACTION = "NO ACTION"
SCRIPT_FAILURE = "SCRIPT FAILURE"
SSH_FAILURE = "SSH FAILURE"
SUCCESS = "SUCCESS"
UNKNOWN_ERROR = "UNKNOWN ERROR"

# key constants
SSH_DIR = "~/.ssh"
AUTHORIZED_KEYS = "authorized_keys"
SSH_PORT = 22
TIMEOUT_SECONDS = 3

######################################################################
# Deployer thread
######################################################################
class DeployKeyThread(Thread):
    """
    Consumer thread.  Reads hosts from the queue and deploys the
    key to them.
    """

    def __init__(self, _config, queue):
        Thread.__init__(self)
        self.config = _config
        self.queue = queue

    def _print_status(self, server, username, statuz):
        prefix = "  copying key to %s@%s:%s/%s " % (
            username,
            server,
            SSH_DIR,
            AUTHORIZED_KEYS)
        suffix = "%s" % (statuz)
        print(prefix[:MAX_HOST_WIDTH].ljust(MAX_HOST_WIDTH, ' ') + " " + suffix)

    def _deploy_key(self, server, username):
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh_client.connect(
                server,
                username=username,
                key_filename=self.config['private_key_file'],
                port=SSH_PORT,
                timeout=TIMEOUT_SECONDS)
            sftp_client = paramiko.SFTPClient.from_transport(ssh_client.get_transport())
        except socket.error:
            return CONNECTION_FAILURE
        except paramiko.AuthenticationException:
            return AUTH_FAILURE
        except paramiko.SSHException: # TODO: retry this type of failure?
            return SSH_FAILURE
        script = SMART_REMOVE_SCRIPT
        if 'append' in self.config:
            script = SMART_APPEND_SCRIPT
        try:
            sftp_client.put(script, script)
        except IOError:
            return IO_FAILURE
        _, stdout, stderr = ssh_client.exec_command('/bin/sh %s' % script)
        if not stdout.channel.recv_exit_status() == 0:
            print (not stdout.channel.recv_exit_status())
            print ("out: %s\n err: %s\n" %(stdout.read().strip(), stderr.read().strip()))
            return UNKNOWN_ERROR
        sftp_client.remove(script)
        return stdout.read().strip()

    def run(self):
        while True:
            line = self.queue.get()
            # support either "host" or "user@host" formats
            words = line.split("@")
            username = self.config['username']
            server = words[0]
            if len(words) > 1:
                username = words[0]
                server = words[1]
            try:
                statuz = self._deploy_key(server, username)
            except:
                statuz = GENERAL_FAILURE
                # TODO: log a stack trace
            self._print_status(server, username, statuz)
            self.queue.task_done()



######################################################################
# Setup
######################################################################
def setup(config):
    """
    Creates the installer scripts that will run on the
    remote host(s)
    """
    key = config['key']
    
    smart_append_logic = """
    # smart append
    mkdir -p %s
    chmod 700 %s
    if grep "%s" %s/%s > /dev/null 2>&1
    then
      echo "%s"
    else
      echo "%s" >> %s/%s
      echo "%s"
      chmod 600 %s/%s
    fi
    """ % (
        SSH_DIR,
        SSH_DIR,
        key, SSH_DIR, AUTHORIZED_KEYS,
        NO_ACTION,
        key, SSH_DIR, AUTHORIZED_KEYS,
        APPENDED,
        SSH_DIR, AUTHORIZED_KEYS)
    stream = open(SMART_APPEND_SCRIPT, 'w')
    stream.write(smart_append_logic)
    stream.close()

    smart_remove_logic = """
    # smart remove mode
    grep -E "%s" > /tmp/keys
    mv /tmp/keys %s/%s
    chmod 600 %s/%s
    echo %s
    """ % (
        key, SSH_DIR, AUTHORIZED_KEYS,
        SSH_DIR, AUTHORIZED_KEYS,
        REMOVED)
    stream = open(SMART_REMOVE_SCRIPT, 'w')
    stream.write(smart_remove_logic)
    stream.close()


######################################################################
# Teardown
######################################################################
def cleanup():
    os.remove(SMART_REMOVE_SCRIPT)
    os.remove(SMART_APPEND_SCRIPT)


######################################################################
# Main flow begins here
######################################################################
def deploy_key(config):
    setup()
    queue = Queue(maxsize=10)

    if not config['private_key_file']:
        print 'Cant continue without private file'
        exit
    
    #print "Starting thread %d" % i
    deployer_thread = DeployKeyThread(config, queue)
    deployer_thread.daemon = True
    deployer_thread.start()
    
    if 'append' in config:
        print ("Distributing key to remote hosts in smart-append mode.")
    else:
        print ("Removing key  from remote hosts in smart-remove mode.")
    
    # Either use the hosts supplied on the command line (the preference) or use hosts read from
    # standard in.
    queue.put(config['host'])
    
    queue.join()
    cleanup()

