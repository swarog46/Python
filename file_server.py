#! /usr/bin/env python3

import socket
from collections import deque
from functools import partial
from pathlib import Path
from selectors import DefaultSelector, EVENT_READ, EVENT_WRITE

# resources closing -- sock, selector
#

class EventLoop:
    def __init__(self):
        self.tasks = deque()
        self.selector = DefaultSelector()

    def run_until_complete(self, task):
        self.tasks.append(task)
        self.run()

    def pause(self):
        return "pause", None

    def schedule(self, target):
        return "schedule", target

    def sock_accept(self, sock):
        yield ("read", sock)
        return sock.accept()

    def sock_recv(self, sock):
        yield ("read", sock)
        return sock.recv(1024)

    def sock_sendall(self, sock, data):
        yield ("write", sock)
        return sock.sendall(data)

    def start_server(self, handler, host, port, backlog=0):
        handler = partial(handler, self)
        with socket.socket() as sock:
            sock.bind((host, port))
            sock.listen(backlog)
            print("Listening on {}:{}".format(host, port))
            while True:
                conn, addr = yield from self.sock_accept(sock)
                print("Accepted client from", addr)
                yield self.schedule(handler(conn))

    def run(self):
        while self.tasks or self.selector.get_map():
            for _ in range(len(self.tasks)):
                try:
                    task = self.tasks.popleft()
                    tag, value = next(task)

                    if tag == "schedule":
                        self.tasks.append(value)
                        self.tasks.append(task)
                    elif tag == "read":
                        self.selector.register(value, EVENT_READ, data=task)
                    elif tag == "write":
                        self.selector.register(value, EVENT_WRITE, data=task)
                    elif tag == "pause":
                        self.tasks.append(task)
                    else:
                        raise ValueError("Incorrect tag")
                except StopIteration:
                    continue

            if self.selector.get_map():
                for key, event in self.selector.select():
                    if event & EVENT_READ or event & EVENT_WRITE:
                        self.tasks.append(key.data)
                    self.selector.unregister(key.fileobj)


# tasks


def getlist(loop, sock, vfs=None):
    while True:
        request = yield from loop.sock_recv(sock)
        request = request.split()
        response = b"ERROR\r\n"
        body = ""

        if not request:
            break
        elif request[0] == b"LIST":
            for f in vfs:
                body += f.decode("utf-8") + "\r\n"
            response = "OK <{}>\r\n{}".format(len(body), body).encode("utf-8")
        elif request[0] == b"GET":
            if len(request) == 2:
                response = vfs.get(request[1], b"ERROR\r\n")

        yield from loop.sock_sendall(sock, response)


def echo(loop, conn):
    while True:
        message = yield from loop.sock_recv(conn)
        if not message:
            break
        yield from loop.sock_sendall(conn, message)


def virtualize(path):
    files = {}
    root = Path(path)
    for f in root.iterdir():
        if not f.is_file():
            continue
        with f.open("rb") as handle:
            files[f.name.encode("utf-8")] = handle.read()
    return files


if __name__ == "__main__":
    loop = EventLoop()
    handler = partial(getlist, vfs=virtualize("./tmp"))
    loop.run_until_complete(loop.start_server(handler, "localhost", 8082))
