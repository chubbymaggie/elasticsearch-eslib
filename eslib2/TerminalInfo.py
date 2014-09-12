# -*- coding: utf-8 -*-

from .Connector import Connector
from .Socket import Socket


class TerminalInfo(object):

    def __init__(self, terminal=None, include_connections=True):
        if terminal:
            self.type = terminal.type # t.__class__.__name__
            owner_name = "orphan"
            if terminal.owner: owner_name = terminal.owner.name or "???"
            if terminal.owner: owner_name = terminal.owner.name or "???"
            self.owner = owner_name
            self.name = terminal.name
            self.protocol = terminal.protocol
            self.description = terminal.description
            connections = terminal.get_connections()
            self.count = len(connections)
            self.connections = []
            if include_connections:
                for c in terminal.get_connections():
                    self.connections.append(TerminalInfo(c, False))

    def DUMP(self, follow_connections=True, verbose=False, indent=0):
        spacing = "  "
        spc = spacing * indent
        type_indicator = "?"
        if self.type is Socket:
            type_indicator = "+"
        elif self.type is Connector:
            type_indicator = "-"

        print "%s%c%s.%s(%s) (conns=%d)" % (spc, type_indicator, self.owner, self.name, self.protocol, self.count)
        if verbose and self.description:
            print "\"%s%s%s%c\"" % (spc, spc, self.description)

        if follow_connections and self.connections:
            if verbose:
                print "%sConnections:" % spc
                indent += 1
            for c in self.connections:
                c.DUMP(False, verbose, indent+1)
