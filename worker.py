#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Coalition worker.
"""

import socket, time, subprocess, thread, getopt, sys, os, base64, signal, string, re, platform, ConfigParser, httplib, urllib, datetime, threading
import random
from sys import modules
from os.path import splitext, abspath

import host_cpu, host_mem

if sys.platform == "win32":
    import _winreg
    import win32serviceutil
    import win32service
    import win32event
    import win32api

# Options
global serverUrl, debug, verbose, sleepTime, broadcastPort, gogogo, workers
debug = False
verbose = False
affinity = ""

name = socket.gethostname()

broadcastPort = 19211
gogogo = True
serverUrl = ""
workers = 1
cpus = None
startup = ""
service = __name__ != "__main__" and sys.platform == "win32"
install = False
Headers = {"Content-type": "application/x-www-form-urlencoded", "Accept": "text/plain"}
Event = threading.Event()

# Go to the script directory
global coalitionDir
if sys.platform == "win32":
    import _winreg

    # under windows, uses the registry setup by the installer
    try:
        hKey = _winreg.OpenKey(
            _winreg.HKEY_LOCAL_MACHINE,
            "SOFTWARE\\Mercenaries Engineering\\Coalition",
            0,
            _winreg.KEY_READ,
        )
        coalitionDir, type = _winreg.QueryValueEx(hKey, "Installdir")
    except OSError:
        coalitionDir = "."
else:
    coalitionDir = "."
os.chdir(coalitionDir)

# Read the config file
config = ConfigParser.SafeConfigParser()
config.read("coalition.ini")


def cfgInt(name, defvalue):
    global config
    if config.has_option("worker", name):
        try:
            return int(config.get("worker", name))
        except:
            pass
    return defvalue


def cfgBool(name, defvalue):
    global config
    if config.has_option("worker", name):
        try:
            return int(config.get("worker", name)) != 0
        except:
            pass
    return defvalue


def cfgStr(name, defvalue):
    global config
    if config.has_option("worker", name):
        try:
            return config.get("worker", name)
        except:
            pass
    return defvalue


serverUrl = cfgStr("serverUrl", "")
workers = cfgInt("workers", 1)
name = cfgStr("name", socket.gethostname())
sleepTime = cfgInt("sleep", 2)
cpus = cfgInt("cpus", None)
startup = cfgStr("startup", "")
verbose = cfgBool("verbose", False)
runcommand = cfgStr("runcommand", "")
logfile = cfgStr("logfile", "./worker.log")


def usage():
    print("Usage: worker [OPTIONS] [SERVER_URL]")
    print("Start a Coalition worker using the server located at SERVER_URL.")
    print(
        "If no SERVER_URL is specified, the worker will try to locate the server using a broadcast.\n"
    )
    print("Options:")
    print("  -h, --help\t\tShow this help")
    print("  -v, --verbose\t\tIncrease verbosity")
    print("  -d, --debug\t\tRun without the main try/catch")
    print("  -u, --startup=COMMAND\t\tStartup command executed at worker startup")
    # print ("  -a, --affinity=AFFINITY\tAffinity words to jobs (default: \"\"")
    print("  -n, --name=NAME\tWorker name (default: " + name + ")")
    print(
        "  -s, --sleep=SLEEPTIME\tSleep time between two heart beats (default: "
        + str(sleepTime)
        + "s)"
    )
    print("  -w, --workers=WORKERS\t\tNumber of workers to run (default: 1)")
    print(
        "  -c, --cpus=CPUS\t\tIndicated number of cpus per worker, determines the number of worker to execute (default: 0, all available cpus)"
    )
    print("  -i, --install\t\tInstall service (Windows only)")
    print("\nExample : worker -s 30 -v http://localhost:19211")


if not service:
    # Parse the options
    try:
        opts, args = getopt.getopt(
            sys.argv[1:],
            "a:c:dhin:s:u:vw:",
            [
                "affinity=",
                "cpus=",
                "debug",
                "help",
                "install",
                "name=",
                "sleep=",
                "startup=",
                "verbose",
                "workers=",
            ],
        )
        if len(args) > 0:
            serverUrl = args[0]
    except getopt.GetoptError as err:
        # print help information and exit:
        print(str(err))  # will print something like "option -a not recognized"
        usage()
        sys.exit(2)
    for o, a in opts:
        if o in ("-a", "--affinity"):
            affinity = a
        elif o in ("-c", "--cpus"):
            cpus = int(a)
        elif o in ("-d", "--debug"):
            debug = True
        elif o in ("-h", "--help"):
            usage()
            sys.exit(2)
        elif o in ("-i", "--install"):
            install = True
        elif o in ("-n", "--name"):
            name = a
        elif o in ("-s", "--sleep"):
            sleepTime = float(a)
        elif o in ("-u", "--startup"):
            startup = a
        elif o in ("-v", "--verbose"):
            verbose = True
        elif o in ("-w", "--workers"):
            workers = int(a)
        else:
            assert False, "unhandled option " + o

if not verbose or service:
    outfile = open(logfile, "a")
    sys.stdout = outfile
    sys.stderr = outfile

# Log for debugging
def vprint(str):
    if verbose:
        print(str)
        sys.stdout.flush()


# Log for debugging
def debugRaw(str):
    if verbose:
        print(str)
        sys.stdout.flush()


vprint("--- Start ------------------------------------------------------------")

# If 'cpus' option set, compute the number of workers out of the total number of cpus
if cpus != None:
    if platform.platform == "win32":
        try:
            totalcpus = int(os.getenv("NUMBER_OF_PROCESSORS"))
            cpus = min(totalcpus, cpus)
            workers = max(1, totalcpus / cpus)
        except:
            pass
    else:
        pass

vprint("Running with " + str(workers) + " workers.")

random.seed()


def shuffleSleepTime(sleepTime):
    return sleepTime * (1.0 + (random.random() - 0.5) * 0.2)


# Safe method to run a command on the server, if retry is true, the function won't return until the message is passed
def workerRun(worker, func, retry):
    global sleepTime, gogogo
    while gogogo:
        serverConn = None
        try:
            serverConn = httplib.HTTPConnection(re.sub("^http://", "", serverUrl))
            result = func(serverConn)
            serverConn.close()
            return result
        except (socket.error, httplib.HTTPException), err:
            print("Error sending to the server : ", str(err))
            pass
        if serverConn != None:
            serverConn.close()
        if not retry:
            vprint("Server down, continue...")
            break
        vprint("No server")
        if gogogo:
            time.sleep(shuffleSleepTime(sleepTime))


# A Singler worker
class Worker:
    def __init__(self, name):
        self.Name = name  # The worker name
        self.Working = False  # The worker current state
        self.PId = 0  # The worker current process pid
        self.User = ""
        self.ErrorCode = 0  # The process exit error code
        self.LogLock = thread.allocate_lock()  # Logs lock
        self.Log = ""  # Logs
        self.HostCPU = host_cpu.HostCPU()
        self.total_memory = host_mem.getTotalMem()

    # LoadAvg
    def workerGetLoadAvg(self):
        usage = self.HostCPU.getUsage()
        return usage

    def workerEvalEnv(self, _str, _env):
        if platform.system() != "Windows":

            def _mapDrive(match):
                return "$(" + match.group(1).upper() + "_DRIVE)"

            _str = re.sub("^([a-zA-Z]):", _mapDrive, _str)

        def _getenv(match):
            m = match.group(1)
            # if _env exists, first try in _env
            if _env:
                try:
                    return _env[m]
                except:
                    pass
            result = os.getenv(m)
            if result == None:
                self.info("ERROR : Environment variable not found : " + match.group(1))
                result = ""
            return result

        while re.search("\$\(([^)]*)\)", _str):
            _str = re.sub("\$\(([^)]*)\)", _getenv, _str)
        return _str

    # Add to the logs
    def info(self, str):
        self.LogLock.acquire()
        try:
            self.Log = self.Log + "* " + str + "\n"
            vprint(str)
        finally:
            self.LogLock.release()

    # Thread function to execute the job process
    def _execProcess(self, cmd, dir, user, environment):
        self.info("START **********************************")
        self.info("WORKER : " + self.Name)
        self.info("DATE : " + datetime.datetime.today().strftime("%d/%m/%y %H:%M"))

        # Special command ?
        if runcommand != "":
            cmd = string.replace(
                string.replace(
                    string.replace(runcommand, "__user__", user), "__dir__", dir
                ),
                "__cmd__",
                cmd,
            )
        else:
            if dir != "":
                try:
                    # Linux, change the \\ for /
                    if sys.platform != "win32":
                        dir = re.sub("\\\\", "/", dir)
                    os.chdir(dir)
                except OSError, err:
                    self.info("ERROR : Can't change dir to " + dir + ": " + str(err))

        # Run the job
        self.info("CMD : " + cmd)

        # Make sure
        os.umask(002)
        process = subprocess.Popen(
            cmd,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=environment,
        )

        # Get the pid
        self.PId = int(process.pid)
        self.User = user
        while 1:
            # Read some lines of logs
            line = process.stdout.readline()

            # "" means EOF
            if line == "":
                break

            debugRaw(line)
            self.LogLock.acquire()
            try:
                self.Log = self.Log + line
            finally:
                self.LogLock.release()

        # Get the error code of the job
        self.ErrorCode = process.wait()
        self.info("EXIT : " + str(self.ErrorCode))
        self.info("END ********\n")

    def execProcess(self, cmd, dir, user, env):
        global debug, sleepTime
        if debug:
            self._execProcess(cmd, dir, user, env)
        else:
            try:
                self._execProcess(cmd, dir, user, env)
            except:
                self.ErrorCode = -1
                print("Fatal error executing the job...")
                time.sleep(shuffleSleepTime(sleepTime))
        # Signal to the main process the job is finished
        self.Working = False
        Event.set()

    ### To kill the current worker job
    def killJob(self):
        if self.PId != 0:
            vprint("kill " + str(self.PId))
            try:
                self.killr(self.PId)
                self.PId = 0
            except OSError as exc:
                vprint("kill failed")
                vprint(exc)
                pass

    ### To kill all child process
    def killr(self, pid):
        if sys.platform != "win32":
            names = os.listdir("/proc/")
            for name in names:
                try:
                    f = open("/proc/" + name + "/stat", "r")
                    line = f.readline()
                    words = string.split(line)
                    if words[3] == str(pid):
                        vprint("Found in " + name)
                        self.killr(int(name))
                except IOError as exc:
                    # vprint (exc)
                    pass
        try:
            if sys.platform == "win32":
                subprocess.Popen(
                    "taskkill /F /T /PID %i" % pid,
                    shell=True,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            elif runcommand != "":
                killcmd = "kill -9 " + str(pid)
                cmd = string.replace(
                    string.replace(
                        string.replace(runcommand, "__user__", self.User),
                        "__dir__",
                        ".",
                    ),
                    "__cmd__",
                    killcmd,
                )
                vprint("Kill process with runcommand : " + cmd)
                subprocess.Popen(
                    cmd,
                    shell=True,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            else:
                vprint("Kill process with os.kill")
                os.kill(pid, signal.SIGKILL)
        except OSError as exc:
            vprint("Can't kill the process %i" % pid)
            vprint(exc)
        except:
            vprint("Can't kill the process %i" % pid)
            vprint(sys.exc_info()[0])

    # Flush the logs to the server
    def heartbeat(self, jobId, retry):
        vprint("Flush logs (" + str(len(self.Log)) + " bytes)")

        def func(serverConn):
            result = True

            self.LogLock.acquire()
            try:
                params = urllib.urlencode(
                    {
                        "hostname": self.Name,
                        "jobId": jobId,
                        "log": base64.b64encode(self.Log),
                        "load": self.workerGetLoadAvg(),
                        "free_memory": int(host_mem.getAvailableMem() / 1024 / 1024),
                        "total_memory": int(self.total_memory / 1024 / 1024),
                    }
                )
                serverConn.request("POST", "/workers/heartbeat", params, Headers)
                response = serverConn.getresponse()
                result = response.read()
                self.Log = ""
            finally:
                self.LogLock.release()

            if result == "false":
                vprint("Server ask to stop the job " + str(jobId))
                # Send the kill signal to the process
                self.killJob()

        workerRun(self, func, retry)

    # Worker main loop
    def mainLoop(self):
        global sleepTime
        vprint("Ask for a job")
        # Function to ask a job to the server
        def startFunc(serverConn):
            params = urllib.urlencode(
                {
                    "hostname": self.Name,
                    "load": self.workerGetLoadAvg(),
                    "free_memory": int(host_mem.getAvailableMem() / 1024 / 1024),
                    "total_memory": int(self.total_memory / 1024 / 1024),
                }
            )
            serverConn.request("POST", "/workers/pickjob", params, Headers)
            response = serverConn.getresponse()
            result = response.read()
            return eval(result)

        # Block until this message to handled by the server
        jobId, cmd, dir, user, env = workerRun(self, startFunc, True)

        if jobId != -1:
            self.Log = ""

            _env = None
            if env:
                # Duplicate environment to add overrides
                _env = {}
                try:
                    for key, value in os.environ.items():
                        _env[key] = value
                except:
                    pass
                try:
                    for k in env.split("\\n"):
                        try:
                            key, value = k.split("=", 1)
                            _env[key] = value
                        except:
                            pass
                except:
                    _env = None

            _cmd = self.workerEvalEnv(cmd, _env)
            _dir = self.workerEvalEnv(dir, _env)

            vprint("Start job " + str(jobId) + " in " + _dir + " : " + _cmd)
            vprint("Job environment is " + str(_env))

            # Reset the globals
            self.Working = True
            stop = False
            self.PId = 0

            # Launch a new thread to run the process

            # Set the working directory in the main thead
            thread.start_new_thread(self.execProcess, (_cmd, _dir, user, _env))

            # Flush the logs
            while self.Working:
                self.heartbeat(jobId, False)
                Event.clear()
                Event.wait(shuffleSleepTime(sleepTime))

            # Flush for real for the last time
            self.heartbeat(jobId, True)

            vprint(
                "Finished job "
                + str(jobId)
                + " (code "
                + str(self.ErrorCode)
                + ") : "
                + _cmd
            )

            # Function to end the job
            def endFunc(serverConn):
                params = urllib.urlencode(
                    {
                        "hostname": self.Name,
                        "jobId": jobId,
                        "errorCode": self.ErrorCode,
                    }
                )
                serverConn.request("POST", "/workers/endjob", params, Headers)
                response = serverConn.getresponse()
                response.read()

            # Block until this message to handled by the server
            workerRun(self, endFunc, True)
        else:
            time.sleep(shuffleSleepTime(sleepTime))


def main():
    global name, serverUrl, sleepTime, broadcastPort, gogogo, workers, startup

    print("Startup command is '" + str(startup) + "'")
    if startup != "":
        cmd = startup
        if sys.platform == "win32":
            cmd = '"' + cmd + '"'
        process = subprocess.Popen(
            cmd,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        errorCode = process.wait()
        print("Startup command exited with code " + str(errorCode))

    # If no server, look for it with a broadcast
    if serverUrl == "":
        from socket import SOL_SOCKET, SO_BROADCAST
        from socket import socket, AF_INET, SOCK_DGRAM, timeout

        s = socket(AF_INET, SOCK_DGRAM)
        s.setsockopt(SOL_SOCKET, SO_BROADCAST, True)
        s.bind(("0.0.0.0", 0))
        s.settimeout(1)
        while gogogo:
            try:
                vprint("Broadcast port " + str(broadcastPort))
                s.sendto("coalition", ("255.255.255.255", broadcastPort))
                data, addr = s.recvfrom(1024)
                if data == "roxor":
                    serverUrl = "http://" + addr[0] + ":" + str(broadcastPort)
                    print("Server found at " + serverUrl)
                    vprint("Found : " + serverUrl)
                    found = True
                    break
            except timeout:
                pass
        s.close()

    while serverUrl[-1] == "/":
        serverUrl = serverUrl[:-1]

    print("Working...")

    def threadfunc(worker):
        global debug, sleepTime, gogogo
        while gogogo:
            if debug:
                worker.mainLoop()
            else:
                try:
                    worker.mainLoop()
                except:
                    print("Fatal error, retry...")
                    if gogogo:
                        time.sleep(shuffleSleepTime(sleepTime))
        vprint("WORKER " + worker.Name + " is kindly asked to quit.")
        # kill any job in process
        worker.killJob()

    # start each thread
    if workers == 1:
        # No suffix if one worker
        worker = Worker(name)
        thread.start_new_thread(threadfunc, (worker,))
    else:
        for k in range(workers):
            worker = Worker(name + "-" + str(k + 1))
            thread.start_new_thread(threadfunc, (worker,))

    # and let the main thread wait
    while gogogo:
        time.sleep(shuffleSleepTime(sleepTime))


if not service:
    main()

# vim: tabstop=4 noexpandtab shiftwidth=4 softtabstop=4 textwidth=79

